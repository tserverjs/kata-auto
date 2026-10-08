#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 自动登录脚本（CloakBrowser 版）- 修复版
- 解决中文乱码（强制 UTF-8 编码与字体设置）
- 严格等待 Turnstile 验证通过（生成 Token）后再执行登录提交
- 带有红色涟漪点击特效与 WebM 视频录制
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


def send_wechat(content: str) -> bool:
    """企业微信通知"""
    if not WECHAT_WEBHOOK_KEY:
        print("⚠️ 未配置 WECHAT_WEBHOOK_KEY，跳过企微通知")
        return False
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"
    try:
        resp = requests.post(url, json={"msgtype": "text", "text": {"content": content}}, timeout=15)
        return resp.json().get("errcode") == 0
    except Exception as e:
        print(f"❌ 企微发送失败: {e}")
        return False


# ==================== Turnstile 严格验证 ====================
def ensure_turnstile_passed(page, timeout=40) -> bool:
    """
    寻找并点击 Turnstile 复选框，并【阻塞等待】直至 Token 注入成功
    """
    print("🛡️ 开始进行 Turnstile 验证拦截与等待...")
    deadline = time.time() + timeout
    clicked = False

    while time.time() < deadline:
        # 1. 判断 token 框内是否已经存在生成的凭证
        try:
            token_input = page.locator('input[name="cf-turnstile-response"]')
            if token_input.count() > 0:
                token_val = token_input.first.get_attribute("value")
                if token_val and len(token_val) > 20:
                    print("  🎉 Turnstile 验证彻底完成（Token 注入成功）")
                    return True
        except Exception:
            pass

        # 2. 若还未点击且发现了复选框，进行点击
        if not clicked:
            try:
                iframe = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
                cb = iframe.locator("input[type='checkbox']")

                if cb.count() > 0 and cb.first.is_visible(timeout=1000):
                    box = cb.first.bounding_box()
                    if box:
                        click_x = box["x"] + box["width"] / 2
                        click_y = box["y"] + box["height"] / 2
                        print(f"  🎯 发现复选框，触发红色涟漪点击: ({click_x:.1f}, {click_y:.1f})")
                        visual_click(page, click_x, click_y)
                        clicked = True  # 标记已点击，后续仅等待 token 填充
            except Exception:
                pass

        time.sleep(1)

    print("  ❌ Turnstile 验证超时，Token 未生成")
    return False


# ==================== 主流程 ====================
def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 包含中文字符集与语言设置，解决乱码问题
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
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},  # 强制中文语言包
        )
        page = context.new_page()

        print(f"🌐 打开登录页: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        shot(page, "01_login_page")

        # 步骤 1：先填写邮箱和密码
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

        print("⌨️ 尝试 Tab + Space 聚焦并勾选 Turnstile...")
        password_input.press("Tab")
        time.sleep(0.3)
        password_input.press("Tab")
        time.sleep(0.3)
        password_input.press("Tab")
        time.sleep(0.3)
        page.keyboard.press("Space")
        time.sleep(1.5)
        # 步骤 2：严格等待 Turnstile 勾选并获取到 Token
        turnstile_ok = ensure_turnstile_passed(page, timeout=35)
        shot(page, "02_turnstile_check")

        if not turnstile_ok:
            print("⚠️ 警告：Turnstile 尚未通过，暂停提交以防登录失败。")
            send_wechat(f"❌ Katabump 登录失败\n\nCloudflare 验证未通过。\n⏰ {now}")
            return

        # 步骤 3：验证通过后再点击 Login 提交
        print("👆 Turnstile 已确认通过，准备点击登录按钮...")
        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Log in")').first
        if submit_btn.is_visible(timeout=3000):
            box_submit = submit_btn.bounding_box()
            if box_submit:
                visual_click(page, box_submit["x"] + box_submit["width"] / 2, box_submit["y"] + box_submit["height"] / 2)
            else:
                submit_btn.click()
        else:
            password_input.press("Enter")

        page.wait_for_timeout(5000)
        shot(page, "03_final_result")

        current_url = page.url
        if "login" not in current_url:
            print(f"🎉 登录成功！当前 URL: {current_url}")
            send_wechat(f"✅ Katabump 自动登录成功\n\nURL: {current_url}\n⏰ {now}")
        else:
            print("⚠️ 仍处于登录页面，请检查截图或录像确认具体原因。")
            send_wechat(f"⚠️ Katabump 登录未成功跳转\n\n请检查截图排查错误。\n⏰ {now}")

    except Exception as e:
        print(f"❌ 运行发生异常: {e}")
        send_wechat(f"❌ Katabump 脚本运行异常: {e}\n⏰ {now}")

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
