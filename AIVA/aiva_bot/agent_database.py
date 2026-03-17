"""
agent_database.py — AIVA DeFi Agent 专用数据库扩展
负责：
  - Agent 钱包状态记录
  - 策略扫描历史
  - 收益记录（模拟 + 真实）
  - 回购销毁记录
  - Agent 运行日志
"""

import sqlite3
import time
import json
import logging
from typing import Optional
from config import DB_FILE

logger = logging.getLogger("AIVA_AGENT_DB")


def get_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_agent_tables():
    """初始化 Agent 相关的数据表（在现有 DB 中新增）"""
    conn = get_conn()
    c = conn.cursor()

    # Agent 钱包状态表
    c.execute("""
        CREATE TABLE IF NOT EXISTS agent_wallet (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            public_key     TEXT UNIQUE,
            sol_balance    REAL DEFAULT 0,
            usdc_balance   REAL DEFAULT 0,
            total_usd      REAL DEFAULT 0,
            last_updated   INTEGER DEFAULT 0
        )
    """)

    # 策略扫描历史表
    c.execute("""
        CREATE TABLE IF NOT EXISTS agent_scans (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time      INTEGER,
            best_strategy  TEXT,   -- JSON
            apy_data       TEXT,   -- JSON
            arb_count      INTEGER DEFAULT 0,
            best_arb_pct   REAL DEFAULT 0,
            sim_mode       INTEGER DEFAULT 1
        )
    """)

    # 收益记录表（模拟或真实）
    c.execute("""
        CREATE TABLE IF NOT EXISTS agent_earnings (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            earn_time      INTEGER,
            strategy_type  TEXT,   -- "arbitrage" | "yield_farming"
            strategy_name  TEXT,
            gross_usd      REAL DEFAULT 0,   -- 毛利润（USD）
            fee_usd        REAL DEFAULT 0,   -- 手续费（USD）
            net_usd        REAL DEFAULT 0,   -- 净利润（USD）
            is_simulated   INTEGER DEFAULT 1, -- 1=模拟 0=真实
            tx_signature   TEXT DEFAULT '',
            notes          TEXT DEFAULT ''
        )
    """)

    # 回购销毁记录表
    c.execute("""
        CREATE TABLE IF NOT EXISTS agent_buybacks (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            buyback_time   INTEGER,
            trigger_source TEXT,   -- "earnings" | "manual" | "scheduled"
            usdc_used      REAL,   -- 用于回购的 USDC 金额
            aiva_bought    REAL,   -- 回购到的 AIVA 数量
            aiva_price     REAL,   -- 回购时 AIVA 价格
            is_burned      INTEGER DEFAULT 0, -- 是否已销毁
            burn_tx_sig    TEXT DEFAULT '',
            buyback_tx_sig TEXT DEFAULT '',
            is_simulated   INTEGER DEFAULT 1,
            notes          TEXT DEFAULT ''
        )
    """)

    # Agent 运行日志表
    c.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            log_time  INTEGER,
            level     TEXT,   -- "INFO" | "WARNING" | "ERROR"
            module    TEXT,
            message   TEXT
        )
    """)

    # Agent 配置表（键值对）
    c.execute("""
        CREATE TABLE IF NOT EXISTS agent_config (
            key   TEXT PRIMARY KEY,
            value TEXT,
            updated_at INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()
    logger.info("[AgentDB] Agent 数据表初始化完成")


# ─────────────────── 钱包状态 ─────────────────────────────────────

def upsert_wallet_state(public_key: str, sol: float, usdc: float, total_usd: float):
    """更新 Agent 钱包状态"""
    conn = get_conn()
    conn.execute("""
        INSERT INTO agent_wallet (public_key, sol_balance, usdc_balance, total_usd, last_updated)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(public_key) DO UPDATE SET
            sol_balance=excluded.sol_balance,
            usdc_balance=excluded.usdc_balance,
            total_usd=excluded.total_usd,
            last_updated=excluded.last_updated
    """, (public_key, sol, usdc, total_usd, int(time.time())))
    conn.commit()
    conn.close()


def get_wallet_state() -> Optional[dict]:
    """获取最新钱包状态"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM agent_wallet ORDER BY last_updated DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────── 策略扫描记录 ────────────────────────────────

def record_strategy_scan(scan_result: dict):
    """记录策略扫描结果"""
    conn = get_conn()
    arb_opps = scan_result.get("arb_opps", [])
    best_arb_pct = max((a.get("profit_pct", 0) for a in arb_opps), default=0)
    conn.execute("""
        INSERT INTO agent_scans
            (scan_time, best_strategy, apy_data, arb_count, best_arb_pct, sim_mode)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        scan_result.get("timestamp", int(time.time())),
        json.dumps(scan_result.get("best_strategy", {})),
        json.dumps(scan_result.get("apy_data", {})),
        len(arb_opps),
        best_arb_pct,
        1 if scan_result.get("sim_mode", True) else 0
    ))
    conn.commit()
    conn.close()


def get_last_scan() -> Optional[dict]:
    """获取最近一次扫描结果"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM agent_scans ORDER BY scan_time DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    r = dict(row)
    r["best_strategy"] = json.loads(r.get("best_strategy") or "{}")
    r["apy_data"]      = json.loads(r.get("apy_data") or "{}")
    return r


def get_recent_scans(limit: int = 24) -> list:
    """获取最近 N 次扫描记录"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_scans ORDER BY scan_time DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        r = dict(row)
        r["best_strategy"] = json.loads(r.get("best_strategy") or "{}")
        result.append(r)
    return result


# ─────────────────── 收益记录 ────────────────────────────────────

def record_earning(
    strategy_type: str,
    strategy_name: str,
    gross_usd: float,
    fee_usd: float,
    net_usd: float,
    is_simulated: bool = True,
    tx_signature: str = "",
    notes: str = ""
):
    """记录一次收益"""
    conn = get_conn()
    conn.execute("""
        INSERT INTO agent_earnings
            (earn_time, strategy_type, strategy_name, gross_usd, fee_usd,
             net_usd, is_simulated, tx_signature, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()), strategy_type, strategy_name,
        gross_usd, fee_usd, net_usd,
        1 if is_simulated else 0, tx_signature, notes
    ))
    conn.commit()
    conn.close()


def get_total_earnings(simulated_only: bool = True) -> dict:
    """获取累计收益统计"""
    conn = get_conn()
    sim_filter = "AND is_simulated=1" if simulated_only else ""
    row = conn.execute(f"""
        SELECT
            COUNT(*) as count,
            SUM(gross_usd) as total_gross,
            SUM(fee_usd) as total_fees,
            SUM(net_usd) as total_net
        FROM agent_earnings
        WHERE 1=1 {sim_filter}
    """).fetchone()
    conn.close()
    if row:
        return {
            "count":       row["count"] or 0,
            "total_gross": round(row["total_gross"] or 0, 4),
            "total_fees":  round(row["total_fees"] or 0, 4),
            "total_net":   round(row["total_net"] or 0, 4),
        }
    return {"count": 0, "total_gross": 0, "total_fees": 0, "total_net": 0}


def get_recent_earnings(limit: int = 10) -> list:
    """获取最近 N 条收益记录"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM agent_earnings ORDER BY earn_time DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_buyback_amount() -> float:
    """
    获取待回购的 USDC 金额（已累积但未触发回购的净利润 * 回购比例）
    """
    earnings = get_total_earnings(simulated_only=False)
    sim_earnings = get_total_earnings(simulated_only=True)
    # 真实净利润的 50% 用于回购
    total_net = earnings["total_net"]
    already_bought = get_total_buyback_amount()
    pending = max(0, total_net * 0.5 - already_bought)
    return round(pending, 4)


def get_total_buyback_amount() -> float:
    """获取历史总回购 USDC 金额"""
    conn = get_conn()
    row = conn.execute(
        "SELECT SUM(usdc_used) as total FROM agent_buybacks WHERE is_simulated=0"
    ).fetchone()
    conn.close()
    return row["total"] or 0.0


# ─────────────────── 回购销毁记录 ────────────────────────────────

def record_buyback(
    usdc_used: float,
    aiva_bought: float,
    aiva_price: float,
    trigger_source: str = "earnings",
    is_burned: bool = False,
    buyback_tx_sig: str = "",
    burn_tx_sig: str = "",
    is_simulated: bool = True,
    notes: str = ""
):
    """记录一次回购销毁操作"""
    conn = get_conn()
    conn.execute("""
        INSERT INTO agent_buybacks
            (buyback_time, trigger_source, usdc_used, aiva_bought, aiva_price,
             is_burned, burn_tx_sig, buyback_tx_sig, is_simulated, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()), trigger_source, usdc_used, aiva_bought, aiva_price,
        1 if is_burned else 0, burn_tx_sig, buyback_tx_sig,
        1 if is_simulated else 0, notes
    ))
    conn.commit()
    conn.close()


def get_buyback_stats() -> dict:
    """获取回购销毁统计"""
    conn = get_conn()
    row = conn.execute("""
        SELECT
            COUNT(*) as count,
            SUM(usdc_used) as total_usdc,
            SUM(aiva_bought) as total_aiva,
            SUM(CASE WHEN is_burned=1 THEN aiva_bought ELSE 0 END) as total_burned
        FROM agent_buybacks
    """).fetchone()
    sim_row = conn.execute("""
        SELECT SUM(aiva_bought) as sim_aiva
        FROM agent_buybacks WHERE is_simulated=1
    """).fetchone()
    conn.close()
    return {
        "total_buybacks":   row["count"] or 0,
        "total_usdc_spent": round(row["total_usdc"] or 0, 2),
        "total_aiva_bought":round(row["total_aiva"] or 0, 0),
        "total_aiva_burned":round(row["total_burned"] or 0, 0),
        "sim_aiva_bought":  round(sim_row["sim_aiva"] or 0, 0),
    }


def get_recent_buybacks(limit: int = 5) -> list:
    """获取最近几次回购记录"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_buybacks ORDER BY buyback_time DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────── Agent 日志 ──────────────────────────────────

def agent_log(level: str, module: str, message: str):
    """写 Agent 运行日志"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO agent_logs (log_time, level, module, message) VALUES (?, ?, ?, ?)",
        (int(time.time()), level, module, message[:500])
    )
    conn.commit()
    conn.close()


def get_recent_logs(limit: int = 20, level: str = None) -> list:
    """获取最近运行日志"""
    conn = get_conn()
    if level:
        rows = conn.execute(
            "SELECT * FROM agent_logs WHERE level=? ORDER BY log_time DESC LIMIT ?",
            (level, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM agent_logs ORDER BY log_time DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────── Agent 配置 ──────────────────────────────────

def set_config(key: str, value: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO agent_config (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, value, int(time.time())))
    conn.commit()
    conn.close()


def get_config(key: str, default: str = "") -> str:
    conn = get_conn()
    row = conn.execute("SELECT value FROM agent_config WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


# ─────────────────── 综合状态快照 ────────────────────────────────

def get_agent_status_snapshot() -> dict:
    """获取 Agent 完整状态，用于 /agent_status 命令"""
    wallet  = get_wallet_state()
    earnings = get_total_earnings(simulated_only=False)
    sim_earnings = get_total_earnings(simulated_only=True)
    buybacks = get_buyback_stats()
    last_scan = get_last_scan()
    recent_earn = get_recent_earnings(limit=3)
    recent_bb   = get_recent_buybacks(limit=3)
    scan_count = conn_count("agent_scans")

    return {
        "wallet":       wallet,
        "earnings":     earnings,
        "sim_earnings": sim_earnings,
        "buybacks":     buybacks,
        "last_scan":    last_scan,
        "recent_earn":  recent_earn,
        "recent_bb":    recent_bb,
        "scan_count":   scan_count,
    }


def conn_count(table: str) -> int:
    """计数"""
    conn = get_conn()
    row = conn.execute(f"SELECT COUNT(*) as n FROM {table}").fetchone()
    conn.close()
    return row["n"] if row else 0
