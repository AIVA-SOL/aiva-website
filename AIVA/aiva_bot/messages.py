"""
messages.py — 所有消息模板
统一管理发送给用户的文字内容
"""

from solana_data import fmt_num, fmt_price, fmt_change, shorten_addr
from config import AIVA_CONTRACT, AIVA_WEBSITE, AIVA_TWITTER, AIVA_TELEGRAM


# ─────────────────────── /start 欢迎 ─────────────────────────────

def msg_start(first_name: str, is_premium: bool) -> str:
    tier = "⭐ Premium" if is_premium else "🆓 Free"
    return f"""🤖 *Welcome to AIVA Solana Intelligence Bot!*

Hello {first_name}! I'm your real-time Solana chain analytics assistant.

*Your Plan:* {tier}

━━━━━━━━━━━━━━━━━━━━━━━━
📊 *Available Commands:*

🔴 *Real-time Data*
/price `<token>` — Token price & market data
/wallet `<address>` — Wallet portfolio analysis
/network — Solana network status (TPS, fees)
/gas — Current gas fee estimate

📈 *Market Intelligence*
/trending — Top 10 trending tokens
/newcoins — Latest Pump.fun new launches
/whale — Recent whale transactions

💎 *AIVA Token*
/aiva — $AIVA token info & price
/verify `<wallet>` — Verify AIVA holdings for free access

⚙️ *Account*
/plan — Your current plan & usage
/premium — Upgrade to Premium
/help — Help & documentation

━━━━━━━━━━━━━━━━━━━━━━━━
🎁 *Free Plan:* 10 queries/day
⭐ *Premium:* Unlimited + real-time alerts

*Powered by $AIVA on Solana* 🚀
"""


# ─────────────────────── 帮助文档 ────────────────────────────────

HELP_TEXT = """📚 *AIVA Bot — Help & Commands*

━━━━━━━━━━━━━━━━━━━━━━━━
🔴 *REAL-TIME DATA*

`/price SOL` — SOL price & stats
`/price <mint>` — Any Solana token by contract address
`/wallet <address>` — Full wallet analysis (SOL balance, tokens, USD value)
`/network` — Solana TPS, slot, epoch, priority fee
`/gas` — Current transaction fee estimate

━━━━━━━━━━━━━━━━━━━━━━━━
📈 *MARKET INTELLIGENCE*

`/trending` — Top 10 hottest tokens right now
`/newcoins` — New Pump.fun launches (last 60 min)
`/whale` — Large transactions (>$10K USD)

━━━━━━━━━━━━━━━━━━━━━━━━
💎 *AIVA ECOSYSTEM*

`/aiva` — $AIVA price, market cap, liquidity
`/verify <wallet>` — Hold 100K+ $AIVA = FREE premium access
`/buy` — How to buy $AIVA

━━━━━━━━━━━━━━━━━━━━━━━━
⚙️ *ACCOUNT MANAGEMENT*

`/plan` — View your plan & remaining quota
`/premium` — Upgrade to Premium (150 Stars/month)
`/start` — Back to main menu

━━━━━━━━━━━━━━━━━━━━━━━━
❓ *Need Help?*
Join our community: [Telegram]({tg}) | [Twitter]({tw})
""".format(tg=AIVA_TELEGRAM, tw=AIVA_TWITTER)


# ─────────────────────── 网络状态 ────────────────────────────────

def msg_network(data: dict) -> str:
    tps = data.get("tps", 0)
    fee = data.get("priority_fee", 0)
    epoch = data.get("epoch", "N/A")
    slot = data.get("slot", "N/A")

    # TPS 评级
    if tps > 2000:
        tps_status = "🔴 Congested"
    elif tps > 1000:
        tps_status = "🟡 Moderate"
    else:
        tps_status = "🟢 Smooth"

    # Fee 评级
    if fee > 100000:
        fee_level = "💸 High"
    elif fee > 10000:
        fee_level = "⚠️ Medium"
    else:
        fee_level = "✅ Low"

    fee_sol = fee / 1e9 if fee else 0

    return f"""🌐 *Solana Network Status*

🚀 TPS: `{tps:,.0f}` — {tps_status}
⚡ Priority Fee: `{fee:,} microLamports` ({fee_level})
   ≈ `{fee_sol:.8f} SOL` per transaction
📦 Current Epoch: `{epoch}`
🎰 Latest Slot: `{slot:,}` 

━━━━━━━━━━━━━━━━━━━━━━━━
💡 *Tip:* Higher TPS = more congestion = higher fees
Normal range: 500-2000 TPS

_Updated just now · Powered by @AIVABot_
"""


# ─────────────────────── 趋势榜 ──────────────────────────────────

def msg_trending(tokens: list) -> str:
    if not tokens:
        return "⚠️ Could not fetch trending data. Please try again later."

    lines = ["📈 *Solana Trending Tokens*\n"]
    for t in tokens:
        rank    = t.get("rank", "?")
        symbol  = t.get("symbol", "?")
        price   = t.get("price", 0)
        change  = t.get("price_change", 0)
        vol     = t.get("volume_24h", 0)
        addr    = t.get("address", "")

        change_str = fmt_change(change)
        rank_emoji = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        emoji = rank_emoji[rank-1] if 1 <= rank <= 10 else f"{rank}."

        lines.append(
            f"{emoji} *${symbol}*\n"
            f"   Price: `{fmt_price(price)}` {change_str}\n"
            f"   Vol 24h: `${fmt_num(vol)}`\n"
            f"   [Chart 🔗](https://dexscreener.com/solana/{addr})\n"
        )

    lines.append("\n_Powered by $AIVA · @AIVABot_")
    return "\n".join(lines)


# ─────────────────────── 新币预警 ────────────────────────────────

def msg_new_coins(tokens: list, max_show: int = 8) -> str:
    if not tokens:
        return "⚠️ No new Pump.fun launches found in the last hour.\nCheck back in a few minutes!"

    lines = [f"🆕 *New Pump.fun Launches* (Last 60 min)\n"]
    for i, t in enumerate(tokens[:max_show]):
        name   = t.get("name", "Unknown")[:20]
        symbol = t.get("symbol", "")
        liq    = t.get("liquidity", 0)
        vol5m  = t.get("volume_5m", 0)
        age    = t.get("age_min", 0)
        url    = t.get("dex_url", "")

        lines.append(
            f"*{i+1}. {name}* (${symbol})\n"
            f"   💧 Liq: `${fmt_num(liq)}`  |  📊 Vol 5m: `${fmt_num(vol5m)}`\n"
            f"   ⏱ Age: `{age:.0f} min`  |  [DexScreener]({url})\n"
        )

    lines.append(f"\n⚠️ _DYOR — New tokens are HIGH risk_")
    lines.append("_Powered by $AIVA · @AIVABot_")
    return "\n".join(lines)


def msg_new_coin_alert(t: dict) -> str:
    """单个新币的频道播报格式"""
    return (
        f"🚨 *NEW LAUNCH ALERT*\n\n"
        f"📛 Name: *{t.get('name', 'Unknown')}* (${t.get('symbol', '')})\n"
        f"💧 Liquidity: `${fmt_num(t.get('liquidity', 0))}`\n"
        f"📊 Volume 5m: `${fmt_num(t.get('volume_5m', 0))}`\n"
        f"⏱ Age: `{t.get('age_min', 0):.0f} minutes`\n"
        f"📋 CA: `{t.get('mint', '')}`\n\n"
        f"🔗 [DexScreener]({t.get('dex_url', '')}) | "
        f"[Pump.fun](https://pump.fun/coin/{t.get('mint', '')})\n\n"
        f"⚠️ _High risk — DYOR_\n"
        f"_@AIVABot • Powered by $AIVA_"
    )


# ─────────────────────── 大额交易 ────────────────────────────────

def msg_whale_alert(tx: dict) -> str:
    """大额交易频道播报格式"""
    sol = tx.get("sol_amount", 0)
    usd = tx.get("usd_value", 0)
    frm = tx.get("from", "Unknown")
    to  = tx.get("to", "Unknown")
    sig = tx.get("signature", "")

    return (
        f"🐳 *WHALE ALERT*\n\n"
        f"💰 Amount: `{sol:,.2f} SOL` (≈`${usd:,.0f}`)\n"
        f"📤 From: `{frm}`\n"
        f"📥 To: `{to}`\n\n"
        f"🔗 [View TX](https://solscan.io/tx/{sig})\n\n"
        f"_@AIVABot • Powered by $AIVA_"
    )


def msg_whale_list(txs: list) -> str:
    if not txs:
        return "🐳 No whale transactions (>$10K) found in the last few minutes.\nCheck back soon!"

    lines = ["🐳 *Recent Whale Transactions*\n"]
    for tx in txs[:8]:
        sol = tx.get("sol_amount", 0)
        usd = tx.get("usd_value", 0)
        sig = tx.get("signature", "")
        lines.append(
            f"💰 `{sol:,.1f} SOL` ≈ `${usd:,.0f}`\n"
            f"   [View TX](https://solscan.io/tx/{sig})\n"
        )

    lines.append("_Powered by $AIVA · @AIVABot_")
    return "\n".join(lines)


# ─────────────────────── 代币价格 ────────────────────────────────

def msg_token_price(data: dict, mint: str = "") -> str:
    name   = data.get("name", "Unknown")
    symbol = data.get("symbol", "?")
    price  = data.get("price_usd", 0)
    change = data.get("price_change_24h", 0)
    vol    = data.get("volume_24h", 0)
    mc     = data.get("market_cap", 0)
    liq    = data.get("liquidity", 0)

    return (
        f"💹 *{name}* (${symbol})\n\n"
        f"💰 Price: `{fmt_price(price)}`\n"
        f"📈 24h Change: {fmt_change(change)}\n"
        f"📊 Volume 24h: `${fmt_num(vol)}`\n"
        f"🏦 Market Cap: `${fmt_num(mc)}`\n"
        f"💧 Liquidity: `${fmt_num(liq)}`\n\n"
        + (f"📋 CA: `{shorten_addr(mint)}`\n"
           f"🔗 [DexScreener](https://dexscreener.com/solana/{mint})\n" if mint else "")
        + f"\n_@AIVABot • Powered by $AIVA_"
    )


def msg_aiva_info(data: dict) -> str:
    price     = data.get("price_usd", 0)
    change_1h = data.get("price_change_1h", 0)
    change_6h = data.get("price_change_6h", 0)
    change_24h= data.get("price_change_24h", 0)
    vol_24h   = data.get("volume_24h", 0)
    vol_1h    = data.get("volume_1h", 0)
    mc        = data.get("market_cap", 0)
    liq       = data.get("liquidity", 0)
    dex       = data.get("dex", "")
    buys_24h  = data.get("buys_24h", 0)
    sells_24h = data.get("sells_24h", 0)
    buys_1h   = data.get("buys_1h", 0)
    sells_1h  = data.get("sells_1h", 0)
    supply    = data.get("total_supply", 1_000_000_000)
    top_pct   = data.get("top_holder_pct", 0)

    # 买卖压力指标
    total_24h = buys_24h + sells_24h
    if total_24h > 0:
        buy_ratio = buys_24h / total_24h * 100
        pressure = "🟢 Bullish" if buy_ratio >= 60 else ("🔴 Bearish" if buy_ratio <= 40 else "🟡 Neutral")
    else:
        buy_ratio = 0
        pressure = "⚪ No data"

    # 流通量百分比（pump.fun 通常有部分在 bonding curve）
    supply_str = f"{supply/1e6:.0f}M" if supply >= 1e6 else f"{supply:,.0f}"

    return (
        f"🤖 *$AIVA — AI Virtual Assistant*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 *Price:* `{fmt_price(price)}`\n"
        f"📈 *Change:*  1h {fmt_change(change_1h)}  6h {fmt_change(change_6h)}  24h {fmt_change(change_24h)}\n\n"
        f"📊 *Volume:*\n"
        f"   1h: `${fmt_num(vol_1h)}`  |  24h: `${fmt_num(vol_24h)}`\n\n"
        f"🔄 *Trades (24h):*\n"
        f"   🟢 Buys: `{buys_24h}`  🔴 Sells: `{sells_24h}`\n"
        f"   {pressure} ({buy_ratio:.0f}% buy pressure)\n\n"
        f"🏦 *Market Cap:* `${fmt_num(mc)}`\n"
        f"💧 *Liquidity:* `${fmt_num(liq)}`\n"
        f"🪙 *Supply:* `{supply_str}` tokens\n"
        f"👑 *Top Holder:* `{top_pct}%` of supply\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *CA:* `{AIVA_CONTRACT}`\n\n"
        f"🔗 *Links:*\n"
        f"• [Website]({AIVA_WEBSITE})  |  [Twitter]({AIVA_TWITTER})\n"
        f"• [Telegram]({AIVA_TELEGRAM})\n"
        f"• [DexScreener](https://dexscreener.com/solana/{AIVA_CONTRACT})\n"
        f"• [Pump.fun](https://pump.fun/coin/{AIVA_CONTRACT})\n\n"
        f"💎 *Hold 100K+ $AIVA = FREE Premium!*\n"
        f"Use `/verify <wallet>` to activate\n"
        f"\n_@AIVABot • Powered by $AIVA_"
    )


# ─────────────────────── 钱包分析 ────────────────────────────────

def msg_wallet(data: dict) -> str:
    wallet  = data.get("wallet", "")
    sol_bal = data.get("sol_balance", 0)
    sol_usd = data.get("sol_usd", 0)
    sol_p   = data.get("sol_price", 0)
    tokens  = data.get("tokens", [])
    count   = data.get("token_count", 0)

    lines = [
        f"👛 *Wallet Analysis*\n",
        f"📍 Address: `{shorten_addr(wallet, 8)}`",
        f"\n💎 *SOL Balance:*",
        f"   `{sol_bal} SOL` ≈ `${sol_usd:,.2f}`",
        f"   _(SOL price: ${sol_p:,.2f})_\n",
        f"🪙 *Token Holdings:* ({count} tokens)\n",
    ]

    if tokens:
        for t in tokens[:10]:
            sym = t.get("symbol", "?")
            bal = t.get("balance", 0)
            dec = t.get("decimals", 0)
            price_info = t.get("price_info", {})
            usd_val = price_info.get("total_price", 0) or 0

            if dec > 0:
                real_bal = bal / (10 ** dec)
            else:
                real_bal = bal

            usd_str = f" ≈ `${usd_val:,.2f}`" if usd_val > 0.01 else ""
            lines.append(f"• *${sym}*: `{fmt_num(real_bal, 2)}`{usd_str}")
    else:
        lines.append("_No fungible tokens found_")

    lines.append(f"\n🔗 [View on Solscan](https://solscan.io/account/{wallet})")
    lines.append("_@AIVABot • Powered by $AIVA_")
    return "\n".join(lines)


# ─────────────────────── 套餐信息 ────────────────────────────────

def msg_plan(user, remaining_calls: int, free_limit: int) -> str:
    is_prem  = user["is_premium"] and user["premium_until"] > __import__("time").time()
    is_aiva  = user["aiva_verified"]
    daily    = user["daily_calls"]
    total    = user["total_calls"]
    join     = __import__("datetime").datetime.fromtimestamp(user["join_time"]).strftime("%Y-%m-%d") if user["join_time"] else "N/A"

    if is_prem:
        import datetime
        exp = datetime.datetime.fromtimestamp(user["premium_until"]).strftime("%Y-%m-%d")
        tier_line = f"⭐ *Premium Member*\nExpires: `{exp}`"
        quota_line = "✅ Unlimited queries"
    elif is_aiva:
        tier_line = "💎 *AIVA Holder — Free Premium*"
        quota_line = "✅ Unlimited queries (AIVA holder benefit)"
    else:
        tier_line = "🆓 *Free Plan*"
        quota_line = f"📊 Today: `{daily}/{free_limit}` queries used | Remaining: `{remaining_calls}`"

    return (
        f"⚙️ *Your Account*\n\n"
        f"{tier_line}\n\n"
        f"{quota_line}\n\n"
        f"📅 Joined: `{join}`\n"
        f"🔢 Total queries: `{total}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *Want unlimited access?*\n"
        f"• `/premium` — 150 Stars/month (~$2)\n"
        f"• Hold 100K $AIVA → `/verify <wallet>` = FREE\n"
    )


def msg_premium_info() -> str:
    return (
        f"⭐ *Upgrade to AIVA Premium*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆓 *Free Plan*\n"
        f"• 10 queries per day\n"
        f"• All commands available\n"
        f"• No auto-alerts\n\n"
        f"⭐ *Premium — 150 Stars/month*\n"
        f"• ✅ Unlimited queries\n"
        f"• ✅ Real-time whale alerts\n"
        f"• ✅ New token alerts\n"
        f"• ✅ Trending updates every 5 min\n"
        f"• ✅ Priority support\n\n"
        f"💎 *AIVA Holder Bonus — FREE!*\n"
        f"• Hold 100,000+ $AIVA tokens\n"
        f"• Use `/verify <wallet>` to activate\n"
        f"• Get ALL premium features for free!\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Buy $AIVA:\n"
        f"[Pump.fun](https://pump.fun/coin/{AIVA_CONTRACT})\n"
        f"CA: `{AIVA_CONTRACT}`\n\n"
        f"_Tap the button below to pay with Telegram Stars_ 👇"
    )


def msg_quota_exceeded(free_limit: int) -> str:
    return (
        f"⚠️ *Daily Limit Reached*\n\n"
        f"You've used all {free_limit} free queries for today.\n"
        f"Resets at midnight UTC.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 *Get Unlimited Access:*\n\n"
        f"⭐ `/premium` — 150 Stars/month\n\n"
        f"💎 *FREE Option:* Hold 100K+ $AIVA\n"
        f"CA: `{AIVA_CONTRACT}`\n"
        f"Then use: `/verify <your_wallet>`\n"
    )
