#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 自动登录与服务器续期监控脚本（CloakBrowser 版）
- 自动登录 Katabump Dashboard
- 自动处理 Cloudflare Turnstile 人机验证
- 自动进入 "Your servers" 列表并点击 "See" 进入服务器详情页
- 自动点击 "Renew" 按钮完成服务器续期
- 自动提取 "Service information" 卡片内容并推送企业微信机器人
- 全全程红色涟漪点击高亮与 WebM 视频录制
"""
import os
import re
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
def show_click_ripple(page, x: float, y: float):
    """在坐标 (x, y) 显示红色涟漪视觉特效"""
    js_code = """
    (pos) => {
        const circle = document.createElement('div');
        circle.style.position = 'fixed';
        circle.style.left = (pos.x - 15) + 'px';
        circle.style.top = (pos.y - 15) + 'px';
        circle.style.width = '30px';
        circle.style.height = '30px';
        circle.style.borderRadius = '50%';
        circle.style.backgroundColor = 'rgba(255, 0, 0, 0.6)';
        circle.style.border = '2px solid red';
        circle.style.boxShadow = '0 0 10px red';
        circle.style.pointerEvents = 'none';
        circle.style.zIndex = '999999';
        circle.style.transition = 'transform 0.4s ease-out, opacity 0.4s ease-out';
        circle.style.transform = 'scale(0.5)';
        circle.style.opacity = '1';

        document.body.appendChild(circle);

        requestAnimationFrame(() => {
            circle.style.transform = 'scale(2.5)';
            circle.style.opacity = '0';
        });

        setTimeout(() => {
            if (circle.parentNode) {
                circle.parentNode.removeChild(circle);
            }
        }, 450);
    }
    """
    try:
        page.evaluate(js_code, {"x": x, "y": y})
    except Exception:
        pass


def visual_click(page, x: float, y: float):
    """带红色涟漪特效的模拟点击"""
    page.mouse.move(x, y, steps=12)
    time.sleep(0.1)
    show_click_ripple(page, x, y)
    time.sleep(0.15)
    page.mouse.down()
    time.sleep(0.08)
    page.mouse.up()


# ==================== 工具函数 ====================
def shot(page, name: str):
    """截屏保存"""
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path, full_page=False)
        print(f"📷 截图已保存: {path}")
    except Exception as e:
        print(f"⚠️ 截图失败 {name}: {e}")


def body_text(page) -> str:
    """提取页面文本内容"""
    try:
        return page.locator("body").inner_text(timeout=5000)
    except Exception:
        return page.content()


def send_wechat(content: str) -> bool:
    """企业微信机器人通知"""
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
    """寻找并点击 Turnstile 复选框，并阻塞等待直至 Token 生成完成"""
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
                    box = cb.first.bounding_box()
                    if box:
                        click_x = box["x"] + box["width"] / 2
                        click_y = box["y"] + box["height"] / 2
                        print(f"  🎯 发现 Turnstile 复选框，触发红色涟漪点击: ({click_x:.1f}, {click_y:.1f})")
                        visual_click(page, click_x, click_y)
                        clicked = True
            except Exception:
                pass

        time.sleep(1)

    print("  ⚠️ Turnstile 验证超时或未生成 Token（可能无需验证）")
    return False


# ==================== 信息解析函数 ====================
def extract_service_info(page) -> str:
    """从 Service information 卡片中提取信息文本"""
    try:
        # 定位 Service information 卡片及其内部所有文本
        card_locator = page.locator('*:has-text("Service information")').last
        if card_locator.is_visible(timeout=5000):
            card_text = card_locator.inner_text()
            print(f"📋 抓取到的卡片原文:\n{card_text}")
            return card_text
    except Exception as e:
        print(f"⚠️ 定位 Service information 卡片失败: {e}")

    # 降级备用逻辑：直接全局获取整页 body 文本
    return body_text(page)


def format_wechat_msg(raw_info: str, renew_status: str, now: str) -> str:
    """将抓取的服务信息格式化为企微推送格式"""
    msg_lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"🤖 Katabump 服务器自动续期通知",
        f"🔄 续期状态：{renew_status}",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 【Service Information 详情】",
    ]

    # 清理不必要的换行并追加信息主体
    cleaned_lines = [line.strip() for line in raw_info.splitlines() if line.strip()]
    
    # 简单过滤重复标题
    for line in cleaned_lines[:15]:  # 保留关键信息行
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

        # ---------------- 1. 打开登录页 ----------------
        print(f"🌐 打开登录页: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        shot(page, "01_login_page")

        # 填写账号密码
        print("🔍 填写账号与密码...")
        email_input = page.locator("#email")
        email_input.wait_for(state="visible", timeout=10000)
        box_email = email_input.bounding_box()
        if box_email:
            visual_click(page, box_email["x"] + box_email["width"] / 2, box_email["y"] + box_email["height"] / 2)
        email_input.fill(ACCOUNT_USER)
        time.sleep(0.3)

        password_input = page.locator("#password")
        box_pass = password_input.bounding_box()
        if box_pass:
            visual_click(page, box_pass["x"] + box_pass["width"] / 2, box_pass["y"] + box_pass["height"] / 2)
        password_input.fill(ACCOUNT_PASS)
        time.sleep(0.5)

        # 键盘快捷操作尝试勾选 Turnstile
        print("⌨️ 尝试 Tab + Space 聚焦并勾选 Turnstile...")
        password_input.press("Tab")
        time.sleep(0.3)
        page.keyboard.press("Tab")
        time.sleep(0.3)
        page.keyboard.press("Space")
        time.sleep(3.0)

        # 确保 Turnstile 验证通过
        turnstile_ok = ensure_turnstile_passed(page, timeout=35)
        shot(page, "02_turnstile_check")

        if not turnstile_ok:
            print("⚠️ 警告：Turnstile 尚未通过，暂停提交以防登录失败。")
            send_wechat(f"❌ Katabump 登录失败\n\nCloudflare 验证未通过。\n⏰ {now}")
            return

        # 点击 Login 提交
        print("👆 准备点击登录按钮...")
        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Log in")').first
        if submit_btn.is_visible(timeout=3000):
            box_submit = submit_btn.bounding_box()
            if box_submit:
                visual_click(page, box_submit["x"] + box_submit["width"] / 2, box_submit["y"] + box_submit["height"] / 2)
            else:
                submit_btn.click()
        else:
            password_input.press("Enter")

        page.wait_for_timeout(4000)
        shot(page, "03_after_login")

        if "login" in page.url:
            print("❌ 仍停留在登录页，登录失败。")
            send_wechat(f"❌ Katabump 登录失败\n\n未能成功跳转 Dashboard。\n⏰ {now}")
            return

        print("🎉 登录成功，已跳转至后台。")

        # ---------------- 2. 进入服务器详情页 (Your servers -> See) ----------------
        print("🔍 查找 Your servers 列表中的 'See' 按钮...")
        see_btn = page.locator('a:has-text("See"), button:has-text("See")').first
        see_btn.wait_for(state="visible", timeout=15000)
        
        box_see = see_btn.bounding_box()
        if box_see:
            visual_click(page, box_see["x"] + box_see["width"] / 2, box_see["y"] + box_see["height"] / 2)
        else:
            see_btn.click()

        page.wait_for_timeout(4000)
        shot(page, "04_server_detail_page")

        # ---------------- 3. 点击 Renew 续期按钮 ----------------
        print("🔄 在详情页查找 'Renew' 按钮...")
        renew_btn = page.locator('button:has-text("Renew"), a:has-text("Renew")').first
        renew_status = "未触发/无需续期"

        if renew_btn.is_visible(timeout=5000):
            box_renew = renew_btn.bounding_box()
            if box_renew:
                print("  🎯 找到 Renew 按钮，触发点击...")
                visual_click(page, box_renew["x"] + box_renew["width"] / 2, box_renew["y"] + box_renew["height"] / 2)
            else:
                renew_btn.click()

            time.sleep(2.0)
            # 点击 Renew 后若弹出 Turnstile 质询，自动处理
            ensure_turnstile_passed(page, timeout=30)
            page.wait_for_timeout(4000)
            shot(page, "05_after_renew")
            renew_status = "✅ 续期操作已点击完成"
        else:
            print("  ℹ️ 未发现 Renew 按钮（可能服务器状态良好，无需续期）。")
            renew_status = "ℹ️ 无需续期/Renew按钮未出现"

        # ---------------- 4. 提取 Service information 并发送企微通知 ----------------
        print("📋 正在读取 Service information 卡片信息...")
        service_info = extract_service_info(page)
        
        wechat_msg = format_wechat_msg(service_info, renew_status, now)
        print("📤 准备发送企微消息:\n" + wechat_msg)
        
        send_wechat(wechat_msg)
        print("✅ 监控全流程顺利完成！")

    except Exception as e:
        print(f"❌ 运行发生异常: {e}")
        send_wechat(f"❌ Katabump 脚本运行异常\n\n错误信息: {e}\n⏰ {now}")

    finally:
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
