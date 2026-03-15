"""
Shadow Tracking (Virtual Trading) System — v1.0.0
==================================================
Tracks blocked/skipped trades virtually to evaluate signal accuracy
without affecting the live trading loop.

CRITICAL: All operations are fire-and-forget (asyncio.create_task).
This module MUST NEVER block the main WebSocket stream.
"""

import asyncio
import csv
import logging
import os
from datetime import datetime, timezone

# CSV output path
_CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "shadow_trades.csv")
_CSV_HEADERS = [
    "Timestamp", "Asset", "Signal", "Reason",
    "RSI", "MACD", "Stoch",
    "Entry_Price", "Exit_Price", "Virtual_Result"
]


def _ensure_csv(path: str) -> None:
    """Create CSV with headers if it doesn't exist."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(_CSV_HEADERS)


def _write_csv_row(path: str, row: dict) -> None:
    """Synchronous CSV append (called via asyncio.to_thread)."""
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_HEADERS)
        writer.writerow(row)


class ShadowTracker:
    """
    Virtual trade tracker. Waits 180 seconds after a blocked signal,
    fetches the exit price, and records WIN/LOSS to CSV.
    """

    def __init__(self):
        self._api = None
        self._csv_lock = asyncio.Lock()
        self._csv_path = os.path.normpath(_CSV_PATH)
        try:
            _ensure_csv(self._csv_path)
        except Exception as e:
            logging.warning(f"[ShadowTracker] Could not init CSV: {e}")

    def set_api(self, api) -> None:
        """Inject the DerivAPI instance after bot authorization."""
        self._api = api
        logging.info("[ShadowTracker] API reference set. Shadow tracking active.")

    async def track_virtual_trade(
        self,
        api,
        asset: str,
        signal: str,
        reason: str,
        entry_price: float,
        indicators: dict,
    ) -> None:
        """
        Fire-and-forget coroutine. Wait 180s, fetch exit price, record result.
        All exceptions are silently swallowed to protect the main loop.
        """
        try:
            await asyncio.sleep(180)

            _api = api or self._api
            if _api is None:
                logging.debug("[ShadowTracker] No API available. Skipping virtual trade.")
                return

            exit_price = await self._get_exit_price(_api, asset)
            if exit_price is None:
                logging.debug(f"[ShadowTracker] Could not fetch exit price for {asset}. Skipping.")
                return

            if signal == "CALL":
                result = "WIN" if exit_price > entry_price else "LOSS"
            elif signal == "PUT":
                result = "WIN" if exit_price < entry_price else "LOSS"
            else:
                result = "UNKNOWN"

            row = {
                "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "Asset":     asset,
                "Signal":    signal,
                "Reason":    reason[:120] if reason else "",
                "RSI":       round(float(indicators.get("rsi", 0) or 0), 2),
                "MACD":      round(float(indicators.get("macd_hist", 0) or 0), 6),
                "Stoch":     round(float(indicators.get("stoch_k", 0) or 0), 2),
                "Entry_Price": round(entry_price, 5),
                "Exit_Price":  round(exit_price, 5),
                "Virtual_Result": result,
            }

            await self._write_row(row)
            logging.info(
                f"[ShadowTracker] {asset} {signal} → {result} "
                f"(Entry={entry_price:.5f} Exit={exit_price:.5f})"
            )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.debug(f"[ShadowTracker] track_virtual_trade error: {e}")

    async def _get_exit_price(self, api, asset: str) -> float | None:
        """Fetch the latest tick price for the asset. Returns None on timeout/error."""
        try:
            response = await asyncio.wait_for(
                api.ticks_history({
                    "ticks_history": asset,
                    "end": "latest",
                    "count": 1,
                    "style": "ticks",
                }),
                timeout=15.0,
            )
            prices = response.get("history", {}).get("prices", [])
            if prices:
                return float(prices[-1])
        except asyncio.TimeoutError:
            logging.debug(f"[ShadowTracker] Ticks history timeout for {asset}")
        except Exception as e:
            logging.debug(f"[ShadowTracker] _get_exit_price error for {asset}: {e}")
        return None

    async def _write_row(self, row: dict) -> None:
        """Append one row to the CSV, protected by asyncio.Lock."""
        async with self._csv_lock:
            try:
                await asyncio.to_thread(_write_csv_row, self._csv_path, row)
            except Exception as e:
                logging.warning(f"[ShadowTracker] CSV write error: {e}")


# Module-level singleton
shadow_tracker = ShadowTracker()
