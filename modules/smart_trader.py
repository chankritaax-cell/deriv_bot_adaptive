"""
🧠 Smart Trader Module (v3.5.3)
Handles Reinforcement Learning (RL), Performance Tracking, and High-Level Trade Decisions.
[v3.5.3] Made Hard Rules Configurable (ENABLE_HARD_RULES).
"""

import os
import json
import random
import datetime
import config
from .technical_analysis import TechnicalConfirmation
from .utils import safe_config_get, save_json_atomic # [v5.1.0] Atomic Persistence Support

# [v3.11.25] Align with ROOT_DIR
ROOT = getattr(config, "ROOT_DIR", os.getcwd())
DATA_DIR = os.path.join(ROOT, "logs", "smart_data")
os.makedirs(DATA_DIR, exist_ok=True)
PERF_FILE = os.path.join(DATA_DIR, "performance.json")
RL_MODEL_FILE = os.path.join(DATA_DIR, "rl_model.json")

class PerformanceTracker:
    def __init__(self):
        self.data = self._load()
    
    def _load(self):
        if os.path.exists(PERF_FILE):
            try:
                with open(PERF_FILE, "r") as f: return json.load(f)
            except: pass
        return {"trades": [], "asset_stats": {}, "strategy_stats": {}, "hourly_stats": {}, "combo_stats": {}}

    def _save(self):
        """Atomic Save: Prevents performance.json corruption during process kills."""
        try:
            save_json_atomic(self.data, PERF_FILE)
        except Exception as e:
            pass # Silent failure to keep trading loop alive

    def record_trade(self, asset, strategy, signal, result, profit, trade_type="UNKNOWN", confidence=0.0, regime="UNKNOWN", adaptive_score=0.0, tf="1m"):
        now = datetime.datetime.now()
        rec = {
            "ts": now.strftime("%Y-%m-%d %H:%M:%S"), "asset": asset, "strategy": strategy,
            "signal": signal, "result": result, "profit": profit, "confidence": confidence
        }
        self.data["trades"].append(rec)
        # Expanded Memory: Keep last 10,000 trades instead of 200
        if len(self.data["trades"]) > 10000: self.data["trades"] = self.data["trades"][-10000:]
        
        # Update Stats (Legacy Combo)
        combo = f"{asset}|{strategy}"
        if combo not in self.data["combo_stats"]: self.data["combo_stats"][combo] = {"wins": 0, "losses": 0, "profit": 0.0}
        s = self.data["combo_stats"][combo]
        if result == "WIN": s["wins"] += 1
        elif result == "LOSS": s["losses"] += 1
        s["profit"] += profit
        
        # Update Stats (Legacy Asset)
        self.data["asset_stats"].setdefault(asset, {"wins":0,"losses":0})
        if result=="WIN": self.data["asset_stats"][asset]["wins"]+=1
        if result=="LOSS": self.data["asset_stats"][asset]["losses"]+=1
        
        # [v3.6.0] Update Stats (Granular: Asset|Strategy|Direction|TF)
        # We use 'signal' as direction (CALL/PUT)
        direction = signal if signal in ["CALL", "PUT"] else "UNKNOWN"
        key = f"{asset}|{strategy}|{direction}|{tf}"
        
        if "combo_stats" not in self.data: self.data["combo_stats"] = {}
        if "asset_stats" not in self.data: self.data["asset_stats"] = {}
        # [v3.6.0] Initialize Granular Stats
        if "strategy_stats" not in self.data: self.data["strategy_stats"] = {}
        if key not in self.data["strategy_stats"]: self.data["strategy_stats"][key] = {"wins": 0, "losses": 0}
        
        gs = self.data["strategy_stats"][key]
        if result == "WIN": gs["wins"] += 1
        elif result == "LOSS": gs["losses"] += 1
        
        self._save()

    def get_win_rate(self, asset=None, strategy=None, last_n=None):
        trades = self.data["trades"]
        if asset: trades = [t for t in trades if t["asset"] == asset]
        if strategy: trades = [t for t in trades if t["strategy"] == strategy]
        if last_n: trades = trades[-last_n:]
        if not trades: return 0.5
        wins = sum(1 for t in trades if t["result"] == "WIN")
        total = sum(1 for t in trades if t["result"] in ["WIN", "LOSS"])
        return wins/total if total>0 else 0.5

    def get_ai_summary(self, current_asset=None):
        recent = self.data["trades"][-10:]
        lines = []
        if recent:
            wins = sum(1 for t in recent if t["result"] == "WIN")
            lines.append(f"Recent (10): {wins}W/{len(recent)-wins}L")
        if current_asset:
            wr = self.get_win_rate(asset=current_asset)
            lines.append(f"Asset {current_asset} WR: {wr:.0%}")
        return "\n".join(lines)

    def get_dynamic_bet_multiplier(self, asset, strategy):
        """Level 1C: Auto-adjust bet size based on recent performance."""
        combo_key = f"{asset}|{strategy}"
        combo_trades = [t for t in self.data["trades"] if f"{t['asset']}|{t['strategy']}" == combo_key][-5:]
        if len(combo_trades) < 3: return 1.0
        wins = sum(1 for t in combo_trades if t["result"] == "WIN")
        wr = wins / len(combo_trades)
        if wr >= 0.8: return 1.25
        elif wr <= 0.2: return 0.75  # [v3.4.1] Raised from 0.5 — prevent sub-dollar stakes
        return 1.0

    def get_martingale_multiplier(self, loss_streak):
        """[v3.11.28] Calculates Martingale multiplier based on loss streak."""
        max_steps = safe_config_get("MAX_MARTINGALE_STEPS", 0)
        multiplier = safe_config_get("MARTINGALE_MULTIPLIER", 1.0)
        
        if loss_streak <= 0 or max_steps <= 0:
            return 1.0
            
        # Limit the steps
        level = min(loss_streak, max_steps)
        return float(multiplier ** level)

    # [v3.6.0] Bayesian Smoothing & Granular Keys
    def _get_bayes_p(self, key, prior_a=3, prior_b=3):
        """Calculate Bayesian smoothed probability with Beta(3,3) prior."""
        stats = self.data["strategy_stats"].get(key, {"wins": 0, "losses": 0})
        wins = stats["wins"]
        losses = stats["losses"]
        return (prior_a + wins) / (prior_a + prior_b + wins + losses)

    def should_block_combo(self, asset, strategy, direction="CALL", tf="1m", threshold=0.45):
        """
        Check if a combo should be blocked using Bayesian probability.
        Key: Asset|Strategy|Direction|TF
        """
        key = f"{asset}|{strategy}|{direction}|{tf}"
        stats = self.data["strategy_stats"].get(key, {"wins": 0, "losses": 0})
        n = stats["wins"] + stats["losses"]
        
        # 1. Min Samples Check
        min_samples = safe_config_get("MIN_TRADES_FOR_BLOCK", 12)
        if n < min_samples:
            return False, {"n": n, "reason": "insufficient_samples"}
            
        # 2. Bayesian Probability
        p_bayes = self._get_bayes_p(key)
        
        # 3. Block Logic (with hysteresis handled by caller or simple threshold for now)
        # Using simple threshold from user request: < 0.45 = BLOCK
        blocked = p_bayes < threshold
        
        return blocked, {
            "wins": stats["wins"],
            "losses": stats["losses"],
            "n": n,
            "p_bayes": round(p_bayes, 4),
            "key": key
        }

class SmartDecisionEngine:
    def __init__(self):
        self.q_table = {}
        self.visit_count = {}
        self.epsilon = 0.0
        self._load()

    def _load(self):
        if os.path.exists(RL_MODEL_FILE):
            try:
                with open(RL_MODEL_FILE, "r") as f:
                    d = json.load(f)
                    self.q_table = d.get("q_table", {})
                    self.visit_count = d.get("visit_count", {})
            except: pass

    def _save(self):
        """Atomic Save: Prevents RL model corruption."""
        try:
            data_to_save = {"q_table": self.q_table, "visit_count": self.visit_count}
            save_json_atomic(data_to_save, RL_MODEL_FILE)
        except Exception as e:
            pass

    def _state_key(self, asset, strategy, conf):
        bucket = "HIGH" if conf >= 0.75 else "MED" if conf >= 0.5 else "LOW"
        return f"{asset}|{strategy}|{bucket}"

    def decide(self, asset, strategy, conf):
        key = self._state_key(asset, strategy, conf)
        if key not in self.q_table:
            self.q_table[key] = {"ENTER": 0.0, "SKIP": 0.0}
            self.visit_count[key] = {"ENTER": 0, "SKIP": 0}
            
        if random.random() < self.epsilon:
            return random.choice(["ENTER", "SKIP"]), 0.5, "Explore"
        
        q_ent = self.q_table[key]["ENTER"]
        q_skip = self.q_table[key]["SKIP"]
        action = "ENTER" if q_ent >= q_skip else "SKIP"
        return action, abs(q_ent - q_skip), "Exploit"

    def update(self, asset, strategy, conf, action, reward):
        key = self._state_key(asset, strategy, conf)
        if key not in self.q_table: return
        old_q = self.q_table[key][action]
        new_q = old_q + 0.1 * (reward - old_q)
        self.q_table[key][action] = new_q
        self.visit_count[key][action] += 1
        self._save()

    def get_stats(self):
        total_updates = sum(sum(v.values()) for v in self.visit_count.values())
        return {
            "total_states": len(self.q_table),
            "total_updates": total_updates,
            "epsilon": self.epsilon
        }

class SmartTrader:
    def __init__(self):
        self.perf = PerformanceTracker()
        self.tech = TechnicalConfirmation()
        self.rl = SmartDecisionEngine()

    async def should_enter(self, api, asset, strategy, signal, regime="UNKNOWN", confidence=0.0, df_1m=None, asset_profile=None):  # [v5.0 BUG-03 FIX]
        """Master decision combining L1 (Perf) → L2 (Tech) → L3 (RL)."""
        details = {
            "level1_perf": {}, "level2_tech": {}, "level3_rl": {},
            "final_decision": "ENTER", "reasons": []
        }

        # [v3.6.0] Level 1: Bayesian Performance Check
        # Restore variables needed for later logic
        combo_wr = self.perf.get_win_rate(asset=asset, strategy=strategy, last_n=10)
        bet_mult = self.perf.get_dynamic_bet_multiplier(asset, strategy)
        
        # Default direction/tf if not provided
        direction = "CALL" # default, ideally passed in
        # Extract direction from signal if possible, or pass as arg. 
        # But 'signal' arg IS the direction usually (CALL/PUT). 
        # Let's assume signal=direction for now.
        direction = signal if signal in ["CALL", "PUT"] else "UNKNOWN"
        tf = "1m" # Default for now
        
        block_th = safe_config_get("BAYES_BLOCK_THRESHOLD", 0.45)
        blocked, block_info = self.perf.should_block_combo(asset, strategy, direction, tf, threshold=block_th)
        
        details["level1_perf"] = block_info
        if blocked:
            details["final_decision"] = "SKIP"
            details["reasons"].append(f"L1: Blocked by Bayes (p={block_info['p_bayes']} < {block_th}, n={block_info['n']})")
            return False, bet_mult, details

        # --- Level 1.5: Hard Rules (Safety Net) ---
        # [v3.5.3] Configurable Technical Filters
        if safe_config_get("ENABLE_HARD_RULES", True):
            is_safe, failure_reason = TechnicalConfirmation.check_hard_rules(df_1m, signal)
            if not is_safe:
                 details["final_decision"] = "SKIP"
                 details["reasons"].append(f"L1.5: {failure_reason}")
                 return False, bet_mult, details

        # --- Strategy Specific Rules (PULLBACK_ENTRY) ---
        if strategy == "PULLBACK_ENTRY" and df_1m is not None and len(df_1m) >= 15:
            # [v5.0 Adaptive Engine] Read RSI zones from asset_profile if available
            # Default zones: PUT=[48,58] CALL=[42,52] (mean-reversion pullback zones)
            _pb_profile_bounds = asset_profile.get("rsi_bounds", {}) if asset_profile else {}

            # PUT pullback zone: RSI dipping back into mid-range after downtrend
            _pb_put_lo  = float(_pb_profile_bounds.get("pullback_put_lo",  48.0))
            _pb_put_hi  = float(_pb_profile_bounds.get("pullback_put_hi",  58.0))
            _pb_put_max = float(_pb_profile_bounds.get("pullback_put_max", 65.0))  # RSI ceiling for PUT

            # CALL pullback zone: RSI bouncing back into mid-range after uptrend
            _pb_call_lo  = float(_pb_profile_bounds.get("pullback_call_lo",  42.0))
            _pb_call_hi  = float(_pb_profile_bounds.get("pullback_call_hi",  52.0))
            _pb_call_min = float(_pb_profile_bounds.get("pullback_call_min", 35.0))  # RSI floor for CALL

            rsi_now = TechnicalConfirmation.get_rsi(df_1m)
            rsi_prev = TechnicalConfirmation.get_rsi(df_1m.iloc[:-1])
            atr_now = TechnicalConfirmation.get_atr(df_1m)
            atr_list = [TechnicalConfirmation.get_atr(df_1m.iloc[:-i]) for i in range(1, 10)]
            atr_list = [a for a in atr_list if a is not None]
            ema_atr = sum(atr_list)/len(atr_list) if atr_list else 0
            
            sma = df_1m["close"].rolling(7).mean()
            slope = 0
            if len(sma) >= 6 and sma.iloc[-6] > 0:
                slope = (sma.iloc[-1] - sma.iloc[-6]) / sma.iloc[-6] * 100
                
            stoch_k, stoch_d = TechnicalConfirmation.get_stochastic(df_1m)
            
            # [v5.0 FIX] Explicit block when indicators unavailable
            if rsi_now is None or rsi_prev is None:
                details["reasons"].append("PULLBACK_ENTRY: RSI unavailable (insufficient candles)")
                return False, bet_mult, details
            if stoch_k is None or stoch_d is None:
                details["reasons"].append("PULLBACK_ENTRY: Stochastic unavailable (insufficient candles)")
                return False, bet_mult, details
            if atr_now is None:
                details["reasons"].append("PULLBACK_ENTRY: ATR unavailable (insufficient candles)")
                return False, bet_mult, details

            if True: # Indicators confirmed available
                if direction == "PUT":
                    if slope >= -0.015:
                        details["reasons"].append(f"PULLBACK_ENTRY: Trend not down (Slope {slope:.3f}% >= -0.015%)")
                        return False, bet_mult, details
                    if rsi_now > _pb_put_max:
                        details["reasons"].append(
                            f"PULLBACK_ENTRY: RSI too high for PUT pullback ({rsi_now:.1f} > {_pb_put_max})"
                        )
                        return False, bet_mult, details
                    if not (_pb_put_lo <= rsi_now <= _pb_put_hi):
                        details["reasons"].append(
                            f"PULLBACK_ENTRY: RSI {rsi_now:.1f} not in pullback zone [{_pb_put_lo}, {_pb_put_hi}]"
                        )
                        return False, bet_mult, details
                    if rsi_now >= rsi_prev:
                        details["reasons"].append(f"PULLBACK_ENTRY: RSI rising ({rsi_now:.1f} >= {rsi_prev:.1f})")
                        return False, bet_mult, details
                    # if stoch_k >= stoch_d:
                    #     details["reasons"].append(f"PULLBACK_ENTRY: Stoch K >= D ({stoch_k:.1f} >= {stoch_d:.1f})")
                    #     return False, bet_mult, details

                    if ema_atr > 0 and atr_now > 2 * ema_atr:
                        details["reasons"].append(f"PULLBACK_ENTRY: ATR spike ({atr_now:.4f} > 2 * {ema_atr:.4f})")
                        return False, bet_mult, details
                elif direction == "CALL":
                    if slope <= 0.015:
                        details["reasons"].append(f"PULLBACK_ENTRY: Trend not up (Slope {slope:.3f}% <= 0.015%)")
                        return False, bet_mult, details
                    if rsi_now < _pb_call_min:
                        details["reasons"].append(
                            f"PULLBACK_ENTRY: RSI too low for CALL pullback ({rsi_now:.1f} < {_pb_call_min})"
                        )
                        return False, bet_mult, details
                    if not (_pb_call_lo <= rsi_now <= _pb_call_hi):
                        details["reasons"].append(
                            f"PULLBACK_ENTRY: RSI {rsi_now:.1f} not in pullback zone [{_pb_call_lo}, {_pb_call_hi}]"
                        )
                        return False, bet_mult, details
                    if rsi_now <= rsi_prev:
                        details["reasons"].append(f"PULLBACK_ENTRY: RSI falling ({rsi_now:.1f} <= {rsi_prev:.1f})")
                        return False, bet_mult, details
                    # if stoch_k <= stoch_d:
                    #     details["reasons"].append(f"PULLBACK_ENTRY: Stoch K <= D ({stoch_k:.1f} <= {stoch_d:.1f})")
                    #     return False, bet_mult, details

                    if ema_atr > 0 and atr_now > 2 * ema_atr:
                        details["reasons"].append(f"PULLBACK_ENTRY: ATR spike ({atr_now:.4f} > 2 * {ema_atr:.4f})")
                        return False, bet_mult, details

        # [v5.0 BUG-12 FIX] TREND_FOLLOWING strategy — enter WITH confirmed trend momentum
        if strategy == "TREND_FOLLOWING" and df_1m is not None and len(df_1m) >= 20:
            rsi_now = TechnicalConfirmation.get_rsi(df_1m)
            macd_line, macd_signal, macd_hist = TechnicalConfirmation.get_macd(df_1m)

            sma = df_1m["close"].rolling(7).mean()
            slope = 0.0
            if len(sma) >= 6 and sma.iloc[-6] > 0:
                slope = (sma.iloc[-1] - sma.iloc[-6]) / sma.iloc[-6] * 100

            # ดึงค่า Config จาก Profile แทนการ Hardcode
            ma_slope_min = float(asset_profile.get("ma_slope_min", 0.025)) if asset_profile else 0.025
            _tf_bounds = asset_profile.get("rsi_bounds", {}) if asset_profile else {}
            call_min = float(_tf_bounds.get("call_min", 55.0))
            call_max = float(_tf_bounds.get("call_max", 65.0))
            put_min = float(_tf_bounds.get("put_min", 35.0))
            put_max = float(_tf_bounds.get("put_max", 45.0))

            if rsi_now is None:
                details["reasons"].append("TREND_FOLLOWING: RSI unavailable")
                return False, bet_mult, details
            if macd_hist is None:
                details["reasons"].append("TREND_FOLLOWING: MACD unavailable")
                return False, bet_mult, details

            if direction == "CALL":
                if slope < ma_slope_min:
                    details["reasons"].append(f"TREND_FOLLOWING: Slope {slope:.3f}% too weak for CALL")
                    return False, bet_mult, details
                # [FIXED] ใช้ค่า Dynamic จาก Profile 
                if not (call_min <= rsi_now <= call_max):
                    details["reasons"].append(f"TREND_FOLLOWING: RSI {rsi_now:.1f} outside CALL zone [{call_min}, {call_max}]")
                    return False, bet_mult, details
                if macd_hist <= 0:
                    details["reasons"].append("TREND_FOLLOWING: MACD hist not bullish")
                    return False, bet_mult, details

            elif direction == "PUT":
                if slope > -ma_slope_min:
                    details["reasons"].append(f"TREND_FOLLOWING: Slope {slope:.3f}% too weak for PUT")
                    return False, bet_mult, details
                # [FIXED] ใช้ค่า Dynamic จาก Profile
                if not (put_min <= rsi_now <= put_max):
                    details["reasons"].append(f"TREND_FOLLOWING: RSI {rsi_now:.1f} outside PUT zone [{put_min}, {put_max}]")
                    return False, bet_mult, details
                if macd_hist >= 0:
                    details["reasons"].append("TREND_FOLLOWING: MACD hist not bearish")
                    return False, bet_mult, details

        # --- Level 2: Technical Confirmation ---
        # AWAIT HERE
        conf_score, conf_details = await self.tech.get_confirmation_score(api, asset, signal, df_1m)
        details["level2_tech"] = {
            "confirmation_score": conf_score, 
            "details": conf_details,
            "rsi_ok": self.tech.get_rsi(df_1m) is not None
        }
        l2_threshold = safe_config_get("L2_MIN_CONFIRMATION", 0.35)  # [v3.4.1] Configurable
        if conf_score < l2_threshold:
            details["final_decision"] = "SKIP"
            details["reasons"].append(f"L2: Confirmation too low ({conf_score})")
            return False, bet_mult, details

        # --- Level 3: RL Decision ---
        action, rl_conf, reason = self.rl.decide(asset, strategy, confidence)
        details["level3_rl"] = {"action": action, "confidence": rl_conf, "reason": reason}
        if action == "SKIP" and rl_conf > 0.5:
            details["final_decision"] = "SKIP"
            details["reasons"].append(f"L3: RL says SKIP ({reason})")
            return False, bet_mult, details

        # --- Adjust Bet (Tech + WR) ---
        # [v3.2.10] Now respects ENABLE_AI_CONFIDENCE_BET_SCALING config
        if safe_config_get("ENABLE_AI_CONFIDENCE_BET_SCALING", False):
            if conf_score >= 0.75 and combo_wr >= 0.6:
                bet_mult = min(bet_mult * 1.25, 1.5)
                details["reasons"].append("High conf + good history → bet boost")
            elif conf_score < 0.5 or combo_wr < 0.4:
                bet_mult = max(bet_mult * 0.75, 0.75)  # [v3.4.1] Floor raised from 0.5
                details["reasons"].append("Low conf or poor history → bet reduce")

        # --- Level 4: AI Confidence Bet Scaling ---
        if safe_config_get("ENABLE_AI_CONFIDENCE_BET_SCALING", False) and confidence > 0:
            hi_th = safe_config_get("AI_CONF_HIGH_THRESHOLD", 0.80)
            hi_mult = safe_config_get("AI_CONF_HIGH_MULTIPLIER", 1.20)
            lo_th = safe_config_get("AI_CONF_LOW_THRESHOLD", 0.50)
            lo_mult = safe_config_get("AI_CONF_LOW_MULTIPLIER", 0.70)
            cap_max = safe_config_get("AI_CONF_BET_MAX_MULTIPLIER", 1.50)
            cap_min = safe_config_get("AI_CONF_BET_MIN_MULTIPLIER", 1.0)

            if confidence >= hi_th:
                bet_mult *= hi_mult
                details["reasons"].append(f"L4: AI Conf {confidence:.2f} >= {hi_th} → bet ×{hi_mult}")
            elif confidence < lo_th:
                bet_mult *= lo_mult
                details["reasons"].append(f"L4: AI Conf {confidence:.2f} < {lo_th} → bet ×{lo_mult}")

            bet_mult = min(cap_max, max(cap_min, bet_mult))
            details["ai_confidence_scaling"] = {"confidence": confidence, "final_mult": round(bet_mult, 2)}

        details["final_decision"] = "ENTER"
        return True, bet_mult, details
    def calculate_intelligence_level(self):
        """Calculates the bot's intelligence level based on experience and performance."""
        trades = self.perf.data.get("trades", [])
        total_trades = len(trades)
        wins = sum(1 for t in trades if t.get("result") == "WIN")
        
        win_rate = (wins / total_trades) if total_trades > 0 else 0.0
        
        # RL states count
        rl_states = len(self.rl.q_table)
        
        # Calculate Score Breakdown
        score_exp = min(total_trades * 2, 40) # Max 40
        score_perf = min(int(win_rate * 40), 40) # Max 40
        score_know = min(rl_states // 2, 20)     # Max 20
        
        # Total Score (0-100)
        total_score = score_exp + score_perf + score_know
        # Normalize to 100 roughly if needed, but the current weights sum to 100 (40+40+20)
        
        level_name = "Newborn"
        level_emoji = "🐣"
        
        if total_score >= 80:
            level_name = "Grandmaster"
            level_emoji = "🧙‍♂️"
        elif total_score >= 60:
            level_name = "Expert"
            level_emoji = "🧠"
        elif total_score >= 40:
            level_name = "Intermediate"
            level_emoji = "📈"
        elif total_score >= 20:
            level_name = "Novice"
            level_emoji = "🌱"
            
        return {
            "score": total_score,
            "level_name": level_name,
            "level_emoji": level_emoji,
            "description": f"AI has analyzed {total_trades} trades with {win_rate:.1%} accuracy.",
            "components": {
                "experience": {"score": min(15, int(score_exp * 0.375))},        # Scale 40 -> 15
                "win_rate": {"score": min(30, int(score_perf * 0.75))},          # Scale 40 -> 30
                "rl_maturity": {"score": min(25, int(score_know * 1.25))},       # Scale 20 -> 25
                "profit_factor": {"score": 0},  # Placeholder for now
                "consistency": {"score": 0}     # Placeholder for now
            }
        }

# Singleton Instance
_SMART_TRADER = SmartTrader()
