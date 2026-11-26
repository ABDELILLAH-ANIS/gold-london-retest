"""
Multi-Agent Trading Intelligence System (FTM / FTMO $5,000 Compliant)
Architecture:
- 5 Specialist Market Agents (Agent_XAUUSD, Agent_EURUSD, Agent_GBPUSD, Agent_US100, Agent_BTCUSD)
  Each evaluates 12 well-known institutional/price-action strategies on M15 OHLC data.
- 1 Manager / Chief Risk Agent (ManagerAgent)
  Reviews all proposals, enforces >= 4/12 multi-strategy consensus + structural confirmation,
  USD correlation guard, High-Impact News (+/-60m) veto, 06:00-18:00 Algiers window,
  max 2 approved signals/day, -$50 daily stop, +$80 daily cap, and <= $25 risk per trade.
NEVER executes trades automatically — manual Telegram alerts only.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import math


def enrich_full_indicators(bars: list[dict]) -> list[dict]:
    """Compute all indicators needed by the 12 strategies (pure Python, zero dependencies)."""
    n = len(bars)
    if n < 30:
        return bars

    def _ema_series(vals: list[float], period: int) -> list[float]:
        k = 2.0 / (period + 1.0)
        out = [vals[0]]
        for v in vals[1:]:
            out.append(v * k + out[-1] * (1.0 - k))
        return out

    closes = [b["c"] for b in bars]
    ema9 = _ema_series(closes, 9)
    ema12 = _ema_series(closes, 12)
    ema20 = _ema_series(closes, 20)
    ema21 = _ema_series(closes, 21)
    ema26 = _ema_series(closes, 26)
    ema50 = _ema_series(closes, 50)

    macd_line = [a - b for a, b in zip(ema12, ema26)]
    macd_sig = _ema_series(macd_line, 9)
    macd_hist = [m - s for m, s in zip(macd_line, macd_sig)]

    # Wilder RSI(14), ATR(14), ADX(14), +DI, -DI
    avg_g, avg_l = 0.0, 0.0
    atr14 = [bars[0]["h"] - bars[0]["l"]]
    tr_list = [bars[0]["h"] - bars[0]["l"]]
    plus_dm = [0.0]
    minus_dm = [0.0]

    for i in range(1, n):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)
        up_m = h - bars[i - 1]["h"]
        dn_m = bars[i - 1]["l"] - l
        plus_dm.append(up_m if (up_m > dn_m and up_m > 0) else 0.0)
        minus_dm.append(dn_m if (dn_m > up_m and dn_m > 0) else 0.0)
        if i < 14:
            atr14.append(sum(tr_list) / len(tr_list))
        elif i == 14:
            atr14.append(sum(tr_list[1:15]) / 14.0)
        else:
            atr14.append((atr14[-1] * 13.0 + tr) / 14.0)

    # Smoothed +DM, -DM, ADX
    sm_tr = sum(tr_list[1:15]) if n > 14 else 1.0
    sm_pdm = sum(plus_dm[1:15]) if n > 14 else 0.0
    sm_mdm = sum(minus_dm[1:15]) if n > 14 else 0.0
    dx_vals = []
    adx_val = 20.0

    # SuperTrend (ATR 14, mult 3.0)
    st_dir = 1
    st_upper = closes[0]
    st_lower = closes[0]

    # Session VWAP (resets each Algiers day, equal-volume typical price cumulative mean)
    vwap_day = None
    vwap_sum = 0.0
    vwap_cnt = 0

    for i in range(n):
        b = bars[i]
        c = b["c"]

        # RSI 14
        if i == 0:
            rsi = 50.0
        else:
            ch = c - bars[i - 1]["c"]
            g, l_v = max(ch, 0.0), max(-ch, 0.0)
            if i <= 14:
                avg_g += g / 14.0
                avg_l += l_v / 14.0
            else:
                avg_g = (avg_g * 13.0 + g) / 14.0
                avg_l = (avg_l * 13.0 + l_v) / 14.0
            rs = (avg_g / avg_l) if avg_l > 0 else 100.0
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # Bollinger Bands (20, 2)
        win = closes[max(0, i - 19) : i + 1]
        bb_mid = sum(win) / len(win)
        var = sum((x - bb_mid) ** 2 for x in win) / len(win)
        bb_std = math.sqrt(var)
        bb_up = bb_mid + 2.0 * bb_std
        bb_dn = bb_mid - 2.0 * bb_std

        # ADX / DI
        if i > 14:
            sm_tr = sm_tr - (sm_tr / 14.0) + tr_list[i]
            sm_pdm = sm_pdm - (sm_pdm / 14.0) + plus_dm[i]
            sm_mdm = sm_mdm - (sm_mdm / 14.0) + minus_dm[i]
        pdi = (100.0 * sm_pdm / sm_tr) if sm_tr > 0 else 0.0
        mdi = (100.0 * sm_mdm / sm_tr) if sm_tr > 0 else 0.0
        dx = (100.0 * abs(pdi - mdi) / (pdi + mdi)) if (pdi + mdi) > 0 else 0.0
        dx_vals.append(dx)
        if len(dx_vals) == 14:
            adx_val = sum(dx_vals) / 14.0
        elif len(dx_vals) > 14:
            adx_val = (adx_val * 13.0 + dx) / 14.0

        # SuperTrend
        hl2 = (b["h"] + b["l"]) / 2.0
        basic_up = hl2 + 3.0 * atr14[i]
        basic_dn = hl2 - 3.0 * atr14[i]
        if i == 0:
            st_upper, st_lower = basic_up, basic_dn
        else:
            st_upper = basic_up if (basic_up < st_upper or bars[i - 1]["c"] > st_upper) else st_upper
            st_lower = basic_dn if (basic_dn > st_lower or bars[i - 1]["c"] < st_lower) else st_lower
            if st_dir == 1 and c < st_lower:
                st_dir = -1
            elif st_dir == -1 and c > st_upper:
                st_dir = 1

        # Daily Session VWAP
        cur_d = b["dt"].date()
        if cur_d != vwap_day:
            vwap_day = cur_d
            vwap_sum = 0.0
            vwap_cnt = 0
        tp_p = (b["h"] + b["l"] + c) / 3.0
        vwap_sum += tp_p
        vwap_cnt += 1
        vwap = vwap_sum / vwap_cnt

        # Stochastic (14, 3) & Keltner Channel (EMA20 +/- 1.5*ATR14)
        st_win = bars[max(0, i - 13) : i + 1]
        hh14 = max(x["h"] for x in st_win)
        ll14 = min(x["l"] for x in st_win)
        stoch_k = (100.0 * (c - ll14) / (hh14 - ll14)) if hh14 > ll14 else 50.0
        b["stoch_k"] = round(stoch_k, 1)
        prev_ks = [bars[j].get("stoch_k", 50.0) for j in range(max(0, i - 2), i)] + [stoch_k]
        b["stoch_d"] = round(sum(prev_ks) / len(prev_ks), 1)

        b["kc_up"] = ema20[i] + 1.5 * atr14[i]
        b["kc_dn"] = ema20[i] - 1.5 * atr14[i]
        b["ema9"] = ema9[i]
        b["ema20"] = ema20[i]
        b["ema21"] = ema21[i]
        b["ema50"] = ema50[i]
        b["rsi14"] = round(rsi, 2)
        b["macd"] = macd_line[i]
        b["macd_sig"] = macd_sig[i]
        b["macd_hist"] = macd_hist[i]
        b["bb_mid"] = bb_mid
        b["bb_up"] = bb_up
        b["bb_dn"] = bb_dn
        b["atr14"] = atr14[i]
        b["pdi"] = round(pdi, 1)
        b["mdi"] = round(mdi, 1)
        b["adx"] = round(adx_val, 1)
        b["supertrend"] = st_dir
        b["vwap"] = vwap

    return bars


class MarketSpecialistAgent:
    """Dedicated specialist agent for one market running 15 strategies (12 core + 3 market-exclusive)."""

    PSYCH_STEPS = {
        "XAUUSD": 10.0,
        "EURUSD": 0.0050,
        "GBPUSD": 0.0050,
        "US100": 100.0,
        "BTCUSD": 500.0,
    }

    STRUCTURAL_STRATEGIES = {
        "1_Asia_Range_Retest",
        "2_Psych_Level_Retest",
        "3_EMA20_50_Pullback",
        "10_SMC_BOS_FVG",
        "11_PriceAction_Engulf_Pinbar",
        "13_Gold_Liquidity_Sweep",
        "15_Gold_OrderBlock_Retest",
        "13_FX_London_Box_Break",
        "14_Donchian20_Breakout",
        "13_GBP_Judas_Sweep",
        "13_US100_NY_ORB_1530",
        "13_BTC_Volatility_Squeeze",
        "15_BTC_Liquidity_Sweep",
    }

    def __init__(self, symbol: str, spec: dict):
        self.symbol = symbol
        self.agent_name = f"Agent_{symbol}"
        self.spec = spec

    def analyze(self, bars: list[dict], data_src: str, now_alg: datetime.datetime) -> dict:
        """Run all 12 strategies on the latest closed M15 candle and return a structured proposal."""
        bars = enrich_full_indicators(bars)
        idx = len(bars) - 2
        b = bars[idx]
        prev = bars[idx - 1]
        prev2 = bars[idx - 2]
        digits = self.spec["digits"]
        today_date = b["dt"].date()

        # Asia Range (00:00 - 06:00 Algiers)
        asia_bars = [
            x
            for x in bars[:-1]
            if x["dt"].date() == today_date
            and self.spec["asia_start_h"] <= x["dt"].hour < self.spec["asia_end_h"]
        ]
        asia_h = max((x["h"] for x in asia_bars), default=0.0)
        asia_l = min((x["l"] for x in asia_bars), default=0.0)
        asia_w = asia_h - asia_l if asia_bars else 0.0
        asia_valid = len(asia_bars) >= 6 and (self.spec["min_asia_w"] <= asia_w <= self.spec["max_asia_w"])

        broke_up, broke_dn = False, False
        if asia_valid:
            for j in range(1, idx):
                x = bars[j]
                if x["dt"].date() != today_date or x["dt"].hour < self.spec["asia_end_h"]:
                    continue
                if x["c"] > asia_h and (x["c"] - x["o"]) >= self.spec["min_breakout_body"]:
                    broke_up = True
                if x["c"] < asia_l and (x["o"] - x["c"]) >= self.spec["min_breakout_body"]:
                    broke_dn = True

        votes: dict[str, str] = {}
        rng = b["h"] - b["l"]
        body = abs(b["c"] - b["o"])
        bull = b["c"] > b["o"]
        bear = b["c"] < b["o"]
        tol = self.spec["retest_tol"]

        # Strategy 1: Asia Range Breakout & Retest
        s1 = "NONE"
        if asia_valid:
            if broke_up and (asia_h - tol <= b["l"] <= asia_h + tol) and b["c"] > asia_h and bull:
                s1 = "BUY"
            elif broke_dn and (asia_l - tol <= b["h"] <= asia_l + tol) and b["c"] < asia_l and bear:
                s1 = "SELL"
        votes["1_Asia_Range_Retest"] = s1

        # Strategy 2: Psychological Round-Number Retest
        step = self.PSYCH_STEPS.get(self.symbol, 10.0)
        lvl_dn = math.floor(b["c"] / step) * step
        lvl_up = lvl_dn + step
        s2 = "NONE"
        if bull and prev["c"] > lvl_dn and (lvl_dn - tol <= b["l"] <= lvl_dn + tol * 0.6) and b["c"] > lvl_dn:
            s2 = "BUY"
        elif bear and prev["c"] < lvl_up and (lvl_up - tol * 0.6 <= b["h"] <= lvl_up + tol) and b["c"] < lvl_up:
            s2 = "SELL"
        votes["2_Psych_Level_Retest"] = s2

        # Strategy 3: EMA 20 / EMA 50 Institutional Trend Pullback
        s3 = "NONE"
        if b["c"] > b["ema20"] > b["ema50"] and bull and b["l"] <= b["ema20"] + b["atr14"] * 0.5:
            s3 = "BUY"
        elif b["c"] < b["ema20"] < b["ema50"] and bear and b["h"] >= b["ema20"] - b["atr14"] * 0.5:
            s3 = "SELL"
        votes["3_EMA20_50_Pullback"] = s3

        # Strategy 4: EMA 9 / EMA 21 Momentum Alignment
        s4 = "NONE"
        if b["ema9"] > b["ema21"] and b["c"] > b["ema9"] and b["c"] > b["ema50"]:
            s4 = "BUY"
        elif b["ema9"] < b["ema21"] and b["c"] < b["ema9"] and b["c"] < b["ema50"]:
            s4 = "SELL"
        votes["4_EMA9_21_Momentum"] = s4

        # Strategy 5: RSI (14) Trend-Zone Rejection
        s5 = "NONE"
        if 50.0 <= b["rsi14"] <= 66.0 and b["rsi14"] > prev["rsi14"]:
            s5 = "BUY"
        elif 34.0 <= b["rsi14"] <= 50.0 and b["rsi14"] < prev["rsi14"]:
            s5 = "SELL"
        votes["5_RSI14_Momentum"] = s5

        # Strategy 6: MACD (12, 26, 9) Trend & Histogram Expansion
        s6 = "NONE"
        if b["macd"] > b["macd_sig"] and b["macd_hist"] > 0 and b["macd_hist"] >= prev["macd_hist"]:
            s6 = "BUY"
        elif b["macd"] < b["macd_sig"] and b["macd_hist"] < 0 and b["macd_hist"] <= prev["macd_hist"]:
            s6 = "SELL"
        votes["6_MACD_Momentum"] = s6

        # Strategy 7: Bollinger Bands (20, 2) Midline Bounce / Expansion
        s7 = "NONE"
        if b["c"] > b["bb_mid"] and b["c"] < b["bb_up"] and bull and b["l"] <= b["bb_mid"] + b["atr14"] * 0.4:
            s7 = "BUY"
        elif b["c"] < b["bb_mid"] and b["c"] > b["bb_dn"] and bear and b["h"] >= b["bb_mid"] - b["atr14"] * 0.4:
            s7 = "SELL"
        votes["7_Bollinger_Trend"] = s7

        # Strategy 8: SuperTrend (ATR 14, 3.0)
        votes["8_SuperTrend"] = "BUY" if b["supertrend"] == 1 else "SELL"

        # Strategy 9: Session VWAP Institutional Bias
        s9 = "NONE"
        if b["c"] > b["vwap"] and bull:
            s9 = "BUY"
        elif b["c"] < b["vwap"] and bear:
            s9 = "SELL"
        votes["9_Session_VWAP"] = s9

        # Strategy 10: Smart Money Concepts (BOS + Fair Value Gap / Structure)
        recent_hi = max(x["h"] for x in bars[idx - 10 : idx - 1])
        recent_lo = min(x["l"] for x in bars[idx - 10 : idx - 1])
        bull_fvg = prev["l"] > bars[idx - 3]["h"]
        bear_fvg = prev["h"] < bars[idx - 3]["l"]
        s10 = "NONE"
        if bull and (b["c"] > recent_hi or (bull_fvg and b["l"] <= prev["l"] + tol)):
            s10 = "BUY"
        elif bear and (b["c"] < recent_lo or (bear_fvg and b["h"] >= prev["h"] - tol)):
            s10 = "SELL"
        votes["10_SMC_BOS_FVG"] = s10

        # Strategy 11: Price Action Engulfing / Pinbar Rejection
        s11 = "NONE"
        if rng > 0:
            lower_wick = min(b["o"], b["c"]) - b["l"]
            upper_wick = b["h"] - max(b["o"], b["c"])
            bull_engulf = bull and prev["c"] < prev["o"] and b["c"] >= prev["o"] and body > abs(prev["c"] - prev["o"])
            bear_engulf = bear and prev["c"] > prev["o"] and b["c"] <= prev["o"] and body > abs(prev["c"] - prev["o"])
            bull_pin = bull and lower_wick >= rng * 0.45 and upper_wick <= rng * 0.25
            bear_pin = bear and upper_wick >= rng * 0.45 and lower_wick <= rng * 0.25
            if bull_engulf or bull_pin:
                s11 = "BUY"
            elif bear_engulf or bear_pin:
                s11 = "SELL"
        votes["11_PriceAction_Engulf_Pinbar"] = s11

        # Strategy 12: ADX (14) + DI Trend Strength Filter
        s12 = "NONE"
        if b["adx"] >= 20.0:
            if b["pdi"] > b["mdi"]:
                s12 = "BUY"
            elif b["mdi"] > b["pdi"]:
                s12 = "SELL"
        votes["12_ADX_Trend_Strength"] = s12

        # --- Market-Exclusive Specialist Strategies (#13, #14, #15) ---
        swing12_hi = max(x["h"] for x in bars[max(0, idx - 12) : idx])
        swing12_lo = min(x["l"] for x in bars[max(0, idx - 12) : idx])
        donch20_hi = max(x["h"] for x in bars[max(0, idx - 20) : idx])
        donch20_lo = min(x["l"] for x in bars[max(0, idx - 20) : idx])
        in_squeeze = (prev["bb_up"] < prev["kc_up"]) and (prev["bb_dn"] > prev["kc_dn"])

        if self.symbol == "XAUUSD":
            # #13 Gold Liquidity Sweep (Stop-Hunt / Turtle Soup)
            s13 = "NONE"
            if b["l"] < swing12_lo and b["c"] > swing12_lo and bull:
                s13 = "BUY"
            elif b["h"] > swing12_hi and b["c"] < swing12_hi and bear:
                s13 = "SELL"
            votes["13_Gold_Liquidity_Sweep"] = s13

            # #14 Gold London Killzone Momentum (08:00-11:00 Algiers)
            s14 = "NONE"
            if 8 <= b["dt"].hour < 11 and b["atr14"] >= prev["atr14"]:
                if b["c"] > b["ema20"] > b["ema50"] and bull:
                    s14 = "BUY"
                elif b["c"] < b["ema20"] < b["ema50"] and bear:
                    s14 = "SELL"
            votes["14_Gold_London_Killzone"] = s14

            # #15 Gold Institutional Order Block Retest
            s15 = "NONE"
            for k in range(max(2, idx - 8), idx - 1):
                ob = bars[k]
                disp = bars[k + 1]
                if ob["c"] < ob["o"] and (disp["c"] - disp["o"]) >= b["atr14"] * 1.2:
                    if bull and ob["l"] <= b["l"] <= ob["h"] and b["c"] > ob["h"]:
                        s15 = "BUY"
                        break
                elif ob["c"] > ob["o"] and (disp["o"] - disp["c"]) >= b["atr14"] * 1.2:
                    if bear and ob["l"] <= b["h"] <= ob["h"] and b["c"] < ob["l"]:
                        s15 = "SELL"
                        break
            votes["15_Gold_OrderBlock_Retest"] = s15

        elif self.symbol in ("EURUSD", "GBPUSD"):
            # #13 Pre-London Box Break (EURUSD) / ICT Judas Sweep (GBPUSD)
            if self.symbol == "EURUSD":
                pre_lon = [x for x in bars[:idx] if x["dt"].date() == today_date and 7 <= x["dt"].hour < 9]
                s13 = "NONE"
                if len(pre_lon) >= 4 and b["dt"].hour >= 9:
                    pl_h = max(x["h"] for x in pre_lon)
                    pl_l = min(x["l"] for x in pre_lon)
                    if b["c"] > pl_h and bull:
                        s13 = "BUY"
                    elif b["c"] < pl_l and bear:
                        s13 = "SELL"
                votes["13_FX_London_Box_Break"] = s13
            else:
                s13 = "NONE"
                if asia_valid and b["dt"].hour >= 8:
                    if b["l"] < asia_l and b["c"] > asia_l and bull:
                        s13 = "BUY"
                    elif b["h"] > asia_h and b["c"] < asia_h and bear:
                        s13 = "SELL"
                votes["13_GBP_Judas_Sweep"] = s13

            # #14 Donchian 20-Bar Trend Breakout
            s14 = "NONE"
            if b["c"] > donch20_hi and bull:
                s14 = "BUY"
            elif b["c"] < donch20_lo and bear:
                s14 = "SELL"
            votes["14_Donchian20_Breakout"] = s14

            # #15 Stochastic (14,3,3) Pullback Cross With EMA50 Trend
            s15 = "NONE"
            if b["c"] > b["ema50"] and b["stoch_k"] > b["stoch_d"] and prev["stoch_k"] <= prev["stoch_d"] and b["stoch_k"] < 55:
                s15 = "BUY"
            elif b["c"] < b["ema50"] and b["stoch_k"] < b["stoch_d"] and prev["stoch_k"] >= prev["stoch_d"] and b["stoch_k"] > 45:
                s15 = "SELL"
            votes["15_FX_Stochastic_Pullback"] = s15

        elif self.symbol == "US100":
            # #13 New York Opening Range Breakout (15:30-15:45 Algiers ORB)
            orb_bars = [x for x in bars[:idx] if x["dt"].date() == today_date and x["dt"].hour == 15 and x["dt"].minute == 30]
            s13 = "NONE"
            if orb_bars and (15 <= b["dt"].hour < 18):
                orb_h, orb_l = orb_bars[0]["h"], orb_bars[0]["l"]
                if b["c"] > orb_h and bull:
                    s13 = "BUY"
                elif b["c"] < orb_l and bear:
                    s13 = "SELL"
            votes["13_US100_NY_ORB_1530"] = s13

            # #14 Donchian 20-Bar Breakout
            s14 = "NONE"
            if b["c"] > donch20_hi and bull:
                s14 = "BUY"
            elif b["c"] < donch20_lo and bear:
                s14 = "SELL"
            votes["14_Donchian20_Breakout"] = s14

            # #15 Keltner/Bollinger Squeeze Fire
            s15 = "NONE"
            if in_squeeze and b["c"] > b["bb_mid"] and bull:
                s15 = "BUY"
            elif in_squeeze and b["c"] < b["bb_mid"] and bear:
                s15 = "SELL"
            votes["15_US100_Keltner_Squeeze"] = s15

        else:  # BTCUSD
            # #13 Volatility Squeeze Breakout (TTM Squeeze style)
            s13 = "NONE"
            if in_squeeze and b["c"] > b["ema50"] and bull:
                s13 = "BUY"
            elif in_squeeze and b["c"] < b["ema50"] and bear:
                s13 = "SELL"
            votes["13_BTC_Volatility_Squeeze"] = s13

            # #14 Donchian 20-Bar Crypto Breakout
            s14 = "NONE"
            if b["c"] > donch20_hi and bull:
                s14 = "BUY"
            elif b["c"] < donch20_lo and bear:
                s14 = "SELL"
            votes["14_Donchian20_Breakout"] = s14

            # #15 BTC 12-Bar Liquidity Sweep Reclaim
            s15 = "NONE"
            if b["l"] < swing12_lo and b["c"] > swing12_lo and bull:
                s15 = "BUY"
            elif b["h"] > swing12_hi and b["c"] < swing12_hi and bear:
                s15 = "SELL"
            votes["15_BTC_Liquidity_Sweep"] = s15

        total_strats = len(votes)
        buy_strats = [k for k, v in votes.items() if v == "BUY"]
        sell_strats = [k for k, v in votes.items() if v == "SELL"]
        buy_n, sell_n = len(buy_strats), len(sell_strats)

        proposed_dir = "NONE"
        agreed = []
        opposed = []
        if buy_n > sell_n and buy_n >= 4:
            proposed_dir = "BUY"
            agreed, opposed = buy_strats, sell_strats
        elif sell_n > buy_n and sell_n >= 4:
            proposed_dir = "SELL"
            agreed, opposed = sell_strats, buy_strats

        has_structural = any(s in self.STRUCTURAL_STRATEGIES for s in agreed)
        confidence = round(100.0 * len(agreed) / float(total_strats), 1) if proposed_dir != "NONE" else 0.0

        # Compute structural SL & TP1 (1:1) / TP2 (1:2)
        entry = round(b["c"], digits)
        sl, tp1, tp2, sl_dist = 0.0, 0.0, 0.0, self.spec["sl_min"]
        if proposed_dir != "NONE":
            swing_lo = min(b["l"], prev["l"])
            swing_hi = max(b["h"], prev["h"])
            raw_sl = (entry - (swing_lo - self.spec["sl_buffer"])) if proposed_dir == "BUY" else ((swing_hi + self.spec["sl_buffer"]) - entry)
            atr_sl = b["atr14"] * 1.25
            sl_dist = max(self.spec["sl_min"], min(max(raw_sl, atr_sl), self.spec["sl_max"]))
            sl = round(entry - sl_dist if proposed_dir == "BUY" else entry + sl_dist, digits)
            tp1 = round(entry + sl_dist if proposed_dir == "BUY" else entry - sl_dist, digits)
            tp2 = round(entry + sl_dist * 2.0 if proposed_dir == "BUY" else entry - sl_dist * 2.0, digits)

        day_bars = [x for x in bars[:-1] if x["dt"].date() == today_date]
        day_open = day_bars[0]["o"] if day_bars else b["o"]

        return {
            "agent": self.agent_name,
            "symbol": self.symbol,
            "data_source": data_src,
            "closed_bar_ts": b["ts"],
            "bar_dt": b["dt"],
            "close_price": entry,
            "ema20": round(b["ema20"], digits),
            "ema50": round(b["ema50"], digits),
            "rsi14": b["rsi14"],
            "adx": b["adx"],
            "atr14": round(b["atr14"], digits),
            "asia_high": round(asia_h, digits),
            "asia_low": round(asia_l, digits),
            "asia_width": round(asia_w, digits),
            "asia_valid": asia_valid,
            "prev_candle_size": round(prev["h"] - prev["l"], digits),
            "cur_candle_size": round(rng, digits),
            "day_move": round(abs(b["c"] - day_open), digits),
            "buy_votes": buy_n,
            "sell_votes": sell_n,
            "proposed_dir": proposed_dir,
            "agreed_strategies": agreed,
            "opposed_strategies": opposed,
            "has_structural_trigger": has_structural,
            "confidence_pct": confidence,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "sl_dist": sl_dist,
            "votes": votes,
        }


class ManagerAgent:
    """Chief Risk & Trade Approval Agent coordinating all 5 Specialist Market Agents."""

    MIN_AGREE_STRATEGIES = 8      # Requires >= 8/15 strategies agreeing (53%+ consensus)
    MIN_MARGIN_OVER_OPPOSE = 5    # Must beat opposite votes by at least 5 strategies

    def __init__(self, market_specs: dict, fetch_fn, lot_fn):
        self.market_specs = market_specs
        self.fetch_fn = fetch_fn
        self.lot_fn = lot_fn
        self.agents = {sym: MarketSpecialistAgent(sym, spec) for sym, spec in market_specs.items()}

    def collect_proposals(self, now_alg: datetime.datetime) -> dict[str, dict]:
        """Run all 5 specialist agents concurrently and collect their proposals."""
        results: dict[str, dict] = {}

        def _run_one(sym: str) -> tuple[str, dict]:
            try:
                bars, src = self.fetch_fn(sym)
                prop = self.agents[sym].analyze(bars, src, now_alg)
                return sym, prop
            except Exception as exc:
                return sym, {"agent": f"Agent_{sym}", "symbol": sym, "error": str(exc), "proposed_dir": "NONE"}

        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = [pool.submit(_run_one, sym) for sym in self.agents]
            for fut in as_completed(futs):
                sym, prop = fut.result()
                results[sym] = prop
        return {sym: results[sym] for sym in self.market_specs if sym in results}

    def audit_and_approve(
        self,
        proposals: dict[str, dict],
        now_alg: datetime.datetime,
        state: dict,
        news_blocked: bool,
        news_msg: str,
    ) -> list[dict]:
        """Audit every specialist proposal against FTM $5K rules, consensus, news, and correlation."""
        approved: list[dict] = []
        today_date = now_alg.date()
        usd_dirs_taken: set[str] = set()

        # Sort proposals by highest confidence first so the strongest setup wins daily slots
        ranked = sorted(
            proposals.values(),
            key=lambda p: (len(p.get("agreed_strategies", [])), p.get("adx", 0.0)),
            reverse=True,
        )

        for prop in ranked:
            sym = prop["symbol"]
            if prop.get("error"):
                prop["manager_decision"] = f"REJECTED: Feed error ({prop['error']})"
                continue

            bar_dt = prop["bar_dt"]
            in_window = (
                bar_dt.date() == today_date
                and bar_dt.weekday() < 5
                and 6 <= bar_dt.hour < 18
                and (now_alg - bar_dt).total_seconds() <= 2700
            )
            spec = self.market_specs[sym]

            if not in_window:
                prop["manager_decision"] = "WAIT: Outside 06:00-18:00 Algiers window"
                continue
            if state.get("stopped_two_losses") or state.get("losses_today", 0) >= 2:
                prop["manager_decision"] = "VETO: Daily stop reached (2 losses / -$50)"
                continue
            if state.get("stopped_profit_cap") or state.get("realized_pnl", 0.0) >= 80.0:
                prop["manager_decision"] = "VETO: Daily profit target (+$80) reached"
                continue
            if state.get("alerts_today", 0) + len(approved) >= 2:
                prop["manager_decision"] = "VETO: Max 2 daily alerts reached"
                continue
            if news_blocked:
                prop["manager_decision"] = f"VETO: High-Impact News ({news_msg})"
                continue
            if state.get("last_alert_bar_by_sym", {}).get(sym) == prop["closed_bar_ts"]:
                prop["manager_decision"] = "SKIP: Bar already alerted"
                continue
            if prop["proposed_dir"] == "NONE":
                prop["manager_decision"] = f"NO SIGNAL (BUY:{prop['buy_votes']}/15 | SELL:{prop['sell_votes']}/15)"
                continue

            agree_n = len(prop["agreed_strategies"])
            oppose_n = len(prop["opposed_strategies"])
            if agree_n < self.MIN_AGREE_STRATEGIES or (agree_n - oppose_n) < self.MIN_MARGIN_OVER_OPPOSE:
                prop["manager_decision"] = f"REJECTED: Weak consensus ({agree_n}/15 vs {oppose_n}/15 oppose)"
                continue
            if not prop["has_structural_trigger"]:
                prop["manager_decision"] = "REJECTED: No structural price-action/retest trigger"
                continue
            if prop["prev_candle_size"] > spec["max_candle"] or prop["cur_candle_size"] > spec["max_candle"] * 1.2:
                prop["manager_decision"] = "VETO: Volatility spike candle too large"
                continue
            if sym == "XAUUSD" and prop["day_move"] > 45.0:
                prop["manager_decision"] = f"VETO: Gold move exhausted (${prop['day_move']} > $45)"
                continue
            if prop["adx"] < 20.0:
                prop["manager_decision"] = f"REJECTED: Sideways/choppy market (ADX {prop['adx']} < 20)"
                continue

            # USD correlation guard: avoid stacking EURUSD & GBPUSD in the same direction on same scan
            if sym in ("EURUSD", "GBPUSD"):
                corr_key = f"FX_USD_{prop['proposed_dir']}"
                if corr_key in usd_dirs_taken:
                    prop["manager_decision"] = "VETO: Duplicate USD exposure with correlated FX pair"
                    continue
                usd_dirs_taken.add(corr_key)

            # Calculate safe FTM $25-risk lot size
            lot = self.lot_fn(sym, prop["sl_dist"])
            risk = round(lot * spec["contract_val"] * prop["sl_dist"])
            reward = round(risk * 2.0)
            digits = spec["digits"]
            clean_names = [s.split("_", 1)[1].replace("_", " ") for s in prop["agreed_strategies"]]

            tg_msg = (
                f"[MANAGER APPROVED] {sym} - {prop['proposed_dir']}\n"
                f"Agent: {prop['agent']} -> ManagerAgent ({agree_n}/15 Strategies | {prop['confidence_pct']:.0f}%)\n"
                f"Agreed: {', '.join(clean_names[:7])}\n"
                f"Entry: {prop['entry']:.{digits}f}\n"
                f"Stop Loss: {prop['sl']:.{digits}f}\n"
                f"TP1 (50% + Move SL to BE): {prop['tp1']:.{digits}f} (1:1)\n"
                f"TP2 (50% Final): {prop['tp2']:.{digits}f} (1:2)\n"
                f"Lot: {lot:.2f} | Risk: ${risk} | Reward: ${reward}\n"
                f"ADX: {prop['adx']} | RSI: {prop['rsi14']} | News: {news_msg}\n"
                f"Time: {bar_dt.strftime('%H:%M')} Algiers Time\n"
                "Confirm in MT5 manually. Trade duration must be > 5 minutes."
            )

            prop["lot"] = lot
            prop["risk_usd"] = risk
            prop["reward_usd"] = reward
            prop["telegram_message"] = tg_msg
            prop["manager_decision"] = f"APPROVED ({agree_n}/15 -> {prop['proposed_dir']})"
            approved.append(prop)

        return approved
