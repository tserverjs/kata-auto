# 🖥️ Katabump Turnstile 自动化登录与续期监控

本项目基于 Python 与 [CloakBrowser](https://github.com/CloakHQ/cloakbrowser)（基于 Playwright 的反检测浏览器）开发，实现了自动化登录 **Katabump Dashboard** (`dashboard.katabump.com`)、自动绕过 Cloudflare Turnstile 人机验证、进入服务器详情页并触发续期（Renew）。

执行结果、警示信息以及服务器详细信息会集中整合，自动推送至企业微信机器人，并支持通过 GitHub Actions 进行每日定时调度与自动执行。

---

## ✨ 核心特性

- 🛡️ **Cloudflare Turnstile 自动绕过**：结合 CloakBrowser 的反指纹能力与严格的 Token 注入检测，高成功率完成 Turnstile 人机验证。
- 🎯 **精准 UI 定位与弹窗处理**：自动适配 Filament / Laravel 框架的后台页面，精确定位 `#renew-modal` 模态框并自动点击提交。
- ⚠️ **动态警示信息捕抓**：自动捕获并提取未到续期时间时的提示信息（例如：`You can't renew your server yet...`）。
- 📊 **结构化数据提取**：自动读取并解析 `Service information` 卡片内容（包括 **Renew period**、**Expiry**、**Auto renew**、**Price**）。
- 🎨 **视觉化调试与录屏**：
  - 支持 Canvas 最顶层红色波纹点击高亮特效，便于精准跟踪模拟点击轨迹。
  - 自动生成 WebM 操作录像与关键节点截图（以 GitHub Actions Artifacts 形式保存）。
- 🌐 **代理弹性降级**：支持 GOST SOCKS5 代理隧道；若代理连接失败，自动无缝降级为网络直连模式运行。
- ⏰ **北京时间自动对齐**：通知中的执行时间统一对齐为 **北京时间（UTC+8）**。

---

## 📁 目录结构

```text
.
├── renew-auto.py               # 主 Python 自动续期脚本
├── .github/
│   └── workflows/
│       └── renew.yml          # GitHub Actions 工作流配置文件
├── screenshots/               # 调试截图输出目录
├── videos/                    # 操作录屏 (.webm) 输出目录
└── README.md                  # 项目说明文档
```

---

## 🛠️ 本地运行指南

### 1. 基础环境准备
需要 Python 3.10+ 环境（建议使用 Python 3.12）。

```bash
# 1. 克隆仓库
git clone <your-repository-url>
cd <repository-folder>

# 2. 安装 Python 依赖
pip install cloakbrowser requests

# 3. 安装 CloakBrowser 二进制及 Playwright 依赖
python -m cloakbrowser install
python -m playwright install ffmpeg
```

### 2. 设置环境变量

在使用脚本前，请配置以下环境变量：

| 环境变量名 | 必填 | 默认值 | 描述 |
| :--- | :---: | :---: | :--- |
| `KATABUMP_USER` | **是** | - | Katabump 账号邮箱 |
| `KATABUMP_PASS` | **是** | - | Katabump 账号密码 |
| `WECHAT_WEBHOOK_KEY` | 否 | `""` | 企业微信机器人的 Webhook Key |
| `PROXY_SERVER` | 否 | `socks5://127.0.0.1:40000` | SOCKS5/HTTP 代理服务地址（置空则直连） |
| `HEADLESS` | 否 | `false` | 是否开启无头模式（建议使用 `false` 配合 xvfb 运行） |
| `CLOAKBROWSER_LICENSE_KEY` | 否 | `""` | CloakBrowser 授权密钥（可选） |

### 3. 运行脚本

```bash
# Linux 环境下建议通过 xvfb 虚拟显示运行
xvfb-run -a --server-args="-screen 0 1920x1080x24" python renew-auto.py
```

---

## 🚀 GitHub Actions 自动化部署

仓库已包含 `.github/workflows/renew.yml`，支持每日自动运行与手动触发。

### 1. 配置 GitHub Secrets

进入 GitHub 仓库：**Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**，添加以下配置：

- `KATABUMP_USER`: 你的 Katabump 账号邮箱
- `KATABUMP_PASS`: 你的 Katabump 账号密码
- `WECHAT_WEBHOOK_KEY`: 企业微信机器人的 Webhook Key
- `GOST_PROXY` *(可选)*: GOST 代理节点地址（例：`relay+tls://user:pass@example.com:8443`）
- `CLOAKBROWSER_LICENSE_KEY` *(可选)*: CloakBrowser 许可证

### 2. 工作流运行配置 (`renew.yml`)

```yaml
name: 🖥️ katabump Turnstile 自动续期（CloakBrowser）

on:
  schedule:
    - cron: '0 2 * * *'  # 每天 UTC 02:00 (北京时间 10:00) 执行
  workflow_dispatch:

env:
  TZ: Asia/Shanghai      # 全局配置为北京时间时区

jobs:
  monitor:
    runs-on: ubuntu-latest

    steps:
      - name: 📥 Checkout repository
        uses: actions/checkout@v4

      - name: 🐍 Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: 📦 安装系统依赖（xvfb + 中文字体 + Chromium 运行库）
        run: |
          sudo apt-get update
          sudo apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei
          sudo apt-get install -y xvfb libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
            libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
            libgbm1 libasound2t64 libpango-1.0-0 libcairo2 libatspi2.0-0

      - name: 📦 安装 Python 依赖 + 预下载 CloakBrowser 二进制
        run: |
          pip install cloakbrowser requests
          python -m cloakbrowser install
          python -m playwright install ffmpeg

      - name: 🌐 启动 GOST 代理隧道（支持失败自动降级直连）
        id: proxy_setup
        env:
          GOST_PROXY: ${{ secrets.GOST_PROXY }}
        run: |
          USE_PROXY="false"
          if [ -n "${GOST_PROXY}" ]; then
            echo "🔍 检测到 GOST_PROXY 配置，尝试启动隧道..."
            GOST_VERSION=$(curl -s [https://api.github.com/repos/go-gost/gost/releases/latest](https://api.github.com/repos/go-gost/gost/releases/latest) | grep '"tag_name"' | cut -d'"' -f4 | tr -d 'v')
            echo "📦 GOST 版本: $GOST_VERSION"
            wget -q "[https://github.com/go-gost/gost/releases/download/v$](https://github.com/go-gost/gost/releases/download/v$){GOST_VERSION}/gost_${GOST_VERSION}_linux_amd64.tar.gz"
            tar -xzf gost_${GOST_VERSION}_linux_amd64.tar.gz
            chmod +x ./gost
            nohup ./gost -L socks5://127.0.0.1:40000 -F "${GOST_PROXY}" > gost.log 2>&1 &
            sleep 6
            
            EXIT_IP=$(curl -s --max-time 6 --proxy socks5://127.0.0.1:40000 [https://api.ipify.org](https://api.ipify.org) || true)
            if [ -n "${EXIT_IP}" ]; then
              echo "✅ 代理节点连通成功，出口 IP: ${EXIT_IP}"
              USE_PROXY="true"
            else
              echo "⚠️ GOST 代理隧道连接失败，自动降级为【直连模式】..."
            fi
          else
            echo "ℹ️ 未配置 GOST_PROXY，直接使用【直连模式】"
          fi

          if [ "$USE_PROXY" = "true" ]; then
            echo "PROXY_SERVER=socks5://127.0.0.1:40000" >> $GITHUB_ENV
          else
            echo "PROXY_SERVER=" >> $GITHUB_ENV
          fi

      - name: 🔍 运行 katabump 监控续期脚本（xvfb + headed 模式）
        env:
          KATABUMP_USER: ${{ secrets.KATABUMP_USER }}
          KATABUMP_PASS: ${{ secrets.KATABUMP_PASS }}
          WECHAT_WEBHOOK_KEY: ${{ secrets.WECHAT_WEBHOOK_KEY }}
          CLOAKBROWSER_LICENSE_KEY: ${{ secrets.CLOAKBROWSER_LICENSE_KEY }}
          HEADLESS: "false"
        run: |
          echo "⏰ 当前运行时间（北京时间）：$(date)"
          echo "🌐 代理配置状态: ${PROXY_SERVER:-直连}"
          xvfb-run -a --server-args="-screen 0 1920x1080x24" python renew-auto.py

      - name: 📷 上传调试截图
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: katabump-screenshots-${{ github.run_id }}
          path: "screenshots/*.png"
          retention-days: 5

      - name: 🎬 上传操作录屏
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: katabump-video-${{ github.run_id }}
          path: "videos/*.webm"
          retention-days: 7
```

---

## 📬 推送示例（企业微信）

工作流运行完成后，企业微信机器人将收到如下格式的消息通知：

```text
━━━━━━━━━━━━━━━━━━━━
🤖 Katabump 服务器自动续期通知
📊 续期操作结果：⚠️ 续期受限/未到时间
━━━━━━━━━━━━━━━━━━━━
⚠️ 提示信息：
You can't renew your server yet. You will be able to as of 11 October (in 2 day(s)).
━━━━━━━━━━━━━━━━━━━━
🖥️ 【Service Information 详细信息】
• Renew period: Every 4 days
• Expiry: 2026-10-12
• Auto renew: Non
• Price: 0 crédits
━━━━━━━━━━━━━━━━━━━━
⏰ 执行时间（北京时间）：2026-10-09 21:27:38
```
