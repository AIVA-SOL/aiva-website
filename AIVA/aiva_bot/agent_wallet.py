"""
agent_wallet.py — AIVA DeFi Agent 钱包管理模块
负责：私钥加密存储 / SOL余额查询 / 交易发送 / 资产查询
安全原则：私钥永远不出现在日志和数据库明文中
"""

import os
import json
import base64
import logging
import asyncio
import aiohttp
from typing import Optional
from cryptography.fernet import Fernet
from config import HELIUS_API_KEY, AGENT_WALLET_KEYPAIR_PATH, PROXY

logger = logging.getLogger("AIVA_AGENT_WALLET")

HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
PROXY_URL  = PROXY  # 统一走代理


# ─────────────────── 加密 / 解密工具 ─────────────────────────────

def _get_or_create_fernet_key() -> bytes:
    """
    从环境变量 AIVA_WALLET_ENC_KEY 读取加密密钥。
    首次运行时自动生成并打印，需要手动保存到环境变量。
    """
    key = os.environ.get("AIVA_WALLET_ENC_KEY", "")
    if not key:
        new_key = Fernet.generate_key()
        logger.warning("=" * 60)
        logger.warning("🔑 首次运行，已生成钱包加密密钥，请将以下密钥保存为环境变量 AIVA_WALLET_ENC_KEY：")
        logger.warning(new_key.decode())
        logger.warning("=" * 60)
        # 临时写到本地文件（仅首次）
        key_file = os.path.join(os.path.dirname(__file__), ".wallet_enc_key")
        with open(key_file, "w") as f:
            f.write(new_key.decode())
        return new_key
    return key.encode()


def _load_fernet() -> Fernet:
    key_file = os.path.join(os.path.dirname(__file__), ".wallet_enc_key")
    env_key = os.environ.get("AIVA_WALLET_ENC_KEY", "")
    if env_key:
        return Fernet(env_key.encode())
    if os.path.exists(key_file):
        with open(key_file) as f:
            return Fernet(f.read().strip().encode())
    _get_or_create_fernet_key()
    return _load_fernet()


# ─────────────────── 钱包创建 / 加载 ─────────────────────────────

def create_agent_wallet() -> dict:
    """
    创建新的 Solana 钱包（Ed25519 密钥对）。
    返回 {"public_key": str, "keypair_b64": str（加密存储用）}
    ⚠️  需要 solders 或 solana-py 库，如未安装使用占位实现
    """
    try:
        from solders.keypair import Keypair
        kp = Keypair()
        pub = str(kp.pubkey())
        secret_b64 = base64.b64encode(bytes(kp)).decode()
        return {"public_key": pub, "keypair_b64": secret_b64}
    except ImportError:
        logger.warning("solders 未安装，使用模拟钱包（仅限测试）")
        import secrets
        fake_key = secrets.token_hex(32)
        return {
            "public_key": "DEMO_WALLET_" + fake_key[:8],
            "keypair_b64": base64.b64encode(fake_key.encode()).decode()
        }


def save_agent_wallet(public_key: str, keypair_b64: str):
    """加密保存钱包到本地文件"""
    fernet = _load_fernet()
    data = json.dumps({"public_key": public_key, "keypair_b64": keypair_b64})
    encrypted = fernet.encrypt(data.encode())
    wallet_file = os.path.join(os.path.dirname(__file__), "agent_wallet.enc")
    with open(wallet_file, "wb") as f:
        f.write(encrypted)
    logger.info(f"[Wallet] 钱包已加密保存：{public_key}")


def load_agent_wallet() -> Optional[dict]:
    """从加密文件加载钱包"""
    wallet_file = os.path.join(os.path.dirname(__file__), "agent_wallet.enc")
    if not os.path.exists(wallet_file):
        return None
    try:
        fernet = _load_fernet()
        with open(wallet_file, "rb") as f:
            encrypted = f.read()
        data = json.loads(fernet.decrypt(encrypted).decode())
        return data
    except Exception as e:
        logger.error(f"[Wallet] 加载钱包失败: {e}")
        return None


def get_or_create_wallet() -> dict:
    """获取现有钱包，不存在则创建"""
    wallet = load_agent_wallet()
    if wallet:
        return wallet
    logger.info("[Wallet] 未找到现有钱包，正在创建新钱包...")
    wallet = create_agent_wallet()
    save_agent_wallet(wallet["public_key"], wallet["keypair_b64"])
    return wallet


# ─────────────────── 链上余额查询 ─────────────────────────────────

async def _rpc_post(payload: dict) -> Optional[dict]:
    """发送 RPC 请求（Helius，不走代理）"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                HELIUS_RPC, json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.error(f"[RPC] 请求失败: {e}")
    return None


async def get_sol_balance(public_key: str) -> float:
    """查询钱包 SOL 余额"""
    data = await _rpc_post({
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [public_key]
    })
    if data and "result" in data:
        return data["result"].get("value", 0) / 1e9
    return 0.0


async def get_token_balance(public_key: str, mint: str) -> float:
    """查询钱包中指定代币余额"""
    data = await _rpc_post({
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            public_key,
            {"mint": mint},
            {"encoding": "jsonParsed"}
        ]
    })
    if data and "result" in data:
        accounts = data["result"].get("value", [])
        total = 0.0
        for acc in accounts:
            parsed = acc.get("account", {}).get("data", {}).get("parsed", {})
            info = parsed.get("info", {})
            amount = float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
            total += amount
        return total
    return 0.0


async def get_usdc_balance(public_key: str) -> float:
    """查询 USDC 余额"""
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    return await get_token_balance(public_key, USDC_MINT)


async def get_wallet_summary(public_key: str) -> dict:
    """获取 Agent 钱包资产概览"""
    from solana_data import get_sol_price
    sol_balance = await get_sol_balance(public_key)
    usdc_balance = await get_usdc_balance(public_key)
    sol_price = await get_sol_price()
    total_usd = sol_balance * sol_price + usdc_balance
    return {
        "public_key":  public_key,
        "sol":         round(sol_balance, 4),
        "usdc":        round(usdc_balance, 2),
        "sol_price":   sol_price,
        "total_usd":   round(total_usd, 2),
    }
