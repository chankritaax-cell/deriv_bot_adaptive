"""
🔬 Backtest: Replay Today's WINNING Trades with Fixed Code
Verify that the enriched market summary does NOT block good trades.
"""
import asyncio
import datetime
import time
import config
from deriv_api import DerivAPI
import market_engine
from technical_analysis import TechnicalConfirmation
from ai_providers import call_ai_with_failover
from smart_trader import SmartTrader

# Today's 7 WINNING trades (Feb 17, 2026, UTC+7)
TRADES = [
    ("2026-02-17 01:40:37", "R_75",    "CALL", "WIN"),    # Trade #1
    ("2026-02-17 03:56:15", "1HZ75V",  "CALL", "WIN"),    # Trade #3
    ("2026-02-17 05:26:51", "1HZ100V", "CALL", "WIN"),    # Trade #5
    ("2026-02-17 06:57:29", "1HZ100V", "CALL", "WIN"),    # Trade #7
    ("2026-02-17 17:06:00", "R_25",    "CALL", "WIN"),    # Trade #12
    ("2026-02-17 18:36:57", "1HZ25V",  "CALL", "WIN"),    # Trade #13
    ("2026-02-17 21:59:44", "1HZ10V",  "CALL", "WIN"),    # Trade #15
]

# UTC offset +7
UTC_OFFSET = 7 * 3600


def time_str_to_epoch(time_str):
    """Convert local time string to UTC epoch."""
    dt = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    epoch = int(dt.timestamp()) - UTC_OFFSET
    return epoch


async def fetch_historical_candles(api, asset, end_epoch, count=100, granularity=60):
    """Fetch candles ending at a specific historical timestamp."""
    start_epoch = end_epoch - (count * granularity)
    try:
        req = {
            "ticks_history": asset,
            "adjust_start_time": 1,
            "count": count,
            "end": end_epoch,
            "start": start_epoch,
            "style": "candles",
            "granularity": granularity
        }
        data = await asyncio.wait_for(api.ticks_history(req), timeout=15.0)
        if "candles" in data:
            import pandas as pd
            df = pd.DataFrame(data["candles"])
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['epoch'] = df['epoch'].astype(int)
            return df
        return None
    except Exception as e:
        print(f"   ❌ Error fetching candles: {e}")
        return None


def build_enriched_summary(asset, df):
    """Build the NEW enriched market summary (same as fixed market_engine)."""
    if df is None or len(df) < 20:
        return None

    price = float(df.iloc[-1]['close'])
    first_price = float(df.iloc[0]['close'])
    change = ((price - first_price) / first_price) * 100
    sma5 = df['close'].rolling(5).mean().iloc[-1]
    sma20 = df['close'].rolling(20).mean().iloc[-1]
    trend = "UPTREND" if sma5 > sma20 else "DOWNTREND"
    sma_gap_pct = abs(sma5 - sma20) / sma20 * 100 if sma20 > 0 else 0

    rsi_str = "N/A"
    macd_str = "N/A"
    atr_str = "N/A"
    stoch_str = "N/A"

    try:
        if len(df) >= 15:
            rsi = TechnicalConfirmation.get_rsi(df)
            if rsi is not None:
                rsi_str = f"{rsi:.1f}"
        if len(df) >= 35:
            macd, macd_sig, hist = TechnicalConfirmation.get_macd(df)
            if hist is not None:
                direction = "bullish" if hist > 0 else "bearish"
                macd_str = f"{hist:.4f} ({direction})"
        if len(df) >= 15:
            atr = TechnicalConfirmation.get_atr(df)
            if atr and price > 0:
                atr_pct = (atr / price) * 100
                atr_str = f"{atr_pct:.4f}%"
        if len(df) >= 17:
            k, d = TechnicalConfirmation.get_stochastic(df)
            if k is not None:
                stoch_str = f"K={k:.1f}, D={d:.1f}"
    except Exception:
        pass

    return (
        f"Asset: {asset}, Close: {price}, Change(100m): {change:.2f}%, "
        f"Trend: {trend}, SMA_Gap: {sma_gap_pct:.3f}%, "
        f"RSI(14): {rsi_str}, MACD_Hist: {macd_str}, "
        f"ATR: {atr_str}, Stoch: {stoch_str}"
    )


async def call_ai_analyst(asset, summary, rsi_val):
    """Call AI Analyst with the same prompt as analyze_and_decide."""
    prompt = f"""
    Analyze this market for {asset}:
    {summary}
    RSI (14): {rsi_val if rsi_val else 'Unknown'}
    
    CRITICAL RULES:
    1. REJECT CALL if RSI > 75 (Overbought).
    2. REJECT PUT if RSI < 25 (Oversold).
    3. FAVOR "Pullbacks" (Dip in Uptrend) over "Breakouts" (already surged).
    
    Recommend ACTION (CALL/PUT/HOLD) and CONFIDENCE (0.0-1.0).
    Return JSON: {{"action": "CALL", "confidence": 0.9, "reason": "Target ..."}}
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, call_ai_with_failover, prompt, "AI_ANALYST", 0.3)
    return result


async def run_l2_check(api, asset, signal, df):
    """Run L2 Technical Confirmation (with fixed stochastic scoring)."""
    score, details = await TechnicalConfirmation.get_confirmation_score(api, asset, signal, df)
    return score, details


async def backtest():
    print("=" * 70)
    print("🔬 BACKTEST: Replaying 7 WINNING Trades with Fixed Code")
    print(f"   Verify fixes do NOT block good trades")
    print("=" * 70)

    api = DerivAPI(app_id=config.DERIV_APP_ID)

    try:
        print("\n🔐 Connecting to Deriv...")
        auth = await api.authorize(config.DERIV_API_TOKEN)
        if "error" in auth:
            print(f"   ❌ Auth failed: {auth['error']['message']}")
            return
        balance = auth['authorize']['balance']
        print(f"   ✅ Connected (Balance: ${balance})")

        results = {"would_enter": 0, "would_skip": 0, "different_signal": 0}


        for i, (time_str, asset, orig_signal, orig_result) in enumerate(TRADES, 1):
            print(f"\n{'─' * 70}")
            print(f"📊 Trade #{i}: {asset} @ {time_str} [Original: {orig_signal} → {orig_result}]")
            print(f"{'─' * 70}")

            epoch = time_str_to_epoch(time_str)

            # Fetch historical candles
            print(f"   📥 Fetching candles ending at epoch {epoch}...")
            df = await fetch_historical_candles(api, asset, epoch)
            if df is None or len(df) < 20:
                print(f"   ❌ Not enough candle data, skipping")
                continue
            print(f"   ✅ Got {len(df)} candles (close: {df.iloc[-1]['close']})")

            # Build NEW enriched summary
            new_summary = build_enriched_summary(asset, df)
            print(f"\n   📝 NEW Summary: {new_summary}")

            # Get RSI for prompt
            rsi_val = None
            if len(df) >= 15:
                rsi_val = TechnicalConfirmation.get_rsi(df)

            # Call AI Analyst with NEW summary
            print(f"\n   🧠 Calling AI Analyst (with enriched data)...")
            ai_result = await call_ai_analyst(asset, new_summary, rsi_val)

            if ai_result:
                new_signal = ai_result.get("action", "HOLD")
                new_conf = ai_result.get("confidence", 0.0)
                new_reason = ai_result.get("reason", "")
                print(f"   🤖 AI Decision: {new_signal} (Conf: {new_conf})")
                print(f"   💬 Reason: {new_reason[:150]}")

                if new_signal not in ("CALL", "PUT"):
                    print(f"   🛑 AI says HOLD → Would SKIP this trade")
                    results["would_skip"] += 1
                    continue

                # Check confidence threshold
                min_conf = getattr(config, "AI_CONFIDENCE_THRESHOLD", 0.65)
                if new_conf < min_conf:
                    print(f"   🛑 Confidence too low ({new_conf:.2f} < {min_conf}) → Would SKIP")
                    results["would_skip"] += 1
                    continue

                if new_signal != orig_signal:
                    print(f"   🔄 Signal CHANGED: {orig_signal} → {new_signal}")
                    results["different_signal"] += 1

                # Run L2 Technical Confirmation
                print(f"\n   📈 Running L2 Tech Confirmation for {new_signal}...")
                l2_score, l2_details = await run_l2_check(api, asset, new_signal, df)
                l2_threshold = getattr(config, "L2_MIN_CONFIRMATION", 0.45)
                print(f"   📊 L2 Score: {l2_score} (threshold: {l2_threshold})")
                print(f"   📋 Details: {l2_details}")

                if l2_score < l2_threshold:
                    print(f"   🛑 L2 too low → Would SKIP this trade")
                    results["would_skip"] += 1
                    continue

                print(f"   ✅ Would ENTER: {new_signal} (Conf: {new_conf}, L2: {l2_score})")
                results["would_enter"] += 1
            else:
                print(f"   ❌ AI returned no result → Would SKIP")
                results["would_skip"] += 1

            # Rate limit between AI calls
            await asyncio.sleep(2)

        # Final Summary
        print(f"\n{'=' * 70}")
        print(f"📊 WINNING TRADES BACKTEST SUMMARY")
        print(f"{'=' * 70}")
        total = len(TRADES)
        print(f"   Total winning trades replayed: {total}")
        print(f"   Would ENTER (preserved win):  {results['would_enter']}")
        print(f"   Would SKIP (lost win):        {results['would_skip']}")
        print(f"   Signal CHANGED (CALL→PUT etc): {results['different_signal']}")
        retain_pct = (results['would_enter'] / total * 100) if total else 0
        print(f"\n   ✅ Win retention rate: {retain_pct:.0f}% ({results['would_enter']}/{total} wins preserved)")
        if results['would_skip'] > 0:
            print(f"   ⚠️ Wins lost by filtering: {results['would_skip']} × $0.95 = ${results['would_skip'] * 0.95:.2f}")

    except Exception as e:
        print(f"\n❌ Backtest error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(backtest())
    except KeyboardInterrupt:
        print("\n⛔ Cancelled.")
