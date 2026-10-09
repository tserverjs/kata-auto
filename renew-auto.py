#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 自动登录与服务器续期监控脚本（精准 Modal 触发按钮版）
- 针对精准 Renew 元素定位: button[data-bs-target="#renew-modal"]
- 自动处理点击后弹出的 #renew-modal 确认框及 Turnstile 验证
- 跨页面持久化红色涟漪点击特效与 WebM 视频录制
"""
import os
import time
import glob
from datetime import datetime

import requests
from cloakbrowser import launch

# ==================== 配置项 ====================
TARGET_URL = "https://dashboard.katabump.com/auth/login"
ACCOUNT_USER = os.getenv("KATABUMP_USER", "your_email@example.com")
ACCOUNT_PASS = os.getenv("KATABUMP_PASS", "your_password")

PROXY_SERVER = os.getenv("PROXY_SERVER", "socks5://127.0.0.1:40000")  # 无代理可留空 ""
WECHAT_WEBHOOK_KEY = os.getenv("WECHAT_WEBHOOK_KEY", "")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
LICENSE_KEY = os.getenv("CLOAKBROWSER_LICENSE_KEY", "")

VIDEO_DIR = "./videos"
SCREENSHOT_DIR = "./screenshots"

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


# ==================== 点击高亮特效 ====================
def trigger_ripple(page, x: float, y: float):
    """强制在坐标 (x, y) 渲染最顶层红色涟漪动画"""
    js_code = """
    ([x, y]) => {
        try {
            const circle = document.createElement('div');
            circle.style.cssText = `
                position: fixed !important;
                left: ${x - 15}px !important;
                top: ${y - 15}px !important;
                width: 30px !important;
                height: 30px !important;
                border-radius: 50% !important;
                background-color: rgba(255, 0, 0, 0.7) !important;
                border: 2px solid red !important;
                box-shadow: 0 0 12px red !important;
                pointer-events: none !important;
                z-index: 2147483647 !important;
                transition: transform 0.4s ease-out, opacity 0.4s ease-out !important;
                transform: scale(0.5) !important;
                opacity: 1 !important;
            `;
            document.body.appendChild(circle);
            requestAnimationFrame(() => {
                circle.style.transform = 'scale(2.5)';
                circle.style.opacity = '0';
            });
            setTimeout(() => {
                if (circle.parentNode) circle.parentNode.removeChild(circle);
            }, 450);
        } catch (e) {
            console.error(e);
        }
    }
    """
    try:
        page.evaluate(js_code, [x, y])
    except Exception:
        pass


def visual_click_locator(page, locator) -> bool:
    """针对 Locator 对象的安全高亮点击"""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
        time.sleep(0.3)
        box = locator.bounding_box()
        if box and box["width"] > 0 and box["height"] > 0:
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            print(f"  🎯 触发红色涟漪坐标点击: ({x:.1f}, {y:.1f})，元素尺寸: {box['width']}x{box['height']}")
            page.mouse.move(x, y, steps=12)
            time.sleep(0.1)
            trigger_ripple(page, x, y)
            time.sleep(0.2)
            page.mouse.down()
            time.sleep(0.08)
            page.mouse.up()
            time.sleep(0.2)
            return True
        else:
            print("  ⚠️ 坐标计算失败，使用 force=True 原生点击")
            locator.click(force=True)
            return True
    except Exception as e:
        print(f"  ⚠️ 视觉点击异常，回退至原生 click: {e}")
        try:
            locator.click(force=True)
            return True
        except Exception:
            return False


# ==================== 工具函数 ====================
def shot(page, name: str):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path, full_page=False)
        print(f"📷 截图已保存: {path}")
    except Exception as e:
        print(f"⚠️ 截图失败 {name}: {e}")


def body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)
    except Exception:
        return page.content()


def send_wechat(content: str) -> bool:
    if not WECHAT_WEBHOOK_KEY:
        print("⚠️ 未配置 WECHAT_WEBHOOK_KEY，跳过企微通知")
        return False
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"
    try:
        resp = requests.post(url, json={"msgtype": "text", "text": {"content": content}}, timeout=15)
        result = resp.json()
        print(f"📤 企微响应结果: {result}")
        return result.get("errcode") == 0
    except Exception as e:
        print(f"❌ 企微发送失败: {e}")
        return False


# ==================== Turnstile 验证处理 ====================
def ensure_turnstile_passed(page, timeout=40) -> bool:
    print("🛡️ 开始进行 Turnstile 验证检查...")
    deadline = time.time() + timeout
    clicked = False

    while time.time() < deadline:
        try:
            token_input = page.locator('input[name="cf-turnstile-response"]')
            if token_input.count() > 0:
                token_val = token_input.first.get_attribute("value")
                if token_val and len(token_val) > 20:
                    print("  🎉 Turnstile 验证通过（Token 成功注入）")
                    return True
        except Exception:
            pass

        if not clicked:
            try:
                iframe = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
                cb = iframe.locator("input[type='checkbox']")

                if cb.count() > 0 and cb.first.is_visible(timeout=1000):
                    print("  🎯 发现 Turnstile 复选框，尝试触发点击...")
                    visual_click_locator(page, cb.first)
                    clicked = True
            except Exception:
                pass

        time.sleep(1)

    print("  ⚠️ Turnstile 验证超时或未生成 Token")
    return False


# ==================== 智能定位与点击 Renew 按钮 ====================
def locate_and_click_renew(page) -> bool:
    """精准定位你提供的按钮元素结构并处理后续弹窗"""
    print("🔍 正在精准检索 Renew 按钮...")

    # 优先强匹配你的准确 HTML 特征
    exact_selectors = [
        'button[data-bs-target="#renew-modal"]',  # 最精准的选择器
        'button.btn-outline-primary:has-text("Renew")',
        'button[data-bs-toggle="modal"]:has-text("Renew")',
        'button:has-text("Renew")'
    ]

    deadline = time.time() + 12
    renew_target = None

    while time.time() < deadline:
        for sel in exact_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible() and loc.is_enabled():
                    renew_target = loc
                    print(f"  ✅ 成功定位到精确 Renew 按钮，选择器: {sel}")
                    break
            except Exception:
                pass

        if renew_target:
            break
        time.sleep(1)

    if not renew_target:
        print("  ⚠️ 页面中未监听到可见的 Renew 按钮")
        return False

    try:
        # 打印匹配元素的外层 HTML 以供确认
        outer_html = renew_target.evaluate("el => el.outerHTML")
        print(f"  📋 匹配到的 HTML 结构: {outer_html}")

        # 1. 点击 Renew 按钮触发 Modal 弹窗
        visual_click_locator(page, renew_target)
        time.sleep(2.0)
        shot(page, "05_renew_modal_opened")

        # 2. 点击 Modal 弹窗内的最终确认提交按钮 (#renew-modal 内部)
        print("🔍 寻找 #renew-modal 弹窗内部的确认按钮...")
        modal_confirm_selectors = [
            '#renew-modal button[type="submit"]',
            '#renew-modal button:has-text("Renew")',
            '#renew-modal button:has-text("Confirm")',
            '#renew-modal button.btn-primary'
        ]

        for m_sel in modal_confirm_selectors:
            try:
                m_btn = page.locator(m_sel).first
                if m_btn.is_visible(timeout=2000):
                    print(f"  👆 发现 Modal 确认按钮 [{m_sel}]，触发点击")
                    visual_click_locator(page, m_btn)
                    break
            except Exception:
                pass

        return True

    except Exception as e:
        print(f"  ❌ 点击 Renew 过程中发生错误: {e}")
        return False


# ==================== 信息解析与格式化 ====================
def extract_service_info(page) -> str:
    try:
        card_locator = page.locator('*:has-text("Service information")').last
        if card_locator.is_visible(timeout=3000):
            return card_locator.inner_text()
    except Exception:
        pass
    return body_text(page)


def format_wechat_msg(raw_info: str, renew_status: str, now: str) -> str:
    msg_lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🤖 Katabump 服务器自动续期通知",
        f"🔄 续期状态：{renew_status}",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 【Service Information 详情】",
    ]

    cleaned_lines = [line.strip() for line in raw_info.splitlines() if line.strip()]
    for line in cleaned_lines[:15]:
        msg_lines.append(f"• {line}")

    msg_lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"⏰ 执行时间：{now}"
    ])
    return "\n".join(msg_lines)


# ==================== 主流程 ====================
def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    launch_kwargs = {
        "headless": HEADLESS,
        "humanize": True,
        "locale": "zh-CN",
        "args": [
            "--window-size=1920,1080",
            "--lang=zh-CN",
            "--font-render-hinting=medium",
        ],
    }
    if PROXY_SERVER:
        launch_kwargs["proxy"] = {"server": PROXY_SERVER}
    if LICENSE_KEY:
        launch_kwargs["license_key"] = LICENSE_KEY

    browser = None
    context = None
    page = None
    try:
        print("🚀 启动 CloakBrowser...")
        browser = launch(**launch_kwargs)

        context = browser.new_context(
            record_video_dir=VIDEO_DIR,
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
        )

        page = context.new_page()

        # ---------------- 1. 打开并登录 ----------------
        print(f"🌐 打开登录页: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        shot(page, "01_login_page")

        # 填写账号密码
        email_input = page.locator("#email")
        email_input.wait_for(state="visible", timeout=10000)
        visual_click_locator(page, email_input)
        email_input.fill(ACCOUNT_USER)
        time.sleep(0.3)

        password_input = page.locator("#password")
        visual_click_locator(page, password_input)
        password_input.fill(ACCOUNT_PASS)
        time.sleep(0.5)

        # Tab + Space 快捷勾选 Turnstile
        print("⌨️ 尝试 Tab + Space 聚焦并勾选 Turnstile...")
        password_input.press("Tab")
        time.sleep(0.3)
        page.keyboard.press("Tab")
        time.sleep(0.3)
        page.keyboard.press("Space")
        time.sleep(3.0)

        turnstile_ok = ensure_turnstile_passed(page, timeout=35)
        shot(page, "02_turnstile_check")

        if not turnstile_ok:
            send_wechat(f"❌ Katabump 登录失败\n\nCloudflare 验证未通过。\n⏰ {now}")
            return

        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Log in")').first
        if submit_btn.is_visible(timeout=3000):
            visual_click_locator(page, submit_btn)
        else:
            password_input.press("Enter")

        page.wait_for_timeout(4000)
        shot(page, "03_after_login")

        if "login" in page.url:
            send_wechat(f"❌ Katabump 登录失败\n\n未能跳转 Dashboard。\n⏰ {now}")
            return

        # ---------------- 2. 点击 See 进入详情页 ----------------
        print("🔍 查找 Your servers 中的 'See' 按钮...")
        see_btn = page.locator('a:has-text("See"), button:has-text("See")').first
        see_btn.wait_for(state="visible", timeout=15000)

        visual_click_locator(page, see_btn)

        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(5000)
        shot(page, "04_server_detail_page")

        # ---------------- 3. 点击 Renew 按钮 ----------------
        renew_clicked = locate_and_click_renew(page)

        if renew_clicked:
            time.sleep(2.0)
            # 点击后如果弹窗内有 Turnstile，再次等待通过
            ensure_turnstile_passed(page, timeout=25)
            page.wait_for_timeout(4000)
            shot(page, "06_after_renew_submit")
            renew_status = "✅ 续期操作已成功点击并提交"
        else:
            shot(page, "06_no_renew_found")
            renew_status = "ℹ️ 未发现可点击的 Renew 按钮"

        # ---------------- 4. 抓取卡片信息并发送通知 ----------------
        print("📋 读取 Service information 信息...")
        service_info = extract_service_info(page)

        wechat_msg = format_wechat_msg(service_info, renew_status, now)
        send_wechat(wechat_msg)
        print("✅ 监控全流程顺利完成！")

    except Exception as e:
        print(f"❌ 运行发生异常: {e}")
        send_wechat(f"❌ Katabump 脚本运行异常\n\n错误信息: {e}\n⏰ {now}")

    finally:
        if page:
            try:
                page.wait_for_timeout(3000)
            except Exception:
                pass
        if context:
            try:
                context.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass

        videos = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.webm")))
        for v in videos:
            print(f"🎬 运行视频已生成: {v}")


if __name__ == "__main__":
    main()
