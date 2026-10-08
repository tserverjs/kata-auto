#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lunafy 自动续期监控（CloakBrowser 版）
- 使用 CloakBrowser（Playwright drop-in）绕过 Cloudflare Turnstile
- 全程视频录制，保存到 ./videos/*.webm
- 企微 Webhook 通知
"""
import os
import re
import json
import time
import glob
from datetime import datetime

import requests
from cloakbrowser import launch  # Playwright drop-in，自带反检测 Chromium

# ==================== 配置 ====================
PROXY_SERVER = os.getenv("PROXY_SERVER", "socks5://127.0.0.1:40000")
WECHAT_WEBHOOK_KEY = os.getenv("WECHAT_WEBHOOK_KEY")
COOKIES_RAW = os.getenv("LUNAFY_COOKIES", "[]")
LICENSE_KEY = os.getenv("CLOAKBROWSER_LICENSE_KEY", "")  # 可选，免费 key
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"  # CI 里用 xvfb 跑 headed
VIDEO_DIR = "./videos"
SCREENSHOT_DIR = "./screenshots"
PANEL_URL = "https://panel.lunafy.run"
LOGIN_URL = f"{PANEL_URL}/login"

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def shot(page, name):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path, full_page=False)
        print(f"📷 截图: {path}")
    except Exception as e:
        print(f"⚠️ 截图失败 {name}: {e}")


def body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)
    except Exception:
        return page.content()


# ==================== 企业微信 ====================
def send_wechat(content: str) -> bool:
    if not WECHAT_WEBHOOK_KEY:
        print("⚠️ 未配置 WECHAT_WEBHOOK_KEY")
        return False
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"
    try:
        resp = requests.post(url, json={"msgtype": "text", "text": {"content": content}}, timeout=15)
        result = resp.json()
        print(f"📤 企微响应: {result}")
        return result.get("errcode") == 0
    except Exception as e:
        print(f"❌ 企微发送失败: {e}")
        return False


# ==================== 页面信息提取 ====================
def extract_info(page) -> dict:
    info = {
        "status": "未知",
        "status_emoji": "❓",
        "next_renewal": "未知",
        "deleted_on": "未知",
        "servers_count": "0",
        "action_text": "",
        "need_renew": False,
        "notice": "",
    }
    html = page.content()
    text = body_text(page)

    m = re.search(r'Server Status:\s*(\w+)', text)
    if m:
        raw = m.group(1).strip()
        info["status"] = raw
        if raw.lower() == "active":
            info["status_emoji"], info["need_renew"] = "✅", False
        elif raw.lower() == "expired":
            info["status_emoji"], info["need_renew"] = "❌", True
        else:
            info["status_emoji"] = "⚠️"
    else:
        if "fi-color-danger" in html or "Expired" in text:
            info.update(status="Expired", status_emoji="❌", need_renew=True)
        elif "Active" in text:
            info.update(status="Active", status_emoji="✅")

    m = re.search(r'Next renewal\s+(\d{2}/\d{2}\s+\d{2}:\d{2})', text)
    if m:
        info["next_renewal"] = m.group(1).strip()

    m = re.search(r'Server deleted on\s+(\d{2}/\d{2}\s+\d{2}:\d{2})', text)
    if m:
        info["deleted_on"] = m.group(1).strip()

    m = re.search(r'SERVERS\s+(\d+)', text)
    if m:
        info["servers_count"] = m.group(1).strip()

    try:
        renew_btn = page.locator('button:has-text("Renew")')
        if renew_btn.first.is_visible(timeout=1500):
            info["action_text"] = "Renew"
            info["need_renew"] = True
    except Exception:
        pass
    if not info["action_text"] and "Unavailable" in text:
        info["action_text"] = "Unavailable"

    if "Discord" in text and "deleted" in text:
        info["notice"] = "验证后将自动加入 Discord，退出会导致服务器被删除"

    print(f"📋 提取结果: {info}")
    return info


def status_block(info) -> str:
    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 服务器状态：{info['status_emoji']} {info['status']}\n"
        f"🖥️ 服务器数量：{info['servers_count']} 台\n"
        f"📅 下次续期：{info['next_renewal']}\n"
        f"🗑️ 删除时间：{info['deleted_on']}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


# ==================== Turnstile 处理 ====================
def pass_turnstile(page, timeout=60) -> bool:
    """
    等待 Security Check 弹窗出现，点击 Turnstile 复选框并等待验证通过。
    CloakBrowser 的反检测 Chromium 在 headed 模式下通常无需人工即可通过，
    这里保留主动点击逻辑作为兜底。
    """
    print("🛡️ 等待 Security Check / Turnstile 出现...")
    deadline = time.time() + timeout
    iframe = None
    while time.time() < deadline:
        try:
            iframe = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
            cb = iframe.locator("input[type='checkbox']")
            if cb.count() > 0 and cb.first.is_visible(timeout=1000):
                print("  ✅ 找到 Turnstile 复选框")
                break
        except Exception:
            pass
        # 可能已自动通过（弹窗消失 / 出现成功文案）
        text = body_text(page)
        if "成功" in text or ("/login" not in page.url and "Security Check" not in text and "Verify you are human" not in text):
            print("  ✅ Turnstile 似乎已自动通过")
            return True
        time.sleep(1)
    else:
        print("  ⚠️ 未找到 Turnstile 复选框")
        return False

    # 人类化点击复选框
    try:
        cb = iframe.locator("input[type='checkbox']").first
        box = cb.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
            time.sleep(0.3)
            page.mouse.down()
            time.sleep(0.1)
            page.mouse.up()
            print("  👆 已点击 Turnstile 复选框")
    except Exception as e:
        print(f"  ⚠️ 点击复选框失败（可能已自动通过）: {e}")

    # 等待通过：复选框变成功状态或弹窗消失
    end = time.time() + timeout
    while time.time() < end:
        text = body_text(page)
        if "成功" in text or "Security Check" not in text:
            print("  ✅ Turnstile 验证通过")
            return True
        # 检查 turnstile token 已生成（复选框不再可见）
        try:
            if page.frame_locator('iframe[src*="challenges.cloudflare.com"]').locator("input[type='checkbox']").count() == 0:
                print("  ✅ Turnstile token 已生成")
                return True
        except Exception:
            pass
        time.sleep(1)

    print("  ❌ Turnstile 等待超时")
    return False


# ==================== 主流程 ====================
def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cookies_raw = json.loads(COOKIES_RAW)
        if not isinstance(cookies_raw, list):
            raise ValueError("LUNAFY_COOKIES 必须是 JSON 数组格式")
    except Exception as e:
        send_wechat(f"❌ Lunafy 监控异常\n\n🍪 Cookie 解析失败：{e}\n\n⏰ {now}")
        return

    # 转成 Playwright cookie 格式
    # sameSite 归一化：Playwright 只认 Strict/Lax/None（首字母大写）
    SS_MAP = {"strict": "Strict", "lax": "Lax", "none": "None",
              "no_restriction": "None", "unspecified": "Lax"}
    cookies = []
    for c in cookies_raw:
        raw_ss = str(c.get("sameSite", "Lax") or "Lax").strip()
        same_site = SS_MAP.get(raw_ss.lower())
        if same_site is None:
            same_site = raw_ss if raw_ss in ("Strict", "Lax", "None") else "Lax"
        cookies.append({
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain") or ".lunafy.run",
            "path": "/",
            "secure": True,
            "httpOnly": bool(c.get("httpOnly", False)),
            "sameSite": same_site,
        })

    # ========== 启动 CloakBrowser（headed + xvfb，Turnstile 通过率最高）==========
    launch_kwargs = {
        "headless": HEADLESS,
        "proxy": {"server": PROXY_SERVER},
        "humanize": True,   # 类人鼠标/键盘行为
        "locale": "zh-CN",
        "args": ["--window-size=1920,1080"],
    }
    if LICENSE_KEY:
        launch_kwargs["license_key"] = LICENSE_KEY

    browser = None
    context = None
    try:
        browser = launch(**launch_kwargs)
        print("🚀 CloakBrowser 启动成功")

        # 视频录制：context 关闭时自动保存 webm
        context = browser.new_context(
            record_video_dir=VIDEO_DIR,
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        context.add_cookies(cookies)
        print(f"🍪 已注入 {len(cookies)} 个 Cookie")

        page = context.new_page()

        # ========== 访问 Dashboard ==========
        print("🌐 访问 Dashboard...")
        page.goto(PANEL_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        shot(page, "01_dashboard")

        if "/login" in page.url:
            send_wechat(
                f"🔐 Lunafy Cookie 已失效\n\n登录状态过期，已被重定向到登录页。\n"
                f"👉 请重新登录并更新 Secrets 中的 LUNAFY_COOKIES\n\n⏰ {now}"
            )
            return

        # ========== 提取状态 ==========
        info = extract_info(page)

        # ========== 分支处理 ==========
        if info["status"].lower() == "active":
            send_wechat(
                f"✅ Lunafy 服务器状态正常\n\n{status_block(info)}\n\n"
                f"⏰ 检测时间：{now}\n🤖 GitHub Actions 自动监控"
            )
            print("✅ 状态正常，已发送通知")
            return

        if info["status"].lower() == "expired":
            if info["need_renew"] and info["action_text"] == "Renew":
                print("🔄 检测到 Renew 按钮，开始续期流程...")
                try:
                    page.locator('button:has-text("Renew")').first.click()
                    print("  ✅ 已点击 Renew")
                except Exception as e:
                    print(f"  ❌ 点击 Renew 失败: {e}")
                    shot(page, "02_renew_click_failed")
                    send_wechat(
                        f"❌ Lunafy 续期失败\n\n{status_block(info)}\n"
                        f"❌ 无法点击 Renew 按钮\n\n⏰ {now}"
                    )
                    return

                page.wait_for_timeout(2000)
                shot(page, "02_renew_clicked")

                # 等待 Security Check 弹窗
                popup = False
                for _ in range(15):
                    text = body_text(page)
                    if "Security Check" in text or "Verify you are human" in text:
                        popup = True
                        break
                    page.wait_for_timeout(1000)
                if not popup:
                    shot(page, "03_no_popup")
                    send_wechat(
                        f"⚠️ Lunafy 续期异常\n\n已点击 Renew，但未出现 Security Check 弹窗。\n"
                        f"👉 请手动检查：{PANEL_URL}/\n\n⏰ {now}"
                    )
                    return

                page.wait_for_timeout(2000)
                shot(page, "03_popup")

                # Cloudflare Turnstile
                turnstile_ok = pass_turnstile(page)
                page.wait_for_timeout(3000)
                shot(page, "04_after_turnstile")

                # 刷新确认最终状态
                page.goto(PANEL_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                shot(page, "05_final")
                info = extract_info(page)

                if turnstile_ok and info["status"].lower() == "active":
                    send_wechat(
                        f"🎉 Lunafy 续期成功！\n\n{status_block(info)}\n\n"
                        f"✅ Turnstile 人机验证已通过\n⏰ {now}"
                    )
                else:
                    send_wechat(
                        f"⚠️ Lunafy 续期结果待确认\n\n{status_block(info)}\n\n"
                        f"🛡️ Turnstile 已尝试，但状态未恢复 Active\n"
                        f"👉 请手动确认：{PANEL_URL}/\n\n⏰ {now}"
                    )
            else:
                send_wechat(
                    f"❌ Lunafy 状态异常\n\n{status_block(info)}\n\n"
                    f"⚠️ 页面显示已过期，但未找到 Renew 按钮\n"
                    f"👉 请手动处理：{PANEL_URL}/\n\n⏰ {now}"
                )
        else:
            send_wechat(
                f"⚠️ Lunafy 状态未知\n\n{status_block(info)}\n\n"
                f"👉 请手动检查：{PANEL_URL}/\n\n⏰ {now}"
            )

        print("✅ 监控流程结束")

    except Exception as e:
        print(f"❌ 脚本异常: {e}")
        send_wechat(f"❌ Lunafy 脚本异常\n\n错误：{str(e)}\n\n⏰ {now}")
    finally:
        # 关闭 context 触发视频落盘
        try:
            if context:
                context.close()
        except Exception as e:
            print(f"⚠️ context 关闭异常: {e}")
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        videos = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.webm")))
        for v in videos:
            print(f"🎬 视频已保存: {v}")


if __name__ == "__main__":
    main()
