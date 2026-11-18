//+------------------------------------------------------------------+
//|                                             GoldLondonRetest.mq5 |
//|                        Personal MT5 Alert Indicator - XAUUSD M15 |
//|   Manual Execution Only - Built for FTM 2 Step Plus $5K Rules    |
//+------------------------------------------------------------------+
#property copyright "Personal Strategy - Gold London Retest (Algiers GMT+1)"
#property version   "1.00"
#property description "Alerts-only M15 Gold London Retest indicator for XAUUSD."
#property description "Respects FTM 2 Step Plus $5,000 rules. NEVER opens trades automatically."
#property indicator_chart_window
#property indicator_buffers 5
#property indicator_plots   4

//--- Plot 0: EMA 50
#property indicator_label1  "EMA 50"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrDodgerBlue
#property indicator_style1  STYLE_SOLID
#property indicator_width1  2

//--- Plot 1: BUY Signal Arrow
#property indicator_label2  "BUY Signal"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrLimeGreen
#property indicator_width2  3

//--- Plot 2: SELL Signal Arrow
#property indicator_label3  "SELL Signal"
#property indicator_type3   DRAW_ARROW
#property indicator_color3  clrOrangeRed
#property indicator_width3  3

//--- Plot 3: Breakout Candle Marker
#property indicator_label4  "Breakout Marker"
#property indicator_type4   DRAW_ARROW
#property indicator_color4  clrGold
#property indicator_width4  2

//--- Input Parameters
input group "=== 1. TELEGRAM CONNECTION (ALERT ONLY - NO AUTO TRADE) ==="
input string   InpTelegramBotToken       = "";       // Telegram Bot Token (from @BotFather)
input string   InpTelegramChatID         = "";       // Telegram Chat ID (from @userinfobot)
input bool     InpEnableTelegramAlerts   = true;     // Send Telegram Alerts
input bool     InpEnablePopupAlerts      = true;     // Show MT5 Popup/Sound Alerts
input bool     InpSendNoSetupAt1200      = true;     // Send "No valid setup today. No trade." at 12:00

input group "=== 2. ALGIERS TIMEZONE (GMT+1) & SESSION WINDOW ==="
input bool     InpAutoDetectAlgiersFromGMT = true;   // Auto-calculate Algiers (GMT+1) from TimeGMT()
input int      InpServerToAlgiersOffsetHrs = 0;      // Fallback offset (Algiers - Server) in Tester
input int      InpAsiaStartHour          = 0;        // Asia Range Start Hour (Algiers Time)
input int      InpAsiaEndHour            = 9;        // Asia Range End Hour (Algiers Time)
input int      InpTradeStartHour         = 9;        // London Window Start Hour (Algiers Time)
input int      InpTradeEndHour           = 12;       // London Window End Hour (Algiers Time)

input group "=== 3. STRATEGY PRESET & VOLATILITY SCALING ==="
input bool     InpUse2026VolatilityScaling = true;   // True = Calibrated 2026 Preset ($8-$65 Tokyo 01-07, Structural SL)
input double   InpMinAsiaRangeDollars    = 4.00;     // Min Asia Range Width ($) [Strict Default: $4.00]
input double   InpMaxAsiaRangeDollars    = 15.00;    // Max Asia Range Width ($) [Strict Default: $15.00]
input int      InpEmaPeriod              = 50;       // Trend EMA Period
input int      InpRsiPeriod              = 14;       // RSI Period
input double   InpRsiBuyMin              = 50.0;     // BUY RSI Min
input double   InpRsiBuyMax              = 65.0;     // BUY RSI Max
input double   InpRsiSellMin             = 35.0;     // SELL RSI Min
input double   InpRsiSellMax             = 50.0;     // SELL RSI Max

input group "=== 4. BREAKOUT, RETEST & LOSS FILTERS ==="
input double   InpMinBreakoutBodyDollars = 0.50;     // Min Breakout Candle Body Beyond Level ($)
input double   InpRetestToleranceDollars = 1.50;     // Max Distance Above/Below Level for Retest Touch ($)
input double   InpMinBodyToRangeRatio    = 0.25;     // Min Candle Body/Range Ratio (avoid doji spikes)
input double   InpMaxCandleSizeDollars   = 5.00;     // Max Pre-Entry & Signal Candle Size ($)
input double   InpMaxSpreadDollars       = 0.35;     // Max Allowed Spread on XAUUSD ($)
input bool     InpUseNativeNewsFilter    = true;     // Block +/- 60m around High-Impact USD News (MT5 Calendar)
input int      InpNewsBufferMinutes      = 60;       // News Buffer Before & After (Minutes)
input bool     InpManualNewsBlockToday   = false;    // Manual High-Impact News Override Today
input int      InpManualNewsHourAlgiers  = 14;       // Manual News Hour (Algiers Time, 24h)
input int      InpManualNewsMinuteAlgiers= 30;       // Manual News Minute (Algiers Time)

input group "=== 5. FTM 2 STEP PLUS $5K RISK MANAGEMENT (STRICT) ==="
input double   InpAccountSizeUSD         = 5000.0;   // FTM Challenge Account Size ($)
input double   InpRiskPerTradeUSD        = 25.0;     // Fixed Risk Per Trade (0.5% = $25.00)
input double   InpStopLossDollars        = 3.00;     // Stop Loss Distance ($) [Strict Default: $3.00]
input double   InpTakeProfitDollars      = 6.00;     // Take Profit Distance ($) [Strict Default: $6.00]
input double   InpBaseLotSize            = 0.08;     // Fixed Lot Size (0.08 for $3 SL / $25 Risk)
input int      InpMaxAlertsPerDay        = 2;        // Max Alerts Per Day
input int      InpMaxLossesPerDay        = 2;        // Stop After 2 Losses (-$50)
input double   InpDailyProfitStopUSD     = 80.0;     // Stop Trading for Day Above +$80 Profit
input double   InpFtmDailyLossLimitUSD   = 200.0;    // FTM Max Daily Drawdown (4% = $200)
input double   InpFtmStaticLossLimitUSD  = 500.0;    // FTM Max Overall Static Drawdown (10% = $500)

input group "=== 6. VISUAL DASHBOARD & LOGGING ==="
input bool     InpDrawDashboard          = true;     // Show FTM & Strategy Dashboard on Chart
input bool     InpShowRsiLabelsOnSignals = true;     // Annotate RSI(14) Value on Chart Arrows
input color    InpAsiaBoxColor           = C'25,38,58';   // Asia Session Box Fill
input color    InpLondonBoxColor         = C'20,45,35';   // London Window Box Fill
input color    InpAsiaHighColor          = clrAqua;       // Asia High Line Color
input color    InpAsiaLowColor           = clrDeepPink;   // Asia Low Line Color
input color    InpRetestZoneColor        = C'65,55,20';   // Retest Zone Highlight Color

//--- Indicator Buffers
double ExtEmaBuffer[];
double ExtBuyArrowBuffer[];
double ExtSellArrowBuffer[];
double ExtBreakoutBuffer[];
double ExtRsiCalcBuffer[];

//--- Indicator Handles
int    g_emaHandle = INVALID_HANDLE;
int    g_rsiHandle = INVALID_HANDLE;

//--- Prefix for Chart Objects
string g_objPrefix = "GLR_";

//--- Daily State (Live Alert & FTM Risk Tracking)
struct DailyState
{
   int      dayKey;                 // YYYYMMDD in Algiers Time
   double   asiaHigh;
   double   asiaLow;
   double   asiaWidth;
   bool     asiaReady;
   bool     asiaValid;
   bool     brokeUp;
   bool     brokeDown;
   int      alertsToday;
   int      lossesToday;
   int      winsToday;
   double   closedPnlToday;
   int      firstSignalDir;         // 1 = BUY, -1 = SELL, 0 = none
   int      firstSignalOutcome;     // 0 = pending/unknown, 1 = win, -1 = loss
   double   firstEntry;
   double   firstSL;
   double   firstTP;
   datetime firstSignalTime;
   bool     stoppedByTwoLosses;
   bool     stoppedByProfitCap;
   bool     sentTwoLossMsg;
   bool     sentNoSetupMsg;
   datetime lastAlertedBarTime;
   string   lastBlockReason;
};

DailyState g_today;
datetime   g_lastProcessedBar = 0;

//+------------------------------------------------------------------+
//| Helper: Check whether symbol matches XAUUSD / Gold               |
//+------------------------------------------------------------------+
bool IsGoldSymbol()
{
   string sym = _Symbol;
   StringToUpper(sym);
   return (StringFind(sym, "XAU") >= 0 || StringFind(sym, "GOLD") >= 0);
}

//+------------------------------------------------------------------+
//| Helper: Compute offset (Algiers GMT+1 minus Broker Server Time)  |
//+------------------------------------------------------------------+
int GetServerToAlgiersOffsetSeconds()
{
   if(InpAutoDetectAlgiersFromGMT && !MQLInfoInteger(MQL_TESTER))
   {
      datetime gmtNow = TimeGMT();
      datetime srvNow = TimeCurrent();
      if(gmtNow > 0 && srvNow > 0)
      {
         long rawDiff = (long)gmtNow - (long)srvNow;
         // Round to nearest 15-minute (900s) timezone boundary + 3600s for GMT+1
         long gmtToSrvRounded = (long)MathRound((double)rawDiff / 900.0) * 900;
         return (int)(gmtToSrvRounded + 3600);
      }
   }
   return InpServerToAlgiersOffsetHrs * 3600;
}

//+------------------------------------------------------------------+
//| Helper: Convert Server datetime -> Algiers (GMT+1) datetime      |
//+------------------------------------------------------------------+
datetime ServerToAlgiers(const datetime serverTime)
{
   return serverTime + GetServerToAlgiersOffsetSeconds();
}

//+------------------------------------------------------------------+
//| Helper: Get YYYYMMDD integer key from Algiers datetime           |
//+------------------------------------------------------------------+
int GetAlgiersDayKey(const datetime algiersTime)
{
   MqlDateTime dt;
   TimeToStruct(algiersTime, dt);
   return dt.year * 10000 + dt.mon * 100 + dt.day;
}

//+------------------------------------------------------------------+
//| Helper: Get effective strategy parameters (Strict vs 2026 Preset)|
//+------------------------------------------------------------------+
void GetEffectiveParams(int &asiaStartH, int &asiaEndH,
                        double &minAsiaW, double &maxAsiaW,
                        double &maxCandle, double &retestTol,
                        double &rsiBuyMax, double &rsiSellMin,
                        bool &useStructuralSL)
{
   if(!InpUse2026VolatilityScaling)
   {
      asiaStartH      = InpAsiaStartHour;
      asiaEndH        = InpAsiaEndHour;
      minAsiaW        = InpMinAsiaRangeDollars;
      maxAsiaW        = InpMaxAsiaRangeDollars;
      maxCandle       = InpMaxCandleSizeDollars;
      retestTol       = InpRetestToleranceDollars;
      rsiBuyMax       = InpRsiBuyMax;
      rsiSellMin      = InpRsiSellMin;
      useStructuralSL = false;
   }
   else
   {
      // Calibrated 2026 Gold Volatility Preset (strictly $25 risk, 1:2 RR, 09:00-12:00 Algiers)
      asiaStartH      = 1;     // Core Tokyo Range 01:00 - 07:00 Algiers
      asiaEndH        = 7;
      minAsiaW        = 8.0;
      maxAsiaW        = 65.0;
      maxCandle       = 10.0;
      retestTol       = 3.50;
      rsiBuyMax       = 68.0;
      rsiSellMin      = 32.0;
      useStructuralSL = true;
   }
}

//+------------------------------------------------------------------+
//| Helper: Calculate Lot Size keeping Risk strictly <= $25.00       |
//+------------------------------------------------------------------+
double CalculateSafeLotSize(const double slDollars)
{
   if(!InpUse2026VolatilityScaling)
      return InpBaseLotSize;

   if(slDollars <= 0.0)
      return InpBaseLotSize;

   // On standard XAUUSD (100 oz contract): $1 move at 0.01 lot = $1.00
   // Risk = Lot * 100 * slDollars  => Lot = Risk / (100 * slDollars)
   double rawLot = InpRiskPerTradeUSD / (100.0 * slDollars);
   double stepped = MathFloor(rawLot / 0.01) * 0.01;
   if(stepped < 0.01) stepped = 0.01;
   if(stepped > InpBaseLotSize) stepped = InpBaseLotSize; // Never exceed 0.08 lot
   return NormalizeDouble(stepped, 2);
}

//+------------------------------------------------------------------+
//| Helper: Reset daily state for a new Algiers day                  |
//+------------------------------------------------------------------+
void ResetDailyState(const int newDayKey)
{
   g_today.dayKey             = newDayKey;
   g_today.asiaHigh           = 0.0;
   g_today.asiaLow            = 0.0;
   g_today.asiaWidth          = 0.0;
   g_today.asiaReady          = false;
   g_today.asiaValid          = false;
   g_today.brokeUp            = false;
   g_today.brokeDown          = false;
   g_today.alertsToday        = 0;
   g_today.lossesToday        = 0;
   g_today.winsToday          = 0;
   g_today.closedPnlToday     = 0.0;
   g_today.firstSignalDir     = 0;
   g_today.firstSignalOutcome = 0;
   g_today.firstEntry         = 0.0;
   g_today.firstSL            = 0.0;
   g_today.firstTP            = 0.0;
   g_today.firstSignalTime    = 0;
   g_today.stoppedByTwoLosses = false;
   g_today.stoppedByProfitCap = false;
   g_today.sentTwoLossMsg     = false;
   g_today.sentNoSetupMsg     = false;
   g_today.lastAlertedBarTime = 0;
   g_today.lastBlockReason    = "Waiting for setup";
}

//+------------------------------------------------------------------+
//| Helper: Compute Today's Manual Closed Trades from MT5 History    |
//+------------------------------------------------------------------+
void UpdateTodayManualPerformance(const datetime nowServer, const int offsetSec)
{
   datetime nowAlgiers = nowServer + offsetSec;
   MqlDateTime dtAlg;
   TimeToStruct(nowAlgiers, dtAlg);
   dtAlg.hour = 0; dtAlg.min = 0; dtAlg.sec = 0;
   datetime algiersMidnightServer = StructToTime(dtAlg) - offsetSec;

   if(!HistorySelect(algiersMidnightServer, nowServer + 60))
      return;

   int deals = HistoryDealsTotal();
   int closedLosses = 0;
   int closedWins   = 0;
   double netPnl    = 0.0;

   for(int i = 0; i < deals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;

      string sym = HistoryDealGetString(ticket, DEAL_SYMBOL);
      if(sym != _Symbol) continue;

      ENUM_DEAL_ENTRY entryType = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(entryType != DEAL_ENTRY_OUT && entryType != DEAL_ENTRY_INOUT)
         continue;

      double pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                 + HistoryDealGetDouble(ticket, DEAL_SWAP)
                 + HistoryDealGetDouble(ticket, DEAL_COMMISSION);

      netPnl += pnl;
      if(pnl < -0.5)
         closedLosses++;
      else if(pnl > 0.5)
         closedWins++;
   }

   // Also check simulated outcome of Alert #1 if user hasn't closed a manual deal yet
   int simLosses = 0;
   if(g_today.firstSignalDir != 0 && g_today.firstSignalOutcome == 0)
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(g_today.firstSignalDir == 1)
      {
         if(bid <= g_today.firstSL) g_today.firstSignalOutcome = -1;
         else if(bid >= g_today.firstTP) g_today.firstSignalOutcome = 1;
      }
      else if(g_today.firstSignalDir == -1)
      {
         if(ask >= g_today.firstSL) g_today.firstSignalOutcome = -1;
         else if(ask <= g_today.firstTP) g_today.firstSignalOutcome = 1;
      }
   }

   if(closedLosses == 0 && g_today.firstSignalOutcome == -1)
      simLosses = 1;

   g_today.lossesToday    = MathMax(closedLosses, simLosses);
   g_today.winsToday      = closedWins;
   g_today.closedPnlToday = netPnl;

   if(g_today.lossesToday >= InpMaxLossesPerDay || netPnl <= -50.0)
      g_today.stoppedByTwoLosses = true;

   if(netPnl >= InpDailyProfitStopUSD)
      g_today.stoppedByProfitCap = true;
}

//+------------------------------------------------------------------+
//| Helper: Check High-Impact USD News within +/- Buffer Minutes     |
//+------------------------------------------------------------------+
bool IsHighImpactNewsWindow(const datetime nowServer, const datetime nowAlgiers, string &newsTitleOut)
{
   newsTitleOut = "No News";

   // 1. Check Manual News Override
   if(InpManualNewsBlockToday)
   {
      MqlDateTime dt;
      TimeToStruct(nowAlgiers, dt);
      int curMins  = dt.hour * 60 + dt.min;
      int newsMins = InpManualNewsHourAlgiers * 60 + InpManualNewsMinuteAlgiers;
      if(MathAbs(curMins - newsMins) <= InpNewsBufferMinutes)
      {
         newsTitleOut = StringFormat("Manual USD News Block (%02d:%02d)", InpManualNewsHourAlgiers, InpManualNewsMinuteAlgiers);
         return true;
      }
   }

   // 2. Check MT5 Built-in Economic Calendar (live mode only)
   if(!InpUseNativeNewsFilter || MQLInfoInteger(MQL_TESTER))
      return false;

   MqlCalendarValue values[];
   datetime fromTime = nowServer - InpNewsBufferMinutes * 60;
   datetime toTime   = nowServer + InpNewsBufferMinutes * 60;

   ResetLastError();
   int count = CalendarValueHistory(values, fromTime, toTime, NULL, "USD");
   if(count <= 0)
      return false;

   for(int i = 0; i < count; i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;

      bool isHigh = (ev.importance == CALENDAR_IMPORTANCE_HIGH);
      string nameUpper = ev.name;
      StringToUpper(nameUpper);

      bool isKeyGoldDriver = (StringFind(nameUpper, "CPI") >= 0
                           || StringFind(nameUpper, "NON-FARM") >= 0
                           || StringFind(nameUpper, "NONFARM") >= 0
                           || StringFind(nameUpper, "NFP") >= 0
                           || StringFind(nameUpper, "FOMC") >= 0
                           || StringFind(nameUpper, "FED ") >= 0
                           || StringFind(nameUpper, "INTEREST RATE") >= 0
                           || StringFind(nameUpper, "POWELL") >= 0
                           || StringFind(nameUpper, "PPI") >= 0
                           || StringFind(nameUpper, "GDP") >= 0
                           || StringFind(nameUpper, "PCE") >= 0
                           || StringFind(nameUpper, "GOLD") >= 0);

      if(isHigh || isKeyGoldDriver)
      {
         newsTitleOut = "USD News: " + ev.name;
         return true;
      }
   }

   return false;
}

//+------------------------------------------------------------------+
//| Helper: Send Message to Telegram via WebRequest                  |
//+------------------------------------------------------------------+
bool SendTelegramMessage(const string text)
{
   if(!InpEnableTelegramAlerts)
      return false;

   if(StringLen(InpTelegramBotToken) < 10 || StringLen(InpTelegramChatID) < 2)
   {
      Print("[GoldLondonRetest] Telegram Token or Chat ID not set yet. Message queued in log:\n", text);
      return false;
   }

   if(MQLInfoInteger(MQL_TESTER))
      return false;

   string url = "https://api.telegram.org/bot" + InpTelegramBotToken + "/sendMessage";

   // Escape JSON special characters safely
   string escaped = text;
   StringReplace(escaped, "\\", "\\\\");
   StringReplace(escaped, "\"", "\\\"");
   StringReplace(escaped, "\r", "");
   StringReplace(escaped, "\n", "\\n");

   string payload = "{\"chat_id\":\"" + InpTelegramChatID + "\",\"text\":\"" + escaped + "\"}";

   char postData[];
   char resultData[];
   string resultHeaders;
   int len = StringToCharArray(payload, postData, 0, WHOLE_ARRAY, CP_UTF8);
   if(len > 0)
      ArrayResize(postData, len - 1); // Strip trailing null terminator

   string headers = "Content-Type: application/json\r\n";
   ResetLastError();
   int res = WebRequest("POST", url, headers, 5000, postData, resultData, resultHeaders);
   if(res == 200)
   {
      Print("[GoldLondonRetest] Telegram alert delivered successfully.");
      return true;
   }

   int err = GetLastError();
   PrintFormat("[GoldLondonRetest] Telegram WebRequest failed. HTTP=%d Error=%d. Add https://api.telegram.org to MT5 Options -> Expert Advisors -> Allow WebRequest.", res, err);
   return false;
}

//+------------------------------------------------------------------+
//| Helper: Append Signal or Daily Summary to CSV for Database Sync  |
//+------------------------------------------------------------------+
void LogEventToCsv(const string eventType, const string direction,
                   const double entry, const double sl, const double tp,
                   const double lot, const double rsiVal, const double emaVal,
                   const double spreadVal, const string note)
{
   string fileName = "GoldLondonRetest_Signals.csv";
   bool exists = FileIsExist(fileName);
   int handle = FileOpen(fileName, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
      return;

   if(!exists)
      FileWrite(handle, "AlgiersTime", "Symbol", "EventType", "Direction", "Entry", "StopLoss", "TakeProfit", "Lot", "RSI14", "EMA50", "Spread", "AsiaHigh", "AsiaLow", "Note");
   else
      FileSeek(handle, 0, SEEK_END);

   string timeStr = TimeToString(ServerToAlgiers(TimeCurrent()), TIME_DATE | TIME_MINUTES);
   FileWrite(handle, timeStr, _Symbol, eventType, direction,
             DoubleToString(entry, 2), DoubleToString(sl, 2), DoubleToString(tp, 2),
             DoubleToString(lot, 2), DoubleToString(rsiVal, 2), DoubleToString(emaVal, 2),
             DoubleToString(spreadVal, 2), DoubleToString(g_today.asiaHigh, 2),
             DoubleToString(g_today.asiaLow, 2), note);
   FileClose(handle);
}

//+------------------------------------------------------------------+
//| Helper: Draw / Update Session Boxes & Horizontal Lines           |
//+------------------------------------------------------------------+
void DrawSessionVisuals(const int dayKey, const datetime asiaStartSrv, const datetime asiaEndSrv,
                        const datetime londonStartSrv, const datetime londonEndSrv,
                        const double asiaH, const double asiaL, const bool isValid)
{
   string keyStr = IntegerToString(dayKey);

   // 1. Asia Range Box
   string boxName = g_objPrefix + "AsiaBox_" + keyStr;
   if(ObjectFind(0, boxName) < 0)
      ObjectCreate(0, boxName, OBJ_RECTANGLE, 0, asiaStartSrv, asiaH, asiaEndSrv, asiaL);
   else
   {
      ObjectSetInteger(0, boxName, OBJPROP_TIME, 0, asiaStartSrv);
      ObjectSetDouble(0, boxName, OBJPROP_PRICE, 0, asiaH);
      ObjectSetInteger(0, boxName, OBJPROP_TIME, 1, asiaEndSrv);
      ObjectSetDouble(0, boxName, OBJPROP_PRICE, 1, asiaL);
   }
   ObjectSetInteger(0, boxName, OBJPROP_COLOR, InpAsiaBoxColor);
   ObjectSetInteger(0, boxName, OBJPROP_FILL, true);
   ObjectSetInteger(0, boxName, OBJPROP_BACK, true);
   ObjectSetInteger(0, boxName, OBJPROP_SELECTABLE, false);

   // 2. London Trading Window Highlight Box
   string lonName = g_objPrefix + "LondonBox_" + keyStr;
   double pad = 2.0;
   if(ObjectFind(0, lonName) < 0)
      ObjectCreate(0, lonName, OBJ_RECTANGLE, 0, londonStartSrv, asiaH + pad, londonEndSrv, asiaL - pad);
   else
   {
      ObjectSetInteger(0, lonName, OBJPROP_TIME, 0, londonStartSrv);
      ObjectSetDouble(0, lonName, OBJPROP_PRICE, 0, asiaH + pad);
      ObjectSetInteger(0, lonName, OBJPROP_TIME, 1, londonEndSrv);
      ObjectSetDouble(0, lonName, OBJPROP_PRICE, 1, asiaL - pad);
   }
   ObjectSetInteger(0, lonName, OBJPROP_COLOR, isValid ? InpLondonBoxColor : C'45,25,25');
   ObjectSetInteger(0, lonName, OBJPROP_FILL, true);
   ObjectSetInteger(0, lonName, OBJPROP_BACK, true);
   ObjectSetInteger(0, lonName, OBJPROP_SELECTABLE, false);

   // 3. Asia High & Low Lines extended across London Window (09:00-12:00)
   string hiLine = g_objPrefix + "AsiaHigh_" + keyStr;
   if(ObjectFind(0, hiLine) < 0)
      ObjectCreate(0, hiLine, OBJ_TREND, 0, asiaStartSrv, asiaH, londonEndSrv, asiaH);
   else
   {
      ObjectSetInteger(0, hiLine, OBJPROP_TIME, 0, asiaStartSrv);
      ObjectSetDouble(0, hiLine, OBJPROP_PRICE, 0, asiaH);
      ObjectSetInteger(0, hiLine, OBJPROP_TIME, 1, londonEndSrv);
      ObjectSetDouble(0, hiLine, OBJPROP_PRICE, 1, asiaH);
   }
   ObjectSetInteger(0, hiLine, OBJPROP_COLOR, InpAsiaHighColor);
   ObjectSetInteger(0, hiLine, OBJPROP_STYLE, isValid ? STYLE_SOLID : STYLE_DOT);
   ObjectSetInteger(0, hiLine, OBJPROP_WIDTH, isValid ? 2 : 1);
   ObjectSetInteger(0, hiLine, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, hiLine, OBJPROP_SELECTABLE, false);

   string loLine = g_objPrefix + "AsiaLow_" + keyStr;
   if(ObjectFind(0, loLine) < 0)
      ObjectCreate(0, loLine, OBJ_TREND, 0, asiaStartSrv, asiaL, londonEndSrv, asiaL);
   else
   {
      ObjectSetInteger(0, loLine, OBJPROP_TIME, 0, asiaStartSrv);
      ObjectSetDouble(0, loLine, OBJPROP_PRICE, 0, asiaL);
      ObjectSetInteger(0, loLine, OBJPROP_TIME, 1, londonEndSrv);
      ObjectSetDouble(0, loLine, OBJPROP_PRICE, 1, asiaL);
   }
   ObjectSetInteger(0, loLine, OBJPROP_COLOR, InpAsiaLowColor);
   ObjectSetInteger(0, loLine, OBJPROP_STYLE, isValid ? STYLE_SOLID : STYLE_DOT);
   ObjectSetInteger(0, loLine, OBJPROP_WIDTH, isValid ? 2 : 1);
   ObjectSetInteger(0, loLine, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, loLine, OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
//| Helper: Highlight Retest Zone and Optional RSI Chart Label       |
//+------------------------------------------------------------------+
void DrawRetestMarker(const datetime barTime, const double levelPrice,
                      const double tolDollars, const bool isBuy, const double rsiVal)
{
   string tag = TimeToString(barTime, TIME_DATE | TIME_MINUTES);
   StringReplace(tag, ":", "");
   StringReplace(tag, " ", "_");

   string zoneName = g_objPrefix + "RetestZone_" + tag;
   if(ObjectFind(0, zoneName) < 0)
   {
      ObjectCreate(0, zoneName, OBJ_RECTANGLE, 0,
                   barTime - PeriodSeconds(PERIOD_M15), levelPrice + tolDollars,
                   barTime + PeriodSeconds(PERIOD_M15) * 2, levelPrice - tolDollars);
      ObjectSetInteger(0, zoneName, OBJPROP_COLOR, InpRetestZoneColor);
      ObjectSetInteger(0, zoneName, OBJPROP_FILL, true);
      ObjectSetInteger(0, zoneName, OBJPROP_BACK, true);
      ObjectSetInteger(0, zoneName, OBJPROP_SELECTABLE, false);
   }

   if(InpShowRsiLabelsOnSignals)
   {
      string lblName = g_objPrefix + "RSI_" + tag;
      if(ObjectFind(0, lblName) < 0)
      {
         double anchorPrice = isBuy ? (levelPrice - tolDollars - 1.2) : (levelPrice + tolDollars + 1.2);
         ObjectCreate(0, lblName, OBJ_TEXT, 0, barTime, anchorPrice);
         ObjectSetString(0, lblName, OBJPROP_TEXT, StringFormat("%s RSI:%.1f", isBuy ? "BUY" : "SELL", rsiVal));
         ObjectSetInteger(0, lblName, OBJPROP_COLOR, isBuy ? clrLimeGreen : clrOrangeRed);
         ObjectSetInteger(0, lblName, OBJPROP_FONTSIZE, 8);
         ObjectSetString(0, lblName, OBJPROP_FONT, "Consolas");
         ObjectSetInteger(0, lblName, OBJPROP_SELECTABLE, false);
      }
   }
}

//+------------------------------------------------------------------+
//| Helper: Set Label on Dashboard                                   |
//+------------------------------------------------------------------+
void SetDashLabel(const string id, const int x, const int y, const string text,
                  const color clr, const int fontSize = 9, const bool bold = false)
{
   string name = g_objPrefix + "Dash_" + id;
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_RIGHT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontSize);
   ObjectSetString(0, name, OBJPROP_FONT, bold ? "Consolas Bold" : "Consolas");
}

//+------------------------------------------------------------------+
//| Helper: Update On-Chart FTM & Strategy Dashboard                 |
//+------------------------------------------------------------------+
void UpdateDashboard(const datetime nowAlgiers, const double curEma, const double curRsi,
                     const double curSpread, const double prevCandleSize, const string newsText)
{
   if(!InpDrawDashboard)
      return;

   string bgName = g_objPrefix + "Dash_BG";
   if(ObjectFind(0, bgName) < 0)
   {
      ObjectCreate(0, bgName, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, bgName, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
      ObjectSetInteger(0, bgName, OBJPROP_XDISTANCE, 12);
      ObjectSetInteger(0, bgName, OBJPROP_YDISTANCE, 18);
      ObjectSetInteger(0, bgName, OBJPROP_XSIZE, 385);
      ObjectSetInteger(0, bgName, OBJPROP_YSIZE, 275);
      ObjectSetInteger(0, bgName, OBJPROP_BGCOLOR, C'14,18,26');
      ObjectSetInteger(0, bgName, OBJPROP_BORDER_TYPE, BORDER_FLAT);
      ObjectSetInteger(0, bgName, OBJPROP_BORDER_COLOR, C'45,62,88');
      ObjectSetInteger(0, bgName, OBJPROP_SELECTABLE, false);
   }

   MqlDateTime dt;
   TimeToStruct(nowAlgiers, dt);
   bool isWeekday = (dt.day_of_week >= 1 && dt.day_of_week <= 5);
   bool inWindow  = (isWeekday && dt.hour >= InpTradeStartHour && dt.hour < InpTradeEndHour);

   string sessLabel = !isWeekday ? "WEEKEND (NO TRADE)"
                    : (inWindow ? "LONDON OPEN ACTIVE (09:00-12:00)"
                    : (dt.hour < InpTradeStartHour ? "ASIA RANGE BUILDING" : "OUTSIDE WINDOW (LOCKED)"));
   color sessClr = inWindow ? clrLimeGreen : clrSilver;

   int aS, aE; double minW, maxW, maxC, tol, rMax, rMin; bool sSL;
   GetEffectiveParams(aS, aE, minW, maxW, maxC, tol, rMax, rMin, sSL);

   string rangeTxt = !g_today.asiaReady ? "Building..."
                   : StringFormat("H:%.2f L:%.2f (W:$%.2f) [%s]",
                                  g_today.asiaHigh, g_today.asiaLow, g_today.asiaWidth,
                                  g_today.asiaValid ? "VALID" : "SKIP");
   color rangeClr  = (!g_today.asiaReady) ? clrSilver : (g_today.asiaValid ? clrAqua : clrOrange);

   string riskTxt = "ACTIVE";
   color  riskClr = clrLimeGreen;
   if(g_today.stoppedByTwoLosses) { riskTxt = "STOPPED: 2 LOSSES (-$50)"; riskClr = clrTomato; }
   else if(g_today.stoppedByProfitCap) { riskTxt = "STOPPED: +$80 CAP HIT"; riskClr = clrGold; }
   else if(g_today.alertsToday >= InpMaxAlertsPerDay) { riskTxt = "MAX 2 ALERTS REACHED"; riskClr = clrOrange; }

   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double ddLeft = bal - (InpAccountSizeUSD - InpFtmStaticLossLimitUSD);

   int x = 24;
   SetDashLabel("L01", x, 26,  "GOLD LONDON RETEST | FTM 2-STEP+ $5K", clrGold, 10, true);
   SetDashLabel("L02", x, 46,  "Algiers (GMT+1): " + TimeToString(nowAlgiers, TIME_DATE | TIME_MINUTES), clrWhite, 9);
   SetDashLabel("L03", x, 64,  "Session: " + sessLabel, sessClr, 9, true);
   SetDashLabel("L04", x, 84,  StringFormat("Preset: %s (%02d-%02d Asia)", InpUse2026VolatilityScaling ? "2026 Vol-Scaled" : "Strict Original", aS, aE), clrLightSkyBlue, 9);
   SetDashLabel("L05", x, 102, "Asia: " + rangeTxt, rangeClr, 9);
   SetDashLabel("L06", x, 122, StringFormat("EMA50: %.2f | RSI(14): %.1f", curEma, curRsi), clrWhite, 9);
   SetDashLabel("L07", x, 140, StringFormat("Spread: $%.2f (Max $%.2f) | PrevBar: $%.2f", curSpread, InpMaxSpreadDollars, prevCandleSize),
                (curSpread <= InpMaxSpreadDollars && prevCandleSize <= maxC) ? clrLightGreen : clrTomato, 9);
   SetDashLabel("L08", x, 158, "News (+/-60m): " + newsText, (newsText == "No News") ? clrLightGreen : clrTomato, 9);
   SetDashLabel("L09", x, 178, StringFormat("Alerts Today: %d/%d | Losses: %d/2 | PnL: $%.2f",
                g_today.alertsToday, InpMaxAlertsPerDay, g_today.lossesToday, g_today.closedPnlToday), clrWhite, 9);
   SetDashLabel("L10", x, 198, "Daily Status: " + riskTxt, riskClr, 9, true);
   SetDashLabel("L11", x, 218, "Filter State: " + g_today.lastBlockReason, clrSilver, 8);
   SetDashLabel("L12", x, 240, StringFormat("FTM Limits: Daily -$%.0f | Static Floor $%.0f (+$%.0f left)",
                InpFtmDailyLossLimitUSD, InpAccountSizeUSD - InpFtmStaticLossLimitUSD, ddLeft), clrSilver, 8);
   SetDashLabel("L13", x, 258, "MANUAL ENTRY ONLY - Trade Duration > 5 min", clrAqua, 8, true);
}

//+------------------------------------------------------------------+
//| Indicator Initialization                                         |
//+------------------------------------------------------------------+
int OnInit()
{
   if(_Period != PERIOD_M15)
      Alert("[GoldLondonRetest] Please attach this indicator to the XAUUSD M15 chart ONLY!");

   if(!IsGoldSymbol())
      Print("[GoldLondonRetest] Warning: Current symbol is ", _Symbol, ". Designed for XAUUSD (Gold).");

   SetIndexBuffer(0, ExtEmaBuffer, INDICATOR_DATA);
   SetIndexBuffer(1, ExtBuyArrowBuffer, INDICATOR_DATA);
   SetIndexBuffer(2, ExtSellArrowBuffer, INDICATOR_DATA);
   SetIndexBuffer(3, ExtBreakoutBuffer, INDICATOR_DATA);
   SetIndexBuffer(4, ExtRsiCalcBuffer, INDICATOR_CALCULATIONS);

   ArraySetAsSeries(ExtEmaBuffer, false);
   ArraySetAsSeries(ExtBuyArrowBuffer, false);
   ArraySetAsSeries(ExtSellArrowBuffer, false);
   ArraySetAsSeries(ExtBreakoutBuffer, false);
   ArraySetAsSeries(ExtRsiCalcBuffer, false);

   PlotIndexSetInteger(1, PLOT_ARROW, 233); // Up arrow
   PlotIndexSetInteger(2, PLOT_ARROW, 234); // Down arrow
   PlotIndexSetInteger(3, PLOT_ARROW, 159); // Breakout dot

   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetDouble(2, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetDouble(3, PLOT_EMPTY_VALUE, EMPTY_VALUE);

   IndicatorSetString(INDICATOR_SHORTNAME, "Gold London Retest (M15 Algiers GMT+1)");
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);

   g_emaHandle = iMA(_Symbol, PERIOD_M15, InpEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   g_rsiHandle = iRSI(_Symbol, PERIOD_M15, InpRsiPeriod, PRICE_CLOSE);

   if(g_emaHandle == INVALID_HANDLE || g_rsiHandle == INVALID_HANDLE)
   {
      Print("[GoldLondonRetest] Failed to create EMA50 or RSI14 indicator handle.");
      return INIT_FAILED;
   }

   ResetDailyState(GetAlgiersDayKey(ServerToAlgiers(TimeCurrent())));
   g_lastProcessedBar = 0;

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Indicator Deinitialization                                       |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_emaHandle != INVALID_HANDLE) IndicatorRelease(g_emaHandle);
   if(g_rsiHandle != INVALID_HANDLE) IndicatorRelease(g_rsiHandle);

   ObjectsDeleteAll(0, g_objPrefix);
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Main Indicator Calculation                                       |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(rates_total < MathMax(InpEmaPeriod, InpRsiPeriod) + 10)
      return 0;

   // Ensure input arrays are indexed chronologically (0 = oldest, rates_total-1 = current)
   ArraySetAsSeries(time, false);
   ArraySetAsSeries(open, false);
   ArraySetAsSeries(high, false);
   ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false);

   int copiedEma = CopyBuffer(g_emaHandle, 0, 0, rates_total, ExtEmaBuffer);
   int copiedRsi = CopyBuffer(g_rsiHandle, 0, 0, rates_total, ExtRsiCalcBuffer);
   if(copiedEma <= 0 || copiedRsi <= 0)
      return 0;

   // Initialize newly added arrow buffer slots to EMPTY_VALUE
   int startIdx = (prev_calculated <= 0) ? InpEmaPeriod : (prev_calculated - 1);
   if(startIdx < InpEmaPeriod) startIdx = InpEmaPeriod;

   if(prev_calculated == 0)
   {
      ArrayInitialize(ExtBuyArrowBuffer, EMPTY_VALUE);
      ArrayInitialize(ExtSellArrowBuffer, EMPTY_VALUE);
      ArrayInitialize(ExtBreakoutBuffer, EMPTY_VALUE);
   }
   else
   {
      for(int k = startIdx; k < rates_total; k++)
      {
         ExtBuyArrowBuffer[k]  = EMPTY_VALUE;
         ExtSellArrowBuffer[k] = EMPTY_VALUE;
         ExtBreakoutBuffer[k]  = EMPTY_VALUE;
      }
   }

   int offsetSec = GetServerToAlgiersOffsetSeconds();
   int aStartH, aEndH;
   double minAsiaW, maxAsiaW, maxCandle, retestTol, rsiBuyMax, rsiSellMin;
   bool useStructuralSL;
   GetEffectiveParams(aStartH, aEndH, minAsiaW, maxAsiaW, maxCandle, retestTol, rsiBuyMax, rsiSellMin, useStructuralSL);

   //--- 1. Historical & Visual Replay Pass (Draws Asia boxes, EMA, Breakout & Retest Arrows)
   int curDay = -1;
   double dAsiaH = -DBL_MAX, dAsiaL = DBL_MAX;
   int dAsiaBars = 0;
   bool dAsiaValid = false;
   bool dBrokeUp = false, dBrokeDn = false;
   int dTrades = 0;
   datetime dAsiaStartSrv = 0, dAsiaEndSrv = 0, dLonStartSrv = 0, dLonEndSrv = 0;

   // On incremental ticks, scan back at least 120 bars (~30 hours) so day context is accurate
   int scanStart = (prev_calculated == 0) ? InpEmaPeriod : MathMax(InpEmaPeriod, rates_total - 120);

   for(int i = scanStart; i < rates_total - 1; i++)
   {
      datetime algTime = time[i] + offsetSec;
      MqlDateTime dt;
      TimeToStruct(algTime, dt);
      int dKey = dt.year * 10000 + dt.mon * 100 + dt.day;

      if(dKey != curDay)
      {
         curDay = dKey;
         dAsiaH = -DBL_MAX;
         dAsiaL = DBL_MAX;
         dAsiaBars = 0;
         dAsiaValid = false;
         dBrokeUp = false;
         dBrokeDn = false;
         dTrades = 0;

         MqlDateTime dtTmp = dt;
         dtTmp.hour = aStartH; dtTmp.min = 0; dtTmp.sec = 0;
         dAsiaStartSrv = StructToTime(dtTmp) - offsetSec;
         dtTmp.hour = aEndH;
         dAsiaEndSrv = StructToTime(dtTmp) - offsetSec;
         dtTmp.hour = InpTradeStartHour;
         dLonStartSrv = StructToTime(dtTmp) - offsetSec;
         dtTmp.hour = InpTradeEndHour;
         dLonEndSrv = StructToTime(dtTmp) - offsetSec;
      }

      if(dt.day_of_week == 0 || dt.day_of_week == 6)
         continue;

      // Accumulate Asia Session High/Low
      if(dt.hour >= aStartH && dt.hour < aEndH)
      {
         if(high[i] > dAsiaH) dAsiaH = high[i];
         if(low[i] < dAsiaL)  dAsiaL = low[i];
         dAsiaBars++;
         if(dAsiaBars >= 6)
         {
            double w = dAsiaH - dAsiaL;
            dAsiaValid = (w >= minAsiaW && w <= maxAsiaW);
            DrawSessionVisuals(dKey, dAsiaStartSrv, dAsiaEndSrv, dLonStartSrv, dLonEndSrv, dAsiaH, dAsiaL, dAsiaValid);
         }
         continue;
      }

      if(!dAsiaValid || dAsiaBars < 6 || dt.hour < aEndH || dt.hour >= InpTradeEndHour)
         continue;

      // Check for strong M15 Breakout Close
      double body = MathAbs(close[i] - open[i]);
      if(!dBrokeUp && close[i] > dAsiaH && (close[i] - open[i]) >= InpMinBreakoutBodyDollars)
      {
         dBrokeUp = true;
         ExtBreakoutBuffer[i] = low[i] - 0.8;
      }
      else if(!dBrokeDn && close[i] < dAsiaL && (open[i] - close[i]) >= InpMinBreakoutBodyDollars)
      {
         dBrokeDn = true;
         ExtBreakoutBuffer[i] = high[i] + 0.8;
      }

      // Entry evaluation strictly inside London Window (09:00 - 12:00 Algiers Time)
      if(dt.hour < InpTradeStartHour || dt.hour >= InpTradeEndHour || dTrades >= InpMaxAlertsPerDay)
         continue;

      if(i < 2) continue;
      double prevCandleSize = high[i - 1] - low[i - 1];
      double curCandleRange = high[i] - low[i];
      if(prevCandleSize > maxCandle || curCandleRange <= 0.0 || curCandleRange > maxCandle * 1.2)
         continue;

      if(body / curCandleRange < InpMinBodyToRangeRatio)
         continue;

      double emaVal = ExtEmaBuffer[i];
      double rsiVal = ExtRsiCalcBuffer[i];

      // BUY Retest Check
      if(dBrokeUp
         && low[i] <= dAsiaH + retestTol && low[i] >= dAsiaH - (useStructuralSL ? 3.5 : InpStopLossDollars * 0.7)
         && close[i] > dAsiaH
         && close[i] > open[i]
         && emaVal < close[i]
         && rsiVal >= InpRsiBuyMin && rsiVal <= rsiBuyMax)
      {
         ExtBuyArrowBuffer[i] = low[i] - 1.0;
         DrawRetestMarker(time[i], dAsiaH, retestTol, true, rsiVal);
         dTrades++;
         dBrokeUp = false;
      }
      // SELL Retest Check
      else if(dBrokeDn
              && high[i] >= dAsiaL - retestTol && high[i] <= dAsiaL + (useStructuralSL ? 3.5 : InpStopLossDollars * 0.7)
              && close[i] < dAsiaL
              && close[i] < open[i]
              && emaVal > close[i]
              && rsiVal >= rsiSellMin && rsiVal <= InpRsiSellMax)
      {
         ExtSellArrowBuffer[i] = high[i] + 1.0;
         DrawRetestMarker(time[i], dAsiaL, retestTol, false, rsiVal);
         dTrades++;
         dBrokeDn = false;
      }
   }

   //--- 2. Live Session State & Alert Trigger on Newly Closed M15 Bar
   int lastClosed = rates_total - 2;
   int liveBar    = rates_total - 1;
   datetime nowServer  = TimeCurrent();
   datetime nowAlgiers = ServerToAlgiers(nowServer);
   int liveDayKey      = GetAlgiersDayKey(nowAlgiers);

   if(liveDayKey != g_today.dayKey)
      ResetDailyState(liveDayKey);

   // Sync live Asia range state from current day's closed bars
   if(curDay == liveDayKey && dAsiaBars >= 6)
   {
      g_today.asiaHigh  = dAsiaH;
      g_today.asiaLow   = dAsiaL;
      g_today.asiaWidth = dAsiaH - dAsiaL;
      g_today.asiaReady = true;
      g_today.asiaValid = dAsiaValid;
      g_today.brokeUp   = dBrokeUp;
      g_today.brokeDown = dBrokeDn;
      if(prev_calculated == 0)
         g_today.alertsToday = dTrades;
   }

   // On initial history load, anchor lastProcessedBar so historical bars never fire stale Telegram alerts
   if(prev_calculated == 0)
      g_lastProcessedBar = time[lastClosed];

   UpdateTodayManualPerformance(nowServer, offsetSec);

   // Check if 2 losses reached -> send stop message once
   if(g_today.stoppedByTwoLosses && !g_today.sentTwoLossMsg && prev_calculated > 0)
   {
      string stopMsg = "Stop for today. 2 losses reached. Come back tomorrow.";
      SendTelegramMessage(stopMsg);
      if(InpEnablePopupAlerts) Alert("[GoldLondonRetest] ", stopMsg);
      LogEventToCsv("DAILY_STOP", "NONE", 0, 0, 0, 0, ExtRsiCalcBuffer[lastClosed], ExtEmaBuffer[lastClosed], 0, stopMsg);
      g_today.sentTwoLossMsg = true;
   }

   // Check if 12:00 Algiers Time reached with 0 valid alerts today (only during 12:00-12:59)
   MqlDateTime nowAlgDt;
   TimeToStruct(nowAlgiers, nowAlgDt);
   bool isWeekdayNow = (nowAlgDt.day_of_week >= 1 && nowAlgDt.day_of_week <= 5);
   if(InpSendNoSetupAt1200 && isWeekdayNow && nowAlgDt.hour == InpTradeEndHour
      && g_today.alertsToday == 0 && !g_today.sentNoSetupMsg && prev_calculated > 0)
   {
      string noTradeMsg = "No valid setup today. No trade.";
      SendTelegramMessage(noTradeMsg);
      if(InpEnablePopupAlerts) Alert("[GoldLondonRetest] ", noTradeMsg);
      LogEventToCsv("NO_SETUP_1200", "NONE", 0, 0, 0, 0, ExtRsiCalcBuffer[lastClosed], ExtEmaBuffer[lastClosed], 0, noTradeMsg);
      g_today.sentNoSetupMsg = true;
   }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double curSpread = (ask > 0 && bid > 0) ? (ask - bid) : 0.0;
   double prevSize  = high[lastClosed] - low[lastClosed];
   string newsStr   = "No News";
   bool newsBlocked = IsHighImpactNewsWindow(nowServer, nowAlgiers, newsStr);

   // Only fire live alerts on a freshly closed M15 bar after initial chart history load
   bool isNewClosedBar = (prev_calculated > 0 && time[lastClosed] != g_lastProcessedBar);
   if(isNewClosedBar)
   {
      g_lastProcessedBar = time[lastClosed];
      datetime barAlgTime = time[lastClosed] + offsetSec;
      MqlDateTime barDt;
      TimeToStruct(barAlgTime, barDt);

      bool inLondonWindow = (barDt.day_of_week >= 1 && barDt.day_of_week <= 5
                             && barDt.hour >= InpTradeStartHour && barDt.hour < InpTradeEndHour);

      if(!inLondonWindow)
      {
         g_today.lastBlockReason = "Outside 09:00-12:00 Algiers";
      }
      else if(g_today.stoppedByTwoLosses)
      {
         g_today.lastBlockReason = "Stopped: 2 losses reached";
      }
      else if(g_today.stoppedByProfitCap)
      {
         g_today.lastBlockReason = "Stopped: +$80 profit cap reached";
      }
      else if(g_today.alertsToday >= InpMaxAlertsPerDay)
      {
         g_today.lastBlockReason = "Max 2 alerts reached today";
      }
      else if(!g_today.asiaReady || !g_today.asiaValid)
      {
         g_today.lastBlockReason = StringFormat("Asia range $%.2f outside [$%.0f-$%.0f]", g_today.asiaWidth, minAsiaW, maxAsiaW);
      }
      else if(newsBlocked)
      {
         g_today.lastBlockReason = "Blocked by " + newsStr;
      }
      else if(curSpread > InpMaxSpreadDollars)
      {
         g_today.lastBlockReason = StringFormat("Spread $%.2f > $%.2f", curSpread, InpMaxSpreadDollars);
      }
      else if(lastClosed >= 2 && (high[lastClosed - 1] - low[lastClosed - 1]) > maxCandle)
      {
         g_today.lastBlockReason = StringFormat("Pre-entry candle $%.2f > $%.2f", high[lastClosed - 1] - low[lastClosed - 1], maxCandle);
      }
      else
      {
         bool hasBuyArrow  = (ExtBuyArrowBuffer[lastClosed]  != EMPTY_VALUE);
         bool hasSellArrow = (ExtSellArrowBuffer[lastClosed] != EMPTY_VALUE);
         double emaClosed  = ExtEmaBuffer[lastClosed];
         double rsiClosed  = ExtRsiCalcBuffer[lastClosed];
         double bodyRatio  = (high[lastClosed] - low[lastClosed] > 0)
                             ? MathAbs(close[lastClosed] - open[lastClosed]) / (high[lastClosed] - low[lastClosed])
                             : 0.0;

         int sigDir = hasBuyArrow ? 1 : (hasSellArrow ? -1 : 0);

         // Stricter rule on 2nd trade if 1st trade was a loss
         if(sigDir != 0 && g_today.lossesToday >= 1)
         {
            bool sameDir = (sigDir == g_today.firstSignalDir);
            if(sameDir)
            {
               bool strongRsi = (sigDir == 1) ? (rsiClosed >= 55.0 && rsiClosed <= 63.0)
                                              : (rsiClosed >= 37.0 && rsiClosed <= 45.0);
               if(!strongRsi || bodyRatio < 0.50)
               {
                  sigDir = 0;
                  g_today.lastBlockReason = "2nd trade blocked: weaker same-dir setup after loss";
               }
            }
         }

         if(sigDir != 0 && g_today.lastAlertedBarTime != time[lastClosed])
         {
            double entry = NormalizeDouble(close[lastClosed], 2);
            double slDist = InpStopLossDollars;
            if(useStructuralSL)
            {
               double rawDist = (sigDir == 1)
                                ? (entry - (MathMin(low[lastClosed], g_today.asiaHigh) - 1.0))
                                : ((MathMax(high[lastClosed], g_today.asiaLow) + 1.0) - entry);
               slDist = MathMax(3.0, MathMin(rawDist, 7.0));
            }
            double tpDist = slDist * 2.0;
            double sl     = NormalizeDouble((sigDir == 1) ? (entry - slDist) : (entry + slDist), 2);
            double tp     = NormalizeDouble((sigDir == 1) ? (entry + tpDist) : (entry - tpDist), 2);
            double lot    = CalculateSafeLotSize(slDist);
            double risk   = NormalizeDouble(lot * 100.0 * slDist, 0);
            double reward = NormalizeDouble(risk * 2.0, 0);

            string dirStr    = (sigDir == 1) ? "BUY" : "SELL";
            string levelDesc = (sigDir == 1) ? "Break + Retest of Asia High, EMA50 below price"
                                             : "Break + Retest of Asia Low, EMA50 above price";
            string algTimeHM = StringFormat("%02d:%02d", barDt.hour, barDt.min);

            string tgMsg = StringFormat(
               "GOLD SIGNAL - %s\n"
               "Entry: %.2f\n"
               "Stop Loss: %.2f\n"
               "Take Profit: %.2f\n"
               "Lot: %.2f\n"
               "Reason: %s, RSI %.0f, No News.\n"
               "Risk: $%.0f | Reward: $%.0f\n"
               "Time: %s Algiers Time\n"
               "Confirm in MT5 manually. Trade duration must be > 5 minutes.",
               dirStr, entry, sl, tp, lot, levelDesc, rsiClosed, risk, reward, algTimeHM
            );

            SendTelegramMessage(tgMsg);
            if(InpEnablePopupAlerts) Alert(tgMsg);

            LogEventToCsv("SIGNAL", dirStr, entry, sl, tp, lot, rsiClosed, emaClosed, curSpread, levelDesc);

            g_today.alertsToday++;
            g_today.lastAlertedBarTime = time[lastClosed];
            g_today.lastBlockReason    = "Signal sent: " + dirStr + " at " + algTimeHM;

            if(g_today.firstSignalDir == 0)
            {
               g_today.firstSignalDir  = sigDir;
               g_today.firstEntry      = entry;
               g_today.firstSL         = sl;
               g_today.firstTP         = tp;
               g_today.firstSignalTime = time[lastClosed];
            }
         }
         else if(sigDir == 0 && g_today.lastBlockReason == "Waiting for setup")
         {
            g_today.lastBlockReason = "Waiting for valid Break+Retest + EMA50 + RSI";
         }
      }
   }

   UpdateDashboard(nowAlgiers, ExtEmaBuffer[liveBar], ExtRsiCalcBuffer[liveBar], curSpread, prevSize, newsStr);
   return rates_total;
}
//+------------------------------------------------------------------+
