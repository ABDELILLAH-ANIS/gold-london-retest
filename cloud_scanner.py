"""
Gold & Multi-Market London Retest - 24/7 Cloud Scanner
Scans 5 uncorrelated FTM/FTMO prop-firm markets in the 09:00-12:00 Algiers Time (GMT+1)
M15 session: XAUUSD, EURUSD, GBPUSD, US100, and BTCUSD.
Enforces strict account-wide FTM $5,000 rules: manual entry only, $25 risk / $50 reward (1:2 RR),
max 2 alerts/day across all markets combined, -$50 (2 losses) daily stop, +$80 daily profit cap,
USD High-Impact News (+/- 60 min) block, morning 09:00 briefing, and 12:00 summary.
"""

import argparse
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request

from gold_london_retest_db import DB_PATH, get_connection, init_db, send_telegram_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "cloud_state.json")
NEWS_CACHE_PATH = os.path.join(BASE_DIR, "news_cache.json")
ALGIERS_TZ = datetime.timezone(datetime.timedelta(hours=1))

_SCAN_LOCK = threading.Lock()
_LAST_STATUS: dict | None = None
_NEWS_CACHE: dict = {"fetched_at": 0.0, "events": None, "last_fail_at": 0.0}

MARKET_SPECS: dict[str, dict] = {
    "XAUUSD": {
        "label": "Gold (XAUUSD)",
        "digits": 2,
        "asia_start_h": 1,
        "asia_end_h": 7,
        "min_asia_w": 8.0,
        "max_asia_w": 65.0,
        "min_breakout_body": 0.50,
        "retest_tol": 3.5,
        "sl_zone_depth": 3.5,
        "max_candle": 10.0,
        "sl_buffer": 1.0,
        "sl_min": 3.0,
        "sl_max": 7.0,
        "rsi_buy_max": 68.0,
        "rsi_sell_min": 32.0,
        "contract_val": 100.0,
        "max_lot": 0.08,
        "lot_step": 0.01,
        "feeds": [("okx", "PAXG-USDT"), ("yahoo", "GC=F"), ("binance", "PAXGUSDT")],
    },
    "EURUSD": {
        "label": "EUR/USD",
        "digits": 5,
        "asia_start_h": 1,
        "asia_end_h": 7,
        "min_asia_w": 0.0010,
        "max_asia_w": 0.0045,
        "min_breakout_body": 0.0002,
        "retest_tol": 0.0007,
        "sl_zone_depth": 0.0007,
        "max_candle": 0.0025,
        "sl_buffer": 0.0003,
        "sl_min": 0.0008,
        "sl_max": 0.0018,
        "rsi_buy_max": 68.0,
        "rsi_sell_min": 32.0,
        "contract_val": 100000.0,
        "max_lot": 0.25,
        "lot_step": 0.01,
        "feeds": [("yahoo", "EURUSD=X"), ("binance", "EURUSDT")],
    },
    "GBPUSD": {
        "label": "GBP/USD",
        "digits": 5,
        "asia_start_h": 1,
        "asia_end_h": 7,
        "min_asia_w": 0.0012,
        "max_asia_w": 0.0050,
        "min_breakout_body": 0.00025,
        "retest_tol": 0.0008,
        "sl_zone_depth": 0.0008,
        "max_candle": 0.0030,
        "sl_buffer": 0.0003,
        "sl_min": 0.0010,
        "sl_max": 0.0020,
        "rsi_buy_max": 68.0,
        "rsi_sell_min": 32.0,
        "contract_val": 100000.0,
        "max_lot": 0.25,
        "lot_step": 0.01,
        "feeds": [("yahoo", "GBPUSD=X")],
    },
    "US100": {
        "label": "Nasdaq 100 (US100)",
        "digits": 2,
        "asia_start_h": 1,
        "asia_end_h": 7,
        "min_asia_w": 60.0,
        "max_asia_w": 220.0,
        "min_breakout_body": 10.0,
        "retest_tol": 18.0,
        "sl_zone_depth": 18.0,
        "max_candle": 70.0,
        "sl_buffer": 10.0,
        "sl_min": 35.0,
        "sl_max": 70.0,
        "rsi_buy_max": 62.0,
        "rsi_sell_min": 38.0,
        "contract_val": 1.0,
        "max_lot": 0.70,
        "lot_step": 0.01,
        "feeds": [("yahoo", "NQ=F")],
    },
    "BTCUSD": {
        "label": "Bitcoin (BTCUSD)",
        "digits": 2,
        "asia_start_h": 1,
        "asia_end_h": 7,
        "min_asia_w": 600.0,
        "max_asia_w": 2000.0,
        "min_breakout_body": 40.0,
        "retest_tol": 200.0,
        "sl_zone_depth": 200.0,
        "max_candle": 600.0,
        "sl_buffer": 60.0,
        "sl_min": 400.0,
        "sl_max": 900.0,
        "rsi_buy_max": 62.0,
        "rsi_sell_min": 38.0,
        "contract_val": 1.0,
        "max_lot": 0.06,
        "lot_step": 0.01,
        "feeds": [("okx", "BTC-USDT"), ("yahoo", "BTC-USD"), ("binance", "BTCUSDT")],
    },
}


def load_telegram_credentials() -> tuple[str, str]:
    """Load Bot Token and Chat ID from env vars first, then fallback to SQLite DB."""
    env_tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    env_cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if env_tok and env_cid:
        return env_tok, env_cid

    if os.path.exists(DB_PATH):
        init_db(DB_PATH)
        with get_connection(DB_PATH) as conn:
            row = conn.execute("SELECT bot_token, chat_id FROM telegram_settings WHERE id = 1").fetchone()
            if row:
                return row["bot_token"], row["chat_id"]
    return "", ""


def compute_indicators(bars: list[dict]) -> list[dict]:
    """Calculate EMA(50) and Wilder RSI(14) identically to MT5."""
    if not bars:
        return bars
    k_ema = 2.0 / 51.0
    ema = bars[0]["c"]
    avg_g = 0.0
    avg_l = 0.0
    bars[0]["ema50"] = round(ema, 6)
    bars[0]["rsi14"] = 50.0

    for i in range(1, len(bars)):
        c = bars[i]["c"]
        ema = c * k_ema + ema * (1.0 - k_ema)
        bars[i]["ema50"] = round(ema, 6)
        ch = c - bars[i - 1]["c"]
        g = max(ch, 0.0)
        l = max(-ch, 0.0)
        if i <= 14:
            avg_g += g / 14.0
            avg_l += l / 14.0
        else:
            avg_g = (avg_g * 13.0 + g) / 14.0
            avg_l = (avg_l * 13.0 + l) / 14.0
        rs = (avg_g / avg_l) if avg_l > 0 else 100.0
        bars[i]["rsi14"] = round(100.0 - (100.0 / (1.0 + rs)), 2)
    return bars


def _fetch_okx(inst_id: str) -> tuple[list[dict], str]:
    url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=15m&limit=250"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    rows = list(reversed(payload.get("data", [])))
    bars = []
    for k in rows:
        dt = datetime.datetime.fromtimestamp(int(k[0]) / 1000.0, ALGIERS_TZ)
        bars.append(
            {
                "dt": dt,
                "ts": dt.strftime("%Y-%m-%d %H:%M"),
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
            }
        )
    return compute_indicators(bars), f"OKX_{inst_id}"


def _fetch_binance(symbol: str) -> tuple[list[dict], str]:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=15m&limit=250"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    bars = []
    for k in data:
        dt = datetime.datetime.fromtimestamp(k[0] / 1000.0, ALGIERS_TZ)
        bars.append(
            {
                "dt": dt,
                "ts": dt.strftime("%Y-%m-%d %H:%M"),
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
            }
        )
    return compute_indicators(bars), f"BINANCE_{symbol}"


def _fetch_yahoo(symbol: str) -> tuple[list[dict], str]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=15m&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        dt = datetime.datetime.fromtimestamp(t, ALGIERS_TZ)
        bars.append(
            {
                "dt": dt,
                "ts": dt.strftime("%Y-%m-%d %H:%M"),
                "o": float(o),
                "h": float(h),
                "l": float(l),
                "c": float(c),
            }
        )
    return compute_indicators(bars), f"YAHOO_{symbol}"


def fetch_market_bars(market_key: str) -> tuple[list[dict], str]:
    """Fetch M15 bars for a market with automatic multi-provider failover."""
    spec = MARKET_SPECS[market_key]
    errors = []
    for provider, sym in spec["feeds"]:
        try:
            if provider == "okx":
                bars, src = _fetch_okx(sym)
            elif provider == "yahoo":
                bars, src = _fetch_yahoo(sym)
            else:
                bars, src = _fetch_binance(sym)
            if len(bars) >= 60:
                return bars, src
        except Exception as exc:
            errors.append(f"{provider}:{sym} -> {exc}")
    raise RuntimeError(f"All feeds failed for {market_key}: " + " | ".join(errors))


def fetch_live_gold_bars() -> tuple[list[dict], str]:
    """Backward-compatible helper for XAUUSD scripts."""
    return fetch_market_bars("XAUUSD")


def _load_weekly_news_events() -> tuple[list[dict] | None, str]:
    """Load ForexFactory weekly calendar with 6-hour memory/disk cache to avoid 429 rate limits."""
    now_ts = time.time()
    ttl = 6 * 3600

    if _NEWS_CACHE["events"] is not None and (now_ts - _NEWS_CACHE["fetched_at"]) < ttl:
        return _NEWS_CACHE["events"], "cached"

    if os.path.exists(NEWS_CACHE_PATH):
        try:
            with open(NEWS_CACHE_PATH, "r", encoding="utf-8") as fh:
                disk = json.load(fh)
            if isinstance(disk.get("events"), list) and (now_ts - float(disk.get("fetched_at", 0.0))) < ttl:
                _NEWS_CACHE["events"] = disk["events"]
                _NEWS_CACHE["fetched_at"] = float(disk["fetched_at"])
                return _NEWS_CACHE["events"], "disk-cached"
        except Exception:
            pass

    if (now_ts - _NEWS_CACHE["last_fail_at"]) < 1800 and _NEWS_CACHE["events"] is not None:
        return _NEWS_CACHE["events"], "stale-cached"

    urls = (
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json",
    )
    last_err = ""
    for url in urls:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                events = json.loads(resp.read().decode("utf-8"))
            if isinstance(events, list):
                _NEWS_CACHE["events"] = events
                _NEWS_CACHE["fetched_at"] = now_ts
                try:
                    with open(NEWS_CACHE_PATH, "w", encoding="utf-8") as fh:
                        json.dump({"fetched_at": now_ts, "events": events}, fh)
                except Exception:
                    pass
                return events, "live"
        except Exception as exc:
            last_err = str(exc)

    _NEWS_CACHE["last_fail_at"] = now_ts
    if _NEWS_CACHE["events"] is not None:
        return _NEWS_CACHE["events"], "stale-cached"
    return None, last_err


def check_usd_high_impact_news(now_alg: datetime.datetime) -> tuple[bool, str]:
    """Check ForexFactory weekly feed for USD/EUR/GBP High-Impact events within +/- 60 minutes."""
    events, err_or_mode = _load_weekly_news_events()
    if events is None:
        return False, f"Calendar unavailable ({err_or_mode})"

    keywords = ("CPI", "NFP", "NON-FARM", "NONFARM", "FOMC", "FED", "POWELL", "PPI", "GDP", "PCE", "RATE")
    for ev in events:
        country = str(ev.get("country", ""))
        if country not in ("USD", "EUR", "GBP"):
            continue
        title = str(ev.get("title", ""))
        impact = str(ev.get("impact", ""))
        if impact != "High" and not (country == "USD" and any(kw in title.upper() for kw in keywords)):
            continue
        date_str = ev.get("date", "")
        if not date_str:
            continue
        try:
            ev_dt = datetime.datetime.fromisoformat(date_str).astimezone(ALGIERS_TZ)
        except Exception:
            continue
        diff_min = abs((now_alg - ev_dt).total_seconds()) / 60.0
        if diff_min <= 60.0:
            return True, f"{country} High News: {title} ({ev_dt.strftime('%H:%M')} Algiers)"
    return False, "No News"


def load_state(today_key: str) -> dict:
    """Load or reset today's account-wide multi-market state from cloud_state.json."""
    default = {
        "day_key": today_key,
        "alerts_today": 0,
        "losses_today": 0,
        "realized_pnl": 0.0,
        "active_signals": [],
        "lost_keys": [],
        "stopped_two_losses": False,
        "stopped_profit_cap": False,
        "sent_two_loss_msg": False,
        "sent_morning_brief": False,
        "sent_no_setup_msg": False,
        "last_alert_bar_by_sym": {},
    }
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                st = json.load(fh)
            if st.get("day_key") == today_key:
                for k, v in default.items():
                    st.setdefault(k, v)
                return st
        except Exception:
            pass
    return default


def save_state(state: dict) -> None:
    """Persist daily state to cloud_state.json."""
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def log_cloud_signal_to_db(sig: dict, tg_msg: str) -> None:
    """Store live cloud signal inside gold_london_retest.db if writable."""
    try:
        init_db(DB_PATH)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_connection(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO signals (
                    run_id, source_type, signal_time_algiers, symbol, direction,
                    entry_price, stop_loss, take_profit, lot_size, ema50, rsi14,
                    asia_high, asia_low, candle_size, outcome, pnl_usd,
                    duration_minutes, telegram_message, created_at
                ) VALUES (NULL, 'CLOUD_SCANNER', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SENT_MANUAL', 0.0, 0.0, ?, ?)
                """,
                (
                    sig["ts"],
                    sig["symbol"],
                    sig["dir"],
                    sig["entry"],
                    sig["sl"],
                    sig["tp"],
                    sig["lot"],
                    sig["ema50"],
                    sig["rsi14"],
                    sig["asia_high"],
                    sig["asia_low"],
                    sig["prev_size"],
                    tg_msg,
                    now_iso,
                ),
            )
            conn.commit()
    except sqlite3.Error:
        pass


def calculate_lot_for_25_risk(market_key: str, sl_dist: float) -> float:
    """Calculate safe lot size so risk is capped at <= $25.00 per trade."""
    spec = MARKET_SPECS[market_key]
    if sl_dist <= 0:
        return spec["lot_step"]
    raw = 25.0 / (spec["contract_val"] * sl_dist)
    step = spec["lot_step"]
    lot = int(raw / step) * step
    lot = max(step, min(round(lot, 2), spec["max_lot"]))
    return round(lot, 2)


def evaluate_market(
    market_key: str,
    now_alg: datetime.datetime,
    state: dict,
    news_blocked: bool,
    news_msg: str,
    bot_token: str,
    chat_id: str,
    dry_run: bool,
) -> dict:
    """Fetch and evaluate one market's latest closed M15 candle."""
    spec = MARKET_SPECS[market_key]
    digits = spec["digits"]
    today_date = now_alg.date()

    bars, data_src = fetch_market_bars(market_key)
    closed_idx = len(bars) - 2
    closed_bar = bars[closed_idx]
    prev_bar = bars[closed_idx - 1]

    # Check if any active signal on this market hit SL or TP
    for sig in state["active_signals"]:
        if sig["symbol"] != market_key or sig.get("resolved"):
            continue
        if sig["dir"] == "BUY":
            if closed_bar["l"] <= sig["sl"]:
                sig["resolved"] = True
                sig["outcome"] = "LOSS"
                state["losses_today"] += 1
                state["realized_pnl"] -= 25.0
                state["lost_keys"].append(f"{market_key}_BUY")
            elif closed_bar["h"] >= sig["tp"]:
                sig["resolved"] = True
                sig["outcome"] = "WIN"
                state["realized_pnl"] += 50.0
        elif sig["dir"] == "SELL":
            if closed_bar["h"] >= sig["sl"]:
                sig["resolved"] = True
                sig["outcome"] = "LOSS"
                state["losses_today"] += 1
                state["realized_pnl"] -= 25.0
                state["lost_keys"].append(f"{market_key}_SELL")
            elif closed_bar["l"] <= sig["tp"]:
                sig["resolved"] = True
                sig["outcome"] = "WIN"
                state["realized_pnl"] += 50.0

    asia_bars = [
        b
        for b in bars[:-1]
        if b["dt"].date() == today_date and spec["asia_start_h"] <= b["dt"].hour < spec["asia_end_h"]
    ]
    asia_high = round(max((b["h"] for b in asia_bars), default=0.0), digits)
    asia_low = round(min((b["l"] for b in asia_bars), default=0.0), digits)
    asia_width = round(asia_high - asia_low, digits) if asia_bars else 0.0
    asia_valid = len(asia_bars) >= 6 and (spec["min_asia_w"] <= asia_width <= spec["max_asia_w"])

    bar_alg = closed_bar["dt"]
    in_window = (
        bar_alg.date() == today_date
        and bar_alg.weekday() < 5
        and 9 <= bar_alg.hour < 12
        and (now_alg - bar_alg).total_seconds() <= 2700
    )

    action_note = "Outside 09:00-12:00 Algiers window"
    if in_window:
        if state["stopped_two_losses"] or state["losses_today"] >= 2:
            action_note = "Stopped: 2 losses reached"
        elif state["stopped_profit_cap"] or state["realized_pnl"] >= 80.0:
            action_note = "Stopped: +$80 daily cap hit"
        elif state["alerts_today"] >= 2:
            action_note = "Max 2 alerts reached today"
        elif not asia_valid:
            action_note = f"Asia width {asia_width:.{digits}f} outside range"
        elif news_blocked:
            action_note = f"Blocked by {news_msg}"
        elif state["last_alert_bar_by_sym"].get(market_key) == closed_bar["ts"]:
            action_note = "Bar already alerted"
        else:
            broke_up, broke_dn = False, False
            for idx in range(1, closed_idx):
                b = bars[idx]
                if b["dt"].date() != today_date or b["dt"].hour < spec["asia_end_h"]:
                    continue
                if b["c"] > asia_high and (b["c"] - b["o"]) >= spec["min_breakout_body"]:
                    broke_up = True
                if b["c"] < asia_low and (b["o"] - b["c"]) >= spec["min_breakout_body"]:
                    broke_dn = True

            prev_size = prev_bar["h"] - prev_bar["l"]
            cur_range = closed_bar["h"] - closed_bar["l"]
            cur_body = abs(closed_bar["c"] - closed_bar["o"])
            sig_dir = None

            if (
                prev_size <= spec["max_candle"]
                and 0 < cur_range <= spec["max_candle"] * 1.2
                and (cur_body / cur_range) >= 0.25
            ):
                if (
                    broke_up
                    and (asia_high - spec["sl_zone_depth"] <= closed_bar["l"] <= asia_high + spec["retest_tol"])
                    and closed_bar["c"] > asia_high
                    and closed_bar["c"] > closed_bar["o"]
                    and closed_bar["ema50"] < closed_bar["c"]
                    and 50.0 <= closed_bar["rsi14"] <= spec["rsi_buy_max"]
                ):
                    sig_dir = "BUY"
                elif (
                    broke_dn
                    and (asia_low - spec["retest_tol"] <= closed_bar["h"] <= asia_low + spec["sl_zone_depth"])
                    and closed_bar["c"] < asia_low
                    and closed_bar["c"] < closed_bar["o"]
                    and closed_bar["ema50"] > closed_bar["c"]
                    and spec["rsi_sell_min"] <= closed_bar["rsi14"] <= 50.0
                ):
                    sig_dir = "SELL"

            if sig_dir and f"{market_key}_{sig_dir}" in state["lost_keys"]:
                strong_rsi = (
                    (55.0 <= closed_bar["rsi14"] <= 63.0)
                    if sig_dir == "BUY"
                    else (37.0 <= closed_bar["rsi14"] <= 45.0)
                )
                if not strong_rsi or (cur_body / cur_range) < 0.50:
                    sig_dir = None
                    action_note = "2nd trade blocked: weaker same-direction setup after loss"

            if sig_dir:
                entry = round(closed_bar["c"], digits)
                raw_dist = (
                    (entry - (min(closed_bar["l"], asia_high) - spec["sl_buffer"]))
                    if sig_dir == "BUY"
                    else ((max(closed_bar["h"], asia_low) + spec["sl_buffer"]) - entry)
                )
                sl_dist = max(spec["sl_min"], min(raw_dist, spec["sl_max"]))
                tp_dist = sl_dist * 2.0
                sl = round(entry - sl_dist if sig_dir == "BUY" else entry + sl_dist, digits)
                tp = round(entry + tp_dist if sig_dir == "BUY" else entry - tp_dist, digits)
                lot = calculate_lot_for_25_risk(market_key, sl_dist)
                risk = round(lot * spec["contract_val"] * sl_dist)
                reward = round(risk * 2.0)

                level_desc = (
                    "Break + Retest of Asia High, EMA50 below price"
                    if sig_dir == "BUY"
                    else "Break + Retest of Asia Low, EMA50 above price"
                )
                tg_msg = (
                    f"{market_key} SIGNAL - {sig_dir}\n"
                    f"Entry: {entry:.{digits}f}\n"
                    f"Stop Loss: {sl:.{digits}f}\n"
                    f"Take Profit: {tp:.{digits}f}\n"
                    f"Lot: {lot:.2f}\n"
                    f"Reason: {level_desc}, RSI {closed_bar['rsi14']:.0f}, No News.\n"
                    f"Risk: ${risk} | Reward: ${reward}\n"
                    f"Time: {bar_alg.strftime('%H:%M')} Algiers Time\n"
                    "Confirm in MT5 manually. Trade duration must be > 5 minutes."
                )

                if not dry_run and bot_token and chat_id:
                    _, info = send_telegram_text(bot_token, chat_id, tg_msg)
                    action_note = f"Signal {sig_dir} sent -> {info}"
                else:
                    action_note = f"Signal {sig_dir} generated (dry_run={dry_run})"

                log_cloud_signal_to_db(
                    {
                        "symbol": market_key,
                        "ts": closed_bar["ts"],
                        "dir": sig_dir,
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "lot": lot,
                        "ema50": round(closed_bar["ema50"], digits),
                        "rsi14": closed_bar["rsi14"],
                        "asia_high": asia_high,
                        "asia_low": asia_low,
                        "prev_size": round(prev_size, digits),
                    },
                    tg_msg,
                )

                if not dry_run:
                    state["alerts_today"] += 1
                    state["last_alert_bar_by_sym"][market_key] = closed_bar["ts"]
                    state["active_signals"].append(
                        {"symbol": market_key, "dir": sig_dir, "entry": entry, "sl": sl, "tp": tp, "resolved": False}
                    )
            elif action_note == "Outside 09:00-12:00 Algiers window":
                action_note = "In window — waiting for valid Break+Retest setup"

    return {
        "symbol": market_key,
        "data_source": data_src,
        "closed_bar_ts": closed_bar["ts"],
        "close_price": round(closed_bar["c"], digits),
        "ema50": round(closed_bar["ema50"], digits),
        "rsi14": closed_bar["rsi14"],
        "asia_high": asia_high,
        "asia_low": asia_low,
        "asia_width": asia_width,
        "asia_valid": asia_valid,
        "action_note": action_note,
    }


def _format_briefing_message(now_alg: datetime.datetime, markets_res: dict, news_msg: str) -> str:
    lines = [
        f"LONDON SESSION BRIEFING ({now_alg.strftime('%Y-%m-%d %H:%M')} Algiers)",
        "Scanning 5 Markets | Risk: $25 | Max 2 Alerts/Day",
        f"News Status: {news_msg}",
        "",
    ]
    for sym, m in markets_res.items():
        if m.get("error"):
            lines.append(f"• {sym}: Feed error")
        else:
            tag = "VALID" if m["asia_valid"] else "SKIP"
            lines.append(
                f"• {sym}: Price {m['close_price']} | Asia {m['asia_low']}-{m['asia_high']} [{tag}] | RSI {m['rsi14']}"
            )
    lines.append("\nManual entry only. Trade duration must be > 5 minutes.")
    return "\n".join(lines)


def evaluate_once(
    strict_mode: bool = False,
    dry_run: bool = False,
    status_report: bool = False,
    send_brief_now: bool = False,
) -> dict:
    """Evaluate all 5 markets on their latest closed M15 candle and send Telegram alerts."""
    now_alg = datetime.datetime.now(ALGIERS_TZ)
    today_key = now_alg.date().isoformat()
    state = load_state(today_key)

    news_blocked, news_msg = check_usd_high_impact_news(now_alg)
    bot_token, chat_id = load_telegram_credentials()

    markets_res: dict[str, dict] = {}
    for sym in MARKET_SPECS:
        try:
            markets_res[sym] = evaluate_market(
                sym, now_alg, state, news_blocked, news_msg, bot_token, chat_id, dry_run
            )
        except Exception as exc:
            markets_res[sym] = {"symbol": sym, "error": str(exc), "asia_valid": False}

    if state["losses_today"] >= 2 or state["realized_pnl"] <= -50.0:
        state["stopped_two_losses"] = True
    if state["realized_pnl"] >= 80.0:
        state["stopped_profit_cap"] = True

    if state["stopped_two_losses"] and not state["sent_two_loss_msg"] and not dry_run:
        if bot_token and chat_id:
            send_telegram_text(bot_token, chat_id, "Stop for today. 2 losses reached. Come back tomorrow.")
        state["sent_two_loss_msg"] = True

    is_weekday = now_alg.weekday() < 5
    # Send automatic 09:00 morning briefing on first weekday scan in 09:00-09:45 Algiers Time
    if (
        (is_weekday and now_alg.hour == 9 and now_alg.minute <= 45 and not state["sent_morning_brief"] and not dry_run)
        or send_brief_now
    ):
        if bot_token and chat_id:
            brief = _format_briefing_message(now_alg, markets_res, news_msg)
            send_telegram_text(bot_token, chat_id, brief)
        if not send_brief_now:
            state["sent_morning_brief"] = True

    if (
        is_weekday
        and 12 <= now_alg.hour <= 13
        and state["alerts_today"] == 0
        and not state["sent_no_setup_msg"]
        and not dry_run
    ):
        if bot_token and chat_id:
            send_telegram_text(
                bot_token,
                chat_id,
                "No valid setup today across XAUUSD, EURUSD, GBPUSD, US100, BTCUSD. No trade.",
            )
        state["sent_no_setup_msg"] = True

    save_state(state)

    gold = markets_res.get("XAUUSD", {})
    summary = {
        "now_algiers": now_alg.strftime("%Y-%m-%d %H:%M:%S"),
        "preset": "Multi-Market London Retest (XAUUSD, EURUSD, GBPUSD, US100, BTCUSD)",
        "news_blocked": news_blocked,
        "news_status": news_msg,
        "alerts_today": state["alerts_today"],
        "losses_today": state["losses_today"],
        "realized_pnl": state["realized_pnl"],
        "markets": markets_res,
        "close_price": gold.get("close_price"),
        "data_source": gold.get("data_source"),
        "action_note": gold.get("action_note", "Scanned 5 markets"),
    }
    if status_report:
        print(json.dumps(summary, indent=2))
    return summary


def seconds_until_next_m15_close(now_utc: datetime.datetime) -> float:
    """Sleep accurately until 8 seconds after the next 15-minute candle boundary."""
    next_min = ((now_utc.minute // 15) + 1) * 15
    target = now_utc.replace(minute=0, second=8, microsecond=0) + datetime.timedelta(minutes=next_min)
    return max(5.0, (target - now_utc).total_seconds())


def _safe_evaluate(
    strict_mode: bool = False,
    dry_run: bool = False,
    status_report: bool = False,
    send_brief_now: bool = False,
) -> dict:
    """Thread-safe evaluation wrapper updating cached _LAST_STATUS."""
    global _LAST_STATUS
    with _SCAN_LOCK:
        res = evaluate_once(
            strict_mode=strict_mode,
            dry_run=dry_run,
            status_report=status_report,
            send_brief_now=send_brief_now,
        )
        _LAST_STATUS = res
        return res


def run_session_loop(strict_mode: bool = False) -> None:
    """Run across today's 09:00-12:05 Algiers London session."""
    print("Starting Multi-Market London Retest Session Loop (09:00-12:05 Algiers Time)...")
    while True:
        now_alg = datetime.datetime.now(ALGIERS_TZ)
        if now_alg.weekday() >= 5:
            print("Weekend detected — exiting session loop cleanly.")
            break
        _safe_evaluate(strict_mode=strict_mode, status_report=True)
        if now_alg.hour >= 12:
            print("12:00+ Algiers Time reached — session complete.")
            break
        wait_s = seconds_until_next_m15_close(datetime.datetime.now(datetime.timezone.utc))
        time.sleep(wait_s)


def run_daemon(strict_mode: bool = False) -> None:
    """Continuous 24/7 cloud daemon."""
    print("Starting 24/7 Multi-Market London Retest Cloud Daemon...")
    while True:
        now_alg = datetime.datetime.now(ALGIERS_TZ)
        if now_alg.weekday() < 5 and 8 <= now_alg.hour <= 13:
            try:
                _safe_evaluate(strict_mode=strict_mode, status_report=True)
            except Exception as exc:
                print(f"[Error] {exc}")
            time.sleep(seconds_until_next_m15_close(datetime.datetime.now(datetime.timezone.utc)))
        else:
            time.sleep(300)


def _trigger_async_scan(strict_mode: bool = False) -> bool:
    """Launch a background evaluation immediately without blocking HTTP callers."""
    if _SCAN_LOCK.locked():
        return False

    def _job() -> None:
        try:
            _safe_evaluate(strict_mode=strict_mode, status_report=True)
        except Exception as exc:
            print(f"[Async scan error] {exc}")

    threading.Thread(target=_job, daemon=True).start()
    return True


def _render_dashboard_html(st: dict | None) -> str:
    """Render a clean multi-market status dashboard."""
    if not st:
        body = "<p>Scanner warming up... Refresh or call <a href='/scan'>/scan</a>.</p>"
    else:
        rows_html = []
        for sym, m in st.get("markets", {}).items():
            if m.get("error"):
                rows_html.append(f"<tr><td>{sym}</td><td colspan='5'>Error: {m['error']}</td></tr>")
            else:
                rows_html.append(
                    f"<tr><td><b>{sym}</b></td><td>{m['close_price']}</td><td>{m['ema50']}</td>"
                    f"<td>{m['rsi14']}</td><td>{m['asia_low']} - {m['asia_high']} ({'VALID' if m['asia_valid'] else 'SKIP'})</td>"
                    f"<td>{m['action_note']}</td></tr>"
                )
        body = (
            f"<p><b>Algiers Time (GMT+1):</b> {st['now_algiers']} | "
            f"<b>News:</b> {st['news_status']} | "
            f"<b>Alerts:</b> {st['alerts_today']}/2 | <b>Losses:</b> {st['losses_today']}/2 | "
            f"<b>PnL:</b> ${st['realized_pnl']:.2f}</p>"
            f"<table><tr><th>Market</th><th>Price</th><th>EMA50</th><th>RSI14</th><th>Asia Range</th><th>Status</th></tr>"
            f"{''.join(rows_html)}</table>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Multi-Market London Retest - Render Cloud Scanner</title>"
        "<style>body{font-family:system-ui,sans-serif;background:#0e121a;color:#e5e7eb;padding:24px;max-width:960px;margin:auto;}"
        "table{width:100%;border-collapse:collapse;margin:16px 0;}th,td{border:1px solid #2d3e58;padding:8px;text-align:left;font-size:14px;}"
        "th{background:#161d2b;color:#38bdf8;}a{color:#38bdf8;}</style></head><body>"
        "<h2>Multi-Market London Retest (XAUUSD, EURUSD, GBPUSD, US100, BTCUSD)</h2>"
        "<p>FTM/FTMO $5K Rules | Manual Entry Only | 09:00-12:00 Algiers Time | $25 Risk / $50 Reward</p>"
        f"{body}"
        "<p><a href='/scan'>Trigger /scan</a> | <a href='/scan-sync'>Sync /scan-sync</a> | "
        "<a href='/test-telegram'>Send Telegram Briefing Test</a> | <a href='/health'>/health</a></p>"
        "</body></html>"
    )


def run_web_server(strict_mode: bool = False) -> None:
    """Run fast non-blocking HTTP server + 24/7 multi-market scanner thread for Render."""
    port = int(os.environ.get("PORT", "10000"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                payload = json.dumps({"status": "ok", "service": "multi-market-london-retest"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)
            elif path == "/scan":
                started = _trigger_async_scan(strict_mode=strict_mode)
                resp_obj = {"status": "ok", "scan_triggered": started, "last_snapshot": _LAST_STATUS}
                payload = json.dumps(resp_obj, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)
            elif path == "/scan-sync":
                try:
                    res = _safe_evaluate(strict_mode=strict_mode)
                    payload = json.dumps(res, indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception as exc:
                    payload = json.dumps({"error": str(exc)}).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)
            elif path == "/test-telegram":
                try:
                    res = _safe_evaluate(strict_mode=strict_mode, dry_run=True, send_brief_now=True)
                    payload = json.dumps({"telegram_briefing_sent": True, "snapshot": res}, indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception as exc:
                    payload = json.dumps({"error": str(exc)}).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)
            else:
                if _LAST_STATUS is None:
                    _trigger_async_scan(strict_mode=strict_mode)
                html = _render_dashboard_html(_LAST_STATUS).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    _trigger_async_scan(strict_mode=strict_mode)
    threading.Thread(target=run_daemon, args=(strict_mode,), daemon=True).start()
    print(f"Render Multi-Market Web Scanner listening on 0.0.0.0:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Market London Retest 24/7 Cloud Scanner")
    parser.add_argument("--once", action="store_true", help="Evaluate all 5 markets once and exit")
    parser.add_argument("--session-loop", action="store_true", help="Run continuously through 12:05 Algiers Time")
    parser.add_argument("--daemon", action="store_true", help="Run 24/7 continuously")
    parser.add_argument("--web", action="store_true", help="Run HTTP server + 24/7 scanner thread (Render)")
    parser.add_argument("--strict", action="store_true", help="Keep strict mode flag")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without sending Telegram messages")
    parser.add_argument("--send-brief", action="store_true", help="Send a live 5-market briefing to Telegram now")
    parser.add_argument("--status-report", action="store_true", help="Print JSON diagnostic snapshot")
    args = parser.parse_args()

    if args.web:
        run_web_server(strict_mode=args.strict)
    elif args.session_loop:
        run_session_loop(strict_mode=args.strict)
    elif args.daemon:
        run_daemon(strict_mode=args.strict)
    else:
        _safe_evaluate(
            strict_mode=args.strict,
            dry_run=args.dry_run,
            status_report=args.status_report or args.once,
            send_brief_now=args.send_brief,
        )


if __name__ == "__main__":
    main()
