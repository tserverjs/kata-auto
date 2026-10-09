#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Katabump 自动登录与服务器续期监控脚本（动态 Alert 捕获与北京时间版）
- 修复：模态框提交后显式等待 .alert 动态生成，精准抓取未到续期时间提示
- 完整提取 Service Information 参数（Expiry, Renew period, Auto renew, Price）
- 消息统一格式化，包含续期状态、提示信息与服务器属性，发送至企微
- 执行时间统一转换为北京时间 (UTC+8)
"""
import os
import time
import glob
from datetime import datetime, timezone, timedelta

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


# ==================== 获取北京时间 ====================
def get_beijing_time_str() -> str:
    """获取当前北京时间 (UTC+8) 格式化字符串"""
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")


# ==================== Canvas 全局最顶层点击高亮特效 ====================
INIT_CANVAS_RIPPLE_JS = """
window.drawClickRipple = function(x, y) {
    try {
        let canvas = document.getElementById('global-click-ripple-canvas');
        if (!canvas) {
            canvas = document.createElement('canvas');
            canvas.id = 'global-click-ripple-canvas';
            canvas.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:2147483647;';
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
            document.documentElement.appendChild(canvas);
        }
        const ctx = canvas.getContext('2d');
        let radius = 10;
        let opacity = 1.0;

        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            if (opacity <= 0) return;

            ctx.beginPath();
            ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(255, 0, 0, ${opacity * 0.5})`;
            ctx.fill();

            ctx.beginPath();
            ctx.arc(x, y, radius + 2, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(255, 0, 0, ${opacity})`;
            ctx.lineWidth = 3;
            ctx.stroke();

            radius += 1.5;
            opacity -= 0.04;
            requestAnimationFrame(animate);
        }
        animate();
    } catch(e) {
        console.error('Ripple Canvas Error:', e);
    }
};
"""


def trigger_ripple(page, x: float, y: float):
    """通过 Canvas 绘制全局红色透明圆圈与扩散动画"""
    try:
        page.evaluate(f"window.drawClickRipple && window.drawClickRipple({x}, {y})")
    except Exception:
        pass


def visual_click_locator(page, locator) -> bool:
    """带 Canvas 红色圆圈特效的模拟点击"""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
        time.sleep(0.3)
        box = locator.bounding_box()
        if box and box["width"] > 0 and box["height"] > 0:
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            print(f"  🎯 触发红色圆圈高亮点击: ({x:.1f}, {y:.1f})")
            page.mouse.move(x, y, steps=10)
            time.sleep(0.1)
            trigger_ripple(page, x, y)
            time.sleep(0.15)
            page.mouse.down()
            time.sleep(0.08)
            page.mouse.up()
            time.sleep(0.2)
            return True
        else:
            locator.click(force=True)
            return True
    except Exception as e:
        print(f"  ⚠️ 坐标点击异常，降级原生点击: {e}")
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
def ensure_turnstile_passed(page, timeout=35) -> bool:
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


# ==================== 动态警示框抓取函数 ====================
def fetch_alert_notice(page) -> str:
    """全面扫描页面及模态框内动态生成的 .alert 节点"""
    alert_selectors = [
        '.alert.alert-danger',
        '.alert.alert-warning',
        '#renew-modal .alert',
        '.alert',
        'div[role="alert"]'
    ]
    for sel in alert_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                for i in range(loc.count()):
                    item = loc.nth(i)
                    if item.is_visible():
                        txt = item.inner_text().strip()
                        if txt:
                            # 过滤换行与多余空格
                            clean_txt = " ".join([line.strip() for line in txt.splitlines() if line.strip()])
                            return clean_txt
        except Exception:
            pass
    return ""


# ==================== 定位与处理 Renew 逻辑 ====================
def locate_and_click_renew(page) -> tuple[bool, str, str]:
    """
    点击 Renew 按钮与模态框确认，并显式等待捕获提交后生成的提示框
    返回值: (是否触发点击, 续期状态简述, 警示/提示详细文本)
    """
    print("🔍 正在精准检索 Renew 按钮...")

    exact_selectors = [
        'button[data-bs-target="#renew-modal"]',
        'button.btn-outline-primary:has-text("Renew")',
        'button[data-bs-toggle="modal"]:has-text("Renew")',
        'button:has-text("Renew")'
    ]

    deadline = time.time() + 10
    renew_target = None

    while time.time() < deadline:
        for sel in exact_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible() and loc.is_enabled():
                    renew_target = loc
                    print(f"  ✅ 成功定位到 Renew 按钮，选择器: {sel}")
                    break
            except Exception:
                pass
        if renew_target:
            break
        time.sleep(1)

    if not renew_target:
        print("  ⚠️ 未寻找到有效的 Renew 按钮")
        return False, "未找到 Renew 按钮", ""

    try:
        # 1. 点击外层 Renew 按钮打开模态框
        visual_click_locator(page, renew_target)
        time.sleep(2.0)
        shot(page, "05_renew_modal_opened")

        # 2. 点击 Modal 弹窗内的提交确认按钮
        print("🔍 寻找 #renew-modal 内部确认提交按钮...")
        modal_confirm_selectors = [
            '#renew-modal button[type="submit"]',
            '#renew-modal button:has-text("Renew")',
            '#renew-modal button:has-text("Confirm")',
            '#renew-modal button.btn-primary'
        ]

        for m_sel in modal_confirm_selectors:
            try:
                m_btn = page.locator(m_sel).first
                if m_btn.is_visible(timeout=1500):
                    print(f"  👆 点击 Modal 确认按钮: {m_sel}")
                    visual_click_locator(page, m_btn)
                    break
            except Exception:
                pass

        # 3. 【关键修复】显式等待后端检测生成的 alert 提示元素出现
        print("⏳ 正在等待点击后的 Alert 提示节点动态生成...")
        try:
            page.locator('.alert.alert-danger, .alert.alert-warning, div[role="alert"]').first.wait_for(state="visible", timeout=5000)
            print("  ✅ 检测到 Alert 提示节点已生成！")
        except Exception:
            print("  ℹ️ 超时未监听到新的 Alert 节点（可能提交成功或提示样式不同）")

        time.sleep(1.5)

        # 4. 提取生成的 alert 提示文案
        notice_msg = fetch_alert_notice(page)
        if notice_msg:
            print(f"  ⚠️ 成功捕抓到续期提示信息: {notice_msg}")
            status_desc = "⚠️ 续期受限/未到时间" if "can't renew" in notice_msg.lower() else "ℹ️ 续期提示"
            return True, status_desc, notice_msg

        return True, "✅ 续期请求已提交", ""

    except Exception as e:
        print(f"  ❌ 点击 Renew 流程发生错误: {e}")
        return False, "续期执行异常", str(e)


# ==================== 强力异步等待与 Service Info 抓取 ====================
def extract_service_info(page) -> dict:
    """
    等待异步 Ajax 内容呈现后，解析并结构化提取 Service Information 数据
    """
    print("📋 开始抓取 Service Information 结构化数据...")

    # 1. 显式等待核心属性关键字加载完毕（最多等待 8 秒）
    for key_term in ["Expiry", "Renew period", "Auto renew", "Price"]:
        try:
            loc = page.locator(f'*:has-text("{key_term}")').first
            loc.wait_for(state="visible", timeout=8000)
            print(f"  ✅ Service Info 渲染完成，捕获到核心节点: [{key_term}]")
            break
        except Exception:
            pass

    # 2. 定位包含这些信息的最精准 DOM 区域
    raw_text = ""
    try:
        card_selectors = [
            '.card:has-text("Service information")',
            'div:has-text("Service information"):has-text("Expiry")',
            'div:has-text("Renew period")',
            'main'
        ]
        for sel in card_selectors:
            card = page.locator(sel).last
            if card.count() > 0 and card.is_visible():
                t = card.inner_text().strip()
                if "Expiry" in t or "Renew period" in t:
                    raw_text = t
                    print(f"  📋 获取到目标卡片文本:\n{raw_text}")
                    break
    except Exception as e:
        print(f"⚠️ 卡片抓取异常: {e}")

    if not raw_text:
        raw_text = body_text(page)

    # 3. 提取 Key-Value 对
    info = {
        "Renew period": "未知",
        "Expiry": "未知",
        "Auto renew": "未知",
        "Price": "未知"
    }

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        for field in info.keys():
            if field.lower() in line.lower():
                if ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        info[field] = parts[1].strip()
                elif i + 1 < len(lines):
                    next_line = lines[i+1]
                    if not any(k.lower() in next_line.lower() for k in info.keys()):
                        info[field] = next_line

    print(f"📊 结构化提取结果: {info}")
    return info


def format_wechat_msg(notice_msg: str, renew_status: str, service_data: dict, beijing_time_str: str) -> str:
    """组合警示文本与服务器属性，生成完整格式的企业微信推送"""
    msg_lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🤖 Katabump 服务器自动续期通知",
        f"📊 续期操作结果：{renew_status}"
    ]

    # 如果存在警告/提示信息（如：未到续期时间），显示在醒目位置
    if notice_msg:
        msg_lines.extend([
            "━━━━━━━━━━━━━━━━━━━━",
            f"⚠️ 提示信息：\n{notice_msg}"
        ])

    msg_lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "🖥️ 【Service Information 详细信息】",
        f"• Renew period: {service_data.get('Renew period', '未知')}",
        f"• Expiry: {service_data.get('Expiry', '未知')}",
        f"• Auto renew: {service_data.get('Auto renew', '未知')}",
        f"• Price: {service_data.get('Price', '未知')}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⏰ 执行时间（北京时间）：{beijing_time_str}"
    ])

    return "\n".join(msg_lines)


# ==================== 主流程 ====================
def main():
    beijing_now = get_beijing_time_str()

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

        # 全局注册 Canvas 点击高亮特效
        context.add_init_script(INIT_CANVAS_RIPPLE_JS)

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
            send_wechat(f"❌ Katabump 登录失败\n\nCloudflare 验证未通过。\n⏰ 北京时间：{beijing_now}")
            return

        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Log in")').first
        if submit_btn.is_visible(timeout=3000):
            visual_click_locator(page, submit_btn)
        else:
            password_input.press("Enter")

        page.wait_for_timeout(4000)
        shot(page, "03_after_login")

        if "login" in page.url:
            send_wechat(f"❌ Katabump 登录失败\n\n未能跳转 Dashboard。\n⏰ 北京时间：{beijing_now}")
            return

        # ---------------- 2. 点击 See 进入详情页 ----------------
        print("🔍 查找 Your servers 中的 'See' 按钮...")
        see_btn = page.locator('a:has-text("See"), button:has-text("See")').first
        see_btn.wait_for(state="visible", timeout=15000)

        visual_click_locator(page, see_btn)

        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(4000)
        shot(page, "04_server_detail_page")

        # ---------------- 3. 点击 Renew 按钮并捕获提示 ----------------
        renew_clicked, renew_status, notice_msg = locate_and_click_renew(page)

        if renew_clicked:
            time.sleep(2.0)
            ensure_turnstile_passed(page, timeout=20)
            page.wait_for_timeout(3000)
            shot(page, "06_after_renew_result")

        # ---------------- 4. 抓取 Service Info 并合并发送通知 ----------------
        service_data = extract_service_info(page)

        wechat_msg = format_wechat_msg(notice_msg, renew_status, service_data, beijing_now)
        print("📤 即将发送合并后的完整推送文本:\n" + wechat_msg)
        send_wechat(wechat_msg)
        print("✅ 监控全流程顺利完成！")

    except Exception as e:
        print(f"❌ 运行发生异常: {e}")
        send_wechat(f"❌ Katabump 脚本运行异常\n\n错误信息: {e}\n⏰ 北京时间：{beijing_now}")

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
