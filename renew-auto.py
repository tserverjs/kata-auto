#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 自动登录与服务器续期监控脚本（CloakBrowser 全局特效版）
- 修复：使用 page.add_init_script 实现跨页面持久化红色涟漪点击特效
- 自动处理 Cloudflare Turnstile 人机验证
- 自动进入 "Your servers" 列表并点击 "See" 进入服务器详情页
- 自动点击 "Renew" 按钮（含 Modal 弹窗处理）完成服务器续期
- 自动提取 "Service information" 卡片内容并推送企业微信机器人
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


# ==================== 持久化点击高亮特效 ====================
INIT_RIPPLE_JS = """
window.showClickRipple = function(x, y) {
    try {
        const circle = document.createElement('div');
        circle.style.position = 'fixed';
        circle.style.left = (x - 15) + 'px';
        circle.style.top = (y - 15) + 'px';
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
    } catch (e) {
        console.error('Ripple error:', e);
    }
};
"""


def trigger_ripple(page, x: float, y: float):
    """调用页面全局绑定的 showClickRipple 函数"""
    try:
        page.evaluate(f"window.showClickRipple && window.showClickRipple({x}, {y})")
    except Exception:
        pass


def visual_click(page, x: float, y: float):
    """带红色涟漪特效的模拟点击"""
    page.mouse.move(x, y, steps=12)
    time.sleep(0.1)
    trigger_ripple(page, x, y)
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

    print("  ⚠️ Turnstile 验证超时或未生成 Token")
    return False


# ==================== 智能定位与点击 Renew 按钮 ====================
def locate_and_click_renew(page) -> bool:
    """多策略寻找并点击 Renew 按钮（处理异步加载与 Confirm 弹窗）"""
    print("🔍 正在检索 Renew 按钮...")
    
    renew_selectors = [
        'button:has-text("Renew")',
        'a:has-text("Renew")',
        '[aria-label*="Renew" i]',
        'button:has-text("续期")',
        'a:has-text("续期")',
        'button.btn-primary:has-text("Renew")',
        'a.btn:has-text("Renew")',
        'button[wire\\:click*="renew"]',
        'a[href*="renew"]'
    ]

    deadline = time.time() + 12
    renew_target = None

    while time.time() < deadline:
        for sel in renew_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    renew_target = loc
                    print(f"  ✅ 成功匹配到 Renew 选择器: {sel}")
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
        box = renew_target.bounding_box()
        if box:
            print(f"  🎯 点击 Renew 按钮，坐标: ({box['x']:.1f}, {box['y']:.1f})")
            visual_click(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        else:
            renew_target.click()
        
        time.sleep(1.5)

        # 检查二次确认 Modal
        confirm_selectors = [
            'div[role="dialog"] button:has-text("Confirm")',
            'div[role="dialog"] button:has-text("Yes")',
            'div[role="dialog"] button:has-text("Renew")',
            '.modal-footer button:has-text("Confirm")',
            'button:has-text("Confirm")'
        ]
        for c_sel in confirm_selectors:
            try:
                c_btn = page.locator(c_sel).first
                if c_btn.is_visible(timeout=1000):
                    c_box = c_btn.bounding_box()
                    print(f"  👆 触发 Modal 确认按钮点击: {c_sel}")
                    if c_box:
                        visual_click(page, c_box["x"] + c_box["width"] / 2, c_box["y"] + c_box["height"] / 2)
                    else:
                        c_btn.click()
                    break
            except Exception:
                pass

        return True

    except Exception as e:
        print(f"  ❌ 点击 Renew 过程中发生错误: {e}")
        return False


# ==================== 信息解析与格式化 ====================
def extract_service_info(page) -> str:
    """提取 Service information 卡片信息"""
    try:
        card_locator = page.locator('*:has-text("Service information")').last
        if card_locator.is_visible(timeout=3000):
            card_text = card_locator.inner_text()
            return card_text
    except Exception:
        pass
    return body_text(page)


def format_wechat_msg(raw_info: str, renew_status: str, now: str) -> str:
    """格式化企业微信消息"""
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
        
        # 🔑 【关键步骤】全局绑定涟漪函数：确保无论跳转/刷新到哪个页面，涟漪函数均有效
        context.add_init_script(INIT_RIPPLE_JS)

        page = context.new_page()

        # ---------------- 1. 打开并登录 ----------------
        print(f"🌐 打开登录页: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        shot(page, "01_login_page")

        # 填写账号密码
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
            send_wechat(f"❌ Katabump 登录失败\n\n未能跳转 Dashboard。\n⏰ {now}")
            return

        # ---------------- 2. 点击 See 进入详情页 ----------------
        print("🔍 查找 Your servers 中的 'See' 按钮...")
        see_btn = page.locator('a:has-text("See"), button:has-text("See")').first
        see_btn.wait_for(state="visible", timeout=15000)

        box_see = see_btn.bounding_box()
        if box_see:
            visual_click(page, box_see["x"] + box_see["width"] / 2, box_see["y"] + box_see["height"] / 2)
        else:
            see_btn.click()

        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(4000)
        shot(page, "04_server_detail_page")

        # ---------------- 3. 点击 Renew 按钮 ----------------
        renew_clicked = locate_and_click_renew(page)
        
        if renew_clicked:
            time.sleep(2.0)
            ensure_turnstile_passed(page, timeout=25)
            page.wait_for_timeout(4000)
            shot(page, "05_after_renew")
            renew_status = "✅ 续期操作已成功点击并提交"
        else:
            shot(page, "05_no_renew_found")
            renew_status = "ℹ️ 未发现 Renew 按钮（状态正常或未到续期时间）"

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
