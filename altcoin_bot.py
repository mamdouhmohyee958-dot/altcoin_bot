"""
🚀 Pump Detection Bot v10.0 — Gate.io Edition + BTC Context Filter
نظام كشف البامب بـ 12 شرط — نظام نقاط نسبة مئوية + فلتر سياق البتكوين:
  ⭐ الأساسية (4 — تمثل 70%): Funding Rate, CVD Divergence, Taker Buy Ratio, Order Book Imbalance
  📊 التكميلية (8 — تمثل 30%): Volume Acceleration, Bid Wall, Whale Accumulation,
                    EMA21 Crossover, Multi-TF Buy Pressure, Short Liquidation,
                    Micro Momentum 3m, Micro Volume Surge 3m
✅ الأربع الأساسية كلهم → إشارة وحدها (بدون الحاجة للتكميلية)

🟠 v10.0 — فلتر سياق البتكوين الذكي:
  🟢 BTC صاعد/محايد:     السماح بكل الإشارات
  🟡 BTC bearish خفيف:   السماح + تحذير في الإشارة
  🔴 BTC bearish قوي:    رفض كل الإشارات
  ⚠️ BTC crash حاد:      إيقاف الفحص تلقائياً لحين الثبات

السكان المستمر يفحص كل عملات Gate.io USDT (فوليم ≥ $500K) ويرسل الإشارات للأدمن.
الأوامر: /start, /status, /chatid, /btc
"""

import asyncio
import aiohttp
import logging
import sys
import json
import os
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==================== الاعدادات ====================
TELEGRAM_TOKEN = "8608851079:AAErIr1R1l7zl4odFE1AH8uUUOHQjxiwYwI"
ADMIN_CHAT_ID  = "6914157653"
CMC_API_KEY    = "7eeaf1fd132e416ab49279ee21cc6ce0"

CMC_LIMIT             = 1000

# ==================== اعدادات الاشارات ====================
MIN_SCORE          = 80       # ✅ تم رفعه من 75 إلى 80
MIN_VOL_FOR_SIGNAL = 500_000  # ✅ v9.0 — خفضناه من 1M إلى 500K

# ✅ جديد v3.1: سكان البامب المستمر
SIGNAL_LOOP_GAP_SECONDS = 120     # ✅ v4.1: 120ث بدل 90 (لأن الفحص الآن أكبر)
SIGNAL_LOOP_ERR_GAP     = 30      # فاصل بعد خطأ
SIGNAL_COOLDOWN_HOURS     = 6     # كان 24h — قللناه عشان السكان المستمر
GATE_MAX_CANDIDATES       = 5000       # ✅ فحص كل عملات Gate.io (لا يوجد قص فعلي)
GATE_PARALLEL_LIMIT       = 25         # طلبات كلاينز متوازية (زدناها لـ 25)

# ════════════════════════════════════════════════════════════════════
# ✅ v9.0 — PUMP DETECTION (12 شرط — نظام نسبة مئوية)
# ════════════════════════════════════════════════════════════════════
# الأربع الأساسية = 70% من النقاط (17.5% لكل واحد)
# الثمانية التكميلية = 30% من النقاط (3.75% لكل واحد)
# 4/4 أساسية → 70% → إشارة STRONG حتى لو التكميلية صفر
# ════════════════════════════════════════════════════════════════════

# ───── الشروط الـ 4 الأساسية (كل واحد = 17.5%) ─────
# المجموع: 70%
PUMP_W_FUNDING_RATE      = 17.5   # 1) ⭐ Funding Rate Anomaly
PUMP_W_CVD_DIVERGENCE    = 17.5   # 2) ⭐ CVD Divergence
PUMP_W_TAKER_BUY_RATIO   = 17.5   # 3) ⭐ Taker Buy Ratio
PUMP_W_OB_IMBALANCE      = 17.5   # 4) ⭐ Order Book Imbalance

# ───── الشروط الـ 8 التكميلية (كل واحد = 3.75%) ─────
# المجموع: 30%
PUMP_W_VOL_ACCEL         = 3.75   # 5) Volume Acceleration
PUMP_W_BID_WALL          = 3.75   # 6) Bid Wall
PUMP_W_WHALE_ACCUM       = 3.75   # 7) Whale Accumulation
PUMP_W_EMA21_CROSS       = 3.75   # 8) EMA21 Crossover
PUMP_W_MTF_BUY           = 3.75   # 9) Multi-TF Buy Pressure
PUMP_W_SHORT_LIQ         = 3.75   # 10) Short Liquidation
PUMP_W_MICRO_MOMENTUM    = 3.75   # 11) ✅ جديد — Micro Momentum 3 دقائق
PUMP_W_MICRO_VOL_SURGE   = 3.75   # 12) ✅ جديد — Micro Volume Surge 3 دقائق

PUMP_MAX_SCORE           = 100.0  # ✅ v9.0 — نظام نسبة مئوية (المجموع = 100%)
PUMP_SCORE_STRONG        = 70.0   # 🚀 STRONG = 70% (يعني 4/4 أساسية يكفي)
PUMP_SCORE_MODERATE      = 50.0   # ⚠️ MODERATE = 50%
PUMP_SIGNAL_COOLDOWN_MIN = 180 # 3 ساعات
PUMP_RESEND_MIN_INCREASE = 7.0    # ✅ v9.0 — لازم النقاط تزيد 7%+ لإعادة الإرسال (نسبة مئوية)
PUMP_RESEND_ON_UPGRADE   = True   # إعادة الإرسال لو ترقّى من MODERATE لـ STRONG


# ───── عتبات الشروط ─────
PUMP_FUNDING_RATE_LOW    = -0.0005   # -0.05% = 2 نقاط
PUMP_FUNDING_RATE_VLOW   = -0.0010   # -0.10% = 3 نقاط
PUMP_CVD_CHANGE_PCT      = 15.0      # CVD ≥ 15% = 3 نقاط
PUMP_CVD_STRONG_PCT      = 50.0      # CVD ≥ 50% = 4 نقاط (ممتاز)
PUMP_PRICE_CHANGE_PCT    = 1.5       # السعر متحرك < 1.5%
PUMP_TAKER_RATIO_MIN     = 0.60      # ≥ 60% = 2 نقاط
PUMP_TAKER_RATIO_STRONG  = 0.70      # ≥ 70% = 3 نقاط
PUMP_OB_IMBALANCE_MIN    = 0.70      # ≥ 70% = 2 نقاط
PUMP_OB_IMBALANCE_STRONG = 0.85      # ≥ 85% = 3 نقاط
PUMP_OB_RANGE_PCT        = 0.02      # نطاق ±2%

# ───── عتبات التكميلية ─────
PUMP_VOL_ACCEL_MIN       = 1.5       # 1.5x = 2 نقاط
PUMP_VOL_ACCEL_STRONG    = 2.5       # 2.5x = 3 نقاط
PUMP_BID_WALL_RANGE      = 0.015     # ±1.5% من السعر
PUMP_BID_WALL_MIN_RATIO  = 2.0       # bid wall ≥ 2x متوسط الـ asks
PUMP_BID_WALL_STRONG     = 4.0       # ≥ 4x = ⭐ قوي جداً

# ───── 7) Whale Accumulation ─────
PUMP_WHALE_TRADES_N      = 50        # آخر 50 صفقة
PUMP_WHALE_MULT          = 10.0      # صفقة ≥ 10x المتوسط = whale (افتراضي)
PUMP_WHALE_MULT_SMALL    = 5.0       # عملة صغيرة (volume قليل) = threshold أخف
PUMP_WHALE_MULT_LARGE    = 15.0      # عملة كبيرة = threshold أعلى
PUMP_WHALE_SMALL_VOL     = 3_000_000 # أقل من كده = صغيرة
PUMP_WHALE_LARGE_VOL     = 30_000_000# أكبر من كده = كبيرة

# ───── 8) EMA21 Crossover ─────
PUMP_EMA21_PERIOD        = 21        # فترة الـ EMA
PUMP_EMA21_CANDLES       = 30        # آخر 30 كاندل 1h

# ───── 9) Multi-Timeframe Buy Pressure ─────
PUMP_MTF_INTERVALS       = ("15m", "1h", "4h")  # 3 تايم فريمز
PUMP_MTF_CANDLES         = 6         # آخر 6 كاندلات في كل TF
PUMP_MTF_GREEN_PCT       = 0.60      # ≥ 60% أخضر في كل TF

# ───── 10) Short Liquidation ─────
PUMP_SHORT_OI_HOURS      = 3         # مقارنة OI آخر 3 ساعات
PUMP_SHORT_OI_INCREASE   = 0.10      # OI زاد ≥ 10%
PUMP_SHORT_PRICE_FLAT    = 0.5       # السعر ثابت/نازل (تغيّر ≤ +0.5%)

# ───── 11) ✅ جديد — Micro Momentum (آخر 3 دقائق) ─────
# يفحص آخر 3 شموع 1m: لازم 2/3 خضراء + السعر صاعد
PUMP_MICRO_CANDLES       = 3         # آخر 3 شموع 1m
PUMP_MICRO_GREEN_MIN     = 2         # على الأقل 2/3 خضراء
PUMP_MICRO_PRICE_RISE    = 0.3       # السعر صاعد ≥ 0.3% في آخر 3 دقائق

# ───── 12) ✅ جديد — Micro Volume Surge (آخر 3 دقائق) ─────
# فوليم آخر 3 دقائق مقابل متوسط الـ 15 دقيقة السابقة
PUMP_MICRO_VOL_X         = 2.0       # 2x متوسط آخر 15 دقيقة
PUMP_MICRO_VOL_BASELINE  = 15        # 15 شمعة 1m كـ baseline

# ═══════════════════════════════════════════════════════════════
# ✅ v10.0 — فلتر سياق البتكوين الذكي
# ═══════════════════════════════════════════════════════════════
BTC_FILTER_ENABLED        = True       # تفعيل فلتر البتكوين
BTC_CHECK_INTERVAL_SEC    = 60         # كل كام ثانية نحدّث حالة BTC
BTC_CACHE_TTL_SEC         = 90         # cache لحالة BTC

# عتبات تغيّر BTC (4 ساعات)
BTC_BEARISH_LIGHT_4H      = -1.0       # -1% إلى -2% = bearish خفيف 🟡
BTC_BEARISH_STRONG_4H     = -2.0       # < -2% = bearish قوي 🔴 (رفض)

# عتبات BTC crash حاد (ساعة واحدة)
BTC_CRASH_1H              = -2.0       # < -2% في ساعة = crash → إيقاف الفحص
BTC_RECOVERY_1H           = -0.5       # لحد ما يرجع فوق -0.5% في 1h = ثبات
BTC_RECOVERY_CHECK_SEC    = 120        # نفحص الـ recovery كل دقيقتين أثناء الإيقاف

# تقلب BTC (ATR على 1h)
BTC_HIGH_VOLATILITY_ATR   = 2.0        # ATR > 2% = تقلب عالي

# ═══════════════════════════════════════════════════════════════
# ✅ v9.0 — نظام نسبة مئوية (المجموع = 100%)
# الأساسية = 70% | التكميلية = 30%
# 4/4 أساسية → 70% → STRONG حتى بدون تكميلية
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# ✅ v5.0 — نظام الـ 15 شرط (Pro Trader System)
# مبني على معايير المتداولين المحترفين
# ═══════════════════════════════════════════════════════════════


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("altcoin_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

previous_signals: dict = {}
seen_coins:       dict = {}
seen_signals:     dict = {}

# ✅ v10.0 — حالة سياق البتكوين
btc_context = {
    "last_check":   None,      # datetime آخر فحص
    "status":       "unknown", # bullish | neutral | bearish_light | bearish_strong | crash
    "change_4h":    0.0,       # % تغير آخر 4 ساعات
    "change_1h":    0.0,       # % تغير آخر ساعة
    "atr_pct":      0.0,       # ATR% على 1h
    "price":        0.0,       # السعر الحالي
    "paused_until": None,      # datetime — متى ينتهي إيقاف الفحص بسبب crash
    "pause_reason": None,      # سبب الإيقاف للعرض في /status
}

# ==================== ✅ منع الإرسال المزدوج ====================
job_locks = {
    "check_signals": asyncio.Lock(),
}
last_job_run = {
    "check_signals": None,
}

# ==================== قوائم الاستبعاد ====================
EXCLUDED_SYMBOLS = {
    "BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","AVAX","SHIB",
    "DOT","LINK","MATIC","LTC","BCH","XLM","ETC","UNI","ATOM","NEAR",
    "FIL","ICP","HBAR","VET","ALGO","EGLD","TON","SUI","APT","OP",
    "ARB","INJ","SEI","TIA","PYTH","JUP","WLD","RENDER","FET","TAO",
    "IMX","GRT","STX","MKR","AAVE","SNX","COMP","CRV","LDO","RPL",
    "SAND","MANA","AXS","ENJ","CHZ","FLOW","GALA","THETA","FTM",
    "ONE","ROSE","ZIL","ICX","QTUM","ZEC","XMR","DASH","DCR","XTZ",
    "EOS","TRB","BAT","ZRX","SUSHI","YFI","UMA","BAL","KNC","WAVES",
    "ONT","ZEN","SC","DGB","RVN","IOST","STORJ","ANKR","CKB","CELR",
    "USDT","USDC","BUSD","DAI","TUSD","USDP","USDD","FDUSD",
    "USDE","PYUSD","GUSD","LUSD","FRAX","SUSD","EURC","USDS",
    "USD1","USDX","CUSD","MUSD","HUSD","USDJ","XUSD","ZUSD",
    "DUSD","NUSD","PUSD","CRVUSD","DOLA","PAX","PAXG","BEAN",
    "WBTC","WETH","STETH","CBETH","RETH","WBNB","WEETH","WSTETH",
    "WMATIC","WAVAX","WSOL","WFTM","WONE","WXDAI","WROSE",
    "BTCB","BTCST","HBTC","RENBTC","SBTC","TBTC",
}



def fmt_price(p):
    if p >= 1:     return f"${p:.4f}"
    if p >= 0.001: return f"${p:.6f}"
    return f"${p:.8f}"


# ==================== جلب البيانات ====================
async def fetch_cmc(session, limit=500):
    url     = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}
    params  = {"limit": limit, "convert": "USD", "sort": "volume_24h", "sort_dir": "desc"}
    try:
        async with session.get(url, headers=headers, params=params,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status == 401: logger.error("CMC API Key غلط!"); return []
            if r.status == 429: logger.error("تجاوزت حد CMC API!"); return []
            data = await r.json()
        coins = data.get("data", [])
        logger.info(f"CMC: {len(coins)} عملة")
        return coins
    except Exception as e:
        logger.error(f"CMC error: {e}"); return []


# ==================== ✅ v4.1 — Gate.io: كل العملات ====================
# نقطة الوصول الكاملة: ~1700-2500 زوج USDT في Gate.io
# الفكرة: نستخدم Gate.io كمصدر العملات، ونثري بـ CMC لما متاح

async def fetch_gate_tickers(session):
    """
    يرجع كل tickers من Gate.io دفعة واحدة (سريع جداً، طلب واحد)
    كل ticker يحتوي: last (السعر), base_volume, quote_volume,
                     change_percentage, currency_pair
    """
    url = "https://api.gateio.ws/api/v4/spot/tickers"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                logger.error(f"Gate tickers status {r.status}")
                return []
            data = await r.json()
        # فقط أزواج USDT
        usdt = [t for t in data if t.get("currency_pair", "").endswith("_USDT")]
        logger.info(f"Gate.io: {len(usdt)} زوج USDT")
        return usdt
    except Exception as e:
        logger.error(f"Gate tickers error: {e}")
        return []


def parse_gate_ticker(t):
    """تحويل ticker من Gate.io إلى dict موحّد"""
    pair  = t.get("currency_pair", "")
    sym   = pair.replace("_USDT", "")
    try:
        price       = float(t.get("last") or 0)
        vol_usdt    = float(t.get("quote_volume") or 0)   # فوليم 24h بالـ USDT
        change_24h  = float(t.get("change_percentage") or 0)
        high_24h    = float(t.get("high_24h") or price)
        low_24h     = float(t.get("low_24h") or price)
    except (ValueError, TypeError):
        return None
    return {
        "symbol":           sym,
        "name":             sym,             # سيُستبدل بـ CMC name لو متاح
        "price":            price,
        "volume_24h":       vol_usdt,
        "price_change_24h": change_24h,
        "price_change_1h":  0.0,             # غير متاح من Gate tickers (سنستخرجه من الكلاينز)
        "price_change_7d":  0.0,             # غير متاح
        "volume_change":    0.0,             # غير متاح (سنحسبه من الكلاينز)
        "high_24h":         high_24h,
        "low_24h":          low_24h,
        "num_market_pairs": 1,
        "rank":             999999,          # سيُستبدل لو في CMC
        "market_cap":       0,               # سيُستبدل لو في CMC
        "tags":             [],
        "source":           "gate",
    }


# ==================== الكلاينز ====================
async def fetch_klines(session, symbol, interval="1h", limit=48):
    url    = "https://api.gateio.ws/api/v4/spot/candlesticks"
    params = {
        "currency_pair": f"{symbol}_USDT",
        "interval": interval,
        "limit": limit
    }
    try:
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status != 200: return []
            data = await r.json()
        return [{"open":   float(k[5]),
                 "high":   float(k[3]),
                 "low":    float(k[4]),
                 "close":  float(k[2]),
                 "volume": float(k[1])} for k in data]
    except:
        return []


# ════════════════════════════════════════════════════════════════════
# ✅ v10.0 — فلتر سياق البتكوين الذكي
# ════════════════════════════════════════════════════════════════════

async def analyze_btc_context(session, force=False):
    """
    يحدّث حالة btc_context العالمية.
    - يجيب آخر 6 شموع 1h للبتكوين
    - يحسب: تغيّر 4h، تغيّر 1h، ATR%
    - يحدد الحالة: bullish | neutral | bearish_light | bearish_strong | crash
    - يدير الإيقاف التلقائي عند crash
    Returns: btc_context dict
    """
    global btc_context
    now = datetime.now()

    # cache: لو الفحص الأخير قريب، نرجع المحفوظ
    if not force and btc_context["last_check"]:
        elapsed = (now - btc_context["last_check"]).total_seconds()
        if elapsed < BTC_CACHE_TTL_SEC:
            return btc_context

    try:
        # نجيب آخر 6 شموع 1h من Gate.io
        candles = await fetch_klines(session, "BTC", interval="1h", limit=6)
        if not candles or len(candles) < 5:
            logger.warning("⚠️ تعذر جلب شموع BTC — السماح بالإشارات بحذر")
            btc_context["last_check"] = now
            btc_context["status"] = "unknown"
            return btc_context

        # السعر الحالي
        price_now = candles[-1]["close"]
        # السعر قبل ساعة (افتتاح آخر شمعة 1h)
        price_1h_ago = candles[-1]["open"]
        # السعر قبل 4 ساعات
        idx_4h = max(0, len(candles) - 5)  # افتتاح الشمعة قبل 4 ساعات
        price_4h_ago = candles[idx_4h]["open"]

        change_1h = (price_now - price_1h_ago) / price_1h_ago * 100 if price_1h_ago > 0 else 0
        change_4h = (price_now - price_4h_ago) / price_4h_ago * 100 if price_4h_ago > 0 else 0

        # حساب ATR% على آخر 5 شموع
        trs = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = sum(trs) / len(trs) if trs else 0
        atr_pct = (atr / price_now * 100) if price_now > 0 else 0

        # ───── تصنيف الحالة ─────
        # crash له الأولوية: تغير 1h حاد
        if change_1h <= BTC_CRASH_1H:
            status = "crash"
            # إيقاف الفحص إن لم يكن موقوفاً بالفعل
            if not btc_context.get("paused_until"):
                btc_context["paused_until"] = now  # placeholder — هيتم recheck
                btc_context["pause_reason"] = (f"BTC crash 🚨 {change_1h:+.2f}% في ساعة "
                                                f"(السعر {price_now:,.0f})")
                logger.warning(f"🚨 BTC CRASH — إيقاف الفحص: {change_1h:+.2f}% في ساعة")
        elif change_4h <= BTC_BEARISH_STRONG_4H:
            status = "bearish_strong"
        elif change_4h <= BTC_BEARISH_LIGHT_4H:
            status = "bearish_light"
        elif change_4h >= 1.0:
            status = "bullish"
        else:
            status = "neutral"

        # ───── فحص الـ recovery لو كنا في pause ─────
        if btc_context.get("paused_until") and status != "crash":
            # BTC بدأ يتعافى لو 1h رجع فوق العتبة
            if change_1h >= BTC_RECOVERY_1H:
                logger.info(f"✅ BTC تعافى — استئناف الفحص ({change_1h:+.2f}% في ساعة)")
                btc_context["paused_until"] = None
                btc_context["pause_reason"] = None

        btc_context.update({
            "last_check": now,
            "status":     status,
            "change_4h":  change_4h,
            "change_1h":  change_1h,
            "atr_pct":    atr_pct,
            "price":      price_now,
        })
        return btc_context

    except Exception as e:
        logger.error(f"❌ خطأ تحليل سياق BTC: {e}")
        btc_context["last_check"] = now
        return btc_context


def get_btc_status_emoji_and_label():
    """يرجع (emoji, label) للعرض في الرسائل حسب حالة BTC الحالية."""
    s = btc_context.get("status", "unknown")
    c4 = btc_context.get("change_4h", 0)
    c1 = btc_context.get("change_1h", 0)
    atr = btc_context.get("atr_pct", 0)

    if s == "bullish":
        return ("🟢", f"BTC bullish ({c4:+.2f}% in 4h)")
    if s == "neutral":
        return ("🟢", f"BTC محايد ({c4:+.2f}% in 4h)")
    if s == "bearish_light":
        return ("🟡", f"BTC bearish خفيف ({c4:+.2f}% in 4h) — حذر")
    if s == "bearish_strong":
        return ("🔴", f"BTC bearish قوي ({c4:+.2f}% in 4h) — رفض")
    if s == "crash":
        return ("🚨", f"BTC CRASH! ({c1:+.2f}% in 1h)")
    return ("⚪", "BTC غير محدد")


def should_allow_signal(result):
    """
    قرار السماح بالإشارة بناءً على سياق BTC.
    Returns: (allowed: bool, reason: str, warning: str)
        - allowed: هل نرسل الإشارة؟
        - reason: سبب الرفض (لو مرفوضة)
        - warning: تحذير يضاف للإشارة (لو مسموحة بتحذير)
    """
    if not BTC_FILTER_ENABLED:
        return (True, "", "")

    s = btc_context.get("status", "unknown")

    # crash: رفض قاطع (الفحص أصلاً موقوف لكن احتياط إضافي)
    if s == "crash":
        return (False, f"BTC CRASH ({btc_context.get('change_1h', 0):+.2f}% في ساعة)", "")

    # bearish قوي: رفض كل الإشارات
    if s == "bearish_strong":
        return (False, f"BTC bearish قوي ({btc_context.get('change_4h', 0):+.2f}% في 4h)", "")

    # bearish خفيف: السماح + تحذير
    if s == "bearish_light":
        warn = (f"⚠️ تحذير: BTC bearish خفيف ({btc_context.get('change_4h', 0):+.2f}% في 4h) "
                f"— ادخل بنصف الحجم العادي")
        return (True, "", warn)

    # تقلب عالي حتى لو الحالة محايدة = تحذير
    if btc_context.get("atr_pct", 0) >= BTC_HIGH_VOLATILITY_ATR:
        warn = (f"⚠️ تحذير: تقلب BTC عالي (ATR {btc_context.get('atr_pct', 0):.1f}%) "
                f"— انتبه للحركة المضادة")
        return (True, "", warn)

    # bullish أو neutral: السماح بدون تحذير
    return (True, "", "")


# ════════════════════════════════════════════════════════════════════
# ✅ v5.0 — Gate.io Pump Detection Data Fetchers
# ════════════════════════════════════════════════════════════════════

async def fetch_gate_funding_rate(session, symbol):
    """
    الشرط 1: Gate.io futures funding rate
    Returns: float (e.g. -0.0012 لـ -0.12%) أو None
    Response format: [{"t": timestamp, "r": "0.0001"}]
    """
    url = "https://api.gateio.ws/api/v4/futures/usdt/funding_rate"
    params = {"contract": f"{symbol}_USDT", "limit": 1}
    try:
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status != 200:
                return None
            data = await r.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        rate = data[0].get("r")
        if rate is None:
            return None
        return float(rate)
    except Exception:
        return None


async def fetch_gate_open_interest(session, symbol):
    """
    الشرط 10 (Short Liquidation): تاريخ الـ Open Interest من Gate.io Futures
    نجيب قراءات بفاصل ساعة لآخر ~4 ساعات لمقارنة OI الحالي بالـ OI قبل 3 ساعات.
    Returns: list of dicts [{"ts": int, "oi": float}] مرتبة زمنياً، أو [] لو غير متاح.
    """
    url = "https://api.gateio.ws/api/v4/futures/usdt/contract_stats"
    params = {"contract": f"{symbol}_USDT", "interval": "1h", "limit": 5}
    try:
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status != 200: return []
            data = await r.json()
        if not data or not isinstance(data, list): return []
        out = []
        for d in data:
            try:
                # 'open_interest' عدد العقود؛ 'lsr_account' ... إلخ — نأخذ OI فقط
                oi = float(d.get("open_interest", 0) or 0)
                ts = int(d.get("time", 0) or 0)
                out.append({"ts": ts, "oi": oi})
            except (ValueError, TypeError):
                continue
        out.sort(key=lambda x: x["ts"])
        return out
    except Exception:
        return []


async def fetch_gate_recent_trades(session, symbol, limit=1000):
    """
    شروط 2 و 4: آخر الصفقات لحساب CVD و Taker Buy Ratio
    Gate.io: 'side' = 'buy' معناها taker buy، 'sell' = taker sell
    """
    url = "https://api.gateio.ws/api/v4/spot/trades"
    params = {"currency_pair": f"{symbol}_USDT", "limit": limit}
    try:
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status != 200: return []
            data = await r.json()
        out = []
        for t in data:
            try:
                out.append({
                    "ts":     int(float(t.get("create_time_ms", 0))),
                    "side":   t.get("side", ""),    # 'buy' = taker buy
                    "qty":    float(t.get("amount", 0)),
                    "price":  float(t.get("price", 0)),
                })
            except (ValueError, TypeError):
                continue
        return out
    except Exception:
        return []


async def fetch_gate_orderbook(session, symbol, limit=20):
    """
    الشرط 5: Order Book snapshot للـ imbalance
    """
    url = "https://api.gateio.ws/api/v4/spot/order_book"
    params = {"currency_pair": f"{symbol}_USDT", "limit": limit}
    try:
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status != 200: return None
            data = await r.json()
        bids = [(float(p), float(q)) for p, q in data.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in data.get("asks", [])]
        return {"bids": bids, "asks": asks}
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════
# ✅ v8.0 — تقييم الـ 12 شرط
# ════════════════════════════════════════════════════════════════════

def eval_funding_rate(funding_rate):
    """
    الشرط 1 — Funding Rate Anomaly (max 17.5%)
    -0.05% → 50% من الوزن، -0.10% → 100% من الوزن
    """
    if funding_rate is None:
        return {"pass": False, "score": 0.0, "value": None, "label": "غير متاح (spot)"}
    pts = 0.0
    if funding_rate < PUMP_FUNDING_RATE_VLOW:
        pts = PUMP_W_FUNDING_RATE        # 17.5% (كامل)
    elif funding_rate < PUMP_FUNDING_RATE_LOW:
        pts = PUMP_W_FUNDING_RATE * 0.6  # ~10.5% (جزئي)
    return {
        "pass":  pts > 0,
        "score": pts,
        "value": funding_rate,
        "label": f"{funding_rate*100:+.3f}%",
    }


def eval_cvd_divergence(trades, klines_recent):
    """
    الشرط 2 — CVD Divergence (max 4 pts)
    Tiered: CVD ≥ 15% = 3 نقاط، CVD ≥ 50% = 4 نقاط
    """
    if not trades or len(trades) < 50:
        return {"pass": False, "score": 0, "value": None, "label": "بيانات غير كافية"}
    trades.sort(key=lambda x: x["ts"])
    mid = len(trades) // 2
    old = trades[:mid]
    def cvd_calc(group):
        cv = 0
        for t in group:
            if t["side"] == "buy":   cv += t["qty"]
            elif t["side"] == "sell": cv -= t["qty"]
        return cv
    cvd_old = cvd_calc(old)
    cvd_new = cvd_calc(trades)
    if abs(cvd_old) < 1e-9:
        cvd_change_pct = 100.0 if cvd_new > 0 else -100.0
    else:
        cvd_change_pct = (cvd_new - cvd_old) / abs(cvd_old) * 100
    if old and trades:
        p_start = old[0]["price"]
        p_end   = trades[-1]["price"]
        price_change_pct = (p_end - p_start) / p_start * 100 if p_start > 0 else 0
    else:
        price_change_pct = 0
    # ✅ v9.0 — tiered نسبة مئوية
    price_ok      = abs(price_change_pct) < PUMP_PRICE_CHANGE_PCT
    is_strong     = cvd_change_pct > PUMP_CVD_STRONG_PCT and price_ok
    is_divergence = cvd_change_pct > PUMP_CVD_CHANGE_PCT and price_ok

    if is_strong:
        pts = PUMP_W_CVD_DIVERGENCE          # 17.5% (كامل)
        passed = True
    elif is_divergence:
        pts = PUMP_W_CVD_DIVERGENCE * 0.7    # ~12.25% (جزئي)
        passed = True
    else:
        pts = 0.0
        passed = False

    return {
        "pass":  passed,
        "score": pts,
        "value": cvd_change_pct,
        "label": f"CVD {cvd_change_pct:+.1f}% / السعر {price_change_pct:+.2f}%",
    }


def eval_taker_buy_ratio(trades):
    """
    الشرط 4 — Taker Buy Ratio (max 3 pts)
    على آخر الصفقات: نسبة taker buys للإجمالي
    Tiered: ≥60% = 2 نقاط، ≥70% = 3 نقاط
    """
    if not trades or len(trades) < 50:
        return {"pass": False, "score": 0, "value": None, "label": "بيانات غير كافية"}
    # نقسم لـ 3 segments (محاكاة "3 دقائق متتالية")
    n = len(trades)
    trades.sort(key=lambda x: x["ts"])
    segments = [trades[i*n//3:(i+1)*n//3] for i in range(3)]
    ratios = []
    for seg in segments:
        buy_qty   = sum(t["qty"] for t in seg if t["side"] == "buy")
        total_qty = sum(t["qty"] for t in seg)
        if total_qty > 0:
            ratios.append(buy_qty / total_qty)
        else:
            ratios.append(0)
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0
    # ✅ v9.0 — نظام نسبة مئوية
    above_count = sum(1 for r in ratios if r >= PUMP_TAKER_RATIO_MIN)
    strong_avg  = avg_ratio >= PUMP_TAKER_RATIO_STRONG and above_count >= 2
    pass_avg    = avg_ratio >= PUMP_TAKER_RATIO_MIN and above_count >= 2

    if strong_avg:
        pts = PUMP_W_TAKER_BUY_RATIO         # 17.5% (كامل)
        passed = True
    elif pass_avg:
        pts = PUMP_W_TAKER_BUY_RATIO * 0.6   # ~10.5% (جزئي)
        passed = True
    else:
        pts = 0.0
        passed = False

    return {
        "pass":  passed,
        "score": pts,
        "value": avg_ratio,
        "label": f"{avg_ratio*100:.1f}% (متوسط 3 شرائح، {above_count}/3 ≥ {PUMP_TAKER_RATIO_MIN*100:.0f}%)",
    }


def eval_orderbook_imbalance(ob, current_price):
    """
    الشرط 4 — Order Book Imbalance (max 17.5%) — tiered
    """
    if not ob or not ob.get("bids") or not ob.get("asks") or current_price <= 0:
        return {"pass": False, "score": 0.0, "value": None, "label": "غير متاح"}
    p_min = current_price * (1 - PUMP_OB_RANGE_PCT)
    p_max = current_price * (1 + PUMP_OB_RANGE_PCT)
    buy_vol  = sum(q for p, q in ob["bids"] if p >= p_min)
    sell_vol = sum(q for p, q in ob["asks"] if p <= p_max)
    total = buy_vol + sell_vol
    if total <= 0:
        return {"pass": False, "score": 0.0, "value": None, "label": "لا توجد سيولة قريبة"}
    imbalance = buy_vol / total
    if imbalance >= PUMP_OB_IMBALANCE_STRONG:
        pts, passed = PUMP_W_OB_IMBALANCE, True             # 17.5% (كامل)
    elif imbalance >= PUMP_OB_IMBALANCE_MIN:
        pts, passed = PUMP_W_OB_IMBALANCE * 0.6, True       # ~10.5% (جزئي)
    else:
        pts, passed = 0.0, False
    return {
        "pass":  passed,
        "score": pts,
        "value": imbalance,
        "label": f"شراء {imbalance*100:.1f}% (نطاق \u00b12%)",
    }


# ════════════════════════════════════════════════════════════════════
# ✅ v6.0 — 3 شروط جديدة قوية (تكميلية للـ 4 الأساسية)
# ════════════════════════════════════════════════════════════════════

def eval_volume_acceleration(candles_1h):
    """
    الشرط 5 — Volume Acceleration (max 3.75%) — tiered
    1.5x = 60%، 2.5x+ = 100%
    """
    if not candles_1h or len(candles_1h) < 12:
        return {"pass": False, "score": 0.0, "value": 0, "label": "كلاينز غير كافية"}
    vols = [c["volume"] for c in candles_1h]
    recent_3 = sum(vols[-3:]) / 3
    older_9  = sum(vols[-12:-3]) / 9
    if older_9 <= 0:
        return {"pass": False, "score": 0.0, "value": 0, "label": "متوسط صفر"}
    ratio = recent_3 / older_9
    if ratio >= PUMP_VOL_ACCEL_STRONG:
        return {"pass": True, "score": PUMP_W_VOL_ACCEL, "value": ratio,
                "label": f"{ratio:.1f}x (آخر 3h vs الـ 9h قبلها) \U0001f525"}
    if ratio >= PUMP_VOL_ACCEL_MIN:
        return {"pass": True, "score": PUMP_W_VOL_ACCEL * 0.6, "value": ratio,
                "label": f"{ratio:.1f}x (آخر 3h vs الـ 9h قبلها)"}
    return {"pass": False, "score": 0.0, "value": ratio,
            "label": f"{ratio:.2f}x (الحد {PUMP_VOL_ACCEL_MIN}x)"}


def _ema_last(values, period):
    """يحسب قيمة EMA الأخيرة من قائمة أسعار (closes)."""
    if not values or len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period   # SMA كبداية
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def eval_whale_accumulation(trades, volume_24h):
    """
    الشرط 7 — 🐋 Whale Accumulation (max 3 pts)
    آخر 50 صفقة: نحسب متوسط حجم الصفقة. أي صفقة buy حجمها ≥ (mult × المتوسط) = whale.
    mult يتكيّف مع حجم العملة: صغيرة=5x, عادية=10x, كبيرة=15x.
    لو في whale buy واحدة على الأقل → 3 نقاط.
    """
    if not trades or len(trades) < 10:
        return {"pass": False, "score": 0.0, "value": 0, "label": "صفقات غير كافية"}
    trades_sorted = sorted(trades, key=lambda x: x["ts"])
    last = trades_sorted[-PUMP_WHALE_TRADES_N:]
    qtys = [t["qty"] for t in last if t["qty"] > 0]
    if not qtys:
        return {"pass": False, "score": 0.0, "value": 0, "label": "لا أحجام"}
    avg_qty = sum(qtys) / len(qtys)
    if avg_qty <= 0:
        return {"pass": False, "score": 0.0, "value": 0, "label": "متوسط صفر"}

    # threshold متكيّف حسب حجم العملة
    if volume_24h and volume_24h < PUMP_WHALE_SMALL_VOL:
        mult = PUMP_WHALE_MULT_SMALL
    elif volume_24h and volume_24h > PUMP_WHALE_LARGE_VOL:
        mult = PUMP_WHALE_MULT_LARGE
    else:
        mult = PUMP_WHALE_MULT
    threshold = avg_qty * mult

    whale_buys = [t for t in last if t["side"] == "buy" and t["qty"] >= threshold]
    biggest = max((t["qty"] for t in whale_buys), default=0)
    is_pass = len(whale_buys) >= 1
    ratio = (biggest / avg_qty) if avg_qty > 0 else 0
    return {
        "pass":  is_pass,
        "score": PUMP_W_WHALE_ACCUM if is_pass else 0.0,
        "value": len(whale_buys),
        "label": (f"🐋 {len(whale_buys)} صفقة whale (أكبرها {ratio:.0f}x المتوسط، حد {mult:.0f}x)"
                  if is_pass else f"لا صفقات whale (حد {mult:.0f}x المتوسط)"),
    }


def eval_ema21_crossover(candles_1h):
    """
    الشرط 8 — 📊 EMA21 Crossover (max 3 pts)
    آخر 30 كاندل 1h: نحسب EMA21.
      - السعر الحالي فوق الـ EMA + الكاندل السابقة كانت تحتها = crossover للتو → 3 نقاط
      - السعر فوق الـ EMA بدون crossover = نقطة واحدة
    """
    if not candles_1h or len(candles_1h) < PUMP_EMA21_PERIOD + 2:
        return {"pass": False, "score": 0.0, "value": 0, "label": "كلاينز غير كافية"}
    closes = [c["close"] for c in candles_1h[-PUMP_EMA21_CANDLES:]]
    if len(closes) < PUMP_EMA21_PERIOD + 2:
        closes = [c["close"] for c in candles_1h]
    # EMA حتى الكاندل الحالية، وEMA حتى الكاندل السابقة
    ema_now  = _ema_last(closes, PUMP_EMA21_PERIOD)
    ema_prev = _ema_last(closes[:-1], PUMP_EMA21_PERIOD)
    if ema_now is None or ema_prev is None:
        return {"pass": False, "score": 0.0, "value": 0, "label": "EMA غير محسوب"}
    price_now  = closes[-1]
    price_prev = closes[-2]

    crossed_up = (price_prev < ema_prev) and (price_now > ema_now)
    above_only = price_now > ema_now

    if crossed_up:
        return {"pass": True, "score": PUMP_W_EMA21_CROSS, "value": price_now - ema_now,
                "label": f"📊 Crossover للتو فوق EMA21 ({fmt_price(price_now)} > {fmt_price(ema_now)})"}
    if above_only:
        return {"pass": True, "score": PUMP_W_EMA21_CROSS * 0.4, "value": price_now - ema_now,
                "label": f"السعر فوق EMA21 بدون crossover"}
    return {"pass": False, "score": 0.0, "value": price_now - ema_now,
            "label": f"السعر تحت EMA21"}


def eval_multi_tf_buy_pressure(mtf_candles):
    """
    الشرط 9 — 🔄 Multi-Timeframe Buy Pressure (max 3 pts)
    mtf_candles: dict {interval: [candles]} للـ 15m و1h و4h.
    في كل TF: آخر 6 كاندلات، نسبة الخضراء.
    لو الـ 3 كلهم ≥ 60% أخضر → 3 نقاط (تأكيد على كل المستويات).
    """
    results = {}
    all_ok = True
    checked = 0
    for tf in PUMP_MTF_INTERVALS:
        candles = mtf_candles.get(tf) or []
        if len(candles) < PUMP_MTF_CANDLES:
            all_ok = False
            results[tf] = None
            continue
        checked += 1
        last = candles[-PUMP_MTF_CANDLES:]
        green = sum(1 for c in last if c["close"] > c["open"])
        pct = green / len(last)
        results[tf] = pct
        if pct < PUMP_MTF_GREEN_PCT:
            all_ok = False

    is_pass = all_ok and checked == len(PUMP_MTF_INTERVALS)
    parts = []
    for tf in PUMP_MTF_INTERVALS:
        p = results.get(tf)
        parts.append(f"{tf}:{p*100:.0f}%" if p is not None else f"{tf}:—")
    return {
        "pass":  is_pass,
        "score": PUMP_W_MTF_BUY if is_pass else 0.0,
        "value": results,
        "label": f"🔄 {' | '.join(parts)} (حد {PUMP_MTF_GREEN_PCT*100:.0f}% لكل TF)",
    }


def eval_short_liquidation(oi_history, funding_rate, candles_1h):
    """
    الشرط 10 — 📉 Short Liquidation (max 4 pts) — أساسي القوة
      أ) Open Interest زاد ≥ 10% في آخر 3 ساعات + السعر ثابت/نازل = شورتات جديدة
      ب) Funding Rate سالب = شورتات أكتر من اللونجات
    الاتنين = 4 نقاط | واحد بس = 2 نقاط
    """
    cond_oi = False
    oi_change_pct = 0.0
    if oi_history and len(oi_history) >= 2:
        oi_now = oi_history[-1]["oi"]
        # القراءة قبل ~3 ساعات (أو أقدم متاح)
        idx = max(0, len(oi_history) - 1 - PUMP_SHORT_OI_HOURS)
        oi_old = oi_history[idx]["oi"]
        if oi_old > 0:
            oi_change_pct = (oi_now - oi_old) / oi_old * 100
        # تغيّر السعر في نفس الفترة (آخر 3 شموع 1h)
        price_flat_or_down = True
        if candles_1h and len(candles_1h) >= PUMP_SHORT_OI_HOURS + 1:
            p_old = candles_1h[-(PUMP_SHORT_OI_HOURS + 1)]["close"]
            p_now = candles_1h[-1]["close"]
            if p_old > 0:
                price_chg = (p_now - p_old) / p_old * 100
                price_flat_or_down = price_chg <= PUMP_SHORT_PRICE_FLAT
        cond_oi = (oi_change_pct >= PUMP_SHORT_OI_INCREASE * 100) and price_flat_or_down

    cond_funding = funding_rate is not None and funding_rate < 0

    if cond_oi and cond_funding:
        return {"pass": True, "score": PUMP_W_SHORT_LIQ, "value": oi_change_pct,
                "label": f"📉 OI +{oi_change_pct:.1f}% (سعر ثابت) + Funding سالب = شورتات محاصرة 🔥"}
    if cond_oi or cond_funding:
        reason = (f"OI +{oi_change_pct:.1f}%" if cond_oi else "Funding سالب")
        return {"pass": True, "score": PUMP_W_SHORT_LIQ * 0.5, "value": oi_change_pct,
                "label": f"📉 إشارة شورت جزئية ({reason})"}
    return {"pass": False, "score": 0.0, "value": oi_change_pct,
            "label": f"لا ضغط شورت (OI {oi_change_pct:+.1f}%)"}


def eval_bid_wall(ob, current_price):
    """
    الشرط 6 — Smart Money Bid Wall (max 3.75%) — tiered
    جدار شراء قوي قريب من السعر = دعم يحمي البامب
    """
    if not ob or not ob.get("bids") or not ob.get("asks") or current_price <= 0:
        return {"pass": False, "score": 0.0, "value": 0, "label": "غير متاح"}
    p_low  = current_price * (1 - PUMP_BID_WALL_RANGE)
    p_high = current_price * (1 + PUMP_BID_WALL_RANGE)
    bid_in_range = [q for p, q in ob["bids"] if p >= p_low]
    ask_in_range = [q for p, q in ob["asks"] if p <= p_high]
    if not bid_in_range or not ask_in_range:
        return {"pass": False, "score": 0.0, "value": 0, "label": "لا توجد سيولة قريبة"}
    max_bid       = max(bid_in_range)
    avg_ask       = sum(ask_in_range) / len(ask_in_range)
    if avg_ask <= 0:
        return {"pass": False, "score": 0.0, "value": 0, "label": "متوسط asks صفر"}
    ratio = max_bid / avg_ask
    if ratio >= PUMP_BID_WALL_STRONG:
        return {"pass": True, "score": PUMP_W_BID_WALL, "value": ratio,
                "label": f"\U0001f9f1 جدار شراء {ratio:.1f}x متوسط asks"}
    if ratio >= PUMP_BID_WALL_MIN_RATIO:
        return {"pass": True, "score": PUMP_W_BID_WALL * 0.6, "value": ratio,
                "label": f"جدار شراء {ratio:.1f}x متوسط asks"}
    return {"pass": False, "score": 0.0, "value": ratio,
            "label": f"لا جدار ({ratio:.1f}x، الحد {PUMP_BID_WALL_MIN_RATIO}x)"}


def eval_micro_momentum_3m(candles_1m):
    """
    الشرط 11 — ✅ جديد — Micro Momentum (آخر 3 دقائق) (max 3.75%)
    آخر 3 شموع 1m:
      - 2/3 خضراء على الأقل + السعر صاعد ≥ 0.3% → كامل (3.75%)
      - 2/3 خضراء فقط (بدون نسبة الصعود) → جزئي (60%)
    """
    if not candles_1m or len(candles_1m) < PUMP_MICRO_CANDLES:
        return {"pass": False, "score": 0.0, "value": 0, "label": "كلاينز 1m غير كافية"}
    last = candles_1m[-PUMP_MICRO_CANDLES:]
    green = sum(1 for c in last if c["close"] > c["open"])
    p_start = last[0]["open"]
    p_end   = last[-1]["close"]
    price_change_pct = (p_end - p_start) / p_start * 100 if p_start > 0 else 0

    strong = (green >= PUMP_MICRO_GREEN_MIN) and (price_change_pct >= PUMP_MICRO_PRICE_RISE)
    weak   = (green >= PUMP_MICRO_GREEN_MIN) and (price_change_pct > 0)

    if strong:
        return {"pass": True, "score": PUMP_W_MICRO_MOMENTUM, "value": price_change_pct,
                "label": f"⚡ {green}/3 خضراء + سعر {price_change_pct:+.2f}% آخر 3د 🔥"}
    if weak:
        return {"pass": True, "score": PUMP_W_MICRO_MOMENTUM * 0.6, "value": price_change_pct,
                "label": f"⚡ {green}/3 خضراء (سعر {price_change_pct:+.2f}%)"}
    return {"pass": False, "score": 0.0, "value": price_change_pct,
            "label": f"⚡ {green}/3 خضراء فقط (سعر {price_change_pct:+.2f}%)"}


def eval_micro_volume_surge_3m(candles_1m):
    """
    الشرط 12 — ✅ جديد — Micro Volume Surge (آخر 3 دقائق) (max 3.75%)
    فوليم آخر 3 دقائق مقابل متوسط الـ 15 دقيقة قبلها.
    ≥ 2x → كامل (3.75%)
    ≥ 1.5x → جزئي (60%)
    """
    needed = PUMP_MICRO_CANDLES + PUMP_MICRO_VOL_BASELINE
    if not candles_1m or len(candles_1m) < needed:
        return {"pass": False, "score": 0.0, "value": 0, "label": "كلاينز 1m غير كافية"}
    vols = [c["volume"] for c in candles_1m]
    recent_3 = sum(vols[-PUMP_MICRO_CANDLES:]) / PUMP_MICRO_CANDLES
    baseline_vols = vols[-(PUMP_MICRO_CANDLES + PUMP_MICRO_VOL_BASELINE):-PUMP_MICRO_CANDLES]
    if not baseline_vols:
        return {"pass": False, "score": 0.0, "value": 0, "label": "baseline غير متاح"}
    avg_baseline = sum(baseline_vols) / len(baseline_vols)
    if avg_baseline <= 0:
        return {"pass": False, "score": 0.0, "value": 0, "label": "متوسط صفر"}
    ratio = recent_3 / avg_baseline

    if ratio >= PUMP_MICRO_VOL_X:
        return {"pass": True, "score": PUMP_W_MICRO_VOL_SURGE, "value": ratio,
                "label": f"📈 فوليم 3د {ratio:.1f}x متوسط 15د السابقة 🔥"}
    if ratio >= PUMP_MICRO_VOL_X * 0.75:  # ≥ 1.5x
        return {"pass": True, "score": PUMP_W_MICRO_VOL_SURGE * 0.6, "value": ratio,
                "label": f"📈 فوليم 3د {ratio:.1f}x (متوسط)"}
    return {"pass": False, "score": 0.0, "value": ratio,
            "label": f"📈 فوليم 3د {ratio:.2f}x (الحد {PUMP_MICRO_VOL_X}x)"}


# ════════════════════════════════════════════════════════════════════
# ✅ v8.0 — المحرك الرئيسي للبامب (12 شرط)
# ════════════════════════════════════════════════════════════════════

async def evaluate_pump_signal(session, symbol, current_price, volume_24h=0):
    """
    يقيم الـ 12 شرط على عملة واحدة (نظام نسبة مئوية)
    """
    # جلب البيانات بالتوازي
    funding, trades, ob, kl1h, kl15m, kl4h, kl1m, oi_hist = await asyncio.gather(
        fetch_gate_funding_rate(session, symbol),
        fetch_gate_recent_trades(session, symbol, limit=1000),
        fetch_gate_orderbook(session, symbol, limit=30),
        fetch_klines(session, symbol, interval="1h", limit=72),
        fetch_klines(session, symbol, interval="15m", limit=12),
        fetch_klines(session, symbol, interval="4h", limit=12),
        fetch_klines(session, symbol, interval="1m", limit=20),   # ✅ v9.0 — للشروط الجديدة
        fetch_gate_open_interest(session, symbol),
        return_exceptions=True
    )
    if isinstance(funding, Exception): funding = None
    if isinstance(trades, Exception):  trades  = []
    if isinstance(ob, Exception):      ob      = None
    if isinstance(kl1h, Exception):    kl1h    = []
    if isinstance(kl15m, Exception):   kl15m   = []
    if isinstance(kl4h, Exception):    kl4h    = []
    if isinstance(kl1m, Exception):    kl1m    = []
    if isinstance(oi_hist, Exception): oi_hist = []

    mtf = {"15m": kl15m, "1h": kl1h, "4h": kl4h}

    # تقييم الشروط (12 شرط — نظام نسبة مئوية)
    r1  = eval_funding_rate(funding)                          # 1) Funding (17.5%) ⭐
    r2  = eval_cvd_divergence(trades, kl1h)                   # 2) CVD (17.5%) ⭐
    r3  = eval_taker_buy_ratio(trades)                        # 3) Taker (17.5%) ⭐
    r4  = eval_orderbook_imbalance(ob, current_price)         # 4) OB Imbalance (17.5%) ⭐
    r5  = eval_volume_acceleration(kl1h)                      # 5) Vol Accel (3.75%)
    r6  = eval_bid_wall(ob, current_price)                    # 6) Bid Wall (3.75%)
    r7  = eval_whale_accumulation(trades, volume_24h)         # 7) Whale (3.75%)
    r8  = eval_ema21_crossover(kl1h)                          # 8) EMA21 (3.75%)
    r9  = eval_multi_tf_buy_pressure(mtf)                     # 9) Multi-TF (3.75%)
    r10 = eval_short_liquidation(oi_hist, funding, kl1h)      # 10) Short Liq (3.75%)
    r11 = eval_micro_momentum_3m(kl1m)                        # 11) ✅ جديد — Micro Momentum (3.75%)
    r12 = eval_micro_volume_surge_3m(kl1m)                    # 12) ✅ جديد — Micro Vol Surge (3.75%)

    total = (r1["score"] + r2["score"] + r3["score"] + r4["score"] + r5["score"]
             + r6["score"] + r7["score"] + r8["score"] + r9["score"] + r10["score"]
             + r11["score"] + r12["score"])

    # ───── ✅ v9.0 — منطق جديد ─────
    # الأربع الأساسية لو تجمعوا (4/4) → إشارة وحدها بدون حاجة لتكميلية
    core_passed = sum(1 for r in [r1, r2, r3, r4] if r["pass"])
    core_all_four = core_passed == 4   # ✅ الكل الأربعة معاً = STRONG مباشرة

    # ───── تصنيف القوة ─────
    # القاعدة الأساسية: لازم على الأقل 3/4 أساسية للإرسال (إلا لو النقاط ≥ 70%)
    if core_all_four:
        # 4/4 = 70% من نفسها → STRONG مباشرة (حتى لو التكميلية صفر)
        strength = "STRONG"
        strength_emoji = "\U0001f680"
        strength_label = "STRONG — 4/4 أساسية متفعلة 🔥🔥 إشارة وحدها كافية"
    elif total >= PUMP_SCORE_STRONG and core_passed >= 3:
        strength = "STRONG"
        strength_emoji = "\U0001f680"
        strength_label = f"STRONG — {total:.1f}% + {core_passed}/4 أساسية 🔥"
    elif total >= PUMP_SCORE_MODERATE and core_passed >= 3:
        strength = "MODERATE"
        strength_emoji = "\u26a0\ufe0f"
        strength_label = f"MODERATE — {total:.1f}% + {core_passed}/4 أساسية"
    else:
        strength = None
        strength_emoji = "\u274c"
        if core_passed < 3:
            strength_label = f"تجاهل — {core_passed}/4 أساسية فقط (الحد 3)"
        else:
            strength_label = f"تجاهل — نقاط منخفضة ({total:.1f}%)"

    # ═══════════════════════════════════════════════════════════════
    # ✅ هدف واستوب ديناميكيين مبنيين على ATR
    # ═══════════════════════════════════════════════════════════════
    targets = calc_targets_and_stop(current_price, kl1h, None)

    return {
        "symbol":     symbol,
        "price":      current_price,
        "score":      total,
        "max_score":  PUMP_MAX_SCORE,
        "strength":   strength,
        "strength_emoji": strength_emoji,
        "strength_label": strength_label,
        "core_passed": core_passed,
        "stop_loss":  targets["stop_loss"],
        "target_1":   targets["target_1"],
        "target_2":   targets["target_2"],
        "rr_ratio":   targets["rr_ratio"],
        "atr_pct":    targets["atr_pct"],
        "conditions": {
            "funding_rate":     r1,
            "cvd_divergence":   r2,
            "taker_buy_ratio":  r3,
            "ob_imbalance":     r4,
            "vol_accel":        r5,
            "bid_wall":         r6,
            "whale_accum":      r7,
            "ema21_cross":      r8,
            "mtf_buy":          r9,
            "short_liq":        r10,
            "micro_momentum":   r11,
            "micro_vol_surge":  r12,
        },
    }


def calc_targets_and_stop(current_price, candles_1h, _unused=None):
    """
    حساب الهدف والاستوب الدقيقين بناءً على:
    - ATR (Average True Range) للـ 14 شمعة 1h = تقلب حقيقي
    - أعلى/أدنى نقاط محلية = دعم/مقاومة فعلية
    - أقرب pivot high كهدف ذكي (لو متاح)
    Returns: {"stop_loss", "target_1", "target_2", "rr_ratio", "atr_pct"}
    """
    # حالة افتراضية لو الكلاينز غير كافية
    fallback = {
        "stop_loss": current_price * 0.97,
        "target_1":  current_price * 1.03,
        "target_2":  current_price * 1.06,
        "rr_ratio":  1.0,
        "atr_pct":   3.0,
    }
    if not candles_1h or len(candles_1h) < 15 or current_price <= 0:
        return fallback

    # ───── 1) حساب ATR على آخر 14 شمعة ─────
    last = candles_1h[-15:]
    trs = []
    for i in range(1, len(last)):
        h, l, pc = last[i]["high"], last[i]["low"], last[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else current_price * 0.01
    atr_pct = (atr / current_price * 100) if current_price > 0 else 3.0
    # حد أدنى للـ ATR (1%) وأقصى (8%) عشان مكنش متطرف
    atr_pct = max(1.0, min(atr_pct, 8.0))
    atr = current_price * atr_pct / 100

    # ───── 2) الاستوب: أدنى نقطة في آخر 10 شموع - نصف ATR (سرعة هروب) ─────
    recent_low = min(c["low"] for c in candles_1h[-10:])
    stop_by_structure = recent_low - (atr * 0.5)
    # حد أقصى: -5% من السعر الحالي (مش هنخسر أكتر من كده)
    stop_by_pct = current_price * 0.95
    stop_loss = max(stop_by_structure, stop_by_pct)
    # حد أدنى: -1.5% (مش قريب أوي عشان الـ noise)
    stop_loss = min(stop_loss, current_price * 0.985)

    # ───── 3) الهدف 1: 1.5x المسافة للاستوب (R:R = 1.5) ─────
    risk = current_price - stop_loss
    target_1 = current_price + (risk * 1.5)

    # ───── 4) الهدف 2: 3x المسافة، أو أقرب cluster قمم إذا موجود ─────
    target_2_by_rr = current_price + (risk * 3.0)

    # نحسب pivot highs ونجيب أقربهم (ذكي - بدون شرط Liquidity Sweep)
    target_2 = target_2_by_rr
    try:
        pivots = []
        for i in range(3, len(candles_1h) - 3):
            h = candles_1h[i]["high"]
            if (h > max(c["high"] for c in candles_1h[i-3:i]) and
                h > max(c["high"] for c in candles_1h[i+1:i+4])):
                pivots.append(h)
        above = [p for p in pivots if p > current_price * 1.02]
        if above:
            nearest_cluster = min(above)  # أقرب قمة فوق
            # نأخذ الأكبر بين هدف R:R وأقرب قمة (عشان منكسرش الـ R:R)
            target_2 = max(target_2_by_rr, nearest_cluster * 0.998)  # بنخرج قبل القمة بشوية
    except Exception:
        pass

    rr_ratio = (target_1 - current_price) / risk if risk > 0 else 1.5

    return {
        "stop_loss": stop_loss,
        "target_1":  target_1,
        "target_2":  target_2,
        "rr_ratio":  rr_ratio,
        "atr_pct":   atr_pct,
    }


def _md2_escape(text):
    """Escape characters for Telegram MarkdownV2."""
    if text is None: return ""
    text = str(text)
    # كل الأحرف اللي لازم تتعمل لها escape في MarkdownV2
    specials = r"_*[]()~`>#+-=|{}.!\\"
    out = []
    for ch in text:
        if ch in specials:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def format_pump_signal_message(result):
    """
    تنسيق الإشارة — 12 شرط (نظام نسبة مئوية) + هدف/استوب ديناميكي + spoiler للشروط
    يستخدم Telegram MarkdownV2 — الشروط مخفية داخل ||spoiler|| تتكشف بالضغط.
    """
    c = result["conditions"]
    sym = result["symbol"]
    price = result["price"]
    sl = result["stop_loss"]
    t1 = result["target_1"]
    t2 = result["target_2"]
    sl_pct = (sl - price) / price * 100
    t1_pct = (t1 - price) / price * 100
    t2_pct = (t2 - price) / price * 100
    rr = result.get("rr_ratio", 1.5)
    atr_pct = result.get("atr_pct", 3.0)

    # ✅ v9.0 — الفوليم على Gate و الفوليم الإجمالي العالمي من CMC
    vol_gate   = result.get("volume_24h", 0) or 0
    vol_global = result.get("volume_global", 0) or 0
    n_markets  = result.get("num_market_pairs", 0) or 0

    def _fmt_vol(v):
        if v >= 1_000_000_000: return f"${v/1_000_000_000:.2f}B"
        if v >= 1_000_000:     return f"${v/1_000_000:.2f}M"
        if v >= 1_000:         return f"${v/1_000:.1f}K"
        return f"${v:.0f}"

    e = _md2_escape  # اختصار

    # ───── الجزء الظاهر (ملخص فقط) ─────
    header_lines = [
        f"{result['strength_emoji']} *إشارة بامب محتملة*",
        "━" * 18,
        f"💎 *العملة:* `{e(sym)}USDT`",
        f"💰 *السعر:* `{e(fmt_price(price))}`",
        f"⭐ *الأساسية:* {result['core_passed']}/4",
        f"📊 *النقاط:* `{e(f'{result['score']:.1f}%')}` \\(من 100%\\)",
        f"🎯 *القوة:* {e(result['strength_label'])}",
        "",
        "━━━ 💹 *الفوليم* ━━━",
        f"🏦 *Gate\\.io 24h:* `{e(_fmt_vol(vol_gate))}`",
    ]
    if vol_global > 0:
        markets_part = f" \\| 🌐 *الأسواق:* {n_markets}" if n_markets else ""
        header_lines.append(f"🌍 *إجمالي العالم 24h:* `{e(_fmt_vol(vol_global))}`{markets_part}")
    else:
        header_lines.append(f"🌍 *إجمالي العالم 24h:* غير متاح \\(غير مدرجة على CMC\\)")

    header_lines += [
        "",
        "━━━ 📍 *الدخول والخروج* ━━━",
        f"🟢 *الدخول:* `{e(fmt_price(price))}`",
        f"🎯 *الهدف 1:* `{e(fmt_price(t1))}` \\({e(f'{t1_pct:+.2f}%')}\\)",
        f"🏆 *الهدف 2:* `{e(fmt_price(t2))}` \\({e(f'{t2_pct:+.2f}%')}\\)",
        f"🛑 *الاستوب:* `{e(fmt_price(sl))}` \\({e(f'{sl_pct:+.2f}%')}\\)",
        f"⚖️ *R:R:* `{e(f'{rr:.2f}')}` \\| *ATR:* `{e(f'{atr_pct:.1f}%')}`",
        "",
    ]

    # ✅ v10.0 — حالة BTC والتحذيرات
    btc_emoji = result.get("btc_status_emoji", "")
    btc_label = result.get("btc_status_label", "")
    btc_warning = result.get("btc_warning", "")
    if btc_emoji or btc_label:
        header_lines.append("━━━ 🟠 *سياق البتكوين* ━━━")
        header_lines.append(f"{btc_emoji} {e(btc_label)}")
        if btc_warning:
            header_lines.append(f"{e(btc_warning)}")
        header_lines.append("")

    # ───── الجزء المخفي (spoiler) — تفاصيل الشروط ─────
    items = [
        ("⭐", "Funding Rate",       c["funding_rate"]),
        ("⭐", "CVD Divergence",     c["cvd_divergence"]),
        ("⭐", "Taker Buy Ratio",    c["taker_buy_ratio"]),
        ("⭐", "Order Book Imb\\.",  c["ob_imbalance"]),
        ("",   "Volume Accel\\.",    c["vol_accel"]),
        ("",   "Bid Wall",            c["bid_wall"]),
        ("",   "Whale Accum\\.",     c["whale_accum"]),
        ("",   "EMA21 Crossover",    c["ema21_cross"]),
        ("",   "Multi\\-TF Buy",     c["mtf_buy"]),
        ("",   "Short Liquidation",  c["short_liq"]),
        ("",   "Micro Momentum 3m",  c["micro_momentum"]),
        ("",   "Micro Vol Surge 3m", c["micro_vol_surge"]),
    ]
    detail_lines = ["📋 الشروط بالتفصيل:", ""]
    for marker, name, r in items:
        icon = "✅" if r["pass"] else "❌"
        lbl = e(r.get("label", ""))
        pts = r.get("score", 0)
        prefix = f"{icon} {marker} " if marker else f"{icon} "
        detail_lines.append(f"{prefix}{name} \\({e(f'{pts:.2f}%')}\\): {lbl}")
    detail_lines.append("")
    detail_lines.append("⭐ \\= شرط أساسي \\(17\\.5% لكل واحد\\)")
    detail_lines.append("📊 الأساسية = 70% \\| التكميلية = 30%")
    detail_text = "\n".join(detail_lines)
    # نلف الجزء كله في spoiler واحد
    spoiler_block = f"👁 *اضغط لإظهار التفاصيل:*\n||{detail_text}||"

    # ───── التذييل ─────
    footer = [
        "",
        "━" * 18,
        f"⏰ {e(datetime.now().strftime('%H:%M:%S'))} \\| 📡 Gate\\.io",
    ]

    return "\n".join(header_lines + [spoiler_block] + footer)


# ════════════════════════════════════════════════════════════════════
# ✅ v8.0 — فحص إشارات البامب (الـ 12 شرط)
# ════════════════════════════════════════════════════════════════════
async def check_signals(bot: Bot, target_chat: int = None):
    global previous_signals
    logger.info("🚀 فحص إشارات البامب (Pump Detection v10.0)...")
    chat_target = target_chat if target_chat else int(ADMIN_CHAT_ID)

    async with aiohttp.ClientSession() as session:
        # ✅ v10.0 — STEP 0: تحليل سياق البتكوين الذكي قبل أي شيء
        if BTC_FILTER_ENABLED:
            await analyze_btc_context(session)
            btc_emoji, btc_label = get_btc_status_emoji_and_label()
            logger.info(f"{btc_emoji} سياق BTC: {btc_label} | ATR {btc_context.get('atr_pct', 0):.2f}%")

            # لو في إيقاف بسبب crash → ما نكملش الدورة
            if btc_context.get("paused_until"):
                reason = btc_context.get("pause_reason", "BTC crash")
                logger.warning(f"⏸ الفحص موقوف: {reason} — في انتظار التعافي")
                return

        # 1️⃣ جلب كل عملات Gate.io USDT
        gate_tickers = await fetch_gate_tickers(session)
        if not gate_tickers:
            logger.error("❌ فشل جلب tickers من Gate.io")
            return

        # 2️⃣ فلتر العملات: فوليم 24h ≥ MIN
        candidates = []
        for t in gate_tickers:
            d = parse_gate_ticker(t)
            if not d: continue
            if d["symbol"] in EXCLUDED_SYMBOLS: continue
            if d["volume_24h"] < MIN_VOL_FOR_SIGNAL: continue
            if d["price"] <= 0: continue
            candidates.append(d)
        candidates = candidates[:GATE_MAX_CANDIDATES]

        # إثراء من CMC للحصول على الاسم الكامل، الفوليم الإجمالي العالمي، عدد الأسواق
        cmc_by_sym = {}
        try:
            cmc_raw = await fetch_cmc(session, limit=CMC_LIMIT)
            cmc_by_sym = {c.get("symbol", "").upper(): c for c in (cmc_raw or [])}
            for d in candidates:
                cmc = cmc_by_sym.get(d["symbol"].upper())
                if cmc:
                    d["name"] = cmc.get("name", d.get("name", ""))
                    d["tags"] = cmc.get("tags", [])
                    # ✅ v9.0 — فوليم العملة الإجمالي على كل المنصات
                    try:
                        quote_usd = (cmc.get("quote", {}) or {}).get("USD", {}) or {}
                        d["volume_global"] = float(quote_usd.get("volume_24h", 0) or 0)
                        d["num_market_pairs"] = int(cmc.get("num_market_pairs", 0) or 0)
                    except (ValueError, TypeError):
                        d["volume_global"] = 0
                        d["num_market_pairs"] = 0
        except Exception as e:
            logger.warning(f"إثراء CMC فشل: {e} — نكمل بالأسماء من Gate فقط")

        logger.info(f"📋 سيتم فحص {len(candidates)} عملة (فوليم ≥ ${MIN_VOL_FOR_SIGNAL/1_000:.0f}K)")

        # 3️⃣ تقييم الـ 12 شرط لكل عملة بالتوازي
        sem = asyncio.Semaphore(GATE_PARALLEL_LIMIT)
        async def analyze(coin):
            async with sem:
                try:
                    result = await evaluate_pump_signal(
                        session, coin["symbol"], coin["price"],
                        volume_24h=coin.get("volume_24h", 0)
                    )
                    # نضيف معلومات العملة
                    result["name"]             = coin.get("name", coin["symbol"])
                    result["volume_24h"]       = coin["volume_24h"]
                    result["volume_global"]    = coin.get("volume_global", 0)       # ✅ v9.0
                    result["num_market_pairs"] = coin.get("num_market_pairs", 0)    # ✅ v9.0
                    result["price_change_24h"] = coin["price_change_24h"]
                    return result
                except Exception as e:
                    logger.warning(f"خطأ تحليل {coin['symbol']}: {e}")
                    return None

        tasks   = [analyze(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # 4️⃣ فلترة: نحتفظ بالإشارات MODERATE+ فقط (لا Early Warning)
    all_results     = [r for r in results if r and not isinstance(r, Exception)]
    main_signals    = [r for r in all_results if r["strength"] in ("STRONG", "MODERATE")]

    # ✅ v6.4 — diagnostic: نعرض كم عملة وصلت لكل مستوى
    strong_count   = sum(1 for r in all_results if r["strength"] == "STRONG")
    moderate_count = sum(1 for r in all_results if r["strength"] == "MODERATE")
    ignored_count  = sum(1 for r in all_results if r["strength"] is None)
    logger.info(f"📊 نتائج الفحص: STRONG={strong_count}, MODERATE={moderate_count}, ignored={ignored_count}")

    # 5️⃣ إزالة المكررات + إعادة إرسال بشروط صارمة
    fresh_main = []
    for r in main_signals:
        sym = r["symbol"]
        if sym in seen_signals:
            entry = seen_signals[sym]
            # entry: tuple (datetime, score, strength) | tuple (datetime, score) | datetime
            last_strength = None
            if isinstance(entry, tuple):
                if len(entry) >= 3:
                    last_time, last_score, last_strength = entry[0], entry[1], entry[2]
                else:
                    last_time, last_score = entry[0], entry[1]
            else:
                last_time, last_score = entry, 0
            elapsed = (datetime.now() - last_time).total_seconds()
            within_cooldown = elapsed < PUMP_SIGNAL_COOLDOWN_MIN * 60

            # ✅ v6.4 — شروط إعادة الإرسال أصرم
            # 1) ترقية من MODERATE إلى STRONG
            upgraded = (PUMP_RESEND_ON_UPGRADE and
                        last_strength == "MODERATE" and
                        r["strength"] == "STRONG")
            # 2) النقاط زادت بـ 3+ نقاط على الأقل
            major_increase = (r["score"] - last_score) >= PUMP_RESEND_MIN_INCREASE

            if within_cooldown and not upgraded and not major_increase:
                logger.info(f"تخطي {sym} — cooldown ({int(elapsed/60)}m, "
                            f"score={r['score']} vs {last_score}, "
                            f"strength={r['strength']} vs {last_strength})")
                continue
            if upgraded:
                logger.info(f"⬆️ {sym} — ترقية من {last_strength} إلى {r['strength']} — إرسال")
            elif major_increase:
                logger.info(f"📈 {sym} — النقاط زادت {last_score}→{r['score']} (+{r['score']-last_score}) — إرسال")
        fresh_main.append(r)

    # 6️⃣ ترتيب: الأقوى أولاً
    fresh_main.sort(key=lambda x: x["score"], reverse=True)

    # ✅ v10.0 — فلتر BTC على الإشارات قبل الإرسال
    btc_filtered = []
    btc_rejected = 0
    for r in fresh_main:
        allowed, reason, warning = should_allow_signal(r)
        if not allowed:
            btc_rejected += 1
            logger.info(f"🚫 رفض {r['symbol']} — {reason}")
            continue
        # نضيف تحذير BTC للإشارة (لو موجود)
        r["btc_warning"] = warning
        # نضيف حالة BTC العامة للعرض في الإشارة
        emoji, label = get_btc_status_emoji_and_label()
        r["btc_status_emoji"] = emoji
        r["btc_status_label"] = label
        btc_filtered.append(r)

    if btc_rejected > 0:
        logger.info(f"🛡️ فلتر BTC: تم رفض {btc_rejected} إشارة بسبب سياق BTC")

    fresh_main = btc_filtered

    if not fresh_main:
        if btc_rejected > 0:
            logger.info(f"⏸ لا توجد إشارات بعد فلتر BTC (تم رفض {btc_rejected})")
        else:
            logger.info(f"✅ لا توجد إشارات بامب جديدة (فحص {len(candidates)} عملة)")
        return

    # 7️⃣ إرسال الإشارات (كل الإشارات بدون حد)
    sent_count = 0
    for r in fresh_main:
        try:
            msg = format_pump_signal_message(r)
            await bot.send_message(chat_id=chat_target, text=msg,
                                    parse_mode="MarkdownV2",
                                    disable_web_page_preview=True)
            # نخزن الوقت + النقاط + القوة (للسماح بإعادة الإرسال لو زادت أو ترقّت)
            seen_signals[r["symbol"]] = (datetime.now(), r["score"], r["strength"])
            sent_count += 1
            await asyncio.sleep(0.7)
        except Exception as e:
            logger.error(f"خطأ ارسال إشارة {r['symbol']}: {e}")

    logger.info(f"📤 تم إرسال {sent_count} إشارة")
    previous_signals = {r["symbol"]: r for r in fresh_main}
    save_seen_signals()   # ✅ v6.4 — حفظ بعد كل دفعة إشارات


# ============================================================
# نظام seen coins
# ============================================================
SEEN_FILE         = "seen_coins.json"
SEEN_SIGNALS_FILE = "seen_signals.json"   # ✅ v6.4

def load_seen_coins():
    global seen_coins
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r") as f:
                data = json.load(f)
            seen_coins = {k: datetime.fromisoformat(v) for k, v in data.items()}
            logger.info(f"تم تحميل {len(seen_coins)} عملة من seen_coins")
    except Exception as e:
        logger.error(f"خطأ تحميل seen_coins: {e}")

def save_seen_coins():
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump({k: v.isoformat() for k, v in seen_coins.items()}, f)
    except Exception as e:
        logger.error(f"خطأ حفظ seen_coins: {e}")


# ✅ v6.4 — حفظ/تحميل seen_signals (للحفاظ على cooldown بين إعادات التشغيل)
def load_seen_signals():
    global seen_signals
    try:
        if os.path.exists(SEEN_SIGNALS_FILE):
            with open(SEEN_SIGNALS_FILE, "r") as f:
                data = json.load(f)
            seen_signals = {}
            for k, v in data.items():
                # v: [timestamp_iso, score, strength]
                if isinstance(v, list) and len(v) >= 3:
                    seen_signals[k] = (datetime.fromisoformat(v[0]), v[1], v[2])
                elif isinstance(v, list) and len(v) == 2:
                    seen_signals[k] = (datetime.fromisoformat(v[0]), v[1], None)
            # نُزيل القديم جداً (أكثر من 24 ساعة) لتنظيف الملف
            now = datetime.now()
            seen_signals = {
                k: v for k, v in seen_signals.items()
                if (now - v[0]).total_seconds() < 86400
            }
            logger.info(f"✅ تم تحميل {len(seen_signals)} إشارة من seen_signals")
    except Exception as e:
        logger.error(f"خطأ تحميل seen_signals: {e}")

def save_seen_signals():
    try:
        out = {}
        for k, v in seen_signals.items():
            if isinstance(v, tuple) and len(v) >= 3:
                out[k] = [v[0].isoformat(), v[1], v[2]]
            elif isinstance(v, tuple) and len(v) == 2:
                out[k] = [v[0].isoformat(), v[1], None]
            else:
                out[k] = [v.isoformat() if isinstance(v, datetime) else str(v), 0, None]
        with open(SEEN_SIGNALS_FILE, "w") as f:
            json.dump(out, f)
    except Exception as e:
        logger.error(f"خطأ حفظ seen_signals: {e}")


# ✅ جديد v3.1: سكان البامب المستمر — يدور بلا توقف، يبعت لو لقى ويسكت لو ملقاش
async def continuous_signal_scanner(bot: Bot):
    """
    حلقة لا نهائية لفحص الإشارات. تشتغل في الخلفية طول عمل البوت.
    - لو لقى إشارة >= MIN_SCORE: يبعتها
    - لو ملقاش: يكمل الدورة التالية بدون رسالة
    - فاصل SIGNAL_LOOP_GAP_SECONDS بين الدورات (تخفيف الضغط على APIs)
    """
    logger.info(f"🔄 السكان المستمر — انطلاق خلال 15 ثانية... فاصل {SIGNAL_LOOP_GAP_SECONDS}ث بين الدورات")
    # ✅ v3.2: ننتظر 15 ثانية فقط بدل 60 (السكان يبدأ بسرعة)
    await asyncio.sleep(15)

    cycle = 0
    while True:
        try:
            cycle += 1
            # نتجنب التشغيل المتزامن لو حد عمل /scan في نفس اللحظة
            if job_locks["check_signals"].locked():
                logger.info(f"⏸  السكان المستمر [دورة {cycle}] — منتظر انتهاء فحص يدوي")
                await asyncio.sleep(SIGNAL_LOOP_GAP_SECONDS)
                continue

            async with job_locks["check_signals"]:
                last_job_run["check_signals"] = datetime.now()
                t0 = datetime.now()
                logger.info(f"🔍 دورة سكان مستمرة #{cycle} ...")
                await check_signals(bot)
                duration = (datetime.now() - t0).total_seconds()
                logger.info(f"✅ دورة #{cycle} انتهت في {duration:.0f}ث — انتظار {SIGNAL_LOOP_GAP_SECONDS}ث")

            await asyncio.sleep(SIGNAL_LOOP_GAP_SECONDS)

        except asyncio.CancelledError:
            logger.info("🛑 السكان المستمر — تم الإيقاف")
            raise
        except Exception as e:
            logger.error(f"❌ خطأ في دورة #{cycle}: {e}", exc_info=True)
            await asyncio.sleep(SIGNAL_LOOP_ERR_GAP)


# ==================== أوامر البوت ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Pump Detection Bot v10.0 — Gate.io + BTC Filter\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "نظام كشف البامب — 12 شرط (نسبة مئوية):\n\n"
        "⭐ الشروط الأساسية (70% — كل واحد 17.5%):\n"
        f"1️⃣ Funding Rate Anomaly     ({PUMP_W_FUNDING_RATE}%)\n"
        f"2️⃣ CVD Divergence            ({PUMP_W_CVD_DIVERGENCE}%)\n"
        f"3️⃣ Taker Buy Ratio           ({PUMP_W_TAKER_BUY_RATIO}%)\n"
        f"4️⃣ Order Book Imbalance      ({PUMP_W_OB_IMBALANCE}%)\n\n"
        "📊 الشروط التكميلية (30% — كل واحد 3.75%):\n"
        f"5️⃣ Volume Acceleration       ({PUMP_W_VOL_ACCEL}%)\n"
        f"6️⃣ Bid Wall (دعم قوي)         ({PUMP_W_BID_WALL}%)\n"
        f"7️⃣ Whale Accumulation 🐋      ({PUMP_W_WHALE_ACCUM}%)\n"
        f"8️⃣ EMA21 Crossover 📊         ({PUMP_W_EMA21_CROSS}%)\n"
        f"9️⃣ Multi-TF Buy Pressure 🔄   ({PUMP_W_MTF_BUY}%)\n"
        f"🔟 Short Liquidation 📉       ({PUMP_W_SHORT_LIQ}%)\n"
        f"1️⃣1️⃣ Micro Momentum 3m ⚡       ({PUMP_W_MICRO_MOMENTUM}%)\n"
        f"1️⃣2️⃣ Micro Vol Surge 3m 📈     ({PUMP_W_MICRO_VOL_SURGE}%)\n\n"
        f"🚀 STRONG ≥ {PUMP_SCORE_STRONG:.0f}%\n"
        f"⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE:.0f}%\n"
        f"✅ 4/4 أساسية = إشارة وحدها (= 70%)\n"
        f"✅ شرط الإرسال: 3/4 أساسية على الأقل\n\n"
        "🟠 فلتر سياق البتكوين (v10.0):\n"
        "  🟢 BTC صاعد/محايد:    السماح بكل الإشارات\n"
        f"  🟡 BTC bearish خفيف ({BTC_BEARISH_LIGHT_4H}% إلى {BTC_BEARISH_STRONG_4H}% في 4h): تحذير\n"
        f"  🔴 BTC bearish قوي (< {BTC_BEARISH_STRONG_4H}% في 4h):   رفض الإشارات\n"
        f"  ⚠️ BTC crash (< {BTC_CRASH_1H}% في 1h):       إيقاف تلقائي\n\n"
        f"🌐 المصدر: كل عملات Gate.io USDT\n"
        f"   فلتر: فوليم 24h ≥ ${MIN_VOL_FOR_SIGNAL/1_000:.0f}K\n"
        f"   📊 الإشارة تعرض الفوليم على Gate + إجمالي العالم\n"
        f"🔄 سكان مستمر — فاصل {SIGNAL_LOOP_GAP_SECONDS}ث\n"
        f"⏱ Cooldown: {PUMP_SIGNAL_COOLDOWN_MIN}m (إلا لو النقاط زادت 7%+)\n\n"
        "الأوامر:\n"
        "/status      — حالة البوت\n"
        "/btc         — حالة سياق البتكوين الآن\n"
        "/chatid      — معرفة الـ Chat ID"
    )


async def cmd_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✅ v10.0 — أمر جديد: عرض حالة سياق البتكوين"""
    # نحدّث الحالة (لو cache قديم)
    async with aiohttp.ClientSession() as session:
        await analyze_btc_context(session)

    emoji, label = get_btc_status_emoji_and_label()
    status = btc_context.get("status", "unknown")
    c4 = btc_context.get("change_4h", 0)
    c1 = btc_context.get("change_1h", 0)
    atr = btc_context.get("atr_pct", 0)
    price = btc_context.get("price", 0)
    paused = btc_context.get("paused_until")
    pause_reason = btc_context.get("pause_reason", "")

    # قرار الفلتر
    if status == "crash":
        decision = "🚨 الفحص متوقف تلقائياً (BTC crash)"
    elif status == "bearish_strong":
        decision = "🚫 رفض كل الإشارات (BTC bearish قوي)"
    elif status == "bearish_light":
        decision = "🟡 السماح + تحذير في الإشارات"
    elif atr >= BTC_HIGH_VOLATILITY_ATR:
        decision = f"🟡 السماح + تحذير (تقلب عالي ATR {atr:.1f}%)"
    elif status in ("bullish", "neutral"):
        decision = "✅ السماح الكامل بالإشارات"
    else:
        decision = "⚪ غير محدد"

    msg = (
        f"🟠 *حالة سياق البتكوين*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{emoji} *الحالة:* {label}\n"
        f"💰 *السعر:* ${price:,.0f}\n"
        f"📊 *تغيّر 1h:* {c1:+.2f}%\n"
        f"📊 *تغيّر 4h:* {c4:+.2f}%\n"
        f"📈 *ATR (1h):* {atr:.2f}%\n\n"
        f"⚖️ *قرار الفلتر:*\n{decision}\n"
    )
    if paused:
        msg += f"\n⏸ *إيقاف نشط:*\n{pause_reason}\n"

    msg += (
        f"\n━━━━━━━━━━━━━━━━━━\n"
        f"📋 *عتبات الفلتر:*\n"
        f"🟡 bearish خفيف:  {BTC_BEARISH_LIGHT_4H}% إلى {BTC_BEARISH_STRONG_4H}% (4h)\n"
        f"🔴 bearish قوي:   < {BTC_BEARISH_STRONG_4H}% (4h)\n"
        f"🚨 crash:          < {BTC_CRASH_1H}% (1h)\n"
        f"✅ تعافي:          ≥ {BTC_RECOVERY_1H}% (1h)\n"
        f"⚡ تقلب عالي:     ATR ≥ {BTC_HIGH_VOLATILITY_ATR}%"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # حالة السكان المستمر
    scanner = context.application.bot_data.get("scanner_task")
    if scanner and not scanner.done():
        scanner_status = "🔄 شغال مستمر"
    elif scanner and scanner.done():
        exc = scanner.exception() if not scanner.cancelled() else None
        scanner_status = f"⛔ متوقف (خطأ: {exc})" if exc else "⛔ متوقف"
    else:
        scanner_status = "⏳ لم يبدأ بعد"
    last = last_job_run.get("check_signals")
    if last:
        elapsed = (datetime.now() - last).total_seconds()
        last_str = f"{last.strftime('%H:%M:%S')} (منذ {int(elapsed)}ث)"
    else:
        last_str = "لم يبدأ بعد"
    # ✅ v10.0 — حالة سياق BTC
    btc_emoji, btc_label = get_btc_status_emoji_and_label()
    btc_paused = "⏸ نعم — " + str(btc_context.get("pause_reason", "")) if btc_context.get("paused_until") else "▶️ لا"

    await update.message.reply_text(
        f"✅ Pump Detection Bot — v10.0\n\n"
        f"🌐 المصدر: كل Gate.io USDT\n"
        f"   فلتر: فوليم ≥ ${MIN_VOL_FOR_SIGNAL/1_000:.0f}K\n"
        f"   توازي: {GATE_PARALLEL_LIMIT} طلب\n\n"
        f"🚀 سكان البامب: {scanner_status}\n"
        f"   فاصل: {SIGNAL_LOOP_GAP_SECONDS}ث\n"
        f"   آخر دورة: {last_str}\n\n"
        f"🟠 سياق البتكوين:\n"
        f"   {btc_emoji} {btc_label}\n"
        f"   تغيّر 1h: {btc_context.get('change_1h', 0):+.2f}% | "
        f"4h: {btc_context.get('change_4h', 0):+.2f}%\n"
        f"   ATR (1h): {btc_context.get('atr_pct', 0):.2f}%\n"
        f"   إيقاف الفحص: {btc_paused}\n\n"
        f"📊 نظام النقاط (نسبة مئوية):\n"
        f"   المجموع الأقصى: {PUMP_MAX_SCORE:.0f}%\n"
        f"   🚀 STRONG ≥ {PUMP_SCORE_STRONG:.0f}%\n"
        f"   ⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE:.0f}%\n"
        f"   Cooldown: {PUMP_SIGNAL_COOLDOWN_MIN} دقيقة\n\n"
        f"🔬 الشروط النشطة (12):\n"
        f"   ⭐ الأساسية (70%):\n"
        f"   1. Funding Rate Anomaly     (17.5%)\n"
        f"   2. CVD Divergence           (17.5%)\n"
        f"   3. Taker Buy Ratio          (17.5%)\n"
        f"   4. Order Book Imbalance     (17.5%)\n"
        f"   📊 التكميلية (30%):\n"
        f"   5. Volume Acceleration      (3.75%)\n"
        f"   6. Bid Wall (دعم شراء قوي)   (3.75%)\n"
        f"   7. Whale Accumulation 🐋     (3.75%)\n"
        f"   8. EMA21 Crossover 📊        (3.75%)\n"
        f"   9. Multi-TF Buy Pressure 🔄  (3.75%)\n"
        f"   10. Short Liquidation 📉    (3.75%)\n"
        f"   11. Micro Momentum 3m ⚡     (3.75%)\n"
        f"   12. Micro Vol Surge 3m 📈   (3.75%)\n\n"
        f"✅ 4/4 أساسية = STRONG وحدها (= 70%)\n"
        f"✅ شرط الإرسال: 3/4 أساسية على الأقل\n"
        f"📊 الإشارة تعرض الفوليم على Gate + إجمالي العالم\n"
        f"🎯 هدف/استوب ديناميكي مبني على ATR\n"
        f"🔒 Lock نشط ضد الإرسال المزدوج"
    )

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID:\n{update.effective_chat.id}")


# ✅ post_init hook لبدء السكان المستمر في الخلفية بعد جاهزية البوت
async def _post_init(app: Application):
    # نشغل السكان المستمر كـ background task
    task = asyncio.create_task(continuous_signal_scanner(app.bot))
    app.bot_data["scanner_task"] = task
    logger.info("=" * 50)
    logger.info("✅ تم تشغيل السكان المستمر في الخلفية")
    logger.info(f"   فاصل بين الدورات: {SIGNAL_LOOP_GAP_SECONDS}ث")
    logger.info(f"   حد الإشارة: score ≥ {MIN_SCORE}")
    logger.info(f"   Cooldown للعملة الواحدة: {SIGNAL_COOLDOWN_HOURS} ساعات")
    logger.info("=" * 50)
    # تنبيه الأدمن إن البوت بدأ
    try:
        await app.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=(
                "🟢 *Pump Detection Bot v10.0 — Gate.io + BTC Filter*\n"
                f"🚀 السكان المستمر: شغال (فاصل {SIGNAL_LOOP_GAP_SECONDS}ث)\n"
                f"🌐 يفحص كل عملات Gate.io USDT (فوليم ≥ ${MIN_VOL_FOR_SIGNAL/1_000:.0f}K)\n"
                f"⚡ 12 شرط نشطة | نسبة مئوية (المجموع: 100%)\n"
                f"🚀 STRONG ≥ {PUMP_SCORE_STRONG:.0f}% | ⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE:.0f}%\n"
                f"✅ 4/4 أساسية = إشارة وحدها\n"
                f"🟠 فلتر BTC الذكي نشط — استخدم /btc لمعرفة الحالة"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"لم نستطع إرسال رسالة البدء: {e}")


async def _post_shutdown(app: Application):
    # إيقاف السكان المستمر بأمان عند إغلاق البوت
    task = app.bot_data.get("scanner_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("✅ تم إيقاف السكان المستمر")


# ==================== ✅ تشغيل البوت مع منع التشغيل المزدوج ====================
def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("chatid",  cmd_chatid))
    app.add_handler(CommandHandler("btc",     cmd_btc))   # ✅ v10.0

    load_seen_coins()
    load_seen_signals()   # ✅ v6.4

    # ✅ التأكد من إضافة الـ jobs مرة واحدة فقط
    jq = app.job_queue
    # إزالة أي jobs قديمة بنفس الاسم (احتياط)
    for j in list(jq.jobs()):
        try: j.schedule_removal()
        except: pass

    # ✅ v5.0 — السكان المستمر فقط (تم حذف تقرير الفوليوم)
    # السكان يبدأ من post_init كـ background task

    print("="*60)
    print("🚀 Pump Detection Bot v10.0 — Gate.io + BTC Filter")
    print(f"🌐 المصدر: كل Gate.io USDT (سقف {GATE_MAX_CANDIDATES} عملة)")
    print(f"   فلتر أولي: فوليم 24h ≥ ${MIN_VOL_FOR_SIGNAL/1_000:.0f}K")
    print(f"   توازي: {GATE_PARALLEL_LIMIT} طلب")
    print(f"")
    print(f"🚨 نظام البامب (12 شرط — نسبة مئوية):")
    print(f"   ⭐ الأساسية (70% — كل واحد 17.5%):")
    print(f"   1. Funding Rate Anomaly      ({PUMP_W_FUNDING_RATE}%)")
    print(f"   2. CVD Divergence             ({PUMP_W_CVD_DIVERGENCE}%)")
    print(f"   3. Taker Buy Ratio            ({PUMP_W_TAKER_BUY_RATIO}%)")
    print(f"   4. Order Book Imbalance       ({PUMP_W_OB_IMBALANCE}%)")
    print(f"   📊 التكميلية (30% — كل واحد 3.75%):")
    print(f"   5. Volume Acceleration        ({PUMP_W_VOL_ACCEL}%)")
    print(f"   6. Bid Wall                   ({PUMP_W_BID_WALL}%)")
    print(f"   7. Whale Accumulation         ({PUMP_W_WHALE_ACCUM}%)")
    print(f"   8. EMA21 Crossover            ({PUMP_W_EMA21_CROSS}%)")
    print(f"   9. Multi-TF Buy Pressure      ({PUMP_W_MTF_BUY}%)")
    print(f"   10. Short Liquidation         ({PUMP_W_SHORT_LIQ}%)")
    print(f"   11. Micro Momentum 3m ⚡       ({PUMP_W_MICRO_MOMENTUM}%)")
    print(f"   12. Micro Vol Surge 3m 📈     ({PUMP_W_MICRO_VOL_SURGE}%)")
    print(f"   ───────────────────────────")
    print(f"   المجموع الأقصى: {PUMP_MAX_SCORE:.0f}%")
    print(f"   🚀 STRONG ≥ {PUMP_SCORE_STRONG:.0f}%  |  ⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE:.0f}%")
    print(f"   ✅ 4/4 أساسية = STRONG وحدها (= 70%)")
    print(f"   ✅ شرط الإرسال: 3/4 أساسية على الأقل")
    print(f"")
    print(f"🟠 فلتر سياق البتكوين (v10.0):")
    print(f"   🟢 BTC صاعد/محايد:                  السماح الكامل")
    print(f"   🟡 BTC bearish خفيف ({BTC_BEARISH_LIGHT_4H}% إلى {BTC_BEARISH_STRONG_4H}% in 4h): السماح + تحذير")
    print(f"   🔴 BTC bearish قوي (< {BTC_BEARISH_STRONG_4H}% in 4h):     رفض الإشارات")
    print(f"   🚨 BTC crash (< {BTC_CRASH_1H}% in 1h):                 إيقاف تلقائي")
    print(f"   ✅ التعافي تلقائي (≥ {BTC_RECOVERY_1H}% in 1h)")
    print(f"   ⚡ تقلب عالي ATR ≥ {BTC_HIGH_VOLATILITY_ATR}%:           تحذير")
    print(f"")
    print(f"🔄 السكان المستمر: فاصل {SIGNAL_LOOP_GAP_SECONDS}ث بين الدورات")
    print(f"   Cooldown لكل عملة: {PUMP_SIGNAL_COOLDOWN_MIN} دقيقة (إلا لو النقاط زادت 7%+)")
    print(f"📊 الإشارة تعرض الفوليم على Gate + إجمالي العالم من CMC")
    print(f"🔔 الإرسال: الأدمن فقط")
    print(f"🔒 Lock نشط ضد الإرسال المزدوج")
    print(f"📲 أوامر جديدة: /btc لعرض حالة البتكوين")
    print("="*60)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
