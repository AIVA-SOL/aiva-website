"""
database.py — SQLite 本地数据库
管理用户信息、订阅状态、使用配额、已播报记录
"""

import sqlite3
import time
from config import DB_FILE


def get_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化所有表"""
    conn = get_conn()
    c = conn.cursor()

    # 用户表
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            join_time     INTEGER DEFAULT 0,
            is_premium    INTEGER DEFAULT 0,   -- 0=免费 1=高级
            premium_until INTEGER DEFAULT 0,   -- 高级到期时间戳
            aiva_verified INTEGER DEFAULT 0,   -- 是否持有 AIVA 享受免费
            daily_calls   INTEGER DEFAULT 0,   -- 今日已查询次数
            last_reset    INTEGER DEFAULT 0,   -- 上次重置配额的日期（天级时间戳）
            total_calls   INTEGER DEFAULT 0,   -- 累计查询次数
            language      TEXT DEFAULT 'en'
        )
    """)

    # 交易记录表（收费记录）
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            amount_stars  INTEGER,
            pay_time      INTEGER,
            expires_time  INTEGER,
            telegram_charge_id TEXT
        )
    """)

    # 已推送大额交易记录（防重复推送）
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            tx_sig   TEXT PRIMARY KEY,
            sent_at  INTEGER
        )
    """)

    # 已推送新币记录
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_tokens (
            mint     TEXT PRIMARY KEY,
            sent_at  INTEGER
        )
    """)

    # 收益统计（用于触发 Tokenized Agents 回购）
    c.execute("""
        CREATE TABLE IF NOT EXISTS revenue (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            amount_stars INTEGER,
            sol_equiv    REAL,
            record_time  INTEGER
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] 数据库初始化完成")


# ─────────────────────────── 用户操作 ───────────────────────────

def ensure_user(user_id: int, username: str = "", first_name: str = ""):
    """确保用户存在，不存在则创建"""
    conn = get_conn()
    c = conn.cursor()
    existing = c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not existing:
        c.execute("""
            INSERT INTO users (user_id, username, first_name, join_time, last_reset)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, first_name, int(time.time()), _today_ts()))
        conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return user


def is_premium(user_id: int) -> bool:
    """判断用户是否有高级权限（付费或持有 AIVA）"""
    user = get_user(user_id)
    if not user:
        return False
    # 付费高级
    if user["is_premium"] == 1 and user["premium_until"] > int(time.time()):
        return True
    # 持有 AIVA 验证
    if user["aiva_verified"] == 1:
        return True
    return False


def check_and_consume_quota(user_id: int, free_limit: int) -> bool:
    """
    检查并消耗免费配额。
    返回 True = 可以继续使用，False = 超出配额
    """
    if is_premium(user_id):
        # 高级用户无限制
        _increment_total(user_id)
        return True

    conn = get_conn()
    c = conn.cursor()
    user = c.execute("SELECT daily_calls, last_reset FROM users WHERE user_id=?", (user_id,)).fetchone()

    today = _today_ts()
    daily_calls = user["daily_calls"] if user else 0
    last_reset  = user["last_reset"]  if user else 0

    # 新的一天，重置配额
    if last_reset < today:
        daily_calls = 0
        c.execute("UPDATE users SET daily_calls=0, last_reset=? WHERE user_id=?", (today, user_id))

    if daily_calls >= free_limit:
        conn.commit()
        conn.close()
        return False  # 超出配额

    c.execute("UPDATE users SET daily_calls=daily_calls+1, total_calls=total_calls+1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


def set_premium(user_id: int, days: int = 30):
    """设置用户为高级会员"""
    expires = int(time.time()) + days * 86400
    conn = get_conn()
    conn.execute("""
        UPDATE users SET is_premium=1, premium_until=? WHERE user_id=?
    """, (expires, user_id))
    conn.commit()
    conn.close()


def set_aiva_verified(user_id: int, verified: bool):
    """设置 AIVA 持币验证状态"""
    conn = get_conn()
    conn.execute("UPDATE users SET aiva_verified=? WHERE user_id=?", (1 if verified else 0, user_id))
    conn.commit()
    conn.close()


def record_payment(user_id: int, stars: int, charge_id: str):
    """记录支付并激活高级会员"""
    conn = get_conn()
    now = int(time.time())
    expires = now + 30 * 86400
    conn.execute("""
        INSERT INTO payments (user_id, amount_stars, pay_time, expires_time, telegram_charge_id)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, stars, now, expires, charge_id))
    conn.execute("""
        UPDATE users SET is_premium=1, premium_until=? WHERE user_id=?
    """, (expires, user_id))
    # 记录收益
    sol_equiv = stars * 0.013 / 120  # 粗略换算，Stars -> USD -> SOL(~$120/SOL)
    conn.execute("""
        INSERT INTO revenue (user_id, amount_stars, sol_equiv, record_time)
        VALUES (?, ?, ?, ?)
    """, (user_id, stars, sol_equiv, now))
    conn.commit()
    conn.close()


def get_total_revenue_sol() -> float:
    """获取累计收益（SOL 等值）"""
    conn = get_conn()
    row = conn.execute("SELECT SUM(sol_equiv) as total FROM revenue").fetchone()
    conn.close()
    return row["total"] or 0.0


# ─────────────────────── 推送去重 ───────────────────────────────

def is_tx_sent(tx_sig: str) -> bool:
    conn = get_conn()
    r = conn.execute("SELECT tx_sig FROM sent_alerts WHERE tx_sig=?", (tx_sig,)).fetchone()
    conn.close()
    return r is not None


def mark_tx_sent(tx_sig: str):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO sent_alerts (tx_sig, sent_at) VALUES (?, ?)",
                 (tx_sig, int(time.time())))
    conn.commit()
    conn.close()


def is_token_sent(mint: str) -> bool:
    conn = get_conn()
    r = conn.execute("SELECT mint FROM sent_tokens WHERE mint=?", (mint,)).fetchone()
    conn.close()
    return r is not None


def mark_token_sent(mint: str):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO sent_tokens (mint, sent_at) VALUES (?, ?)",
                 (mint, int(time.time())))
    conn.commit()
    conn.close()


def cleanup_old_records(days: int = 3):
    """清理超过 N 天的旧推送记录"""
    cutoff = int(time.time()) - days * 86400
    conn = get_conn()
    conn.execute("DELETE FROM sent_alerts WHERE sent_at < ?", (cutoff,))
    conn.execute("DELETE FROM sent_tokens WHERE sent_at < ?", (cutoff,))
    conn.commit()
    conn.close()


# ─────────────────────── 统计 ────────────────────────────────────

def get_stats():
    """获取全局统计数据"""
    conn = get_conn()
    total_users    = conn.execute("SELECT COUNT(*) as n FROM users").fetchone()["n"]
    premium_users  = conn.execute("SELECT COUNT(*) as n FROM users WHERE is_premium=1 AND premium_until>?",
                                   (int(time.time()),)).fetchone()["n"]
    aiva_holders   = conn.execute("SELECT COUNT(*) as n FROM users WHERE aiva_verified=1").fetchone()["n"]
    total_revenue  = conn.execute("SELECT SUM(amount_stars) as n FROM payments").fetchone()["n"] or 0
    total_calls    = conn.execute("SELECT SUM(total_calls) as n FROM users").fetchone()["n"] or 0
    conn.close()
    return {
        "total_users":   total_users,
        "premium_users": premium_users,
        "aiva_holders":  aiva_holders,
        "total_revenue": total_revenue,
        "total_calls":   total_calls,
    }


# ─────────────────────── 工具函数 ────────────────────────────────

def _today_ts() -> int:
    """返回今天 00:00:00 的时间戳"""
    import datetime
    today = datetime.date.today()
    return int(time.mktime(today.timetuple()))


def _increment_total(user_id: int):
    conn = get_conn()
    conn.execute("UPDATE users SET total_calls=total_calls+1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
