# AIVA Solana Intelligence Bot — 完整部署文档

## 目录

1. [项目简介](#1-项目简介)
2. [功能列表](#2-功能列表)
3. [准备工作](#3-准备工作)
4. [本地运行](#4-本地运行)
5. [云端部署（推荐）](#5-云端部署推荐)
6. [配置说明](#6-配置说明)
7. [收益与回购机制](#7-收益与回购机制)
8. [运营指南](#8-运营指南)
9. [常见问题](#9-常见问题)

---

## 1. 项目简介

AIVA Bot 是一个 Telegram 智能机器人，提供 Solana 链上实时数据服务：

- 🐳 大额交易鲸鱼预警
- 🆕 Pump.fun 新币监控
- 📈 代币趋势榜
- 💹 任意代币价格查询
- 👛 钱包资产分析
- 🌐 Solana 网络状态

**变现机制**：
- 免费用户：每天 10 次查询
- 高级用户：150 Telegram Stars/月（约 $2）= 无限查询 + 实时播报
- **持有 100K+ $AIVA 代币 = 免费解锁高级功能**

**收益回购**：累计收益达到阈值后，自动触发 Pump.fun Tokenized Agents 回购 $AIVA，形成正向飞轮。

---

## 2. 功能列表

| 命令 | 说明 | 权限 |
|------|------|------|
| `/start` | 欢迎界面 + 快捷按钮 | 所有人 |
| `/help` | 完整帮助文档 | 所有人 |
| `/price <token>` | 代币价格查询 | 免费（计配额） |
| `/aiva` | $AIVA 价格和信息 | 免费（计配额） |
| `/trending` | Top 10 热门代币 | 免费（计配额） |
| `/newcoins` | Pump.fun 新币 | 免费（计配额） |
| `/whale` | 鲸鱼大额交易 | 免费（计配额） |
| `/wallet <地址>` | 钱包资产分析 | 免费（计配额） |
| `/network` | 网络 TPS/Gas | 免费（计配额） |
| `/gas` | 快速Gas查询 | 免费（计配额） |
| `/verify <钱包>` | AIVA持币验证 | 所有人 |
| `/premium` | 升级高级版 | 所有人 |
| `/plan` | 查看当前套餐 | 所有人 |
| `/buy` | 如何购买$AIVA | 所有人 |

---

## 3. 准备工作

### 3.1 创建 Telegram Bot

1. 打开 Telegram，搜索 **@BotFather**
2. 发送 `/newbot`
3. 设置 Bot 名称：`AIVA Solana Intelligence`
4. 设置用户名：`AIVADataBot`（或其他未被占用的名称）
5. 复制获得的 **Bot Token**（格式：`123456789:ABCdefGHI...`）
6. 发送 `/setpayments` 开启 Telegram Stars 支付（选择 Stars）
7. 发送 `/setcommands` 批量设置命令列表（可选，提升体验）：

```
start - 主菜单
help - 帮助文档
price - 查询代币价格
aiva - AIVA代币信息
trending - 热门代币榜单
newcoins - Pump.fun新币预警
whale - 鲸鱼大额交易
wallet - 钱包资产分析
network - 网络状态
gas - Gas费用
verify - AIVA持币验证
premium - 升级高级版
plan - 我的套餐
buy - 购买AIVA
```

### 3.2 获取 Helius API Key（免费）

1. 访问 https://helius.dev
2. 点击 "Get Started Free"，用邮箱注册
3. 创建项目，选择 Mainnet
4. 复制 **API Key**

**免费套餐限额**：
- 每月 1,000,000 Credits（约 100 万次基础调用）
- 足够支撑前期运营

### 3.3 获取 Birdeye API Key（免费）

1. 访问 https://birdeye.so/developers
2. 注册账号，生成 API Key
3. 免费套餐：每月 50,000 次调用

> 💡 **注意**：如果 Birdeye 无法获取，趋势榜功能会自动降级使用 DexScreener（完全免费，无需 key）

---

## 4. 本地运行

### 4.1 安装 Python 3.10+

确认版本：
```bash
python --version
```

### 4.2 安装依赖

```bash
cd C:\tmp_aiva\aiva_bot
pip install -r requirements.txt
```

### 4.3 填写配置

打开 `config.py`，填入你的：

```python
TELEGRAM_BOT_TOKEN = "你的BotToken"
HELIUS_API_KEY     = "你的Helius_API_Key"
BIRDEYE_API_KEY    = "你的Birdeye_API_Key（可以先留空）"
```

### 4.4 启动 Bot

```bash
python main.py
```

看到以下输出说明启动成功：
```
[DB] 数据库初始化完成
✅ 后台任务已启动
✅ 所有处理器已注册，Bot 开始运行
```

然后在 Telegram 找到你的 Bot，发送 `/start` 测试。

---

## 5. 云端部署（推荐）

本地运行需要电脑一直开着。推荐部署到云端，24小时不停机。

### 方案 A：Railway（最简单，免费额度够用）

1. 注册 https://railway.app
2. 新建项目，选择 "Deploy from GitHub"
3. 把代码传到 GitHub（**注意：config.py 在 .gitignore 里，不要上传**）
4. 在 Railway 的 Variables 里设置环境变量：
   - `TELEGRAM_BOT_TOKEN` = 你的Token
   - `HELIUS_API_KEY` = 你的Key
   - `BIRDEYE_API_KEY` = 你的Key

5. 修改 `config.py`，从环境变量读取：
```python
import os
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
HELIUS_API_KEY     = os.environ.get("HELIUS_API_KEY", "")
BIRDEYE_API_KEY    = os.environ.get("BIRDEYE_API_KEY", "")
```

6. 添加 `Procfile`（告诉 Railway 如何启动）：
```
worker: python main.py
```

### 方案 B：VPS 部署（稳定，月费约 $5）

推荐 DigitalOcean / Vultr / Hetzner

```bash
# 上传代码到服务器
scp -r C:\tmp_aiva\aiva_bot root@your_server_ip:/opt/aiva_bot

# 在服务器上
cd /opt/aiva_bot
pip install -r requirements.txt

# 用 screen 保持后台运行
screen -S aiva_bot
python main.py
# Ctrl+A, Ctrl+D 退出 screen

# 或者用 systemd（更专业）
cat > /etc/systemd/system/aiva_bot.service << EOF
[Unit]
Description=AIVA Telegram Bot

[Service]
WorkingDirectory=/opt/aiva_bot
ExecStart=/usr/bin/python3 main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl enable aiva_bot
systemctl start aiva_bot
```

---

## 6. 配置说明

### 核心参数（config.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `FREE_DAILY_CALLS` | 10 | 免费用户每天查询次数 |
| `PREMIUM_PRICE_STARS` | 150 | 高级版价格（Stars） |
| `WHALE_ALERT_MIN_USD` | 10000 | 鲸鱼预警最低金额 |
| `NEW_TOKEN_MIN_LIQUIDITY` | 500 | 新币最低流动性（USD） |
| `TRENDING_TOP_N` | 10 | 趋势榜显示数量 |
| `BROADCAST_CHANNEL_ID` | 空 | 播报频道 ID（选填） |

### 开启频道自动播报

1. 创建 Telegram 频道（如 "AIVA Alerts"）
2. 把你的 Bot 添加为频道管理员
3. 获取频道 ID（方法：把任意消息转发给 @userinfobot）
4. 填入 `config.py`：
```python
BROADCAST_CHANNEL_ID = "-1001234567890"
```
5. 重启 Bot，大额交易和新币会自动播报到频道

---

## 7. 收益与回购机制

### 收入来源

| 来源 | 金额 | 说明 |
|------|------|------|
| 高级会员 | 150 Stars/月 ≈ $2 | Telegram Stars 直接到账 |
| 早期用户 10人 | $20/月 | 第一阶段目标 |
| 用户 100人 | $200/月 | 第二阶段目标 |
| 用户 1000人 | $2000/月 | 成熟阶段 |

### 回购机制

1. Bot 累计收益超过 0.1 SOL（在 `config.py` 的 `BUYBACK_THRESHOLD_SOL` 设置）
2. 系统自动记录日志提醒
3. 前往 Pump.fun 的 **Tokenized Agents** 界面
4. 设置回购比例（建议 30%）
5. 每次有收益，自动买入 $AIVA，拉升价格

### 正向飞轮

```
Bot 用户增加 → 订阅收入增加 → 自动回购 $AIVA → 价格上涨
     ↑                                              ↓
$AIVA 持币用户获得免费 Premium ← 更多人买 $AIVA ←
```

---

## 8. 运营指南

### 推广策略

**第一周**：先在 Telegram 群里推广 Bot
```
🤖 FREE Solana Intelligence Bot!

✅ Real-time whale alerts
✅ Pump.fun new coin alerts  
✅ Token prices & wallet analysis
✅ Network status & gas fees

Free: 10 queries/day
Premium: 150 Stars/month ($2)
💎 Hold 100K $AIVA = FREE premium!

Try it: @AIVADataBot
```

**推特推文**：
```
🚀 Introducing @AIVADataBot

Your FREE Solana intelligence bot!

✅ Whale alerts
✅ New Pump.fun launches
✅ Token prices & trends
✅ Wallet analysis

Hold 100K $AIVA = FREE premium access 💎
CA: FMKA3FQBu5qqPLxAvf7YTpmP3GpLsSENQYu4xJ72pump

Try now: t.me/AIVADataBot
```

### 每周维护

- 检查 Helius API 余额（避免超限）
- 查看 Bot 的用户统计（运行 `/admin` 命令，如需添加）
- 查看收益并决定是否手动触发回购

---

## 9. 常见问题

### Q: Bot 收到消息但不回复？
A: 检查 `TELEGRAM_BOT_TOKEN` 是否正确，确认 Bot 没有被限制。

### Q: 趋势榜显示空白？
A: Birdeye API Key 可能失效，Bot 会自动使用 DexScreener 备用接口。

### Q: 鲸鱼预警没有推送？
A: 需要填写 `BROADCAST_CHANNEL_ID`，并且 Bot 需要是频道管理员。

### Q: 支付按钮无效？
A: 确认在 BotFather 开启了 Stars 支付；另外支付功能只在私聊中有效。

### Q: 如何查看有多少用户？
A: 数据库文件 `aiva_bot.db` 存储所有数据，可以用 SQLite Browser 工具查看。

---

*AIVA Bot — Powered by $AIVA on Solana*  
*CA: FMKA3FQBu5qqPLxAvf7YTpmP3GpLsSENQYu4xJ72pump*
