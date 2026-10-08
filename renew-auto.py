#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 自动登录脚本（CloakBrowser 版）
- 支持动态识别 Email/Username 及 Password 输入框
- 处理 Cloudflare Turnstile 人机验证
- 全程视频录制与截图保存
"""
import os
import re
import time
import glob
from datetime import datetime

import requests
from cloakbrowser import launch  # Playwright drop-in

# ==================== 配置 ====================
TARGET_URL = "https://dashboard.katabump.com/auth/login"
ACCOUNT_USER = os.getenv("KATABUMP_USER", "your_email@example.com")
ACCOUNT_PASS = os.getenv("KATABUMP_PASS", "your_password")

PROXY_SERVER = os.getenv("PROXY_SERVER", "socks5://127.0.0.1:40000")
WECHAT_WEBHOOK_KEY = os.getenv("WECHAT_WEBHOOK_KEY")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
LICENSE_KEY = os.getenv("CLOAKBROWSER_LICENSE_KEY", "")

VIDEO_DIR = "./videos"
SCREENSHOT_DIR = "./screenshots"

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


def send_wechat(content: str) -> bool:
    if not WECHAT_WEBHOOK_KEY:
        print("⚠️ 未配置 WECHAT_WEBHOOK_KEY")
        return False
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"
    try:
        resp = requests.post(url, json={"msgtype": "text", "text": {"content": content}}, timeout=15)
        return resp.json().get("errcode") == 0
    except Exception as e:
        print(f"❌ 企微发送失败: {e}")
        return False


def pass_turnstile(page, timeout=30) -> bool:
    """等待并处理 Turnstile 验证框"""
    print("🛡️ 检测是否存在 Turnstile 验证...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 检查是否已无验证码或直接跳转
        if "auth/login" not in page.url:
            return True
        
        try:
            iframe = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
            cb = iframe.locator("input[type='checkbox']")
            if cb.count() > 0 and cb.first.is_visible(timeout=1000):
                box = cb.first.bounding_box()
                if box:
                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=10)
                    time.sleep(0.2)
                    page.mouse.down()
                    time.sleep(0.1)
                    page.mouse.up()
                    print("  👆 已点击 Turnstile 框")
                    time.sleep(2)
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def fill_login_form(page) -> bool:
    """
    自动模糊匹配并填写用户名/密码框
    """
    print("🔍 正在定位登录表单元素...")
    
    # 1. 定位用户名/邮箱输入框 (尝试多种通用 Selector)
    user_input_selectors = [
        'input[type="email"]',
        'input[name="email"]',
        'input[name="username"]',
        'input[name="login"]',
        'input[id*="email"]',
        'input[id*="user"]',
        'input[placeholder*="email" i]',
        'input[placeholder*="username" i]',
        'input[type="text"]'  # 兜底：第一个文本输入框
    ]
    
    user_field = None
    for sel in user_input_selectors:
        loc = page.locator(sel).first
        if loc.is_visible(timeout=1000):
            user_field = loc
            print(f"  ✅ 匹配到账号输入框: {sel}")
            break

    if not user_field:
        print("  ❌ 未找到账号输入框")
        return False

    # 2. 定位密码输入框
    pass_field = page.locator('input[type="password"]').first
    if not pass_field.is_visible(timeout=2000):
        print("  ❌ 未找到密码输入框")
        return False
    print("  ✅ 匹配到密码输入框: input[type='password']")

    # 3. 模拟人类输入
    user_field.click()
    user_field.fill(ACCOUNT_USER)
    time.sleep(0.5)

    pass_field.click()
    pass_field.fill(ACCOUNT_PASS)
    time.sleep(0.5)

    # 4. 点击登录按钮
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Log in")',
        'button:has-text("Login")',
        'button:has-text("登录")',
        'form button'
    ]
    
    for sel in submit_selectors:
        btn = page.locator(sel).first
        if btn.is_visible(timeout=1000):
            print(f"  👆 点击登录按钮: {sel}")
            btn.click()
            return True

    print("  ⚠️ 未找到明显提交按钮，尝试回车提交")
    pass_field.press("Enter")
    return True


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    launch_kwargs = {
        "headless": HEADLESS,
        "proxy": {"server": PROXY_SERVER} if PROXY_SERVER else None,
        "humanize": True,
        "locale": "zh-CN",
        "args": ["--window-size=1920,1080"],
    }
    if LICENSE_KEY:
        launch_kwargs["license_key"] = LICENSE_KEY

    browser = None
    context = None
    try:
        browser = launch(**launch_kwargs)
        context = browser.new_context(
            record_video_dir=VIDEO_DIR,
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = context.new_page()

        print(f"🌐 打开登录页: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        shot(page, "01_login_page")

        # 处理登录前可能存在的 Cloudflare 质询
        pass_turnstile(page)

        # 填充并提交表单
        if fill_login_form(page):
            page.wait_for_timeout(3000)
            shot(page, "02_after_submit")

            # 提交后可能再次触发 Turnstile
            pass_turnstile(page)

            # 等待页面跳转或加载完成
            page.wait_for_timeout(5000)
            shot(page, "03_final_result")

            current_url = page.url
            if "login" not in current_url:
                print(f"🎉 登录成功，当前页面: {current_url}")
                send_wechat(f"✅ Katabump 自动登录成功\n\n当前 URL: {current_url}\n⏰ {now}")
            else:
                print("⚠️ 仍然停留在登录页，可能登录失败或需要二次验证")
                send_wechat(f"⚠️ Katabump 登录状态异常\n\n未能成功跳转，请检查截图。\n⏰ {now}")
        else:
            send_wechat(f"❌ Katabump 自动登录失败\n\n无法定位输入框。\n⏰ {now}")

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        send_wechat(f"❌ Katabump 脚本运行异常: {e}\n⏰ {now}")
    finally:
        if context:
            context.close()
        if browser:
            browser.close()

        videos = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.webm")))
        for v in videos:
            print(f"🎬 录像已保存: {v}")


if __name__ == "__main__":
    main()
