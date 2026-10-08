#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 自动登录脚本（CloakBrowser 版）
- 支持 Cloudflare Turnstile 复选框自动识别与类人点击
- 包含红色涟漪（Red Ripple）点击视觉特效，便于观察定位精度
- 使用精准 DOM 选择器（#email, #password）进行表单填充
- 支持全流程截图与 WebM 视频录制，支持企微通知
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


# ==================== 可视化点击特效 ====================
def show_click_ripple(page, x: float, y: float):
    """
    在指定坐标 (x, y) 动态注入一个红色的涟漪波纹，方便观察点击位置
    """
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
    """带红色涟漪特效的平滑移动与点击"""
    # 模拟人类轨迹移动到目标坐标
    page.mouse.move(x, y, steps=12)
    time.sleep(0.1)
    # 显示红色涟漪视觉反馈
    show_click_ripple(page, x, y)
    time.sleep(0.15)
    # 执行实际点击
    page.mouse.down()
    time.sleep(0.08)
    page.mouse.up()


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
        return resp.json().get("errcode") == 0
    except Exception as e:
        print(f"❌ 企微发送失败: {e}")
        return False


# ==================== Turnstile 自动点击 ====================
def pass_turnstile(page, timeout=30) -> bool:
    """
    自动寻找并点击 Cloudflare Turnstile 复选框，带有红色涟漪视觉效果
    """
    print("🛡️ 检测并尝试点击 Turnstile 验证框...")
    deadline = time.time() + timeout

    while time.time() < deadline:
        # 1. 优先校验 Token 是否已经自动生成
        try:
            token_input = page.locator('input[name="cf-turnstile-response"]')
            if token_input.count() > 0:
                token_val = token_input.first.get_attribute("value")
                if token_val and len(token_val) > 10:
                    print("  ✅ Turnstile 验证已成功通过（已获取 Token）")
                    return True
        except Exception:
            pass

        # 2. 定位 iframe 内的复选框并点击
        try:
            iframe = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
            cb = iframe.locator("input[type='checkbox']")

            if cb.count() > 0 and cb.first.is_visible(timeout=1000):
                box = cb.first.bounding_box()
                if box:
                    # 计算绝对点击坐标
                    click_x = box["x"] + box["width"] / 2
                    click_y = box["y"] + box["height"] / 2
                    print(f"  🎯 找到 Turnstile 复选框坐标: ({click_x:.1f}, {click_y:.1f})，准备点击...")

                    # 带红色涟漪效果的点击
                    visual_click(page, click_x, click_y)
                    time.sleep(2)
        except Exception as e:
            pass

        time.sleep(1)

    print("  ⚠️ Turnstile 验证在超时时间内未完全通过")
    return False


# ==================== 登录表单填充 ====================
def fill_login_form(page) -> bool:
    """针对 Katabump 登录页面的表单填充函数（带红色涟漪点击）"""
    print("🔍 开始定位并填写登录表单...")
    try:
        # 1. 定位并填写账号框 (#email)
        email_input = page.locator("#email")
        email_input.wait_for(state="visible", timeout=10000)
        box_email = email_input.bounding_box()
        if box_email:
            visual_click(page, box_email["x"] + box_email["width"] / 2, box_email["y"] + box_email["height"] / 2)
        email_input.fill(ACCOUNT_USER)
        print("  ✅ 已填写账号/邮箱")
        time.sleep(0.3)

        # 2. 定位并填写密码框 (#password)
        password_input = page.locator("#password")
        box_pass = password_input.bounding_box()
        if box_pass:
            visual_click(page, box_pass["x"] + box_pass["width"] / 2, box_pass["y"] + box_pass["height"] / 2)
        password_input.fill(ACCOUNT_PASS)
        print("  ✅ 已填写密码")
        time.sleep(0.3)

        # 3. 定位并点击提交按钮
        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Log in")').first
        if submit_btn.is_visible(timeout=2000):
            box_submit = submit_btn.bounding_box()
            if box_submit:
                print("  👆 红色涟漪高亮并点击登录按钮")
                visual_click(page, box_submit["x"] + box_submit["width"] / 2, box_submit["y"] + box_submit["height"] / 2)
            else:
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

        # 1. 检测并自动点击 Turnstile 验证框
        pass_turnstile(page, timeout=20)

        # 2. 填写表单并点击提交按钮
        if fill_login_form(page):
            page.wait_for_timeout(3000)
            shot(page, "02_after_submit")

            # 3. 提交后如果遭遇二次质询，再次处理 Turnstile
            pass_turnstile(page, timeout=15)

            # 等待最终结果
            page.wait_for_timeout(5000)
            shot(page, "03_final_result")

            current_url = page.url
            if "login" not in current_url:
                print(f"🎉 登录成功！当前页面地址: {current_url}")
                send_wechat(f"✅ Katabump 自动登录成功\n\nURL: {current_url}\n⏰ {now}")
            else:
                print("⚠️ 页面仍处于登录状态，请排查截图或录像")
                send_wechat(f"⚠️ Katabump 登录未成功跳转\n\n请检查截图排查错误。\n⏰ {now}")
        else:
            send_wechat(f"❌ Katabump 自动登录失败\n\n无法定位输入元素。\n⏰ {now}")

    except Exception as e:
        print(f"❌ 运行过程中发生异常: {e}")
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
