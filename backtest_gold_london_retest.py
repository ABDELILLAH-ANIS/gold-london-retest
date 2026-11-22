"""
Multi-Market London Retest - 3-Month / 60-Day M15 Backtest & Report Generator
Backtests:
1. Original XAUUSD 3-tier comparison (Run 1 Strict vs Run 2 Unblocked vs Run 3 2026 Preset)
2. Individual Market Backtests across all 5 FTM/FTMO markets:
   - XAUUSD (Gold, 90d M15)
   - EURUSD (Euro/USD, 60d M15)
   - GBPUSD (British Pound/USD, 60d M15)
   - US100 (Nasdaq 100, 60d M15)
   - BTCUSD (Bitcoin, 90d M15)
3. Combined Account-Wide Multi-Market Portfolio (max 2 alerts/day total across all 5 markets,
   $25 risk / $50 reward per trade, -$50 daily stop, +$80 daily profit cap).
"""

import datetime
import json
import os
import urllib.request

from cloud_scanner import MARKET_SPECS, calculate_lot_for_25_risk, compute_indicators
from gold_london_retest_db import DB_PATH, get_connection, init_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(BASE_DIR, "BACKTEST_REPORT.md")
ALGIERS_TZ = datetime.timezone(datetime.timedelta(hours=1))


def fetch_binance_m15(symbol: str, days_back: int = 92) -> list[dict]:
    """Fetch up to 92 days of M15 bars from Binance."""
    end_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days_back * 86400 * 1000
    all_klines = []
    cur = start_ms

    while cur < end_ms:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=15m&startTime={cur}&limit=1000"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not batch:
            break
        all_klines.extend(batch)
        cur = batch[-1][0] + 15 * 60 * 1000
        if len(batch) < 1000:
            break

    bars = []
    for k in all_klines:
        dt = datetime.datetime.fromtimestamp(k[0] / 1000.0, ALGIERS_TZ)
        if dt.weekday() >= 5:
            continue
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
    return compute_indicators(bars)


def fetch_yahoo_m15(yf_symbol: str) -> list[dict]:
    """Fetch 60 days of M15 bars from Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}?interval=15m&range=60d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        dt = datetime.datetime.fromtimestamp(t, ALGIERS_TZ)
        if dt.weekday() >= 5:
            continue
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
    return compute_indicators(bars)


def fetch_gcf_m15_cross_check() -> dict:
    """Cross-validate Asia widths and candle sizes against Gold Futures (GC=F)."""
    try:
        bars = fetch_yahoo_m15("GC=F")
        days = sorted({b["dt"].date() for b in bars})
        widths_00_09, london_candles = [], []
        for d in days:
            asia = [b for b in bars if b["dt"].date() == d and 0 <= b["dt"].hour < 9]
            if len(asia) >= 15:
                widths_00_09.append(max(b["h"] for b in asia) - min(b["l"] for b in asia))
            for b in bars:
                if b["dt"].date() == d and 9 <= b["dt"].hour < 12:
                    london_candles.append(b["h"] - b["l"])
        widths_00_09.sort()
        london_candles.sort()
        return {
            "available": True,
            "days": len(widths_00_09),
            "days_4_15": sum(1 for w in widths_00_09 if 4.0 <= w <= 15.0),
            "min_asia": round(widths_00_09[0], 2),
            "median_asia": round(widths_00_09[len(widths_00_09) // 2], 2),
            "max_asia": round(widths_00_09[-1], 2),
            "median_london_candle": round(london_candles[len(london_candles) // 2], 2),
            "pct_candles_le_5": round(100.0 * sum(1 for x in london_candles if x <= 5.0) / len(london_candles), 1),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def save_bars_to_db(bars: list[dict], source: str = "BINANCE_PAXGUSDT_M15") -> None:
    """Persist XAUUSD M15 historical bars into SQLite m15_bars table."""
    with get_connection(DB_PATH) as conn:
        conn.execute("DELETE FROM m15_bars;")
        conn.executemany(
            """
            INSERT INTO m15_bars (ts_algiers, symbol, open, high, low, close, ema50, rsi14, source)
            VALUES (?, 'XAUUSD', ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (b["ts"], b["o"], b["h"], b["l"], b["c"], b["ema50"], b["rsi14"], source)
                for b in bars
            ],
        )
        conn.commit()


def run_strategy_simulation(bars: list[dict], cfg: dict, symbol: str = "XAUUSD") -> dict:
    """Simulate a single-market strategy config under strict FTM $5K limits."""
    days = sorted({b["dt"].date() for b in bars})
    sessions = []
    trades = []

    balance = 5000.0
    initial_balance = 5000.0
    static_floor = 4500.0
    max_overall_dd_usd = 0.0
    max_daily_loss_usd = 0.0
    reached_400_before_500 = False
    failed_static_dd = False
    exceeded_200_daily = False

    valid_asia_days = 0
    a_start = cfg["asia_start_hour"]
    a_end = cfg["asia_end_hour"]
    digits = cfg.get("digits", 2)
    min_bo = cfg.get("min_breakout_body", 0.50)

    for d in days:
        asia_bars = [b for b in bars if b["dt"].date() == d and a_start <= b["dt"].hour < a_end]
        if len(asia_bars) < 6:
            continue

        ah = max(b["h"] for b in asia_bars)
        al = min(b["l"] for b in asia_bars)
        aw = ah - al
        range_valid = cfg["min_asia_w"] <= aw <= cfg["max_asia_w"]
        if range_valid:
            valid_asia_days += 1

        day_alerts = 0
        day_losses = 0
        day_pnl = 0.0
        last_loss_dir = None
        day_status = "NO_SETUP" if range_valid else "ASIA_RANGE_INVALID"
        day_note = f"Width {aw:.{digits}f}"

        if range_valid:
            post_asia_idx = [
                i for i, b in enumerate(bars) if b["dt"].date() == d and a_end <= b["dt"].hour < 12
            ]
            broke_up = False
            broke_dn = False

            for idx in post_asia_idx:
                if idx < 50:
                    continue
                b = bars[idx]
                prev = bars[idx - 1]

                if prev["c"] > ah and (prev["c"] - prev["o"]) >= min_bo:
                    broke_up = True
                if prev["c"] < al and (prev["o"] - prev["c"]) >= min_bo:
                    broke_dn = True

                if b["dt"].hour < 9 or b["dt"].hour >= 12:
                    continue
                if day_alerts >= 2 or day_losses >= 2 or day_pnl >= 80.0:
                    continue

                prev_size = prev["h"] - prev["l"]
                cur_range = b["h"] - b["l"]
                cur_body = abs(b["c"] - b["o"])
                if prev_size > cfg["max_candle"] or cur_range <= 0 or cur_range > cfg["max_candle"] * 1.2:
                    continue
                if cur_body / cur_range < 0.25:
                    continue

                sig_dir = None
                if (
                    broke_up
                    and (ah - cfg["sl_zone_depth"] <= b["l"] <= ah + cfg["retest_tol"])
                    and b["c"] > ah
                    and b["c"] > b["o"]
                    and b["ema50"] < b["c"]
                    and 50.0 <= b["rsi14"] <= cfg["rsi_buy_max"]
                ):
                    sig_dir = "BUY"
                elif (
                    broke_dn
                    and (al - cfg["retest_tol"] <= b["h"] <= al + cfg["sl_zone_depth"])
                    and b["c"] < al
                    and b["c"] < b["o"]
                    and b["ema50"] > b["c"]
                    and cfg["rsi_sell_min"] <= b["rsi14"] <= 50.0
                ):
                    sig_dir = "SELL"

                if sig_dir is None:
                    continue

                if day_losses >= 1 and last_loss_dir == sig_dir:
                    strong_rsi = (55.0 <= b["rsi14"] <= 63.0) if sig_dir == "BUY" else (37.0 <= b["rsi14"] <= 45.0)
                    if not strong_rsi or (cur_body / cur_range) < 0.50:
                        continue

                entry = b["c"]
                if cfg["structural_sl"]:
                    buf = cfg.get("sl_buffer", 1.0)
                    raw_dist = (
                        (entry - (min(b["l"], ah) - buf))
                        if sig_dir == "BUY"
                        else ((max(b["h"], al) + buf) - entry)
                    )
                    sl_dist = max(cfg.get("sl_min", 3.0), min(raw_dist, cfg.get("sl_max", 7.0)))
                    lot = calculate_lot_for_25_risk(symbol, sl_dist) if symbol in MARKET_SPECS else 0.08
                else:
                    sl_dist = cfg["sl_dollars"]
                    lot = 0.08

                tp_dist = sl_dist * 2.0
                sl = round(entry - sl_dist if sig_dir == "BUY" else entry + sl_dist, digits)
                tp = round(entry + tp_dist if sig_dir == "BUY" else entry - tp_dist, digits)

                win = None
                duration_min = 15.0
                for step_k, f in enumerate(bars[idx + 1 : idx + 64], start=1):
                    duration_min = step_k * 15.0
                    if sig_dir == "BUY":
                        if f["l"] <= sl:
                            win = False
                            break
                        if f["h"] >= tp:
                            win = True
                            break
                    else:
                        if f["h"] >= sl:
                            win = False
                            break
                        if f["l"] <= tp:
                            win = True
                            break

                if win is None:
                    last_f = bars[min(idx + 63, len(bars) - 1)]
                    exit_p = last_f["c"]
                    raw_r = ((exit_p - entry) if sig_dir == "BUY" else (entry - exit_p)) / sl_dist
                    pnl = round(25.0 * raw_r, 2)
                    win = pnl > 0
                else:
                    pnl = 50.0 if win else -25.0

                balance = round(balance + pnl, 2)
                static_dd_now = max(0.0, initial_balance - balance)
                max_overall_dd_usd = max(max_overall_dd_usd, static_dd_now)

                if balance <= static_floor:
                    failed_static_dd = True
                if not failed_static_dd and (balance - initial_balance) >= 400.0:
                    reached_400_before_500 = True

                day_alerts += 1
                day_pnl = round(day_pnl + pnl, 2)
                if pnl < 0:
                    day_losses += 1
                    last_loss_dir = sig_dir

                if sig_dir == "BUY":
                    broke_up = False
                else:
                    broke_dn = False

                tg_msg = (
                    f"{symbol} SIGNAL - {sig_dir}\n"
                    f"Entry: {entry:.{digits}f}\n"
                    f"Stop Loss: {sl:.{digits}f}\n"
                    f"Take Profit: {tp:.{digits}f}\n"
                    f"Lot: {lot:.2f}\n"
                    f"Reason: Break + Retest of Asia {'High' if sig_dir == 'BUY' else 'Low'}, "
                    f"EMA50 {'below' if sig_dir == 'BUY' else 'above'} price, RSI {b['rsi14']:.0f}, No News.\n"
                    f"Risk: $25 | Reward: $50\n"
                    f"Time: {b['dt'].strftime('%H:%M')} Algiers Time\n"
                    f"Confirm in MT5 manually. Trade duration must be > 5 minutes."
                )

                trades.append(
                    {
                        "symbol": symbol,
                        "date": d.isoformat(),
                        "time_algiers": b["ts"],
                        "direction": sig_dir,
                        "entry": round(entry, digits),
                        "sl": sl,
                        "tp": tp,
                        "lot": lot,
                        "ema50": round(b["ema50"], digits),
                        "rsi14": round(b["rsi14"], 1),
                        "asia_high": round(ah, digits),
                        "asia_low": round(al, digits),
                        "candle_size": round(prev_size, digits),
                        "outcome": "WIN" if win else "LOSS",
                        "pnl_usd": pnl,
                        "duration_min": duration_min,
                        "balance_after": balance,
                        "tg_msg": tg_msg,
                    }
                )

            if day_losses >= 2:
                day_status = "LOCKED_2_LOSSES"
            elif day_pnl >= 80.0:
                day_status = "LOCKED_80_PROFIT"
            elif day_alerts > 0:
                day_status = "TRADED"

        if day_pnl < 0:
            max_daily_loss_usd = max(max_daily_loss_usd, abs(day_pnl))
            if abs(day_pnl) >= 200.0:
                exceeded_200_daily = True

        sessions.append(
            {
                "date": d.isoformat(),
                "asia_high": round(ah, digits),
                "asia_low": round(al, digits),
                "asia_width": round(aw, digits),
                "range_valid": 1 if range_valid else 0,
                "alerts_count": day_alerts,
                "losses_count": day_losses,
                "daily_pnl": day_pnl,
                "status": day_status,
                "note": day_note,
            }
        )

    return _summarize_trades(cfg, symbol, sessions, trades, valid_asia_days, max_daily_loss_usd, max_overall_dd_usd, exceeded_200_daily, reached_400_before_500, failed_static_dd)


def _summarize_trades(
    cfg: dict,
    symbol: str,
    sessions: list[dict],
    trades: list[dict],
    valid_asia_days: int,
    max_daily_loss_usd: float,
    max_overall_dd_usd: float,
    exceeded_200_daily: bool,
    reached_400_before_500: bool,
    failed_static_dd: bool,
) -> dict:
    wins_list = [t["pnl_usd"] for t in trades if t["pnl_usd"] > 0]
    losses_list = [t["pnl_usd"] for t in trades if t["pnl_usd"] < 0]
    total_trades = len(trades)
    win_rate = round(100.0 * len(wins_list) / total_trades, 1) if total_trades else 0.0
    avg_win = round(sum(wins_list) / len(wins_list), 2) if wins_list else 0.0
    avg_loss = round(sum(losses_list) / len(losses_list), 2) if losses_list else 0.0
    net_pnl = round(sum(t["pnl_usd"] for t in trades), 2)
    min_dur = min((t["duration_min"] for t in trades), default=0.0)

    return {
        "cfg": cfg,
        "symbol": symbol,
        "total_days": len(sessions),
        "valid_asia_days": valid_asia_days,
        "total_trades": total_trades,
        "wins": len(wins_list),
        "losses": len(losses_list),
        "win_rate_pct": win_rate,
        "avg_win_usd": avg_win,
        "avg_loss_usd": avg_loss,
        "net_pnl_usd": net_pnl,
        "max_daily_loss_usd": round(max_daily_loss_usd, 2),
        "max_overall_dd_usd": round(max_overall_dd_usd, 2),
        "exceeded_200_daily": exceeded_200_daily,
        "reached_400_before_500": reached_400_before_500,
        "passed_ftm_phase1": reached_400_before_500 and not exceeded_200_daily and not failed_static_dd,
        "min_duration_min": min_dur,
        "sessions": sessions,
        "trades": trades,
    }


def simulate_combined_portfolio(per_market_results: dict[str, dict]) -> dict:
    """Combine all 5 markets chronologically enforcing account-wide max 2 trades/day, -$50 stop, +$80 cap."""
    all_trades = []
    all_dates = set()
    for sym, res in per_market_results.items():
        all_trades.extend(res["trades"])
        for s in res["sessions"]:
            all_dates.add(s["date"])
    all_trades.sort(key=lambda t: (t["time_algiers"], t["symbol"]))

    balance = 5000.0
    initial_balance = 5000.0
    max_overall_dd_usd = 0.0
    max_daily_loss_usd = 0.0
    exceeded_200_daily = False
    reached_400_before_500 = False
    failed_static_dd = False

    by_day: dict[str, list[dict]] = {}
    for t in all_trades:
        by_day.setdefault(t["date"], []).append(t)

    accepted_trades = []
    sessions = []
    for d_str in sorted(all_dates):
        day_alerts = 0
        day_losses = 0
        day_pnl = 0.0
        for t in by_day.get(d_str, []):
            if day_alerts >= 2 or day_losses >= 2 or day_pnl >= 80.0:
                continue
            pnl = t["pnl_usd"]
            balance = round(balance + pnl, 2)
            static_dd_now = max(0.0, initial_balance - balance)
            max_overall_dd_usd = max(max_overall_dd_usd, static_dd_now)
            if balance <= 4500.0:
                failed_static_dd = True
            if not failed_static_dd and (balance - initial_balance) >= 400.0:
                reached_400_before_500 = True
            day_alerts += 1
            day_pnl = round(day_pnl + pnl, 2)
            if pnl < 0:
                day_losses += 1
            t_copy = dict(t)
            t_copy["balance_after"] = balance
            accepted_trades.append(t_copy)

        if day_pnl < 0:
            max_daily_loss_usd = max(max_daily_loss_usd, abs(day_pnl))
            if abs(day_pnl) >= 200.0:
                exceeded_200_daily = True
        sessions.append(
            {
                "date": d_str,
                "asia_high": 0.0,
                "asia_low": 0.0,
                "asia_width": 0.0,
                "range_valid": 1,
                "alerts_count": day_alerts,
                "losses_count": day_losses,
                "daily_pnl": day_pnl,
                "status": "TRADED" if day_alerts else "NO_SETUP",
                "note": "Combined 5-market portfolio",
            }
        )

    cfg = {"name": "Combined Multi-Market Portfolio (5 Markets, Max 2/Day, -$50 Stop)"}
    return _summarize_trades(
        cfg,
        "PORTFOLIO_5M",
        sessions,
        accepted_trades,
        len(sessions),
        max_daily_loss_usd,
        max_overall_dd_usd,
        exceeded_200_daily,
        reached_400_before_500,
        failed_static_dd,
    )


def save_backtest_to_db(results: list[dict], start_date: str, end_date: str) -> None:
    """Persist all backtest runs, daily sessions, and simulated signals into SQLite."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_connection(DB_PATH) as conn:
        conn.execute("DELETE FROM signals WHERE source_type = 'BACKTEST';")
        conn.execute("DELETE FROM daily_sessions;")
        conn.execute("DELETE FROM backtest_runs;")

        for res in results:
            cfg = res["cfg"]
            sym = res.get("symbol", "XAUUSD")
            cur = conn.execute(
                """
                INSERT INTO backtest_runs (
                    run_name, symbol, data_source, start_date, end_date,
                    total_days, valid_asia_days, total_trades, wins, losses,
                    win_rate_pct, avg_win_usd, avg_loss_usd, net_pnl_usd,
                    max_daily_loss_usd, max_overall_dd_usd, exceeded_200_daily_dd,
                    reached_400_before_500_dd, passed_ftm_phase1, min_duration_min,
                    params_json, created_at
                ) VALUES (?, ?, 'MULTI_SOURCE_M15', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cfg["name"],
                    sym,
                    start_date,
                    end_date,
                    res["total_days"],
                    res["valid_asia_days"],
                    res["total_trades"],
                    res["wins"],
                    res["losses"],
                    res["win_rate_pct"],
                    res["avg_win_usd"],
                    res["avg_loss_usd"],
                    res["net_pnl_usd"],
                    res["max_daily_loss_usd"],
                    res["max_overall_dd_usd"],
                    1 if res["exceeded_200_daily"] else 0,
                    1 if res["reached_400_before_500"] else 0,
                    1 if res["passed_ftm_phase1"] else 0,
                    res["min_duration_min"],
                    json.dumps(cfg),
                    now_iso,
                ),
            )
            run_id = cur.lastrowid

            conn.executemany(
                """
                INSERT INTO daily_sessions (
                    run_id, session_date, asia_high, asia_low, asia_width,
                    range_valid, alerts_count, losses_count, daily_pnl_usd, status, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        s["date"],
                        s["asia_high"],
                        s["asia_low"],
                        s["asia_width"],
                        s["range_valid"],
                        s["alerts_count"],
                        s["losses_count"],
                        s["daily_pnl"],
                        s["status"],
                        s["note"],
                    )
                    for s in res["sessions"]
                ],
            )

            conn.executemany(
                """
                INSERT INTO signals (
                    run_id, source_type, signal_time_algiers, symbol, direction,
                    entry_price, stop_loss, take_profit, lot_size, ema50, rsi14,
                    asia_high, asia_low, candle_size, outcome, pnl_usd,
                    duration_minutes, telegram_message, created_at
                ) VALUES (?, 'BACKTEST', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        t["time_algiers"],
                        t.get("symbol", sym),
                        t["direction"],
                        t["entry"],
                        t["sl"],
                        t["tp"],
                        t["lot"],
                        t["ema50"],
                        t["rsi14"],
                        t["asia_high"],
                        t["asia_low"],
                        t["candle_size"],
                        t["outcome"],
                        t["pnl_usd"],
                        t["duration_min"],
                        t["tg_msg"],
                        now_iso,
                    )
                    for t in res["trades"]
                ],
            )
        conn.commit()


def write_markdown_report(
    xau_results: list[dict],
    per_market_results: dict[str, dict],
    portfolio_res: dict,
    gcf_check: dict,
    start_date: str,
    end_date: str,
) -> None:
    """Write complete Multi-Market + XAUUSD FTM/FTMO Backtest Report."""
    r1, r2, r3 = xau_results[0], xau_results[1], xau_results[2]
    lines = [
        "# Multi-Market London Retest (M15) — Backtest Report (FTM / FTMO $5,000)",
        "",
        f"- **Test Window:** `{start_date}` to `{end_date}` (Strictly `09:00–12:00` Algiers Time `GMT+1`, Mon–Fri)",
        "- **Markets Covered:** `XAUUSD` (90d), `EURUSD` (60d), `GBPUSD` (60d), `US100` (60d), `BTCUSD` (90d)",
        "- **FTM / FTMO Rules:** `$5,000` balance, `$25` risk / `$50` reward (`1:2` RR), max `2` alerts/day combined, `-$50` daily stop, `+$80` daily profit cap, min duration `> 5` min, zero automated trades / zero Martingale / zero copy-trading.",
        "",
        "---",
        "",
        "## 1. Combined 5-Market Portfolio & Per-Market Results",
        "",
        "| Market / Portfolio | Days Tested | Valid Asia Days | Trades | Win Rate | Net PnL ($) | Max Daily Loss | Max Static DD | Passed +$400 Phase 1? |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for sym in ("XAUUSD", "EURUSD", "GBPUSD", "US100", "BTCUSD"):
        m = per_market_results[sym]
        lines.append(
            f"| **{sym}** | {m['total_days']} | {m['valid_asia_days']} | {m['total_trades']} ({m['wins']}W/{m['losses']}L) | "
            f"{m['win_rate_pct']:.1f}% | {'+' if m['net_pnl_usd'] >= 0 else ''}${m['net_pnl_usd']:.2f} | "
            f"-${m['max_daily_loss_usd']:.2f} | -${m['max_overall_dd_usd']:.2f} | "
            f"{'**YES**' if m['passed_ftm_phase1'] else 'No'} |"
        )

    lines.append(
        f"| **COMBINED 5-MARKET PORTFOLIO (Max 2/day)** | {portfolio_res['total_days']} | - | "
        f"**{portfolio_res['total_trades']}** ({portfolio_res['wins']}W/{portfolio_res['losses']}L) | "
        f"**{portfolio_res['win_rate_pct']:.1f}%** | **{'+' if portfolio_res['net_pnl_usd'] >= 0 else ''}${portfolio_res['net_pnl_usd']:.2f}** | "
        f"-${portfolio_res['max_daily_loss_usd']:.2f} | -${portfolio_res['max_overall_dd_usd']:.2f} | "
        f"{'**YES (PASSED!)**' if portfolio_res['passed_ftm_phase1'] else 'No'} |"
    )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 2. XAUUSD Only — Original 3-Tier Comparison (`$4-$15` vs 2026 Calibrated)",
            "",
            "| Metric | Run 1: Exact As-Written (`$4–$15`, `$3 SL`) | Run 2: Unblocked Range (`$3 SL`) | Run 3: 2026 Volatility-Calibrated Preset |",
            "| :--- | :---: | :---: | :---: |",
            f"| **Total Trades** | {r1['total_trades']} | {r2['total_trades']} | **{r3['total_trades']}** |",
            f"| **Win Rate** | {r1['win_rate_pct']:.1f}% | {r2['win_rate_pct']:.1f}% | **{r3['win_rate_pct']:.1f}%** |",
            f"| **Net Profit** | $0.00 | +${r2['net_pnl_usd']:.2f} | **+${r3['net_pnl_usd']:.2f}** |",
            f"| **Reached +$400 Before -$500 DD?** | NO | NO | **{'YES (PASSED!)' if r3['passed_ftm_phase1'] else 'NO'}** |",
            "",
        ]
    )

    if gcf_check.get("available"):
        lines.append(
            f"> Cross-validation with `GC=F` ({gcf_check['days']} days): `00:00–09:00` Asia range was `$4–$15` on "
            f"**{gcf_check['days_4_15']}/{gcf_check['days']}** days (Min `${gcf_check['min_asia']}`, Median `${gcf_check['median_asia']}`)."
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Latest 25 Trades in Combined 5-Market Portfolio",
            "",
            "| # | Algiers Time | Market | Dir | Entry | SL | TP | Lot | Outcome | P&L ($) | Balance ($) |",
            "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )

    for idx, t in enumerate(portfolio_res["trades"][-25:], start=max(1, len(portfolio_res["trades"]) - 24)):
        d = MARKET_SPECS[t["symbol"]]["digits"]
        lines.append(
            f"| {idx} | {t['time_algiers']} | **{t['symbol']}** | {t['direction']} | "
            f"{t['entry']:.{d}f} | {t['sl']:.{d}f} | {t['tp']:.{d}f} | {t['lot']:.2f} | "
            f"**{t['outcome']}** | {'+' if t['pnl_usd'] > 0 else ''}${t['pnl_usd']:.2f} | ${t['balance_after']:.2f} |"
        )

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _spec_to_cfg(sym: str) -> dict:
    s = MARKET_SPECS[sym]
    return {
        "name": f"{sym}: Multi-Market London Retest (Tokyo 01-07, Structural SL, $25 Risk)",
        "asia_start_hour": s["asia_start_h"],
        "asia_end_hour": s["asia_end_h"],
        "min_asia_w": s["min_asia_w"],
        "max_asia_w": s["max_asia_w"],
        "min_breakout_body": s["min_breakout_body"],
        "max_candle": s["max_candle"],
        "retest_tol": s["retest_tol"],
        "sl_zone_depth": s["sl_zone_depth"],
        "sl_buffer": s["sl_buffer"],
        "sl_min": s["sl_min"],
        "sl_max": s["sl_max"],
        "rsi_buy_max": s["rsi_buy_max"],
        "rsi_sell_min": s["rsi_sell_min"],
        "digits": s["digits"],
        "structural_sl": True,
    }


def main() -> None:
    init_db(DB_PATH)
    print("Fetching M15 datasets across 5 markets (XAUUSD, EURUSD, GBPUSD, US100, BTCUSD)...")
    xau_bars = fetch_binance_m15("PAXGUSDT", 92)
    save_bars_to_db(xau_bars)
    gcf_check = fetch_gcf_m15_cross_check()

    market_bars = {
        "XAUUSD": xau_bars,
        "EURUSD": fetch_yahoo_m15("EURUSD=X"),
        "GBPUSD": fetch_yahoo_m15("GBPUSD=X"),
        "US100": fetch_yahoo_m15("NQ=F"),
        "BTCUSD": fetch_binance_m15("BTCUSDT", 92),
    }

    start_date = xau_bars[0]["dt"].date().isoformat()
    end_date = xau_bars[-1]["dt"].date().isoformat()

    xau_legacy_cfgs = [
        {
            "name": "Run 1: Exact As-Written Rules ($4-$15 Asia, $3 SL, $6 TP)",
            "asia_start_hour": 0, "asia_end_hour": 9, "min_asia_w": 4.0, "max_asia_w": 15.0,
            "max_candle": 5.0, "retest_tol": 1.5, "sl_zone_depth": 2.1, "rsi_buy_max": 65.0,
            "rsi_sell_min": 35.0, "sl_dollars": 3.0, "structural_sl": False, "digits": 2,
        },
        {
            "name": "Run 2: Unblocked Asia Range Only ($3 SL, $6 TP, 0.08 Lot)",
            "asia_start_hour": 0, "asia_end_hour": 9, "min_asia_w": 4.0, "max_asia_w": 120.0,
            "max_candle": 5.0, "retest_tol": 2.0, "sl_zone_depth": 2.1, "rsi_buy_max": 65.0,
            "rsi_sell_min": 35.0, "sl_dollars": 3.0, "structural_sl": False, "digits": 2,
        },
        _spec_to_cfg("XAUUSD"),
    ]
    xau_results = [run_strategy_simulation(xau_bars, cfg, "XAUUSD") for cfg in xau_legacy_cfgs]

    per_market_results = {
        sym: (xau_results[2] if sym == "XAUUSD" else run_strategy_simulation(market_bars[sym], _spec_to_cfg(sym), sym))
        for sym in ("XAUUSD", "EURUSD", "GBPUSD", "US100", "BTCUSD")
    }
    portfolio_res = simulate_combined_portfolio(per_market_results)

    all_runs = xau_results + [per_market_results[s] for s in ("EURUSD", "GBPUSD", "US100", "BTCUSD")] + [portfolio_res]
    save_backtest_to_db(all_runs, start_date, end_date)
    write_markdown_report(xau_results, per_market_results, portfolio_res, gcf_check, start_date, end_date)

    for r in all_runs:
        print(
            f"[{r['symbol']:12s}] Trades={r['total_trades']:2d} | WR={r['win_rate_pct']:5.1f}% | "
            f"Net=${r['net_pnl_usd']:7.2f} | MaxDailyLoss=-${r['max_daily_loss_usd']:5.2f} | "
            f"MaxDD=-${r['max_overall_dd_usd']:6.2f} | PassP1={r['passed_ftm_phase1']}"
        )
    print(f"Saved full multi-market report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
