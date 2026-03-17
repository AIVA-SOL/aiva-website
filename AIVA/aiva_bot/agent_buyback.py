"""
agent_buyback.py — AIVA 回购销毁模块
负责：
  - 触发回购：收益到达阈值时，用 USDC 市价买入 $AIVA
  - 销毁操作：将买到的 $AIVA 发送到黑洞地址（Solana 标准销毁）
  - 播报：回购完成后向 Telegram 频道/群发公告
  - 安全限制：单次最大回购金额、频率限制

当前阶段：模拟模式
  - 真实回购：等待资金≥$50 USDC 且 7 天稳定盈利后开放
  - 模拟模式：按真实 AIVA 市价计算"假设买到的数量"并记录
"""

import asyncio
import logging
import time
from typing import Optional
from config import AIVA_CONTRACT, PROXY, HELIUS_API_KEY, BUYBACK_THRESHOLD_SOL

logger = logging.getLogger("AIVA_BUYBACK")

# Solana 黑洞地址（代币销毁标准地址）
BURN_ADDRESS = "1nc1nerator11111111111111111111111111111111"

# 单次最大回购金额（USDC），安全限制
MAX_SINGLE_BUYBACK_USD = 50.0

# 最小回购触发金额（USDC）
MIN_BUYBACK_TRIGGER_USD = 1.0

# Jupiter V6 兑换 API
JUPITER_SWAP_API   = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_EXEC  = "https://quote-api.jup.ag/v6/swap"

# USDC mint
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def simulate_buyback(usdc_amount: float, aiva_price_usd: float) -> dict:
    """
    模拟回购：计算如果用 usdc_amount USDC 买 $AIVA 会买到多少
    不执行真实交易，仅记录
    """
    if aiva_price_usd <= 0:
        logger.warning("[Buyback] AIVA 价格为 0，无法模拟回购")
        return {"success": False, "reason": "AIVA price is zero"}

    # 估算买到的 AIVA 数量（扣除 0.5% 滑点 + 手续费）
    slippage_factor = 0.995
    fee_factor = 0.997  # 约 0.3% DEX 手续费
    aiva_bought = (usdc_amount / aiva_price_usd) * slippage_factor * fee_factor

    result = {
        "success":        True,
        "simulated":      True,
        "usdc_used":      round(usdc_amount, 4),
        "aiva_bought":    round(aiva_bought, 2),
        "aiva_price":     aiva_price_usd,
        "buyback_tx_sig": f"SIM_BUY_{int(time.time())}",
        "burn_tx_sig":    f"SIM_BURN_{int(time.time())}",
        "burned":         True,  # 模拟中直接标记为已销毁
        "timestamp":      int(time.time()),
    }

    # 写数据库
    import agent_database as adb
    adb.record_buyback(
        usdc_used=usdc_amount,
        aiva_bought=aiva_bought,
        aiva_price=aiva_price_usd,
        trigger_source="earnings",
        is_burned=True,
        buyback_tx_sig=result["buyback_tx_sig"],
        burn_tx_sig=result["burn_tx_sig"],
        is_simulated=True,
        notes=f"Simulated buyback at ${aiva_price_usd:.8f}/AIVA"
    )
    adb.agent_log("INFO", "Buyback",
        f"[SIM] 模拟回购 ${usdc_amount:.2f} USDC → {aiva_bought:.0f} AIVA (已销毁)")

    logger.info(f"[Buyback] 🔥 模拟回购: ${usdc_amount:.2f} → {aiva_bought:.0f} AIVA (销毁)")
    return result


async def check_and_trigger_buyback(
    net_earnings_usd: float,
    aiva_price_usd: float,
    is_simulated: bool = True
) -> Optional[dict]:
    """
    检查是否达到回购触发条件，满足则执行（或模拟）回购

    回购规则：
      - 净利润的 50% 用于回购销毁
      - 待回购金额 >= MIN_BUYBACK_TRIGGER_USD 才触发
      - 单次不超过 MAX_SINGLE_BUYBACK_USD
    """
    import agent_database as adb

    # 计算待回购金额
    buyback_amount = net_earnings_usd * 0.50  # 50% 净利润用于回购

    if buyback_amount < MIN_BUYBACK_TRIGGER_USD:
        logger.debug(f"[Buyback] 待回购 ${buyback_amount:.4f}，未达触发阈值 ${MIN_BUYBACK_TRIGGER_USD}")
        return None

    # 限制单次上限
    actual_amount = min(buyback_amount, MAX_SINGLE_BUYBACK_USD)

    if is_simulated:
        return await simulate_buyback(actual_amount, aiva_price_usd)
    else:
        # 真实执行（第二阶段开放）
        logger.warning("[Buyback] 真实回购模式尚未开放，请先积累 7 天模拟数据")
        return None


def format_buyback_announcement(buyback_result: dict, total_burned: float) -> str:
    """
    生成回购销毁公告文本（发到 Telegram 频道）
    """
    aiva_bought = buyback_result.get("aiva_bought", 0)
    usdc_used   = buyback_result.get("usdc_used", 0)
    aiva_price  = buyback_result.get("aiva_price", 0)
    is_sim      = buyback_result.get("simulated", True)
    burn_sig    = buyback_result.get("burn_tx_sig", "")
    sim_note    = "_(Simulated — Real buybacks start when Agent reaches $50+ earnings)_\n\n" if is_sim else ""

    msg = (
        f"🔥 *$AIVA Buyback & Burn Executed!*\n\n"
        f"{sim_note}"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 USDC Used:      `${usdc_used:.2f}`\n"
        f"🤖 $AIVA Bought:   `{aiva_bought:,.0f} AIVA`\n"
        f"📊 Buy Price:      `${aiva_price:.8f}`\n"
        f"🔥 Status:         *BURNED ✅*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📉 *Total $AIVA Burned (All Time)*\n"
        f"  `{total_burned:,.0f} AIVA`\n\n"
        f"💡 50% of all AIVA Agent revenue is used to\n"
        f"   buy back and permanently burn $AIVA.\n\n"
        f"CA: `FMKA3FQBu5qqPLxAvf7YTpmP3GpLsSENQYu4xJ72pump`\n"
        f"[Buy $AIVA on Pump.fun](https://pump.fun/coin/FMKA3FQBu5qqPLxAvf7YTpmP3GpLsSENQYu4xJ72pump)"
    )
    if burn_sig and not is_sim:
        msg += f"\n\n[View Burn Transaction](https://solscan.io/tx/{burn_sig})"
    return msg


def format_agent_status_message(snapshot: dict) -> str:
    """
    格式化 /agent_status 命令的回复消息
    """
    wallet     = snapshot.get("wallet") or {}
    earnings   = snapshot.get("earnings") or {}
    sim_earn   = snapshot.get("sim_earnings") or {}
    buybacks   = snapshot.get("buybacks") or {}
    last_scan  = snapshot.get("last_scan") or {}
    scan_count = snapshot.get("scan_count", 0)

    # 时间格式化
    def fmt_time(ts):
        if not ts:
            return "Never"
        import datetime
        return datetime.datetime.fromtimestamp(ts).strftime("%m/%d %H:%M")

    last_scan_time = fmt_time(last_scan.get("scan_time", 0))
    best_strategy  = last_scan.get("best_strategy", {})
    strategy_name  = best_strategy.get("name", "No scan yet")
    strategy_apy   = best_strategy.get("estimated_apy", 0)

    # 钱包余额
    sol_bal  = wallet.get("sol_balance", 0)
    usdc_bal = wallet.get("usdc_balance", 0)
    total_usd = wallet.get("total_usd", 0)

    # 收益
    total_net_sim = sim_earn.get("total_net", 0)
    total_net_real = earnings.get("total_net", 0)

    # 回购
    total_aiva_bought = buybacks.get("total_aiva_bought", 0)
    sim_aiva_bought   = buybacks.get("sim_aiva_bought", 0)
    total_buybacks    = buybacks.get("total_buybacks", 0)

    mode_tag = "🟡 _Simulation Mode_" if total_net_real == 0 else "🟢 _Live Mode_"

    msg = (
        f"🤖 *AIVA DeFi Agent Status*\n"
        f"{mode_tag}\n\n"

        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 *Agent Wallet*\n"
        f"  SOL:  `{sol_bal:.4f} SOL`\n"
        f"  USDC: `${usdc_bal:.2f}`\n"
        f"  Total: `${total_usd:.2f}`\n\n"

        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Strategy Engine*\n"
        f"  Scans Run:      `{scan_count}`\n"
        f"  Last Scan:      `{last_scan_time}`\n"
        f"  Current Best:   _{strategy_name}_\n"
        f"  Est. APY:       `{strategy_apy:.1f}%`\n\n"

        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Simulated Earnings*\n"
        f"  Total Net:      `${total_net_sim:.4f}`\n"
        f"  Transactions:   `{sim_earn.get('count', 0)}`\n\n"

        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 *$AIVA Buyback & Burn*\n"
        f"  Total Buybacks:  `{total_buybacks}`\n"
        f"  AIVA Bought(Sim):`{sim_aiva_bought:,.0f}`\n"
        f"  AIVA Burned:     `{buybacks.get('total_aiva_burned', 0):,.0f}`\n\n"

        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ Real buybacks activate when Agent\n"
        f"   reaches $50+ net earnings.\n\n"
        f"CA: `FMKA3FQBu5qqPLxAvf7YTpmP3GpLsSENQYu4xJ72pump`"
    )
    return msg
