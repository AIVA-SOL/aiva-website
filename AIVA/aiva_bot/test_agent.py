"""
test_agent.py — DeFi Agent 功能测试脚本
验证所有模块正常初始化和基本功能
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

def run_tests():
    print("=" * 55)
    print("  AIVA DeFi Agent — 功能测试")
    print("=" * 55)
    passed = 0
    failed = 0

    # --- Test 1: 数据库初始化 ---
    try:
        import database as db
        import agent_database as adb
        db.init_db()
        adb.init_agent_tables()
        print("[1/7] ✅ 数据库初始化 OK")
        passed += 1
    except Exception as e:
        print(f"[1/7] ❌ 数据库初始化失败: {e}")
        failed += 1

    # --- Test 2: 钱包创建/加载 ---
    try:
        import agent_wallet as aw
        wallet = aw.get_or_create_wallet()
        pub = wallet.get("public_key", "")
        assert pub, "钱包公钥为空"
        print(f"[2/7] ✅ 钱包 OK: {pub[:20]}...")
        passed += 1
    except Exception as e:
        print(f"[2/7] ❌ 钱包失败: {e}")
        failed += 1

    # --- Test 3: 策略模块 import ---
    try:
        from agent_strategies import StrategyEngine, get_all_stable_apys
        eng = StrategyEngine(simulation_mode=True)
        assert eng.simulation_mode == True
        print("[3/7] ✅ 策略引擎 import OK")
        passed += 1
    except Exception as e:
        print(f"[3/7] ❌ 策略引擎失败: {e}")
        failed += 1

    # --- Test 4: 收益记录 ---
    try:
        adb.record_earning(
            strategy_type="arbitrage",
            strategy_name="USDC→SOL→USDC",
            gross_usd=0.050,
            fee_usd=0.003,
            net_usd=0.047,
            is_simulated=True,
            notes="unit test"
        )
        earnings = adb.get_total_earnings(simulated_only=True)
        assert earnings["count"] >= 1
        print(f"[4/7] ✅ 收益记录 OK (累计净利润: ${earnings['total_net']:.4f})")
        passed += 1
    except Exception as e:
        print(f"[4/7] ❌ 收益记录失败: {e}")
        failed += 1

    # --- Test 5: 模拟回购 ---
    async def test_buyback():
        import agent_buyback as bb
        result = await bb.simulate_buyback(usdc_amount=1.0, aiva_price_usd=0.0001)
        assert result["success"] == True
        assert result["aiva_bought"] > 0
        return result

    try:
        result = asyncio.run(test_buyback())
        print(f"[5/7] ✅ 模拟回购 OK: $1.00 → {result['aiva_bought']:,.0f} AIVA (销毁)")
        passed += 1
    except Exception as e:
        print(f"[5/7] ❌ 模拟回购失败: {e}")
        failed += 1

    # --- Test 6: 回购统计 ---
    try:
        stats = adb.get_buyback_stats()
        assert "total_buybacks" in stats
        print(f"[6/7] ✅ 回购统计 OK: {stats['total_buybacks']} buybacks, "
              f"{stats['sim_aiva_bought']:,.0f} AIVA sim-bought")
        passed += 1
    except Exception as e:
        print(f"[6/7] ❌ 回购统计失败: {e}")
        failed += 1

    # --- Test 7: Agent 状态快照 + 消息格式化 ---
    try:
        import agent_buyback as bb
        snapshot = adb.get_agent_status_snapshot()
        msg = bb.format_agent_status_message(snapshot)
        assert "AIVA DeFi Agent" in msg
        assert len(msg) > 100
        print(f"[7/7] ✅ 状态消息格式化 OK ({len(msg)} chars)")
        passed += 1
    except Exception as e:
        print(f"[7/7] ❌ 状态消息失败: {e}")
        failed += 1

    print()
    print("=" * 55)
    print(f"  结果: {passed}/7 通过   {failed} 失败")
    print("=" * 55)
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
