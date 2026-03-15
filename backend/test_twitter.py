"""
推特模块独立测试脚本
用法：
    cd backend
    python test_twitter.py
    python test_twitter.py --coin SOL --refresh
"""
import asyncio
import argparse
import json
import sys
import os

# 让脚本可以直接运行（不依赖包安装）
sys.path.insert(0, os.path.dirname(__file__))

# 设置最小环境变量（避免 config 加载报错）
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("GATE_API_KEY", "")


async def test_single(coin: str, refresh: bool):
    """测试单个币种推特情绪"""
    from src.twitter import get_twitter_sentiment, get_raw_tweets, KNOWN_ACCOUNTS

    print(f"\n{'='*60}")
    print(f"  测试币种: {coin.upper()}")
    account = KNOWN_ACCOUNTS.get(coin.upper(), "（自动发现）")
    print(f"  推特账号: @{account}")
    print(f"{'='*60}")

    print("\n[1] 爬取推文...")
    tweets = await get_raw_tweets(coin.upper())
    print(f"    获取到 {len(tweets)} 条推文")
    if tweets:
        print("\n  最新3条推文：")
        for tw in tweets[:3]:
            print(f"  ─ [{tw['time'] or '时间未知'}]")
            print(f"    {tw['text'][:100]}...")
            print(f"    ❤️ {tw['likes']}  🔁 {tw['retweets']}  💬 {tw['replies']}")

    print("\n[2] 情绪分析...")
    score = await get_twitter_sentiment(coin.upper(), force_refresh=refresh)
    print(f"  推特状态   : {score.tweet_status.value}")
    print(f"  最新推文时间: {score.last_tweet_time or '未知'}")
    print(f"  7天推文数  : {score.tweet_count_7d}")
    print(f"  正向推文比 : {score.positive_ratio * 100:.1f}%")
    print(f"  情绪评分   : {score.tweet_score:.1f} / 100")


async def test_batch(coins: list):
    """测试批量爬取"""
    from src.twitter import batch_get_twitter_sentiment

    print(f"\n{'='*60}")
    print(f"  批量测试: {coins}")
    print(f"{'='*60}\n")

    results = await batch_get_twitter_sentiment(coins, concurrency=3)

    print(f"{'币种':<8} {'状态':<12} {'情绪分':<10} {'7天推文':<10} {'正向比'}")
    print("-" * 60)
    for coin, score in results.items():
        print(
            f"{coin:<8} "
            f"{score.tweet_status.value:<12} "
            f"{score.tweet_score:<10.1f} "
            f"{score.tweet_count_7d:<10} "
            f"{score.positive_ratio * 100:.1f}%"
        )


async def test_nitter_health():
    """测试 Nitter 实例可用性"""
    from src.twitter import _nitter_manager, NITTER_INSTANCES

    print(f"\n{'='*60}")
    print("  Nitter 实例健康检测")
    print(f"{'='*60}\n")
    print(f"待检测实例数: {len(NITTER_INSTANCES)}")

    best = await _nitter_manager.get_best()
    all_healthy = await _nitter_manager.get_all_healthy()

    print(f"\n✅ 首选实例  : {best}")
    print(f"✅ 全部健康  : {all_healthy}")
    print(f"❌ 不可用数  : {len(NITTER_INSTANCES) - len(all_healthy)}")


async def main():
    parser = argparse.ArgumentParser(description="推特模块测试")
    parser.add_argument("--coin",    default="BTC",  help="单个币种（默认 BTC）")
    parser.add_argument("--batch",   default="BTC,ETH,SOL,DOGE", help="批量币种（逗号分隔）")
    parser.add_argument("--refresh", action="store_true", help="强制刷新缓存")
    parser.add_argument("--health",  action="store_true", help="只检测 Nitter 实例健康")
    args = parser.parse_args()

    if args.health:
        await test_nitter_health()
        return

    await test_nitter_health()
    await test_single(args.coin, args.refresh)
    await test_batch([c.strip() for c in args.batch.split(",")])

    print("\n\n✅ 所有测试完成\n")


if __name__ == "__main__":
    asyncio.run(main())
