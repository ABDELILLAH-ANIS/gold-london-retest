"""
Gold London Retest - SQLite Database & Telegram Manager
Manages FTM 2 Step Plus $5,000 rules, Telegram credentials, M15 historical bars,
daily session logs, signal records, and backtest performance metrics.
"""

import argparse
import csv
import datetime
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "gold_london_retest.db")
MQ5_PATH = os.path.join(BASE_DIR, "GoldLondonRetest.mq5")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Open SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Create all schema tables and seed the FTM 2 Step Plus $5,000 challenge rules."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ftm_challenge_rules (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                challenge_name TEXT NOT NULL,
                account_size REAL NOT NULL,
                phase1_target REAL NOT NULL,
                phase2_target REAL NOT NULL,
                max_static_dd REAL NOT NULL,
                static_dd_floor REAL NOT NULL,
                max_daily_dd REAL NOT NULL,
                min_trading_days INTEGER NOT NULL,
                consistency_rule INTEGER NOT NULL,
                profit_split INTEGER NOT NULL,
                shield_protocol_enabled INTEGER NOT NULL,
                floating_1pct_rule_enabled INTEGER NOT NULL,
                min_trade_duration_sec INTEGER NOT NULL,
                inactivity_limit_days INTEGER NOT NULL,
                risk_per_trade REAL NOT NULL,
                reward_per_trade REAL NOT NULL,
                lot_size REAL NOT NULL,
                max_daily_losses INTEGER NOT NULL,
                max_daily_loss_usd REAL NOT NULL,
                daily_profit_cap_usd REAL NOT NULL,
                max_alerts_per_day INTEGER NOT NULL,
                trading_window_algiers TEXT NOT NULL,
                asia_window_algiers TEXT NOT NULL,
                timezone TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS telegram_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                bot_token TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                is_verified INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS m15_bars (
                ts_algiers TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                ema50 REAL,
                rsi14 REAL,
                source TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                data_source TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                total_days INTEGER NOT NULL,
                valid_asia_days INTEGER NOT NULL,
                total_trades INTEGER NOT NULL,
                wins INTEGER NOT NULL,
                losses INTEGER NOT NULL,
                win_rate_pct REAL NOT NULL,
                avg_win_usd REAL NOT NULL,
                avg_loss_usd REAL NOT NULL,
                net_pnl_usd REAL NOT NULL,
                max_daily_loss_usd REAL NOT NULL,
                max_overall_dd_usd REAL NOT NULL,
                exceeded_200_daily_dd INTEGER NOT NULL,
                reached_400_before_500_dd INTEGER NOT NULL,
                passed_ftm_phase1 INTEGER NOT NULL,
                min_duration_min REAL NOT NULL,
                params_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES backtest_runs(id) ON DELETE CASCADE,
                session_date TEXT NOT NULL,
                asia_high REAL,
                asia_low REAL,
                asia_width REAL,
                range_valid INTEGER NOT NULL,
                alerts_count INTEGER NOT NULL DEFAULT 0,
                losses_count INTEGER NOT NULL DEFAULT 0,
                daily_pnl_usd REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL,
                note TEXT,
                UNIQUE(run_id, session_date)
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES backtest_runs(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL,
                signal_time_algiers TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                lot_size REAL NOT NULL,
                ema50 REAL NOT NULL,
                rsi14 REAL NOT NULL,
                asia_high REAL,
                asia_low REAL,
                candle_size REAL,
                outcome TEXT NOT NULL,
                pnl_usd REAL NOT NULL,
                duration_minutes REAL NOT NULL,
                telegram_message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO ftm_challenge_rules (
                id, challenge_name, account_size, phase1_target, phase2_target,
                max_static_dd, static_dd_floor, max_daily_dd, min_trading_days,
                consistency_rule, profit_split, shield_protocol_enabled,
                floating_1pct_rule_enabled, min_trade_duration_sec,
                inactivity_limit_days, risk_per_trade, reward_per_trade,
                lot_size, max_daily_losses, max_daily_loss_usd,
                daily_profit_cap_usd, max_alerts_per_day,
                trading_window_algiers, asia_window_algiers, timezone, updated_at
            ) VALUES (
                1, 'FTM 2 Step Plus $5,000', 5000.0, 400.0, 250.0,
                500.0, 4500.0, 200.0, 3,
                0, 70, 0,
                0, 300,
                30, 25.0, 50.0,
                0.08, 2, 50.0,
                80.0, 2,
                '09:00-12:00', '00:00-09:00', 'Africa/Algiers (GMT+1)', ?
            )
            ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at;
            """,
            (now_iso,),
        )
        conn.commit()


def send_telegram_text(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Send a plain text alert message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                return True, "Telegram test message delivered successfully."
            return False, f"Telegram API returned ok=False: {body}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
    except Exception as exc:
        return False, str(exc)


def update_mq5_telegram_inputs(bot_token: str, chat_id: str) -> bool:
    """Safely inject Bot Token and Chat ID into GoldLondonRetest.mq5 inputs."""
    if not os.path.exists(MQ5_PATH):
        return False
    with open(MQ5_PATH, "r", encoding="utf-8") as fh:
        src = fh.read()
    src = re.sub(
        r'(input string\s+InpTelegramBotToken\s*=\s*")[^"]*(";)',
        rf"\g<1>{bot_token}\g<2>",
        src,
        count=1,
    )
    src = re.sub(
        r'(input string\s+InpTelegramChatID\s*=\s*")[^"]*(";)',
        rf"\g<1>{chat_id}\g<2>",
        src,
        count=1,
    )
    with open(MQ5_PATH, "w", encoding="utf-8") as fh:
        fh.write(src)
    return True


def set_telegram_credentials(
    bot_token: str, chat_id: str, send_test: bool = False, db_path: str = DB_PATH
) -> None:
    """Store Telegram credentials in SQLite, patch MQ5, and optionally send a test alert."""
    init_db(db_path)
    verified = 0
    if send_test:
        sample = (
            "GOLD SIGNAL - BUY (TEST CONNECTION)\n"
            "Entry: 3740.00\n"
            "Stop Loss: 3737.00\n"
            "Take Profit: 3746.00\n"
            "Lot: 0.08\n"
            "Reason: Test connection from Gold London Retest (FTM 2 Step Plus $5K).\n"
            "Risk: $25 | Reward: $50\n"
            "Time: 09:45 Algiers Time\n"
            "Confirm in MT5 manually. Trade duration must be > 5 minutes."
        )
        ok, msg = send_telegram_text(bot_token, chat_id, sample)
        print(msg)
        verified = 1 if ok else 0

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO telegram_settings (id, bot_token, chat_id, is_verified, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                bot_token = excluded.bot_token,
                chat_id = excluded.chat_id,
                is_verified = excluded.is_verified,
                updated_at = excluded.updated_at;
            """,
            (bot_token, chat_id, verified, now_iso),
        )
        conn.commit()

    patched = update_mq5_telegram_inputs(bot_token, chat_id)
    print(f"Saved Telegram settings to {db_path}. Patched GoldLondonRetest.mq5: {patched}")


def sync_mt5_csv(csv_path: str, db_path: str = DB_PATH) -> int:
    """Import live signals written by GoldLondonRetest.mq5 into SQLite signals table."""
    init_db(db_path)
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}")
        return 0

    inserted = 0
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(csv_path, "r", encoding="utf-8") as fh, get_connection(db_path) as conn:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("EventType") != "SIGNAL":
                continue
            exists = conn.execute(
                "SELECT 1 FROM signals WHERE source_type = 'LIVE_MT5' AND signal_time_algiers = ? AND direction = ?",
                (row["AlgiersTime"], row["Direction"]),
            ).fetchone()
            if exists:
                continue
            msg = (
                f"GOLD SIGNAL - {row['Direction']}\n"
                f"Entry: {row['Entry']}\n"
                f"Stop Loss: {row['StopLoss']}\n"
                f"Take Profit: {row['TakeProfit']}\n"
                f"Lot: {row['Lot']}\n"
                f"Reason: {row['Note']}, RSI {row['RSI14']}, No News.\n"
                f"Risk: $25 | Reward: $50\n"
                f"Time: {row['AlgiersTime']} Algiers Time\n"
                "Confirm in MT5 manually. Trade duration must be > 5 minutes."
            )
            conn.execute(
                """
                INSERT INTO signals (
                    run_id, source_type, signal_time_algiers, symbol, direction,
                    entry_price, stop_loss, take_profit, lot_size, ema50, rsi14,
                    asia_high, asia_low, candle_size, outcome, pnl_usd,
                    duration_minutes, telegram_message, created_at
                ) VALUES (NULL, 'LIVE_MT5', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'MANUAL_PENDING', 0.0, 0.0, ?, ?)
                """,
                (
                    row["AlgiersTime"],
                    row["Symbol"],
                    row["Direction"],
                    float(row["Entry"]),
                    float(row["StopLoss"]),
                    float(row["TakeProfit"]),
                    float(row["Lot"]),
                    float(row["EMA50"]),
                    float(row["RSI14"]),
                    float(row["AsiaHigh"]),
                    float(row["AsiaLow"]),
                    msg,
                    now_iso,
                ),
            )
            inserted += 1
        conn.commit()
    print(f"Synced {inserted} new MT5 signals into {db_path}.")
    return inserted


def print_status(db_path: str = DB_PATH) -> None:
    """Print database summary, FTM rules, Telegram status, and backtest runs."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rules = dict(conn.execute("SELECT * FROM ftm_challenge_rules WHERE id = 1").fetchone())
        tg_row = conn.execute("SELECT * FROM telegram_settings WHERE id = 1").fetchone()
        bars_cnt = conn.execute("SELECT COUNT(*) FROM m15_bars").fetchone()[0]
        runs = conn.execute("SELECT * FROM backtest_runs ORDER BY id").fetchall()
        sigs_cnt = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        sess_cnt = conn.execute("SELECT COUNT(*) FROM daily_sessions").fetchone()[0]

    print("=== GOLD LONDON RETEST DATABASE STATUS ===")
    print(f"DB File: {db_path}")
    print(f"Challenge: {rules['challenge_name']} | Account: ${rules['account_size']:.0f} | Split: {rules['profit_split']}%")
    print(f"Targets: Phase 1 +${rules['phase1_target']:.0f} | Phase 2 +${rules['phase2_target']:.0f}")
    print(f"Limits: Daily DD -${rules['max_daily_dd']:.0f} | Static DD -${rules['max_static_dd']:.0f} (Floor ${rules['static_dd_floor']:.0f})")
    print(f"Strategy Risk: ${rules['risk_per_trade']:.0f} risk / ${rules['reward_per_trade']:.0f} reward | Max Lot: {rules['lot_size']:.2f}")
    print(f"Shield Risk Protocol: {'ON' if rules['shield_protocol_enabled'] else 'OFF'} | 1% Floating Rule: {'ON' if rules['floating_1pct_rule_enabled'] else 'OFF'}")
    if tg_row:
        masked = tg_row["bot_token"][:8] + "..." + tg_row["bot_token"][-4:] if len(tg_row["bot_token"]) > 12 else "***"
        print(f"Telegram: Configured (Token={masked}, ChatID={tg_row['chat_id']}, Verified={bool(tg_row['is_verified'])})")
    else:
        print("Telegram: NOT CONFIGURED YET (awaiting Bot Token & Chat ID)")
    print(f"Tables -> m15_bars: {bars_cnt} | backtest_runs: {len(runs)} | daily_sessions: {sess_cnt} | signals: {sigs_cnt}")
    for r in runs:
        print(
            f"  [Run #{r['id']}] {r['run_name']} | Trades={r['total_trades']} | "
            f"WR={r['win_rate_pct']:.1f}% | Net=${r['net_pnl_usd']:.2f} | "
            f"MaxDailyLoss=-${r['max_daily_loss_usd']:.2f} | MaxDD=-${r['max_overall_dd_usd']:.2f} | "
            f"PassP1={'YES' if r['passed_ftm_phase1'] else 'NO'}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Gold London Retest SQLite & Telegram Manager")
    parser.add_argument("--init", action="store_true", help="Initialize database schema")
    parser.add_argument("--status", action="store_true", help="Show database and challenge status")
    parser.add_argument("--set-telegram", nargs=2, metavar=("BOT_TOKEN", "CHAT_ID"), help="Save Telegram Bot Token and Chat ID")
    parser.add_argument("--send-test", action="store_true", help="Send a test Telegram message when setting credentials")
    parser.add_argument("--sync-csv", metavar="CSV_PATH", help="Import live signals CSV exported by GoldLondonRetest.mq5")
    args = parser.parse_args()

    if args.set_telegram:
        set_telegram_credentials(args.set_telegram[0], args.set_telegram[1], send_test=args.send_test)
    elif args.sync_csv:
        sync_mt5_csv(args.sync_csv)
    elif args.init:
        init_db()
        print(f"Initialized SQLite database at {DB_PATH}")
    else:
        print_status()


if __name__ == "__main__":
    main()
