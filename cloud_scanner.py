"""
Gold London Retest - 24/7 Cloud Scanner (PC-Independent Telegram Alerts)
Runs the exact XAUUSD M15 Gold London Retest strategy in the cloud (GitHub Actions,
VPS, Railway, Render) so alerts arrive on Telegram even when your PC is powered off.
NEVER executes trades automatically.
"""

import argparse
import datetime
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request

from gold_london_retest_db import DB_PATH, get_connection, init_db, send_telegram_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "cloud_state.json")
ALGIERS_TZ = datetime.timezone(datetime.timedelta(hours=1))


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
    bars[0]["ema50"] = round(ema, 4)
    bars[0]["rsi14"] = 50.0

    for i in range(1, len(bars)):
        c = bars[i]["c"]
        ema = c * k_ema + ema * (1.0 - k_ema)
        bars[i]["ema50"] = round(ema, 4)
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


def fetch_from_binance() -> tuple[list[dict], str]:
    """Fetch 250 M15 bars of PAXGUSDT spot Gold proxy from Binance."""
    url = "https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=15m&limit=250"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
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
    return compute_indicators(bars), "BINANCE_PAXGUSDT_M15"


def fetch_from_okx() -> tuple[list[dict], str]:
    """Fetch 250 M15 bars of PAXG-USDT from OKX (works on US cloud runners)."""
    url = "https://www.okx.com/api/v5/market/candles?instId=PAXG-USDT&bar=15m&limit=250"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
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
    return compute_indicators(bars), "OKX_PAXGUSDT_M15"


def fetch_from_yahoo() -> tuple[list[dict], str]:
    """Fetch 5-day M15 bars of Gold Futures (GC=F) from Yahoo Finance."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=15m&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
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
    return compute_indicators(bars), "YAHOO_GCF_M15"


def fetch_live_gold_bars() -> tuple[list[dict], str]:
    """Fetch M15 Gold bars with automatic multi-provider cloud failover."""
    errors = []
    for fetcher in (fetch_from_binance, fetch_from_okx, fetch_from_yahoo):
        try:
            bars, src = fetcher()
            if len(bars) >= 60:
                return bars, src
        except Exception as exc:
            errors.append(f"{fetcher.__name__}: {exc}")
    raise RuntimeError("All Gold M15 feeds failed: " + " | ".join(errors))


def check_usd_high_impact_news(now_alg: datetime.datetime) -> tuple[bool, str]:
    """Check ForexFactory weekly feed for USD High-Impact events within +/- 60 minutes."""
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            events = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return False, f"Calendar unavailable ({exc})"

    keywords = ("CPI", "NFP", "NON-FARM", "NONFARM", "FOMC", "FED", "POWELL", "PPI", "GDP", "PCE", "GOLD")
    for ev in events:
        if ev.get("country") != "USD":
            continue
        title = str(ev.get("title", ""))
        impact = str(ev.get("impact", ""))
        if impact != "High" and not any(kw in title.upper() for kw in keywords):
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
            return True, f"USD High News: {title} ({ev_dt.strftime('%H:%M')} Algiers)"
    return False, "No News"


def load_state(today_key: str) -> dict:
    """Load or reset today's state from cloud_state.json."""
    default = {
        "day_key": today_key,
        "alerts_today": 0,
        "losses_today": 0,
        "realized_pnl": 0.0,
        "first_dir": None,
        "first_entry": None,
        "first_sl": None,
        "first_tp": None,
        "first_resolved": False,
        "stopped_two_losses": False,
        "stopped_profit_cap": False,
        "sent_two_loss_msg": False,
        "sent_no_setup_msg": False,
        "last_bar_ts": None,
        "last_alert_bar_ts": None,
    }
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                st = json.load(fh)
            if st.get("day_key") == today_key:
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
                ) VALUES (NULL, 'CLOUD_SCANNER', ?, 'XAUUSD', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SENT_MANUAL', 0.0, 0.0, ?, ?)
                """,
                (
                    sig["ts"],
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


def get_preset_params(strict_mode: bool) -> dict:
    """Return strategy parameters matching GoldLondonRetest.mq5."""
    if strict_mode:
        return {
            "name": "Strict Original ($4-$15, $3 SL)",
            "asia_start_h": 0,
            "asia_end_h": 9,
            "min_asia_w": 4.0,
            "max_asia_w": 15.0,
            "max_candle": 5.0,
            "retest_tol": 1.5,
            "sl_zone_depth": 2.1,
            "rsi_buy_max": 65.0,
            "rsi_sell_min": 35.0,
            "structural_sl": False,
        }
    return {
        "name": "2026 Volatility-Calibrated Preset ($8-$65 Tokyo 01-07, Structural SL, $25 Risk)",
        "asia_start_h": 1,
        "asia_end_h": 7,
        "min_asia_w": 8.0,
        "max_asia_w": 65.0,
        "max_candle": 10.0,
        "retest_tol": 3.5,
        "sl_zone_depth": 3.5,
        "rsi_buy_max": 68.0,
        "rsi_sell_min": 32.0,
        "structural_sl": True,
    }


def evaluate_once(strict_mode: bool = False, dry_run: bool = False, status_report: bool = False) -> dict:
    """Evaluate the latest closed M15 candle and send Telegram alerts if all conditions pass."""
    now_alg = datetime.datetime.now(ALGIERS_TZ)
    today_date = now_alg.date()
    today_key = today_date.isoformat()
    state = load_state(today_key)

    bars, data_src = fetch_live_gold_bars()
    # Second-to-last bar is the most recently closed M15 candle
    closed_idx = len(bars) - 2
    closed_bar = bars[closed_idx]
    prev_bar = bars[closed_idx - 1]
    cfg = get_preset_params(strict_mode)

    asia_bars = [
        b
        for b in bars[:-1]
        if b["dt"].date() == today_date and cfg["asia_start_h"] <= b["dt"].hour < cfg["asia_end_h"]
    ]
    asia_high = max((b["h"] for b in asia_bars), default=0.0)
    asia_low = min((b["l"] for b in asia_bars), default=0.0)
    asia_width = round(asia_high - asia_low, 2) if asia_bars else 0.0
    asia_valid = len(asia_bars) >= 6 and (cfg["min_asia_w"] <= asia_width <= cfg["max_asia_w"])

    news_blocked, news_msg = check_usd_high_impact_news(now_alg)
    bot_token, chat_id = load_telegram_credentials()

    # Check if Signal #1 resolved on latest closed bar
    if state["first_dir"] and not state["first_resolved"]:
        if state["first_dir"] == "BUY":
            if closed_bar["l"] <= state["first_sl"]:
                state["losses_today"] += 1
                state["realized_pnl"] -= 25.0
                state["first_resolved"] = True
            elif closed_bar["h"] >= state["first_tp"]:
                state["realized_pnl"] += 50.0
                state["first_resolved"] = True
        elif state["first_dir"] == "SELL":
            if closed_bar["h"] >= state["first_sl"]:
                state["losses_today"] += 1
                state["realized_pnl"] -= 25.0
                state["first_resolved"] = True
            elif closed_bar["l"] <= state["first_tp"]:
                state["realized_pnl"] += 50.0
                state["first_resolved"] = True

    if state["losses_today"] >= 2 or state["realized_pnl"] <= -50.0:
        state["stopped_two_losses"] = True
    if state["realized_pnl"] >= 80.0:
        state["stopped_profit_cap"] = True

    if state["stopped_two_losses"] and not state["sent_two_loss_msg"] and not dry_run:
        if bot_token and chat_id:
            send_telegram_text(bot_token, chat_id, "Stop for today. 2 losses reached. Come back tomorrow.")
        state["sent_two_loss_msg"] = True

    is_weekday = now_alg.weekday() < 5
    if (
        is_weekday
        and now_alg.hour == 12
        and state["alerts_today"] == 0
        and not state["sent_no_setup_msg"]
        and not dry_run
    ):
        if bot_token and chat_id:
            send_telegram_text(bot_token, chat_id, "No valid setup today. No trade.")
        state["sent_no_setup_msg"] = True

    # Evaluate breakout + retest only if inside 09:00-12:00 Algiers window on a weekday
    bar_alg = closed_bar["dt"]
    in_window = (bar_alg.weekday() < 5) and (9 <= bar_alg.hour < 12)
    action_note = "Outside 09:00-12:00 Algiers window"

    if in_window:
        if state["stopped_two_losses"]:
            action_note = "Stopped: 2 losses reached"
        elif state["stopped_profit_cap"]:
            action_note = "Stopped: +$80 daily cap hit"
        elif state["alerts_today"] >= 2:
            action_note = "Max 2 alerts reached today"
        elif not asia_valid:
            action_note = f"Asia width ${asia_width:.2f} outside range"
        elif news_blocked:
            action_note = f"Blocked by {news_msg}"
        elif state["last_alert_bar_ts"] == closed_bar["ts"]:
            action_note = "Bar already alerted"
        else:
            # Scan post-asia bars today up to closed_bar for prior breakout
            broke_up, broke_dn = False, False
            for idx in range(1, closed_idx):
                b = bars[idx]
                if b["dt"].date() != today_date or b["dt"].hour < cfg["asia_end_h"]:
                    continue
                if b["c"] > asia_high and (b["c"] - b["o"]) >= 0.50:
                    broke_up = True
                if b["c"] < asia_low and (b["o"] - b["c"]) >= 0.50:
                    broke_dn = True

            prev_size = prev_bar["h"] - prev_bar["l"]
            cur_range = closed_bar["h"] - closed_bar["l"]
            cur_body = abs(closed_bar["c"] - closed_bar["o"])
            sig_dir = None

            if prev_size <= cfg["max_candle"] and 0 < cur_range <= cfg["max_candle"] * 1.2 and (cur_body / cur_range) >= 0.25:
                if (
                    broke_up
                    and (asia_high - cfg["sl_zone_depth"] <= closed_bar["l"] <= asia_high + cfg["retest_tol"])
                    and closed_bar["c"] > asia_high
                    and closed_bar["c"] > closed_bar["o"]
                    and closed_bar["ema50"] < closed_bar["c"]
                    and 50.0 <= closed_bar["rsi14"] <= cfg["rsi_buy_max"]
                ):
                    sig_dir = "BUY"
                elif (
                    broke_dn
                    and (asia_low - cfg["retest_tol"] <= closed_bar["h"] <= asia_low + cfg["sl_zone_depth"])
                    and closed_bar["c"] < asia_low
                    and closed_bar["c"] < closed_bar["o"]
                    and closed_bar["ema50"] > closed_bar["c"]
                    and cfg["rsi_sell_min"] <= closed_bar["rsi14"] <= 50.0
                ):
                    sig_dir = "SELL"

            if sig_dir and state["losses_today"] >= 1 and state["first_dir"] == sig_dir:
                strong_rsi = (
                    (55.0 <= closed_bar["rsi14"] <= 63.0)
                    if sig_dir == "BUY"
                    else (37.0 <= closed_bar["rsi14"] <= 45.0)
                )
                if not strong_rsi or (cur_body / cur_range) < 0.50:
                    sig_dir = None
                    action_note = "2nd trade blocked: weaker same-direction setup after loss"

            if sig_dir:
                entry = round(closed_bar["c"], 2)
                if cfg["structural_sl"]:
                    raw_dist = (
                        (entry - (min(closed_bar["l"], asia_high) - 1.0))
                        if sig_dir == "BUY"
                        else ((max(closed_bar["h"], asia_low) + 1.0) - entry)
                    )
                    sl_dist = max(3.0, min(raw_dist, 7.0))
                else:
                    sl_dist = 3.0
                tp_dist = sl_dist * 2.0
                sl = round(entry - sl_dist if sig_dir == "BUY" else entry + sl_dist, 2)
                tp = round(entry + tp_dist if sig_dir == "BUY" else entry - tp_dist, 2)
                lot = min(0.08, max(0.01, round(25.0 / (100.0 * sl_dist), 2))) if cfg["structural_sl"] else 0.08
                risk = round(lot * 100.0 * sl_dist)
                reward = round(risk * 2.0)

                level_desc = (
                    "Break + Retest of Asia High, EMA50 below price"
                    if sig_dir == "BUY"
                    else "Break + Retest of Asia Low, EMA50 above price"
                )
                tg_msg = (
                    f"GOLD SIGNAL - {sig_dir}\n"
                    f"Entry: {entry:.2f}\n"
                    f"Stop Loss: {sl:.2f}\n"
                    f"Take Profit: {tp:.2f}\n"
                    f"Lot: {lot:.2f}\n"
                    f"Reason: {level_desc}, RSI {closed_bar['rsi14']:.0f}, No News.\n"
                    f"Risk: ${risk} | Reward: ${reward}\n"
                    f"Time: {bar_alg.strftime('%H:%M')} Algiers Time\n"
                    "Confirm in MT5 manually. Trade duration must be > 5 minutes."
                )

                if not dry_run and bot_token and chat_id:
                    ok, info = send_telegram_text(bot_token, chat_id, tg_msg)
                    action_note = f"Signal {sig_dir} sent -> {info}"
                else:
                    action_note = f"Signal {sig_dir} generated (dry_run={dry_run})"

                log_cloud_signal_to_db(
                    {
                        "ts": closed_bar["ts"],
                        "dir": sig_dir,
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "lot": lot,
                        "ema50": closed_bar["ema50"],
                        "rsi14": closed_bar["rsi14"],
                        "asia_high": asia_high,
                        "asia_low": asia_low,
                        "prev_size": round(prev_size, 2),
                    },
                    tg_msg,
                )

                state["alerts_today"] += 1
                state["last_alert_bar_ts"] = closed_bar["ts"]
                if not state["first_dir"]:
                    state["first_dir"] = sig_dir
                    state["first_entry"] = entry
                    state["first_sl"] = sl
                    state["first_tp"] = tp
            elif action_note == "Outside 09:00-12:00 Algiers window":
                action_note = "In window — waiting for valid Break+Retest setup"

    state["last_bar_ts"] = closed_bar["ts"]
    save_state(state)

    summary = {
        "now_algiers": now_alg.strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": data_src,
        "preset": cfg["name"],
        "closed_bar_ts": closed_bar["ts"],
        "close_price": round(closed_bar["c"], 2),
        "ema50": round(closed_bar["ema50"], 2),
        "rsi14": closed_bar["rsi14"],
        "asia_high": round(asia_high, 2),
        "asia_low": round(asia_low, 2),
        "asia_width": asia_width,
        "asia_valid": asia_valid,
        "news_blocked": news_blocked,
        "news_status": news_msg,
        "alerts_today": state["alerts_today"],
        "losses_today": state["losses_today"],
        "action_note": action_note,
    }
    if status_report:
        print(json.dumps(summary, indent=2))
    return summary


def seconds_until_next_m15_close(now_utc: datetime.datetime) -> float:
    """Sleep accurately until 8 seconds after the next 15-minute candle boundary."""
    next_min = ((now_utc.minute // 15) + 1) * 15
    target = now_utc.replace(minute=0, second=8, microsecond=0) + datetime.timedelta(minutes=next_min)
    return max(5.0, (target - now_utc).total_seconds())


def run_session_loop(strict_mode: bool = False) -> None:
    """Run across today's 09:00-12:05 Algiers London session (for GitHub Actions / cron)."""
    print("Starting Gold London Retest Cloud Session Loop (09:00-12:05 Algiers Time)...")
    while True:
        now_alg = datetime.datetime.now(ALGIERS_TZ)
        if now_alg.weekday() >= 5:
            print("Weekend detected — exiting session loop cleanly.")
            break
        res = evaluate_once(strict_mode=strict_mode, status_report=True)
        if now_alg.hour >= 12:
            print("12:00+ Algiers Time reached — session complete.")
            break
        wait_s = seconds_until_next_m15_close(datetime.datetime.now(datetime.timezone.utc))
        print(f"Sleeping {wait_s:.0f}s until next M15 close...")
        time.sleep(wait_s)


def run_daemon(strict_mode: bool = False) -> None:
    """Continuous 24/7 cloud daemon (for VPS, Railway, Render, Fly.io)."""
    print("Starting 24/7 Gold London Retest Cloud Daemon...")
    while True:
        now_alg = datetime.datetime.now(ALGIERS_TZ)
        if now_alg.weekday() < 5 and 8 <= now_alg.hour <= 12:
            try:
                evaluate_once(strict_mode=strict_mode, status_report=True)
            except Exception as exc:
                print(f"[Error] {exc}")
            time.sleep(seconds_until_next_m15_close(datetime.datetime.now(datetime.timezone.utc)))
        else:
            time.sleep(300)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gold London Retest 24/7 Cloud Scanner")
    parser.add_argument("--once", action="store_true", help="Evaluate latest closed M15 candle once and exit")
    parser.add_argument("--session-loop", action="store_true", help="Run continuously through 12:05 Algiers Time")
    parser.add_argument("--daemon", action="store_true", help="Run 24/7 continuously")
    parser.add_argument("--strict", action="store_true", help="Use strict $4-$15 / $3 SL mode instead of 2026 preset")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without sending Telegram messages")
    parser.add_argument("--status-report", action="store_true", help="Print JSON diagnostic snapshot")
    args = parser.parse_args()

    if args.session_loop:
        run_session_loop(strict_mode=args.strict)
    elif args.daemon:
        run_daemon(strict_mode=args.strict)
    else:
        evaluate_once(strict_mode=args.strict, dry_run=args.dry_run, status_report=args.status_report or args.once)


if __name__ == "__main__":
    main()
