#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 自动登录脚本（CloakBrowser 版）
- 使用精准 DOM 选择器（#email, #password）进行表单填充
- 支持 Cloudflare Turnstile 人机验证自动处理
- 支持全流程截图与 WebM 视频录制
- 支持企微 Webhook 消息通知
"""
import os
import time
import glob
from datetime import datetime

import requests
from cloakbrowser import launch  # Playwright drop-in 反检测浏览器

# ==================== 配置项 ====================
TARGET_URL = "https://dashboard.katabump.com/auth/login"
ACCOUNT_USER = os.getenv("KATABUMP_USER", "your_email@example.com")
ACCOUNT_PASS = os.getenv("KATABUMP_PASS", "your_password")

PROXY_SERVER = os.getenv("PROXY_SERVER", "socks5://127.0.0.1:40000")  # 若无代理可置空 ""
WECHAT_WEBHOOK_KEY = os.getenv("WECHAT_WEBHOOK_KEY", "")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
LICENSE_KEY = os.getenv("CLOAKBROWSER_LICENSE_KEY", "")

VIDEO_DIR = "./videos"
SCREENSHOT_DIR = "./screenshots"

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


# ==================== 工具函数 ====================
def shot(page, name: str):
    """保存屏幕截图"""
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path, full_page=False)
        print(f"📷 截图已保存: {path}")
    except Exception as e:
        print(f"⚠️ 截图失败 {name}: {e}")


def send_wechat(content: str) -> bool:
    """发送企业微信机器人通知"""
    if not WECHAT_WEBHOOK_KEY:
        print("⚠️ 未配置 WECHAT_WEBHOOK_KEY，跳过企微通知")
        return False
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"
    try:
        resp = requests.post(url, json={"msgtype": "text", "text": {"content": content}}, timeout=15)
        result = resp.json()
        return result.get("errcode") == 0
    except Exception as e:
        print(f"❌ 企微发送失败: {e}")
        return False


def pass_turnstile(page, timeout=30) -> bool:
    """自动检测并尝试通过 Cloudflare Turnstile 人机验证"""
    print("🛡️ 检测是否存在 Turnstile 验证框...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 如果 URL 已不包含 auth/login，说明页面已成功跳转
        if "auth/login" not in page.url:
            return True
        
        try:
            iframe = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
            cb = iframe.locator("input[type='checkbox']")
            if cb.count() > 0 and cb.first.is_visible(timeout=1000):
                box = cb.first.bounding_box()
                if box:
                    # 模拟人类轨迹移动并点击
                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=10)
                    time.sleep(0.2)
                    page.mouse.down()
                    time.sleep(0.1)
                    page.mouse.up()
                    print("  👆 已点击 Turnstile 勾选框")
                    time.sleep(2)
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def fill_login_form(page) -> bool:
    """
    针对 Katabump 登录页面的精准表单填充函数
    """
    print("🔍 开始定位并填写登录表单...")
    try:
        # 1. 定位并填写账号框 (#email)
        email_input = page.locator("#email")
        email_input.wait_for(state="visible", timeout=10000)
        email_input.click()
        email_input.fill(ACCOUNT_USER)
        print("  ✅ 已填写账号/邮箱")
        time.sleep(0.3)

        # 2. 定位并填写密码框 (#password)
        password_input = page.locator("#password")
        password_input.click()
        password_input.fill(ACCOUNT_PASS)
        print("  ✅ 已填写密码")
        time.sleep(0.3)

        # 3. 定位并点击提交按钮
        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Log in")').first
        if submit_btn.is_visible(timeout=2000):
            print("  👆 点击登录按钮")
            submit_btn.click()
        else:
            print("  ⚠️ 未寻找到明显提交按钮，按 Enter 键提交")
            password_input.press("Enter")

        return True

    except Exception as e:
        print(f"  ❌ 填写登录表单失败: {e}")
        return False


# ==================== 主流程 ====================
def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    launch_kwargs = {
        "headless": HEADLESS,
        "humanize": True,
        "locale": "zh-CN",
        "args": ["--window-size=1920,1080"],
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
        )
        page = context.new_page()

        print(f"🌐 正在打开登录页: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        shot(page, "01_login_page")

        # 登录前的 Turnstile 拦截处理
        pass_turnstile(page)

        # 执行输入与提交
        if fill_login_form(page):
            page.wait_for_timeout(3000)
            shot(page, "02_after_submit")

            # 提交后可能触发二次 Turnstile 验证
            pass_turnstile(page)

            # 等待最终页面跳转
            page.wait_for_timeout(5000)
            shot(page, "03_final_result")

            current_url = page.url
            if "login" not in current_url:
                print(f"🎉 登录成功！当前页面地址: {current_url}")
                send_wechat(f"✅ Katabump 自动登录成功\n\nURL: {current_url}\n⏰ {now}")
            else:
                print("⚠️ 页面仍处于登录状态，请检查密码或截图确认是否遭遇二次验证/账号错误")
                send_wechat(f"⚠️ Katabump 登录未成功跳转\n\n请检查截图排查错误。\n⏰ {now}")
        else:
            send_wechat(f"❌ Katabump 自动登录失败\n\n无法定位到 #email 或 #password 元素。\n⏰ {now}")

    except Exception as e:
        print(f"❌ 运行过程中发生异常: {e}")
        send_wechat(f"❌ Katabump 脚本运行异常: {e}\n⏰ {now}")

    finally:
        # 关闭 Context 保存视频文件
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
