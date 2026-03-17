"""
main.py — AIVA Solana Intelligence Bot 主程序
启动入口，注册所有命令和回调处理器
"""

import asyncio
import logging
import time
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

import config
import database as db
import solana_data as sol
import messages as msg

# ── DeFi Agent 模块 ───────────────────────────────────────────────
import agent_database as adb
import agent_strategies as strat
import agent_buyback as buyback
import agent_wallet as wallet_mod

# ─────────────────────── 日志 ────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AIVA_BOT")


# ─────────────────────── 通用装饰器 ──────────────────────────────

def with_quota(func):
    """检查配额的装饰器，群聊超限时提示去私聊升级"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        db.ensure_user(user.id, user.username or "", user.first_name or "")
        if not db.check_and_consume_quota(user.id, config.FREE_DAILY_CALLS):
            if is_group_chat(update):
                # 群里超限：简短提示 + 私聊链接
                bot_name = get_bot_username(context)
                await update.message.reply_text(
                    f"⚠️ {user.first_name}, you've used all your free queries for today!\n\n"
                    f"👉 DM [@{bot_name}](https://t.me/{bot_name}) to upgrade Premium for unlimited access ⭐",
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
            else:
                await update.message.reply_text(
                    msg.msg_quota_exceeded(config.FREE_DAILY_CALLS),
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
            return
        return await func(update, context)
    return wrapper


async def safe_reply(update: Update, text: str, reply_markup=None, disable_preview=True):
    """安全发送消息，自动截断超长内容"""
    if len(text) > 4000:
        text = text[:4000] + "\n\n_...truncated_"
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_preview
    )


def is_group_chat(update: Update) -> bool:
    """判断当前消息是否来自群聊"""
    return update.effective_chat.type in ("group", "supergroup")


def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    """获取 Bot 用户名"""
    return context.bot.username or "AIVADataBot"


async def redirect_to_pm(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str = ""):
    """
    Redirect group users to private chat for sensitive operations.
    reason: what action requires PM (e.g. 'upgrade Premium' / 'verify wallet')
    """
    bot_name = get_bot_username(context)
    text = (
        f"👉 Please DM me to {reason}!\n\n"
        f"[@{bot_name}](https://t.me/{bot_name}) — send the same command there"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )


# ─────────────────────── 命令处理器 ──────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username or "", user.first_name or "")

    # 群聊里 /start 只做简短介绍，完整功能引导去私聊
    if is_group_chat(update):
        bot_name = get_bot_username(context)
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm *AIVA Bot* — your Solana on-chain intelligence assistant.\n\n"
            f"🔍 Available commands in this group:\n"
            f"`/price` `/aiva` `/trending` `/newcoins` `/whale` `/network`\n\n"
            f"⭐ Want Premium or FREE access via $AIVA holdings?\n"
            f"👉 DM [@{bot_name}](https://t.me/{bot_name}) to get started",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        return

    is_prem = db.is_premium(user.id)
    keyboard = [
        [InlineKeyboardButton("📈 Trending", callback_data="trending"),
         InlineKeyboardButton("🆕 New Coins", callback_data="newcoins")],
        [InlineKeyboardButton("🌐 Network", callback_data="network"),
         InlineKeyboardButton("🤖 $AIVA", callback_data="aiva")],
        [InlineKeyboardButton("⭐ Premium", callback_data="premium"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        msg.msg_start(user.first_name, is_prem),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup,
        disable_web_page_preview=True
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply(update, msg.HELP_TEXT)


@with_quota
async def cmd_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching Solana network status...")
    data = await sol.get_network_status()
    await safe_reply(update, msg.msg_network(data))


@with_quota
async def cmd_gas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gas 费用快速查询（network 的简化版）"""
    await update.message.reply_text("⏳ Fetching fee estimate...")
    data = await sol.get_network_status()
    fee = data.get("priority_fee", 0)
    fee_sol = fee / 1e9

    if fee > 100000:
        level = "💸 HIGH — consider waiting"
    elif fee > 10000:
        level = "⚠️ MEDIUM"
    else:
        level = "✅ LOW — good time to transact"

    text = (
        f"⚡ *Current Solana Fee Estimate*\n\n"
        f"Priority Fee: `{fee:,} microLamports`\n"
        f"≈ `{fee_sol:.8f} SOL`\n\n"
        f"Status: {level}\n\n"
        f"_Base fee is always 5,000 lamports_\n"
        f"_@AIVABot • Powered by $AIVA_"
    )
    await safe_reply(update, text)


@with_quota
async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Loading trending tokens...")
    tokens = await sol.get_trending_tokens(config.TRENDING_TOP_N)
    if not tokens:
        tokens = await sol.get_trending_dexscreener(config.TRENDING_TOP_N)
    await safe_reply(update, msg.msg_trending(tokens))


@with_quota
async def cmd_newcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Scanning Pump.fun for new launches...")
    tokens = await sol.get_truly_new_tokens(
        min_liquidity=config.NEW_TOKEN_MIN_LIQUIDITY,
        max_age_min=60
    )
    await safe_reply(update, msg.msg_new_coins(tokens))


@with_quota
async def cmd_whale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Scanning whale transactions...")
    txs = await sol.get_recent_large_transactions(
        min_usd=config.WHALE_ALERT_MIN_USD,
        limit=50
    )
    await safe_reply(update, msg.msg_whale_list(txs))


@with_quota
async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update,
            "ℹ️ Usage: `/price <token_symbol_or_contract>`\n\nExamples:\n"
            "`/price SOL`\n"
            "`/price FMKA3FQBu5qqPLxAvf7YTpmP3GpLsSENQYu4xJ72pump`"
        )
        return

    query = context.args[0].strip()

    # AIVA 别名映射到合约地址
    _ALIASES = {
        "AIVA": config.AIVA_CONTRACT,
    }
    query = _ALIASES.get(query.upper(), query)

    await update.message.reply_text(f"⏳ Fetching price for `{query}`...")

    # SOL 特殊处理
    if query.upper() == "SOL":
        price = await sol.get_sol_price()
        text = (
            f"💹 *SOL — Solana*\n\n"
            f"💰 Price: `${price:,.2f}`\n\n"
            f"🔗 [CoinGecko](https://www.coingecko.com/en/coins/solana)\n"
            f"_@AIVABot • Powered by $AIVA_"
        )
        await safe_reply(update, text)
        return

    # 尝试合约地址查询
    data = await sol.get_token_price(query)
    if data:
        await safe_reply(update, msg.msg_token_price(data, mint=query))
    else:
        await safe_reply(update,
            f"⚠️ Could not find price data for `{query}`\n\n"
            "Please provide a valid Solana token contract address.\n"
            "Example: `/price FMKA3FQBu5qqPLxAvf7YTpmP3GpLsSENQYu4xJ72pump`"
        )


@with_quota
async def cmd_aiva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching $AIVA data...")
    data = await sol.get_aiva_price()
    if data:
        await safe_reply(update, msg.msg_aiva_info(data), disable_preview=True)
    else:
        await safe_reply(update,
            f"🤖 *$AIVA — AI Virtual Assistant*\n\n"
            f"Price data temporarily unavailable.\n\n"
            f"📋 CA: `{config.AIVA_CONTRACT}`\n\n"
            f"🔗 [DexScreener](https://dexscreener.com/solana/{config.AIVA_CONTRACT})\n"
            f"🔗 [Pump.fun](https://pump.fun/coin/{config.AIVA_CONTRACT})\n"
            f"🌐 [Website]({config.AIVA_WEBSITE})"
        )


@with_quota
async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update,
            "ℹ️ Usage: `/wallet <solana_address>`\n\n"
            "Example:\n`/wallet 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`"
        )
        return

    wallet_addr = context.args[0].strip()
    if len(wallet_addr) < 32 or len(wallet_addr) > 44:
        await safe_reply(update, "⚠️ Invalid Solana address format. Addresses are 32-44 characters.")
        return

    await update.message.reply_text(f"⏳ Analyzing wallet `{wallet_addr[:8]}...`")
    data = await sol.get_wallet_portfolio(wallet_addr)
    if data:
        await safe_reply(update, msg.msg_wallet(data))
    else:
        await safe_reply(update, "⚠️ Could not fetch wallet data. Please check the address and try again.")


async def cmd_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """验证持有 AIVA 以获取免费高级权限"""
    user = update.effective_user
    db.ensure_user(user.id, user.username or "", user.first_name or "")

    # 群里验证涉及钱包地址，建议去私聊保护隐私
    if is_group_chat(update):
        await redirect_to_pm(update, context, "verify your AIVA holdings 🔒 (keeps your wallet private)")
        return

    if not context.args:
        await safe_reply(update,
            "ℹ️ *Verify AIVA Holdings for Free Premium*\n\n"
            f"Hold 100,000+ $AIVA tokens and get unlimited access!\n\n"
            f"Usage: `/verify <your_solana_wallet>`\n\n"
            f"Buy $AIVA:\n"
            f"[Pump.fun](https://pump.fun/coin/{config.AIVA_CONTRACT})\n"
            f"CA: `{config.AIVA_CONTRACT}`"
        )
        return

    wallet_addr = context.args[0].strip()
    await update.message.reply_text(f"⏳ Checking AIVA balance in `{wallet_addr[:8]}...`")

    holds = await sol.check_aiva_holding(wallet_addr, min_amount=100_000)
    if holds:
        db.set_aiva_verified(user.id, True)
        await safe_reply(update,
            f"✅ *Verification Successful!*\n\n"
            f"🎉 You hold 100,000+ $AIVA!\n"
            f"Premium access has been activated.\n\n"
            f"Enjoy unlimited queries and all features! 🚀"
        )
    else:
        await safe_reply(update,
            f"❌ *Verification Failed*\n\n"
            f"Wallet `{wallet_addr[:8]}...` does not hold 100,000+ $AIVA.\n\n"
            f"Buy $AIVA:\n"
            f"[Pump.fun](https://pump.fun/coin/{config.AIVA_CONTRACT})\n"
            f"CA: `{config.AIVA_CONTRACT}`\n\n"
            f"_Holding threshold: 100,000 $AIVA_"
        )


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username or "", user.first_name or "")
    user_data = db.get_user(user.id)
    if not user_data:
        await safe_reply(update, "⚠️ Could not fetch your account info.")
        return

    daily_used = user_data["daily_calls"]
    remaining = max(0, config.FREE_DAILY_CALLS - daily_used)
    await safe_reply(update, msg.msg_plan(user_data, remaining, config.FREE_DAILY_CALLS))


async def cmd_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 群聊里不能发起 Stars 支付，引导去私聊
    if is_group_chat(update):
        await redirect_to_pm(update, context, "upgrade to Premium ⭐")
        return

    keyboard = [
        [InlineKeyboardButton("⭐ Pay 150 Stars (1 Month)", callback_data="buy_premium")],
        [InlineKeyboardButton("💎 Verify AIVA Holdings (FREE)", callback_data="verify_info")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        msg.msg_premium_info(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup,
        disable_web_page_preview=True
    )


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """如何购买 AIVA"""
    text = (
        f"💎 *How to Buy $AIVA*\n\n"
        f"*Step 1:* Download [Phantom Wallet](https://phantom.app)\n"
        f"*Step 2:* Buy some SOL and transfer to Phantom\n"
        f"*Step 3:* Go to Pump.fun and paste the CA:\n"
        f"`{config.AIVA_CONTRACT}`\n"
        f"*Step 4:* Swap SOL for $AIVA!\n\n"
        f"🔗 [Buy on Pump.fun](https://pump.fun/coin/{config.AIVA_CONTRACT})\n\n"
        f"💡 Hold 100K $AIVA = FREE premium bot access!\n"
        f"Use `/verify <your_wallet>` to activate\n\n"
        f"_@AIVABot • Powered by $AIVA_"
    )
    await safe_reply(update, text, disable_preview=True)


# ─────────────────────── Inline 按钮回调 ─────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    user = query.from_user
    db.ensure_user(user.id, user.username or "", user.first_name or "")

    if data == "trending":
        await query.message.reply_text("⏳ Loading trending tokens...")
        if db.check_and_consume_quota(user.id, config.FREE_DAILY_CALLS):
            tokens = await sol.get_trending_tokens(config.TRENDING_TOP_N)
            if not tokens:
                tokens = await sol.get_trending_dexscreener(config.TRENDING_TOP_N)
            await query.message.reply_text(
                msg.msg_trending(tokens),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
        else:
            await query.message.reply_text(msg.msg_quota_exceeded(config.FREE_DAILY_CALLS), parse_mode=ParseMode.MARKDOWN)

    elif data == "newcoins":
        await query.message.reply_text("⏳ Scanning Pump.fun...")
        if db.check_and_consume_quota(user.id, config.FREE_DAILY_CALLS):
            tokens = await sol.get_truly_new_tokens(min_liquidity=config.NEW_TOKEN_MIN_LIQUIDITY)
            await query.message.reply_text(
                msg.msg_new_coins(tokens),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
        else:
            await query.message.reply_text(msg.msg_quota_exceeded(config.FREE_DAILY_CALLS), parse_mode=ParseMode.MARKDOWN)

    elif data == "network":
        await query.message.reply_text("⏳ Checking network status...")
        network_data = await sol.get_network_status()
        await query.message.reply_text(
            msg.msg_network(network_data),
            parse_mode=ParseMode.MARKDOWN
        )

    elif data == "aiva":
        await query.message.reply_text("⏳ Fetching $AIVA data...")
        aiva_data = await sol.get_aiva_price()
        if aiva_data:
            await query.message.reply_text(
                msg.msg_aiva_info(aiva_data),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

    elif data == "premium":
        keyboard = [
            [InlineKeyboardButton("⭐ Pay 150 Stars", callback_data="buy_premium")],
            [InlineKeyboardButton("💎 Verify AIVA", callback_data="verify_info")],
        ]
        markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            msg.msg_premium_info(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup,
            disable_web_page_preview=True
        )

    elif data == "help":
        await query.message.reply_text(
            msg.HELP_TEXT,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )

    elif data == "buy_premium":
        # 群聊里不能发起 Stars 支付，需要在私聊中完成
        chat_type = query.message.chat.type
        if chat_type in ("group", "supergroup"):
            bot_name = context.bot.username or "AIVADataBot"
            await query.message.reply_text(
                f"⭐ Stars payments can only be made in private chat!\n\n"
                f"👉 DM [@{bot_name}](https://t.me/{bot_name}) and send /premium",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            return
        # 私聊：发起 Telegram Stars 支付
        try:
            await context.bot.send_invoice(
                chat_id=query.message.chat_id,
                title="AIVA Bot Premium",
                description="30-day unlimited access to all AIVA Bot features: real-time alerts, unlimited queries, whale tracking, and more.",
                payload="premium_30d",
                provider_token="",  # Telegram Stars 不需要 provider_token
                currency="XTR",     # XTR = Telegram Stars
                prices=[LabeledPrice("Premium (30 days)", config.PREMIUM_PRICE_STARS)],
            )
        except Exception as e:
            logger.error(f"支付错误: {e}")
            bot_name = context.bot.username or "AIVADataBot"
            await query.message.reply_text(
                f"⚠️ Payment failed. Please DM @{bot_name} and try again."
            )

    elif data == "verify_info":
        await query.message.reply_text(
            f"💎 *AIVA Holder Verification*\n\n"
            f"1️⃣ Buy $AIVA on Pump.fun\n"
            f"CA: `{config.AIVA_CONTRACT}`\n\n"
            f"2️⃣ Make sure you hold at least 100,000 $AIVA\n\n"
            f"3️⃣ Use `/verify <your_wallet_address>`\n\n"
            f"✅ Verification is instant and free!",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )

    elif data == "agent_refresh":
        try:
            snapshot = adb.get_agent_status_snapshot()
            msg_text = buyback.format_agent_status_message(snapshot)
            keyboard = [[
                InlineKeyboardButton("🔄 Refresh", callback_data="agent_refresh"),
                InlineKeyboardButton("📊 Scan Now", callback_data="agent_scan"),
            ]]
            markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                msg_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
                disable_web_page_preview=True
            )
        except Exception as e:
            await query.message.reply_text(f"⚠️ Refresh error: {e}")

    elif data == "agent_scan":
        await query.message.reply_text("🔍 Running scan... Use /agent_scan for full results.")


# ─────────────────────── 支付处理 ────────────────────────────────

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """验证支付请求"""
    query = update.pre_checkout_query
    if query.invoice_payload == "premium_30d":
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Invalid payment payload")


async def payment_success_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """支付成功处理"""
    user = update.effective_user
    payment = update.message.successful_payment
    charge_id = payment.telegram_payment_charge_id
    stars = payment.total_amount

    db.record_payment(user.id, stars, charge_id)
    logger.info(f"💰 Payment: user={user.id}, stars={stars}, charge={charge_id}")

    await update.message.reply_text(
        f"🎉 *Payment Successful!*\n\n"
        f"⭐ Stars paid: `{stars}`\n"
        f"✅ Premium activated for 30 days!\n\n"
        f"You now have:\n"
        f"• Unlimited queries\n"
        f"• Real-time whale alerts\n"
        f"• New token alerts\n"
        f"• Priority updates\n\n"
        f"Thank you for supporting $AIVA! 🤖🚀",
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────── 后台任务（播报）────────────────────────

async def broadcast_whale_alerts(app: Application):
    """定期扫描大额交易，推送到频道"""
    if not config.BROADCAST_CHANNEL_ID:
        return
    while True:
        try:
            txs = await sol.get_recent_large_transactions(
                min_usd=config.WHALE_ALERT_MIN_USD,
                limit=20
            )
            for tx in txs:
                sig = tx.get("signature", "")
                if sig and not db.is_tx_sent(sig):
                    text = msg.msg_whale_alert(tx)
                    await app.bot.send_message(
                        chat_id=config.BROADCAST_CHANNEL_ID,
                        text=text,
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=True
                    )
                    db.mark_tx_sent(sig)
                    await asyncio.sleep(1)  # 避免速率限制
        except Exception as e:
            logger.error(f"[Whale Alert] 错误: {e}")
        await asyncio.sleep(config.WHALE_ALERT_INTERVAL)


async def broadcast_new_tokens(app: Application):
    """定期扫描新币，推送到频道"""
    if not config.BROADCAST_CHANNEL_ID:
        return
    while True:
        try:
            tokens = await sol.get_truly_new_tokens(
                min_liquidity=config.NEW_TOKEN_MIN_LIQUIDITY,
                max_age_min=10  # 只推送 10 分钟内的新币
            )
            for t in tokens:
                mint = t.get("mint", "")
                if mint and not db.is_token_sent(mint):
                    text = msg.msg_new_coin_alert(t)
                    await app.bot.send_message(
                        chat_id=config.BROADCAST_CHANNEL_ID,
                        text=text,
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=True
                    )
                    db.mark_token_sent(mint)
                    await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"[New Token] 错误: {e}")
        await asyncio.sleep(config.NEW_TOKEN_INTERVAL)


async def auto_buyback_check(app: Application):
    """检查累计收益，触发 Pump.fun Tokenized Agents 回购"""
    if not config.AUTO_BUYBACK_ENABLED:
        return
    while True:
        try:
            total_sol = db.get_total_revenue_sol()
            if total_sol >= config.BUYBACK_THRESHOLD_SOL:
                logger.info(f"[Buyback] 累计收益 {total_sol:.4f} SOL，触发回购提醒")
        except Exception as e:
            logger.error(f"[Buyback] 错误: {e}")
        await asyncio.sleep(3600)


# ─────────────────────── DeFi Agent 后台任务 ──────────────────────

async def agent_scan_loop(app: Application):
    """
    DeFi Agent 主循环：定期扫描市场机会，执行策略，触发回购
    """
    if not config.AGENT_ENABLED:
        logger.info("[Agent] Agent 未启用，跳过")
        return

    logger.info("[Agent] 🤖 DeFi Agent 后台任务已启动")

    # 确保钱包存在
    agent_wallet_info = wallet_mod.get_or_create_wallet()
    pub_key = agent_wallet_info["public_key"]
    logger.info(f"[Agent] 使用钱包：{pub_key}")
    adb.agent_log("INFO", "Agent", f"Agent 启动，钱包: {pub_key[:20]}...")

    # 第一次启动先立刻扫一次
    await asyncio.sleep(5)

    while True:
        try:
            logger.info(f"[Agent] 开始策略扫描...")
            adb.agent_log("INFO", "Agent", "开始策略扫描")

            # 1. 更新钱包状态
            try:
                w_summary = await wallet_mod.get_wallet_summary(pub_key)
                adb.upsert_wallet_state(
                    public_key=pub_key,
                    sol=w_summary.get("sol", 0),
                    usdc=w_summary.get("usdc", 0),
                    total_usd=w_summary.get("total_usd", 0)
                )
            except Exception as e:
                logger.error(f"[Agent] 钱包状态更新失败: {e}")

            # 2. 运行策略扫描
            scan_result = await strat.engine.run_full_scan()
            best = scan_result.get("best_strategy", {})

            # 3. 模拟收益记录（如果有套利机会）
            arb_opps = scan_result.get("arb_opps", [])
            if arb_opps and arb_opps[0].get("viable"):
                best_arb = arb_opps[0]
                # 模拟以 $10 USDC 执行一次套利
                sim_gross = best_arb["input_usdc"] * (best_arb["profit_pct"] / 100)
                sim_fee   = 0.003  # Solana 手续费约 $0.003
                sim_net   = sim_gross - sim_fee
                if sim_net > 0:
                    adb.record_earning(
                        strategy_type="arbitrage",
                        strategy_name=best_arb["path"],
                        gross_usd=round(sim_gross, 6),
                        fee_usd=sim_fee,
                        net_usd=round(sim_net, 6),
                        is_simulated=True,
                        notes=f"profit_pct={best_arb['profit_pct']:.3f}%"
                    )
                    adb.agent_log("INFO", "Earnings",
                        f"[SIM] 套利模拟收益 ${sim_net:.4f} via {best_arb['path']}")

            # 4. 检查是否触发回购
            sim_earn = adb.get_total_earnings(simulated_only=True)
            total_net_sim = sim_earn.get("total_net", 0)

            if total_net_sim >= config.AGENT_MIN_BUYBACK_USD:
                # 获取 AIVA 当前价格
                try:
                    aiva_info = await sol.get_aiva_price()
                    aiva_price = aiva_info.get("price_usd", 0) if aiva_info else 0
                except:
                    aiva_price = 0

                if aiva_price > 0:
                    bb_result = await buyback.check_and_trigger_buyback(
                        net_earnings_usd=total_net_sim,
                        aiva_price_usd=aiva_price,
                        is_simulated=True
                    )

                    # 5. 通知管理员/频道
                    if bb_result and bb_result.get("success"):
                        bb_stats = adb.get_buyback_stats()
                        total_burned = bb_stats.get("sim_aiva_bought", 0)
                        announcement = buyback.format_buyback_announcement(bb_result, total_burned)

                        # 发给管理员
                        if config.AGENT_ADMIN_USER_ID:
                            try:
                                await app.bot.send_message(
                                    chat_id=config.AGENT_ADMIN_USER_ID,
                                    text=announcement,
                                    parse_mode=ParseMode.MARKDOWN,
                                    disable_web_page_preview=True
                                )
                            except Exception as e:
                                logger.error(f"[Agent] 发送管理员通知失败: {e}")

                        # 发到播报频道
                        if config.BROADCAST_CHANNEL_ID:
                            try:
                                await app.bot.send_message(
                                    chat_id=config.BROADCAST_CHANNEL_ID,
                                    text=announcement,
                                    parse_mode=ParseMode.MARKDOWN,
                                    disable_web_page_preview=True
                                )
                            except Exception as e:
                                logger.error(f"[Agent] 发送频道通知失败: {e}")

        except Exception as e:
            logger.error(f"[Agent] 主循环错误: {e}")
            adb.agent_log("ERROR", "Agent", f"主循环错误: {str(e)[:200]}")

        # 等待下一次扫描
        logger.info(f"[Agent] 下次扫描将在 {config.AGENT_SCAN_INTERVAL // 60} 分钟后")
        await asyncio.sleep(config.AGENT_SCAN_INTERVAL)


# ─────────────────────── Agent 命令处理器 ─────────────────────────

async def cmd_agent_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /agent_status — 查看 DeFi Agent 运行状态和收益概览
    Premium 用户专享命令
    """
    user = update.effective_user
    db.ensure_user(user.id, user.username or "", user.first_name or "")

    if not db.is_premium(user.id):
        await safe_reply(update,
            "🔒 *Agent Status is Premium Only*\n\n"
            "Use /premium to upgrade, or /verify if you hold $AIVA."
        )
        return

    await update.message.reply_text("⏳ Fetching Agent status...")

    try:
        snapshot = adb.get_agent_status_snapshot()
        msg_text = buyback.format_agent_status_message(snapshot)
        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="agent_refresh"),
            InlineKeyboardButton("📊 Scan Now", callback_data="agent_scan"),
        ]]
        markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            msg_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"[cmd_agent_status] {e}")
        await safe_reply(update, f"⚠️ Error fetching Agent status: {e}")


async def cmd_agent_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /agent_scan — 手动触发一次策略扫描（管理员命令）
    """
    user = update.effective_user
    if config.AGENT_ADMIN_USER_ID and user.id != config.AGENT_ADMIN_USER_ID:
        await safe_reply(update, "🔒 Admin only command.")
        return

    msg_obj = await update.message.reply_text("🔍 Running DeFi strategy scan...")
    try:
        scan_result = await strat.engine.run_full_scan()
        best = scan_result.get("best_strategy", {})
        arb_opps = scan_result.get("arb_opps", [])
        apy_data = scan_result.get("apy_data", {})

        # 格式化结果
        arb_lines = ""
        if arb_opps:
            for a in arb_opps[:3]:
                viable = "✅" if a.get("viable") else "⚠️"
                arb_lines += f"  {viable} {a['path']}: `+{a['profit_pct']:.3f}%` (${a['profit_usd']:.4f})\n"
        else:
            arb_lines = "  _No arbitrage opportunities found_\n"

        apy_lines = ""
        for name, data in apy_data.items():
            if name.startswith("_"):
                continue
            est = " _(est)_" if data.get("is_estimate") else ""
            apy_lines += f"  • {name} {data['asset']}: `{data['apy']:.1f}%` APY{est}\n"

        reply = (
            f"🔍 *Strategy Scan Complete*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Best Strategy:*\n"
            f"  _{best.get('name', 'None')}_\n"
            f"  Est. APY: `{best.get('estimated_apy', 0):.1f}%`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Arbitrage Opportunities:*\n{arb_lines}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 *Stable Yield APYs:*\n{apy_lines}\n"
            f"🤖 _Simulation mode: ON_"
        )
        await msg_obj.edit_text(
            reply,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await msg_obj.edit_text(f"⚠️ Scan error: {e}")


async def cmd_buyback_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /buyback — 查看回购销毁历史记录
    """
    if is_group_chat(update):
        await redirect_to_pm(update, context, "view buyback history")
        return

    stats = adb.get_buyback_stats()
    recent = adb.get_recent_buybacks(limit=5)

    lines = ""
    for bb in recent:
        import datetime
        t = datetime.datetime.fromtimestamp(bb["buyback_time"]).strftime("%m/%d")
        sim = " _(sim)_" if bb["is_simulated"] else ""
        burned = "🔥" if bb["is_burned"] else "⏳"
        lines += f"  {burned} {t}: `${bb['usdc_used']:.2f}` → `{bb['aiva_bought']:,.0f} AIVA`{sim}\n"

    if not lines:
        lines = "  _No buybacks yet — accumulating earnings..._\n"

    reply = (
        f"🔥 *$AIVA Buyback & Burn History*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *All Time Stats*\n"
        f"  Total Buybacks:    `{stats['total_buybacks']}`\n"
        f"  Total USDC Spent:  `${stats['total_usdc_spent']:.2f}`\n"
        f"  AIVA Bought (Sim): `{stats['sim_aiva_bought']:,.0f}`\n"
        f"  AIVA Burned:       `{stats['total_aiva_burned']:,.0f}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Recent Buybacks:*\n{lines}\n"
        f"💡 50% of Agent earnings → buy & burn $AIVA\n"
        f"CA: `FMKA3FQBu5qqPLxAvf7YTpmP3GpLsSENQYu4xJ72pump`"
    )
    await safe_reply(update, reply)


# ─────────────────────── 启动 ─────────────────────────────────

async def post_init(app: Application):
    """Bot 初始化完成后启动后台任务"""
    asyncio.create_task(broadcast_whale_alerts(app))
    asyncio.create_task(broadcast_new_tokens(app))
    asyncio.create_task(auto_buyback_check(app))
    asyncio.create_task(agent_scan_loop(app))   # 🤖 DeFi Agent 主循环
    logger.info("✅ 后台任务已启动（含 DeFi Agent）")


def main():
    db.init_db()
    adb.init_agent_tables()      # 初始化 Agent 数据表
    logger.info("🤖 AIVA Bot starting...")

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # 命令处理器
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("network",  cmd_network))
    app.add_handler(CommandHandler("gas",      cmd_gas))
    app.add_handler(CommandHandler("trending", cmd_trending))
    app.add_handler(CommandHandler("newcoins", cmd_newcoins))
    app.add_handler(CommandHandler("whale",    cmd_whale))
    app.add_handler(CommandHandler("price",    cmd_price))
    app.add_handler(CommandHandler("aiva",     cmd_aiva))
    app.add_handler(CommandHandler("wallet",   cmd_wallet))
    app.add_handler(CommandHandler("verify",   cmd_verify))
    app.add_handler(CommandHandler("plan",     cmd_plan))
    app.add_handler(CommandHandler("premium",  cmd_premium))
    app.add_handler(CommandHandler("buy",          cmd_buy))
    app.add_handler(CommandHandler("agent_status", cmd_agent_status))
    app.add_handler(CommandHandler("agent_scan",   cmd_agent_scan))
    app.add_handler(CommandHandler("buyback",      cmd_buyback_history))

    # Inline 按钮回调
    app.add_handler(CallbackQueryHandler(callback_handler))

    # 支付处理
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_success_handler))

    logger.info("✅ 所有处理器已注册，Bot 开始运行")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
