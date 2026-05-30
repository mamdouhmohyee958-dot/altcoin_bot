"""
🚀 Pump Detection Bot v11.0 — Gate.io Edition (Pre-Pump Engine)
نظام كشف البامب المحسّن بـ 12 شرط + 6 تحسينات دقة:
  ⭐ الأساسية (4): Funding Rate, CVD Divergence, Taker Buy Ratio, Order Book Imbalance
  📊 التكميلية (8): Volume Acceleration, Bid Wall, Whale Accumulation,
                    VWAP Position, Multi-TF Buy Pressure, Liquidity Grab,
                    Candle Momentum, Early Volume Surge
  🔒 فلاتر الدقة: Anti-Wash Trading, Confluence Check, EMA50/4h Trend,
                  Spread Filter, Score History Penalty, S/R Targets
الأوامر: /start, /status, /btc, /chatid
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

# ==================== فلتر البيتكوين ====================
BTC_FILTER_ENABLED    = True
BTC_BEARISH_STRONG    = -2.0   # 4h change < -2% → رفض كل الإشارات
BTC_BEARISH_LIGHT_MIN = -2.0   # 4h between -1% and -2% → تحذير
BTC_BEARISH_LIGHT_MAX = -1.0
BTC_HIGH_ATR_PCT      = 2.0    # ATR >= 2% → تحذير
BTC_CRASH_1H          = -2.0   # 1h < -2% → إيقاف فوري
BTC_RECOVERY_1H       = -0.5   # 1h >= -0.5% → استئناف تلقائي

# ==================== فلاتر الدقة الجديدة v10 ====================
# --- Anti Wash Trading ---
WASH_REPEAT_THRESHOLD    = 0.001   # صفقتان بنفس الحجم ±0.1% = wash
WASH_MIN_REPEAT_COUNT    = 5       # لو 5+ صفقات متكررة = مشبوه
WASH_MAX_RATIO           = 0.30    # لو wash > 30% من الصفقات = رفض

# --- Spread Filter ---
SPREAD_MAX_PCT           = 0.005   # spread > 0.5% = سيولة ضعيفة → تجاهل

# --- Confluence Penalty ---
# لو CVD قوي لكن OB ضعيف = نقص في الثقة
CONFLUENCE_PENALTY_PCT   = 5       # خصم 5% من النسبة النهائية

# --- EMA50 Trend Filter (4h) ---
EMA50_CANDLES_4H         = 60      # آخر 60 شمعة 4h لحساب EMA50

# --- Score History Penalty ---
# لو العملة بعتت إشارة قبل كده وما تحركتش = خصم
HISTORY_PENALTY_PCT      = 10      # خصم 10% لو سبق إرسالها وفشلت
HISTORY_FAIL_THRESHOLD   = 0.005   # السعر ما تغيرش أكتر من 0.5% = فشل

# ==================== اعدادات الاشارات ====================
MIN_SCORE          = 45       # الحد الأدنى للإرسال (نسبة مئوية %)
MIN_VOL_FOR_SIGNAL = 25_000

# ✅ جديد v3.1: سكان البامب المستمر
SIGNAL_LOOP_GAP_SECONDS = 120     # ✅ v4.1: 120ث بدل 90 (لأن الفحص الآن أكبر)
SIGNAL_LOOP_ERR_GAP     = 30      # فاصل بعد خطأ
SIGNAL_COOLDOWN_HOURS     = 6     # كان 24h — قللناه عشان السكان المستمر
GATE_MAX_CANDIDATES       = 5000       # فحص كل عملات Gate.io
GATE_PARALLEL_LIMIT       = 30         # طلبات متوازية

# ── Pre-scan Filter (المرحلة 1) ──
PRESCAN_MIN_VOL_24H       = 25_000     # فوليم 24h ≥ $25K
PRESCAN_MIN_CHANGE_24H    = -15.0      # تغيّر 24h > -15% (مش انهيار)
PRESCAN_MAX_CHANGE_24H    = 25.0       # تغيّر 24h < +25% (مش فات القطار)
PRESCAN_MIN_ACTIVITY      = 0.3        # range_24h / price ≥ 0.3% (في حركة)
PRESCAN_LARGE_VOL         = 3_000_000  # فوليم ≥ $3M = تتفحص دايماً بغض النظر عن التغيّر
PRESCAN_MAX_PULLBACK      = 15.0       # لو القمة أعلى من السعر الحالي بـ 15%+ = بامب وراح

# ════════════════════════════════════════════════════════════════════
# ✅ v8.0 — PUMP DETECTION (12 شرط قوية — Gate.io)
# ════════════════════════════════════════════════════════════════════
# الـ 4 شروط الأساسية: Funding + CVD + Taker + OB Imbalance
# + 6 شروط تكميلية قوية تأكد الجودة
# لا "قيد المراقبة" — فقط فرص جاهزة
# الإشارة لا تتكرر إلا لو النقاط زادت
# ════════════════════════════════════════════════════════════════════

# ───── الشروط الـ 4 الأساسية (كل شرط = 15% من المجموع) ─────
PUMP_W_FUNDING_RATE      = 6   # 1) ⭐ Funding Rate Anomaly    (15%)
PUMP_W_CVD_DIVERGENCE    = 6   # 2) ⭐ CVD Divergence          (15%)
PUMP_W_TAKER_BUY_RATIO   = 6   # 3) ⭐ Taker Buy Ratio         (15%)
PUMP_W_OB_IMBALANCE      = 6   # 4) ⭐ Order Book Imbalance    (15%)

# ───── الشروط الـ 6 التكميلية ─────
PUMP_W_VOL_ACCEL         = 3   # 5) Volume Acceleration
PUMP_W_BID_WALL          = 3   # 6) Bid Wall (دعم شراء قوي)
PUMP_W_WHALE_ACCUM       = 3   # 7) ✅ جديد — Whale Accumulation
PUMP_W_EMA21_CROSS       = 3   # 8) ✅ جديد — EMA21 Crossover
PUMP_W_MTF_BUY           = 3   # 9) ✅ جديد — Multi-Timeframe Buy Pressure
PUMP_W_SHORT_LIQ         = 4   # 10) ✅ جديد — Short Liquidation

PUMP_MAX_SCORE           = 45  # المجموع الأقصى (24 أساسية + 21 تكميلية) — كل أساسي 15%
PUMP_SCORE_STRONG        = 31  # 🚀 STRONG (≈ 68%)
PUMP_SCORE_MODERATE      = 23  # ⚠️ MODERATE (≈ 50%)
PUMP_SIGNAL_COOLDOWN_MIN = 180 # ✅ v6.4 — 3 ساعات بدل ساعة
PUMP_RESEND_MIN_INCREASE = 3   # ✅ v6.4 — لازم النقاط تزيد 3+ لإعادة الإرسال
PUMP_RESEND_ON_UPGRADE   = True # ✅ v6.4 — إعادة الإرسال لو ترقّى من MODERATE لـ STRONG


# ───── عتبات الشروط ─────
# ── Funding Rate (4 مستويات) ──
PUMP_FUNDING_RATE_L1     = -0.0003   # -0.03% → 5%
PUMP_FUNDING_RATE_L2     = -0.0005   # -0.05% → 10%
PUMP_FUNDING_RATE_L3     = -0.0010   # -0.10% → 15%
# backward compat
PUMP_FUNDING_RATE_LOW    = -0.0005
PUMP_FUNDING_RATE_VLOW   = -0.0010

# ── CVD Divergence (4 مستويات) ──
PUMP_CVD_L1              = 10.0      # CVD ≥ 10%  → 5%
PUMP_CVD_L2              = 25.0      # CVD ≥ 25%  → 10%
PUMP_CVD_L3              = 50.0      # CVD ≥ 50%  → 15%
PUMP_CVD_CHANGE_PCT      = 15.0      # backward compat
PUMP_CVD_STRONG_PCT      = 50.0
PUMP_PRICE_CHANGE_PCT    = 1.5       # السعر متحرك < 1.5%

# ── Taker Buy Ratio (4 مستويات) ──
PUMP_TAKER_L1            = 0.58      # ≥ 58% → 5%
PUMP_TAKER_L2            = 0.65      # ≥ 65% → 10%
PUMP_TAKER_L3            = 0.72      # ≥ 72% → 15%
PUMP_TAKER_RATIO_MIN     = 0.60      # backward compat
PUMP_TAKER_RATIO_STRONG  = 0.70

# ── Order Book Imbalance (4 مستويات) ──
PUMP_OB_L1               = 0.62      # ≥ 62% → 5%
PUMP_OB_L2               = 0.72      # ≥ 72% → 10%
PUMP_OB_L3               = 0.85      # ≥ 85% → 15%
PUMP_OB_IMBALANCE_MIN    = 0.70      # backward compat
PUMP_OB_IMBALANCE_STRONG = 0.85
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

# ───── 11) Candle Momentum — شمعة الاندفاع ─────
PUMP_W_CANDLE_MOM        = 1         # نقطة واحدة
PUMP_CANDLE_BODY_PCT     = 0.70      # جسم الشمعة >= 70% من الـ range = اندفاع قوي
PUMP_CANDLE_VOL_X        = 1.5       # فوليم الشمعة >= 1.5x متوسط آخر 7 شموع

# ───── 12) Early Volume Surge — اندفاع الفوليم المبكر ─────
PUMP_W_EARLY_SURGE       = 1         # نقطة واحدة
# الشرطين الجداد (13, 14)
PUMP_W_VOL_PRICE_CONF    = 1         # 13) Volume/Price Confirmation
PUMP_W_BUYSELL_PRESSURE  = 1         # 14) Buy/Sell Pressure

# ───── تأكيد إلزامي للفوليم/الشراء (v11) ─────
# الإشارة لازم يكون فيها تأكيد قوي واحد على الأقل من دول، غير كده تترفض
CONFIRM_VOL_SURGE_X      = 2.0       # فوليم الشمعة >= 2x المتوسط
CONFIRM_BUY_PRESSURE     = 0.62      # ضغط شراء >= 62%
CONFIRM_REQUIRED         = True      # تفعيل الشرط الإلزامي
PUMP_EARLY_SURGE_MIN_X   = 2.0       # فوليم أول شمعة 15m >= 2x متوسط الـ 7 شموع قبلها

# ───── 🔮 Pre-Pump Detector (v11) — رصد الصعود قبل حدوثه ─────
# يجمع 4 إشارات مبكرة في درجة واحدة (0-100):
PREPUMP_WHALE_WEIGHT     = 30        # تراكم الحيتان
PREPUMP_WALL_WEIGHT      = 20        # جدران الشراء
PREPUMP_VOLSURGE_WEIGHT  = 30        # انفجار الفوليم المبكر
PREPUMP_ACCEL_WEIGHT     = 20        # تسارع ضغط الشراء
PREPUMP_BONUS_PCT        = 10        # لو الدرجة >= 60 → +10% للإشارة
PREPUMP_STRONG_THRESHOLD = 60        # حد "صعود وشيك"
PREPUMP_ELITE_THRESHOLD  = 80        # حد "انفجار وشيك جداً"

# ═══════════════════════════════════════════════════════════════
# ✅ تحديث: مجموع الأوزان الجديد = 32 + 1 + 1 = 34
# الـ STRONG و MODERATE اتعدلوا بنفس النسبة (~69% و ~50%)
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
btc_crashed:      bool = False   # حالة إيقاف الفحص بسبب Crash

# ==================== ✅ منع الإرسال المزدوج ====================
job_locks = {
    "check_signals": asyncio.Lock(),
}
last_job_run = {
    "check_signals": None,
}

# ==================== العملات المحرمة (يدوي) ====================
# أضف هنا أي عملة تعتبرها محرمة أو مشبوهة
HARAM_SYMBOLS = {
    # ميم كوينز / قمار
    "FARTCOIN",
    # مشاريع مشبوهة
    "CTR",     # CTRUSDT
    "UP",      # UPUSDT
    "ESPORTS", # ESPORTSUSDT
    "SLX",     # SLXUSDT
    "BAS",     # BASUSDT
    "BEAT",    # BEATUSDT
    "GENIUS",  # GENIUSUSDT
    # أضف هنا ↓
}

HARAM_FILE = "haram_symbols.json"

def normalize_symbol(raw):
    """تطبيع رمز العملة: حروف كبيرة + إزالة USDT/مسافات/رموز."""
    if not raw:
        return ""
    s = str(raw).upper().strip()
    # إزالة اللاحقات الشائعة
    for suffix in ("_USDT", "/USDT", "-USDT", "USDT"):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            break
    # إزالة أي رموز غير حروف/أرقام
    s = "".join(ch for ch in s if ch.isalnum())
    return s.strip()

def load_haram_symbols():
    """تحميل العملات المحرمة من الملف ودمجها مع الافتراضية."""
    global HARAM_SYMBOLS
    try:
        import os, json
        if os.path.exists(HARAM_FILE):
            with open(HARAM_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # تطبيع كل الرموز المحمّلة
            HARAM_SYMBOLS = {normalize_symbol(s) for s in saved if s}
            # نضيف الافتراضية كمان
            for s in ["FARTCOIN","CTR","UP","ESPORTS","SLX","BAS","BEAT","GENIUS"]:
                HARAM_SYMBOLS.add(s)
    except Exception:
        pass

def save_haram_symbols():
    """حفظ العملات المحرمة في الملف."""
    try:
        import json
        with open(HARAM_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(HARAM_SYMBOLS), f, ensure_ascii=False)
    except Exception:
        pass

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




async def fetch_cmc_quote(session, symbol):
    """
    يجيب بيانات عملة واحدة من CMC (الفوليم الإجمالي عبر كل المنصات).
    Returns: dict {name, volume_24h, price, change_24h, num_pairs} أو None
    """
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}
    params  = {"symbol": symbol.upper(), "convert": "USD"}
    try:
        async with session.get(url, headers=headers, params=params,
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                return None
            data = await r.json()
        coin_data = data.get("data", {}).get(symbol.upper())
        if not coin_data:
            return None
        # قد ترجع list لو في أكثر من عملة بنفس الرمز
        if isinstance(coin_data, list):
            coin_data = coin_data[0]
        quote = coin_data.get("quote", {}).get("USD", {})
        return {
            "name":        coin_data.get("name", symbol),
            "symbol":      coin_data.get("symbol", symbol),
            "volume_24h":  float(quote.get("volume_24h", 0) or 0),
            "price":       float(quote.get("price", 0) or 0),
            "change_24h":  float(quote.get("percent_change_24h", 0) or 0),
            "num_pairs":   coin_data.get("num_market_pairs", 0),
        }
    except Exception as e:
        logger.error(f"CMC quote error ({symbol}): {e}")
        return None


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




import re as _re_lev
_LEVERAGED_PATTERN = _re_lev.compile(r"(\d+)(L|S)$")  # 3L, 5L, 3S, 5S...

def is_leveraged_token(symbol):
    """
    كشف التوكنات ذات الرافعة المالية (Leveraged Tokens).
    أمثلة: BTC3L, ETH5S, NEAR5S, WLD3L
    دي توكنات خطيرة (بتتآكل قيمتها) ومش عملات حقيقية للتداول.
    """
    s = symbol.upper()
    # ينتهي برقم + L أو S (3L, 5S, 3S, 5L...)
    if _LEVERAGED_PATTERN.search(s):
        return True
    # حالات شائعة أخرى
    if s.endswith("UP") or s.endswith("DOWN") or s.endswith("BULL") or s.endswith("BEAR"):
        return True
    return False


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



async def fetch_btc_status(session):
    """
    يجيب حالة البيتكوين من Gate.io:
    - تغيّر 1h (crash detection)
    - تغيّر 4h (اتجاه السوق)
    - ATR 4h (تقلب)
    Returns: dict {change_1h, change_4h, atr_pct, status, warning}
    """
    try:
        kl1h = await fetch_klines(session, "BTC", interval="1h", limit=6)
        kl4h = await fetch_klines(session, "BTC", interval="4h", limit=16)
    except Exception:
        return {"status": "UNKNOWN", "warning": None, "change_1h": 0, "change_4h": 0, "atr_pct": 0}

    # تغيّر 1h
    change_1h = 0.0
    if kl1h and len(kl1h) >= 2:
        c_now  = kl1h[-1]["close"]
        c_prev = kl1h[-2]["close"]
        if c_prev > 0:
            change_1h = (c_now - c_prev) / c_prev * 100

    # تغيّر 4h
    change_4h = 0.0
    if kl4h and len(kl4h) >= 2:
        c_now  = kl4h[-1]["close"]
        c_prev = kl4h[-2]["close"]
        if c_prev > 0:
            change_4h = (c_now - c_prev) / c_prev * 100

    # ATR 4h (آخر 14 شمعة)
    atr_pct = 0.0
    if kl4h and len(kl4h) >= 15:
        last = kl4h[-15:]
        trs = []
        for i in range(1, len(last)):
            h, l, pc = last[i]["high"], last[i]["low"], last[i-1]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = sum(trs) / len(trs) if trs else 0
        price = kl4h[-1]["close"]
        atr_pct = (atr / price * 100) if price > 0 else 0

    # تحديد الحالة
    if change_1h < BTC_CRASH_1H:
        status  = "CRASH"
        warning = f"🚨 BTC Crash: {change_1h:.2f}% في 1h — الفحص موقوف تلقائياً"
    elif change_4h < BTC_BEARISH_STRONG:
        status  = "BEARISH_STRONG"
        warning = f"🔴 BTC Bearish قوي: {change_4h:.2f}% في 4h — تم رفض كل الإشارات"
    elif BTC_BEARISH_LIGHT_MIN <= change_4h < BTC_BEARISH_LIGHT_MAX:
        status  = "BEARISH_LIGHT"
        warning = f"🟡 BTC Bearish خفيف: {change_4h:.2f}% في 4h — تحذير"
    elif atr_pct >= BTC_HIGH_ATR_PCT:
        status  = "HIGH_VOL"
        warning = f"🟡 BTC تقلب عالي: ATR {atr_pct:.2f}% — تحذير"
    elif change_4h >= 1.0:
        status  = "BULLISH"
        warning = None
    else:
        status  = "NEUTRAL"
        warning = None

    return {
        "status":    status,
        "warning":   warning,
        "change_1h": change_1h,
        "change_4h": change_4h,
        "atr_pct":   atr_pct,
    }


async def fetch_gate_recent_trades(session, symbol, limit=1000):
    """
    شروط 2 و 4: آخر الصفقات لحساب CVD و Taker Buy Ratio
    Gate.io: 'side' = 'buy' معناها taker buy، 'sell' = taker sell
    v10: نجيب أكبر عدد ممكن (1000 = الحد الأقصى لـ Gate.io)
    """
    url = "https://api.gateio.ws/api/v4/spot/trades"
    params = {"currency_pair": f"{symbol}_USDT", "limit": min(limit, 1000)}
    try:
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200: return []
            data = await r.json()
        out = []
        for t in data:
            try:
                qty   = float(t.get("amount", 0))
                price = float(t.get("price", 0))
                if qty <= 0 or price <= 0:
                    continue
                out.append({
                    "ts":     int(float(t.get("create_time_ms", 0))),
                    "side":   t.get("side", ""),
                    "qty":    qty,
                    "price":  price,
                })
            except (ValueError, TypeError):
                continue
        return out
    except Exception:
        return []


def detect_wash_trading(trades):
    """
    v10 — كشف Wash Trading:
    لو نسبة الصفقات المتكررة بنفس الحجم تقريباً > 30% = مشبوه.
    Returns: (is_wash: bool, wash_ratio: float)
    """
    if not trades or len(trades) < 20:
        return False, 0.0
    qtys = [round(t["qty"], 4) for t in trades]
    from collections import Counter
    counts = Counter(qtys)
    repeat_trades = sum(c for c in counts.values() if c >= WASH_MIN_REPEAT_COUNT)
    wash_ratio = repeat_trades / len(trades)
    return wash_ratio > WASH_MAX_RATIO, wash_ratio


def check_spread(ob, current_price):
    """
    v10 — فلتر السيولة عبر الـ Spread:
    لو الفرق بين أفضل bid وأفضل ask > 0.5% = سيولة ضعيفة.
    Returns: (spread_ok: bool, spread_pct: float)
    """
    if not ob or not ob.get("bids") or not ob.get("asks") or current_price <= 0:
        return True, 0.0   # مش متاح = نتجاوز الفلتر
    best_bid = ob["bids"][0][0] if ob["bids"] else 0
    best_ask = ob["asks"][0][0] if ob["asks"] else 0
    if best_bid <= 0 or best_ask <= 0:
        return True, 0.0
    spread_pct = (best_ask - best_bid) / current_price
    return spread_pct <= SPREAD_MAX_PCT, spread_pct


def check_confluence(r2, r4):
    """
    v10 — Confluence Check:
    CVD قوي (pass) لكن OB Imbalance ضعيف (fail) = خصم ثقة.
    Returns: penalty_pct (0 أو CONFLUENCE_PENALTY_PCT)
    """
    cvd_strong = r2.get("pass") and r2.get("value", 0) > 30
    ob_weak    = not r4.get("pass")
    if cvd_strong and ob_weak:
        return CONFLUENCE_PENALTY_PCT
    return 0


async def fetch_ema50_4h(session, symbol):
    """
    v10 — EMA50 على 4h للتأكد من الاتجاه الكبير.
    السعر فوق EMA50/4h = اتجاه صعودي كبير = إشارة أقوى.
    Returns: (above_ema50: bool, ema50_val: float)
    """
    candles = await fetch_klines(session, symbol, interval="4h", limit=EMA50_CANDLES_4H)
    if not candles or len(candles) < 52:
        return True, 0.0   # مش كافي = نتجاوز الفلتر
    closes = [c["close"] for c in candles]
    k = 2 / (50 + 1)
    ema = sum(closes[:50]) / 50
    for v in closes[50:]:
        ema = v * k + ema * (1 - k)
    current = closes[-1]
    return current > ema, ema


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
    الشرط 1 — Funding Rate Anomaly (max 6 pts — 15%)
    -0.05% → 3 نقاط، -0.10% → 6 نقاط
    """
    if funding_rate is None:
        return {"pass": False, "score": 0, "value": None, "tier": 0, "label": "غير متاح (spot)"}
    # 4 مستويات: 0% / 5% / 10% / 15%
    if funding_rate < PUMP_FUNDING_RATE_L3:
        tier, pts = 3, PUMP_W_FUNDING_RATE   # 15%
    elif funding_rate < PUMP_FUNDING_RATE_L2:
        tier, pts = 2, PUMP_W_FUNDING_RATE * 2 // 3  # 10%
    elif funding_rate < PUMP_FUNDING_RATE_L1:
        tier, pts = 1, PUMP_W_FUNDING_RATE // 3       # 5%
    else:
        tier, pts = 0, 0
    tier_label = ["—", "🟡 خفيف", "🟠 متوسط", "🔴 قوي"][tier]
    return {
        "pass":  pts > 0,
        "score": pts,
        "tier":  tier,
        "value": funding_rate,
        "label": f"{funding_rate*100:+.3f}% {tier_label}",
    }


def eval_cvd_divergence(trades, klines_recent):
    """
    الشرط 2 — CVD Divergence (max 6 pts — 15%)
    Tiered: CVD ≥ 15% = 3 نقاط، CVD ≥ 50% = 6 نقاط
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
    # ✅ v6.0 — tiered: divergence أقوى = نقاط أكثر
    price_ok = abs(price_change_pct) < PUMP_PRICE_CHANGE_PCT

    # 4 مستويات
    if price_ok and cvd_change_pct >= PUMP_CVD_L3:
        tier, pts = 3, PUMP_W_CVD_DIVERGENCE        # 15%
    elif price_ok and cvd_change_pct >= PUMP_CVD_L2:
        tier, pts = 2, PUMP_W_CVD_DIVERGENCE * 2 // 3  # 10%
    elif price_ok and cvd_change_pct >= PUMP_CVD_L1:
        tier, pts = 1, PUMP_W_CVD_DIVERGENCE // 3       # 5%
    else:
        tier, pts = 0, 0
    tier_label = ["—", "🟡 خفيف", "🟠 متوسط", "🔴 قوي"][tier]
    return {
        "pass":  pts > 0,
        "score": pts,
        "tier":  tier,
        "value": cvd_change_pct,
        "label": f"CVD {cvd_change_pct:+.1f}% {tier_label} / سعر {price_change_pct:+.2f}%",
    }


def eval_taker_buy_ratio(trades):
    """
    الشرط 3 — Taker Buy Ratio (max 6 pts — 15%)
    على آخر الصفقات: نسبة taker buys للإجمالي
    Tiered: ≥60% = 3 نقاط، ≥70% = 6 نقاط
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
    # ✅ v6.0 — منطق tiered ومُصحَّح
    # نشترط: المتوسط ≥ العتبة + 2 على الأقل من الـ 3 شرائح ≥ العتبة
    above_count = sum(1 for r in ratios if r >= PUMP_TAKER_L1)

    # 4 مستويات
    if avg_ratio >= PUMP_TAKER_L3 and above_count >= 2:
        tier, pts = 3, PUMP_W_TAKER_BUY_RATIO           # 15%
    elif avg_ratio >= PUMP_TAKER_L2 and above_count >= 2:
        tier, pts = 2, PUMP_W_TAKER_BUY_RATIO * 2 // 3  # 10%
    elif avg_ratio >= PUMP_TAKER_L1 and above_count >= 1:
        tier, pts = 1, PUMP_W_TAKER_BUY_RATIO // 3       # 5%
    else:
        tier, pts = 0, 0
    tier_label = ["—", "🟡 خفيف", "🟠 متوسط", "🔴 قوي"][tier]
    return {
        "pass":  pts > 0,
        "score": pts,
        "tier":  tier,
        "value": avg_ratio,
        "label": f"{avg_ratio*100:.1f}% {tier_label} ({above_count}/3 شرائح)",
    }


def eval_orderbook_imbalance(ob, current_price):
    """
    الشرط 4 — Order Book Imbalance (max 6 pts — 15%) — tiered
    """
    if not ob or not ob.get("bids") or not ob.get("asks") or current_price <= 0:
        return {"pass": False, "score": 0, "value": None, "label": "غير متاح"}
    p_min = current_price * (1 - PUMP_OB_RANGE_PCT)
    p_max = current_price * (1 + PUMP_OB_RANGE_PCT)
    buy_vol  = sum(q for p, q in ob["bids"] if p >= p_min)
    sell_vol = sum(q for p, q in ob["asks"] if p <= p_max)
    total = buy_vol + sell_vol
    if total <= 0:
        return {"pass": False, "score": 0, "value": None, "label": "لا توجد سيولة قريبة"}
    imbalance = buy_vol / total
    if imbalance >= PUMP_OB_IMBALANCE_STRONG:
        pts, passed = PUMP_W_OB_IMBALANCE, True   # 6 (15%)
    elif imbalance >= PUMP_OB_IMBALANCE_MIN:
        pts, passed = 3, True
    else:
        pts, passed = 0, False
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
    الشرط 5 — Volume Acceleration (max 3 pts) — tiered
    الفوليم آخر 3 ساعات vs متوسط الـ 9 ساعات قبلها
    1.5x = 2 نقاط، 2.5x+ = 3 نقاط
    """
    if not candles_1h or len(candles_1h) < 12:
        return {"pass": False, "score": 0, "value": 0, "label": "كلاينز غير كافية"}
    vols = [c["volume"] for c in candles_1h]
    recent_3 = sum(vols[-3:]) / 3
    older_9  = sum(vols[-12:-3]) / 9
    if older_9 <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "متوسط صفر"}
    ratio = recent_3 / older_9
    if ratio >= PUMP_VOL_ACCEL_STRONG:
        return {"pass": True, "score": PUMP_W_VOL_ACCEL, "value": ratio,
                "label": f"{ratio:.1f}x (آخر 3h vs الـ 9h قبلها) \U0001f525"}
    if ratio >= PUMP_VOL_ACCEL_MIN:
        return {"pass": True, "score": 2, "value": ratio,
                "label": f"{ratio:.1f}x (آخر 3h vs الـ 9h قبلها)"}
    return {"pass": False, "score": 0, "value": ratio,
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
        return {"pass": False, "score": 0, "value": 0, "label": "صفقات غير كافية"}
    trades_sorted = sorted(trades, key=lambda x: x["ts"])
    last = trades_sorted[-PUMP_WHALE_TRADES_N:]
    qtys = [t["qty"] for t in last if t["qty"] > 0]
    if not qtys:
        return {"pass": False, "score": 0, "value": 0, "label": "لا أحجام"}
    avg_qty = sum(qtys) / len(qtys)
    if avg_qty <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "متوسط صفر"}

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
        "score": PUMP_W_WHALE_ACCUM if is_pass else 0,
        "value": len(whale_buys),
        "label": (f"🐋 {len(whale_buys)} صفقة whale (أكبرها {ratio:.0f}x المتوسط، حد {mult:.0f}x)"
                  if is_pass else f"لا صفقات whale (حد {mult:.0f}x المتوسط)"),
    }


def eval_rsi_momentum(candles_1h):
    """
    الشرط 8 — 📈 RSI Momentum (max 3 pts) — بديل VWAP (يتجمّع بسهولة)
    RSI بيطلع من منطقة التشبع البيعي/الحياد لفوق = بداية زخم صاعد.
      - RSI عبر 50 صاعد + RSI الحالي بين 50-70 (مش متشبع) = 3 نقاط
      - RSI صاعد بس لسه تحت 50 = نقطة واحدة
    """
    if not candles_1h or len(candles_1h) < 16:
        return {"pass": False, "score": 0, "value": 0, "label": "كلاينز غير كافية"}
    closes = [c["close"] for c in candles_1h]
    period = 14
    # حساب RSI الحالي والسابق
    def rsi_at(prices):
        if len(prices) < period + 1:
            return None
        gains, losses = [], []
        for i in range(len(prices) - period, len(prices)):
            ch = prices[i] - prices[i-1]
            gains.append(max(ch, 0))
            losses.append(max(-ch, 0))
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - (100 / (1 + rs))

    rsi_now  = rsi_at(closes)
    rsi_prev = rsi_at(closes[:-1])
    if rsi_now is None or rsi_prev is None:
        return {"pass": False, "score": 0, "value": 0, "label": "RSI غير محسوب"}

    rising = rsi_now > rsi_prev
    # المثالي: RSI صاعد + بين 50 و70 (زخم بدون تشبع)
    if rising and 50 <= rsi_now <= 70:
        return {"pass": True, "score": PUMP_W_EMA21_CROSS, "value": rsi_now,
                "label": f"📈 RSI {rsi_now:.0f} صاعد 🔥 (زخم صحي)"}
    if rising and 45 <= rsi_now < 50:
        return {"pass": True, "score": 2, "value": rsi_now,
                "label": f"📈 RSI {rsi_now:.0f} بيقترب من الصعود"}
    if rising and rsi_now < 45:
        return {"pass": True, "score": 1, "value": rsi_now,
                "label": f"RSI {rsi_now:.0f} صاعد (لسه ضعيف)"}
    if rsi_now > 70:
        return {"pass": False, "score": 0, "value": rsi_now,
                "label": f"⚠️ RSI {rsi_now:.0f} متشبع شرائياً"}
    return {"pass": False, "score": 0, "value": rsi_now,
            "label": f"RSI {rsi_now:.0f} هابط"}


def eval_higher_lows(candles_15m):
    """
    الشرط 9 — 📐 Higher Lows (max 3 pts) — بديل Multi-TF (يتجمّع بسهولة)
    السعر بيعمل قيعان صاعدة = هيكل صاعد (المشترين بيدافعوا عند مستويات أعلى).
      - 3 قيعان صاعدة متتالية = 3 نقاط
      - 2 قاع صاعد = 2 نقطة
    """
    if not candles_15m or len(candles_15m) < 12:
        return {"pass": False, "score": 0, "value": 0, "label": "كلاينز 15m غير كافية"}
    # نقسّم آخر 12 شمعة لـ 3 مجموعات ونجيب أدنى قاع في كل مجموعة
    window = candles_15m[-12:]
    seg = len(window) // 3
    lows = []
    for i in range(3):
        chunk = window[i*seg:(i+1)*seg] if i < 2 else window[2*seg:]
        if chunk:
            lows.append(min(c["low"] for c in chunk))
    if len(lows) < 3:
        return {"pass": False, "score": 0, "value": 0, "label": "قيعان غير كافية"}

    # هل القيعان صاعدة؟
    rising_3 = lows[0] < lows[1] < lows[2]
    rising_2 = lows[1] < lows[2]

    if rising_3:
        return {"pass": True, "score": PUMP_W_MTF_BUY, "value": 3,
                "label": f"📐 3 قيعان صاعدة 🔥 (هيكل صاعد قوي)"}
    if rising_2:
        return {"pass": True, "score": 2, "value": 2,
                "label": f"📐 قاعين صاعدين (هيكل صاعد)"}
    return {"pass": False, "score": 0, "value": 0,
            "label": f"لا قيعان صاعدة"}


def eval_liquidity_grab(candles_15m, candles_1h):
    """
    الشرط 10 — 🎯 Liquidity Grab (max 4 pts) — بديل Short Liquidation (أسرع)
    السعر يكسر قاع سابق (يصطاد ستوبات البائعين) وبعدين يرتد بسرعة فوقه.
    ده انعكاس قوي = المؤسسات بتجمّع عند القيعان.
      - كسر قاع + إغلاق فوقه + شمعة خضراء قوية = 4 نقاط
      - فتيل سفلي طويل (رفض القاع) = 2 نقاط
    """
    if not candles_15m or len(candles_15m) < 10:
        return {"pass": False, "score": 0, "value": 0, "label": "كلاينز 15m غير كافية"}

    recent = candles_15m[-10:]
    last = recent[-1]
    # أدنى قاع في آخر 8 شموع قبل الأخيرة
    prior_low = min(c["low"] for c in recent[:-1])

    # 1) كسر القاع وارتداد: الشمعة الأخيرة نزلت تحت القاع لكن أغلقت فوقه
    wicked_below = last["low"] < prior_low
    closed_above = last["close"] > prior_low
    is_green     = last["close"] > last["open"]

    # حجم الفتيل السفلي
    candle_range = last["high"] - last["low"]
    if candle_range <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "range صفر"}
    body_low = min(last["open"], last["close"])
    lower_wick = body_low - last["low"]
    wick_ratio = lower_wick / candle_range

    if wicked_below and closed_above and is_green:
        return {"pass": True, "score": PUMP_W_SHORT_LIQ, "value": wick_ratio,
                "label": f"🎯 صيد سيولة: كسر القاع وارتد 🔥 (انعكاس قوي)"}
    if wick_ratio >= 0.5:
        return {"pass": True, "score": 2, "value": wick_ratio,
                "label": f"🎯 فتيل سفلي {wick_ratio*100:.0f}% (رفض القاع)"}
    return {"pass": False, "score": 0, "value": wick_ratio,
            "label": f"لا صيد سيولة (فتيل {wick_ratio*100:.0f}%)"}


def eval_bid_wall(ob, current_price):
    """
    الشرط 7 — Smart Money Bid Wall (max 3 pts) — tiered
    جدار شراء قوي قريب من السعر = دعم يحمي البامب
    نقارن: حجم الـ bids في نطاق -1.5% vs متوسط الـ asks في نطاق +1.5%
    """
    if not ob or not ob.get("bids") or not ob.get("asks") or current_price <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "غير متاح"}
    p_low  = current_price * (1 - PUMP_BID_WALL_RANGE)
    p_high = current_price * (1 + PUMP_BID_WALL_RANGE)
    bid_in_range = [q for p, q in ob["bids"] if p >= p_low]
    ask_in_range = [q for p, q in ob["asks"] if p <= p_high]
    if not bid_in_range or not ask_in_range:
        return {"pass": False, "score": 0, "value": 0, "label": "لا توجد سيولة قريبة"}
    # نبحث عن أكبر bid level
    max_bid       = max(bid_in_range)
    avg_ask       = sum(ask_in_range) / len(ask_in_range)
    if avg_ask <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "متوسط asks صفر"}
    ratio = max_bid / avg_ask
    if ratio >= PUMP_BID_WALL_STRONG:
        return {"pass": True, "score": PUMP_W_BID_WALL, "value": ratio,
                "label": f"\U0001f9f1 جدار شراء {ratio:.1f}x متوسط asks"}
    if ratio >= PUMP_BID_WALL_MIN_RATIO:
        return {"pass": True, "score": 2, "value": ratio,
                "label": f"جدار شراء {ratio:.1f}x متوسط asks"}
    return {"pass": False, "score": 0, "value": ratio,
            "label": f"لا جدار ({ratio:.1f}x، الحد {PUMP_BID_WALL_MIN_RATIO}x)"}


def eval_candle_momentum(candles_15m):
    """
    الشرط 11 — 🕯️ Candle Momentum (1 pt)
    آخر شمعة 15m:
    - جسمها >= 70% من الـ range الكامل (شمعة اندفاع خضراء قوية)
    - فوليمها >= 1.5x متوسط آخر 7 شموع
    الاتنين مع بعض = momentum حقيقي في اللحظة الحالية.
    """
    if not candles_15m or len(candles_15m) < 8:
        return {"pass": False, "score": 0, "value": 0, "label": "كلاينز 15m غير كافية"}

    last  = candles_15m[-1]
    o, h, l, c = last["open"], last["high"], last["low"], last["close"]

    # شرط الاتجاه: الشمعة لازم خضراء
    if c <= o:
        return {"pass": False, "score": 0, "value": 0, "label": "الشمعة الأخيرة حمراء"}

    candle_range = h - l
    if candle_range <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "range = صفر"}

    body_pct = (c - o) / candle_range

    # فوليم الشمعة vs متوسط الـ 7 قبلها
    vols_prev = [candles_15m[i]["volume"] for i in range(-8, -1)]
    avg_vol   = sum(vols_prev) / max(1, len(vols_prev))
    vol_ratio = last["volume"] / avg_vol if avg_vol > 0 else 0

    passed = body_pct >= PUMP_CANDLE_BODY_PCT and vol_ratio >= PUMP_CANDLE_VOL_X
    if passed:
        return {"pass": True, "score": PUMP_W_CANDLE_MOM, "value": body_pct,
                "label": f"🕯️ جسم {body_pct*100:.0f}% من الـ range | فوليم {vol_ratio:.1f}x"}
    return {"pass": False, "score": 0, "value": body_pct,
            "label": f"جسم {body_pct*100:.0f}% (الحد {PUMP_CANDLE_BODY_PCT*100:.0f}%) | فوليم {vol_ratio:.1f}x"}


def eval_early_volume_surge(candles_15m):
    """
    الشرط 12 — 📈 Early Volume Surge (1 pt)
    فوليم أول شمعة 15m الحالية >= 2x متوسط الـ 7 شموع قبلها.
    اندفاع مبكر في الفوليم = دخول مال جديد.
    """
    if not candles_15m or len(candles_15m) < 8:
        return {"pass": False, "score": 0, "value": 0, "label": "كلاينز 15m غير كافية"}
    vols = [c["volume"] for c in candles_15m]
    baseline = vols[-8:-1]
    avg = sum(baseline) / max(1, len(baseline))
    curr = vols[-1]
    if avg <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "متوسط صفر"}
    ratio = curr / avg
    if ratio >= PUMP_EARLY_SURGE_MIN_X:
        return {"pass": True, "score": PUMP_W_EARLY_SURGE, "value": ratio,
                "label": f"📈 فوليم {ratio:.1f}x المتوسط 🔥 (اندفاع مبكر)"}
    return {"pass": False, "score": 0, "value": ratio,
            "label": f"{ratio:.1f}x (الحد {PUMP_EARLY_SURGE_MIN_X}x)"}


# ════════════════════════════════════════════════════════════════════
# ✅ v8.0 — المحرك الرئيسي للبامب (12 شرط)
# ════════════════════════════════════════════════════════════════════

def eval_volume_price_confirm(candles_15m):
    """
    الشرط 13 — ✅ Volume/Price Confirmation (1 pt)
    آخر شمعة صاعدة + فوليمها أعلى من المتوسط = الصعود مدعوم بفوليم حقيقي
    (مش مجرد حركة فاضية). تأكيد بسيط بيتجمّع مع أي شرط.
    """
    if not candles_15m or len(candles_15m) < 6:
        return {"pass": False, "score": 0, "value": 0, "label": "كلاينز غير كافية"}
    last = candles_15m[-1]
    is_green = last["close"] > last["open"]
    vols = [c["volume"] for c in candles_15m[-6:-1]]
    avg_vol = sum(vols) / len(vols) if vols else 0
    if avg_vol <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "فوليم صفر"}
    vol_ratio = last["volume"] / avg_vol
    if is_green and vol_ratio >= 1.2:
        return {"pass": True, "score": PUMP_W_VOL_PRICE_CONF, "value": vol_ratio,
                "label": f"✅ صعود مدعوم بفوليم {vol_ratio:.1f}x"}
    return {"pass": False, "score": 0, "value": vol_ratio,
            "label": f"بدون تأكيد فوليم ({vol_ratio:.1f}x)"}


def eval_buysell_pressure(trades):
    """
    الشرط 14 — ⚖️ Buy/Sell Pressure (1 pt)
    نسبة فوليم الشراء للبيع في آخر الصفقات.
    لو الشراء أكبر بوضوح = ضغط شراء حقيقي. بيتجمّع مع أي شرط بسهولة.
    """
    if not trades or len(trades) < 20:
        return {"pass": False, "score": 0, "value": 0, "label": "صفقات غير كافية"}
    buy_vol  = sum(t["qty"] * t["price"] for t in trades if t["side"] == "buy" and t["price"] > 0)
    sell_vol = sum(t["qty"] * t["price"] for t in trades if t["side"] == "sell" and t["price"] > 0)
    total = buy_vol + sell_vol
    if total <= 0:
        return {"pass": False, "score": 0, "value": 0, "label": "لا فوليم"}
    buy_pct = buy_vol / total
    if buy_pct >= 0.58:
        return {"pass": True, "score": PUMP_W_BUYSELL_PRESSURE, "value": buy_pct,
                "label": f"⚖️ ضغط شراء {buy_pct*100:.0f}% 🔥"}
    return {"pass": False, "score": 0, "value": buy_pct,
            "label": f"ضغط شراء {buy_pct*100:.0f}% (الحد 58%)"}


def eval_prepump_detector(trades, ob, candles_15m, current_price, volume_24h):
    """
    🔮 Pre-Pump Detector (v11) — يرصد علامات الصعود قبل ما يحصل.
    يجمع 4 إشارات مبكرة في درجة 0-100:
      1) تراكم الحيتان (30): صفقات شراء ضخمة متتالية
      2) جدران الشراء (20): سيولة bid قوية تحت السعر
      3) انفجار الفوليم المبكر (30): تسارع مفاجئ في الفوليم
      4) تسارع ضغط الشراء (20): buy ratio بيزيد عبر الوقت

    Returns: {"score": 0-100, "label", "signals": {...}}
    """
    score = 0
    signals = {}

    # ── 1) تراكم الحيتان (تسلسل شراء ضخم) ──
    whale_pts = 0
    if trades and len(trades) >= 20:
        ts = sorted(trades, key=lambda x: x["ts"])
        qtys = [t["qty"] for t in ts if t["qty"] > 0]
        if qtys:
            avg_q = sum(qtys) / len(qtys)
            # عدد صفقات الشراء الكبيرة (>= 5x المتوسط) في آخر 30 صفقة
            recent = ts[-30:]
            big_buys = [t for t in recent if t["side"] == "buy" and t["qty"] >= avg_q * 5]
            big_sells = [t for t in recent if t["side"] == "sell" and t["qty"] >= avg_q * 5]
            n_big = len(big_buys)
            # تراكم = شراء كبير أكتر من بيع كبير
            if n_big >= 3 and len(big_buys) > len(big_sells):
                whale_pts = PREPUMP_WHALE_WEIGHT
            elif n_big >= 2 and len(big_buys) > len(big_sells):
                whale_pts = PREPUMP_WHALE_WEIGHT * 2 // 3
            elif n_big >= 1:
                whale_pts = PREPUMP_WHALE_WEIGHT // 3
            signals["whales"] = n_big
    score += whale_pts

    # ── 2) جدران الشراء (bid walls تحت السعر) ──
    wall_pts = 0
    if ob and ob.get("bids") and ob.get("asks") and current_price > 0:
        p_lo = current_price * 0.97   # في نطاق -3%
        bid_vol = sum(q for p, q in ob["bids"] if p >= p_lo)
        ask_vol = sum(q for p, q in ob["asks"] if p <= current_price * 1.03)
        if ask_vol > 0:
            wall_ratio = bid_vol / ask_vol
            if wall_ratio >= 3.0:
                wall_pts = PREPUMP_WALL_WEIGHT
            elif wall_ratio >= 2.0:
                wall_pts = PREPUMP_WALL_WEIGHT * 2 // 3
            elif wall_ratio >= 1.5:
                wall_pts = PREPUMP_WALL_WEIGHT // 3
            signals["wall_ratio"] = round(wall_ratio, 2)
    score += wall_pts

    # ── 3) انفجار الفوليم المبكر (15m) ──
    vol_pts = 0
    if candles_15m and len(candles_15m) >= 8:
        vols = [c["volume"] for c in candles_15m]
        baseline = sum(vols[-8:-1]) / 7 if len(vols) >= 8 else 0
        curr = vols[-1]
        if baseline > 0:
            vsurge = curr / baseline
            if vsurge >= 3.0:
                vol_pts = PREPUMP_VOLSURGE_WEIGHT
            elif vsurge >= 2.0:
                vol_pts = PREPUMP_VOLSURGE_WEIGHT * 2 // 3
            elif vsurge >= 1.5:
                vol_pts = PREPUMP_VOLSURGE_WEIGHT // 3
            signals["vol_surge"] = round(vsurge, 2)
    score += vol_pts

    # ── 4) تسارع ضغط الشراء (buy ratio بيزيد) ──
    accel_pts = 0
    if trades and len(trades) >= 30:
        ts = sorted(trades, key=lambda x: x["ts"])
        n = len(ts)
        third = n // 3
        def buy_ratio(seg):
            bq = sum(t["qty"] for t in seg if t["side"] == "buy")
            tot = sum(t["qty"] for t in seg)
            return bq / tot if tot > 0 else 0
        r_early = buy_ratio(ts[:third])
        r_mid   = buy_ratio(ts[third:2*third])
        r_late  = buy_ratio(ts[2*third:])
        # تسارع = الشراء بيزيد مع الوقت + الأخير قوي
        if r_late > r_mid > r_early and r_late >= 0.6:
            accel_pts = PREPUMP_ACCEL_WEIGHT
        elif r_late > r_early and r_late >= 0.58:
            accel_pts = PREPUMP_ACCEL_WEIGHT * 2 // 3
        elif r_late >= 0.55:
            accel_pts = PREPUMP_ACCEL_WEIGHT // 3
        signals["buy_accel"] = f"{r_early*100:.0f}%→{r_late*100:.0f}%"
    score += accel_pts

    score = min(100, score)

    # تصنيف
    if score >= PREPUMP_ELITE_THRESHOLD:
        label = f"🔮🔥 انفجار وشيك جداً ({score}/100)"
    elif score >= PREPUMP_STRONG_THRESHOLD:
        label = f"🔮 صعود كبير وشيك ({score}/100)"
    elif score >= 30:
        label = f"علامات مبكرة ({score}/100)"
    else:
        label = f"ضعيف ({score}/100)"

    return {"score": score, "label": label, "signals": signals}


def has_strong_confirmation(trades, candles_15m):
    """
    تأكيد إلزامي (v11): الإشارة لازم يكون فيها واحد على الأقل من:
      1) انفجار فوليم: آخر شمعة 15m فوليمها >= 2x المتوسط
      2) ضغط شراء قوي: >= 62% من فوليم الصفقات شراء
    لو مفيش أي تأكيد → الإشارة ضعيفة وتترفض.
    Returns: (confirmed: bool, reason: str)
    """
    # 1) انفجار فوليم
    vol_ok = False
    vol_x = 0
    if candles_15m and len(candles_15m) >= 6:
        vols = [c["volume"] for c in candles_15m[-6:-1]]
        avg = sum(vols) / len(vols) if vols else 0
        if avg > 0:
            vol_x = candles_15m[-1]["volume"] / avg
            vol_ok = vol_x >= CONFIRM_VOL_SURGE_X

    # 2) ضغط شراء
    buy_ok = False
    buy_pct = 0
    if trades and len(trades) >= 20:
        bv = sum(t["qty"]*t["price"] for t in trades if t["side"]=="buy" and t["price"]>0)
        tv = sum(t["qty"]*t["price"] for t in trades if t["price"]>0)
        if tv > 0:
            buy_pct = bv / tv
            buy_ok = buy_pct >= CONFIRM_BUY_PRESSURE

    if vol_ok or buy_ok:
        parts = []
        if vol_ok: parts.append(f"فوليم {vol_x:.1f}x")
        if buy_ok: parts.append(f"شراء {buy_pct*100:.0f}%")
        return True, " + ".join(parts)
    return False, f"ضعيف (فوليم {vol_x:.1f}x، شراء {buy_pct*100:.0f}%)"


async def evaluate_pump_signal(session, symbol, current_price, volume_24h=0):
    """
    v10 — يقيم الـ 12 شرط + 5 فلاتر دقة على عملة واحدة
    """
    # جلب البيانات بالتوازي (أضفنا EMA50/4h)
    funding, trades, ob, kl1h, kl15m, kl4h, oi_hist, above_ema50 = await asyncio.gather(
        fetch_gate_funding_rate(session, symbol),
        fetch_gate_recent_trades(session, symbol, limit=1000),
        fetch_gate_orderbook(session, symbol, limit=50),
        fetch_klines(session, symbol, interval="1h", limit=72),
        fetch_klines(session, symbol, interval="15m", limit=12),
        fetch_klines(session, symbol, interval="4h", limit=60),
        fetch_gate_open_interest(session, symbol),
        fetch_ema50_4h(session, symbol),
        return_exceptions=True
    )
    if isinstance(funding, Exception):    funding    = None
    if isinstance(trades, Exception):     trades     = []
    if isinstance(ob, Exception):         ob         = None
    if isinstance(kl1h, Exception):       kl1h       = []
    if isinstance(kl15m, Exception):      kl15m      = []
    if isinstance(kl4h, Exception):       kl4h       = []
    if isinstance(oi_hist, Exception):    oi_hist    = []
    if isinstance(above_ema50, Exception): above_ema50 = (True, 0.0)

    ema50_above, ema50_val = above_ema50 if isinstance(above_ema50, tuple) else (True, 0.0)

    # ── فلتر Wash Trading ──
    is_wash, wash_ratio = detect_wash_trading(trades)
    if is_wash:
        return {
            "symbol": symbol, "price": current_price, "score": 0, "max_score": 45,
            "strength": None, "strength_emoji": "🚫", "core_passed": 0,
            "strength_label": f"رفض — Wash Trading مشتبه ({wash_ratio*100:.0f}% صفقات مكررة)",
            "stop_loss": current_price*0.97, "target": current_price*1.08,
            "breakeven": current_price*1.04,
            "rr_ratio": 1.0, "atr_pct": 3.0, "trail_pct": 2.0,
            "sr_based": False, "prepump": {"score": 0, "label": "", "signals": {}},
            "confirmed": False, "confirm_reason": "wash",
            "conditions": {k: {"pass": False, "score": 0, "value": 0, "label": "wash"} for k in
                ["funding_rate","cvd_divergence","taker_buy_ratio","ob_imbalance",
                 "vol_accel","bid_wall","whale_accum","ema21_cross","mtf_buy",
                 "short_liq","first_3min","early_surge","vol_price_conf","buysell_press"]},
            "filters": {"wash": True, "spread_ok": True, "ema50_above": True,
                        "confluence_penalty": 0, "history_penalty": 0, "prepump_bonus": 0},
        }

    # ── فلتر Spread ──
    spread_ok, spread_pct = check_spread(ob, current_price)

    mtf = {"15m": kl15m, "1h": kl1h, "4h": kl4h}

    # تقييم الشروط الـ 12
    r1  = eval_funding_rate(funding)
    r2  = eval_cvd_divergence(trades, kl1h)
    r3  = eval_taker_buy_ratio(trades)
    r4  = eval_orderbook_imbalance(ob, current_price)
    r5  = eval_volume_acceleration(kl1h)
    r6  = eval_bid_wall(ob, current_price)
    r7  = eval_whale_accumulation(trades, volume_24h)
    r8  = eval_rsi_momentum(kl1h)
    r9  = eval_higher_lows(kl15m)
    r10 = eval_liquidity_grab(kl15m, kl1h)
    r11 = eval_candle_momentum(kl15m)
    r12 = eval_early_volume_surge(kl15m)
    r13 = eval_volume_price_confirm(kl15m)
    r14 = eval_buysell_pressure(trades)

    # ── Confluence Penalty ──
    confluence_penalty = check_confluence(r2, r4)

    total = (r1["score"] + r2["score"] + r3["score"] + r4["score"] + r5["score"]
             + r6["score"] + r7["score"] + r8["score"] + r9["score"] + r10["score"]
             + r11["score"] + r12["score"] + r13["score"] + r14["score"])

    # ───── شرط الـ core الإلزامي: لازم 3 من 4 أساسية على الأقل ─────
    core_passed = sum(1 for r in [r1, r2, r3, r4] if r["pass"])
    core_ok = core_passed >= 3          # ✅ الحد الأدنى للإرسال = 3/4 أساسية

    # ───── Override: 3+ من 4 أساسية = إشارة دخول STRONG فورية ─────
    core_override = core_passed >= 3

    # ───── تصنيف القوة ─────
    if not core_ok:
        # أقل من 3 أساسية = تجاهل تماماً مهما كانت النقاط
        strength = None
        strength_emoji = "\u274c"
        strength_label = "تجاهل — أقل من 3/4 أساسية"
    elif core_override:
        strength = "STRONG"
        strength_emoji = "\U0001f680"
        if core_passed == 4:
            strength_label = f"STRONG — 4/4 أساسية متفعلة 🔥🔥 إشارة مثالية"
        else:
            strength_label = "STRONG — 3/4 أساسية متفعلة 🔥 إشارة دخول"
    elif total >= PUMP_SCORE_STRONG:
        strength = "STRONG"
        strength_emoji = "\U0001f680"
        strength_label = "STRONG — نقاط عالية + أساسية كافية"
    elif total >= PUMP_SCORE_MODERATE:
        strength = "MODERATE"
        strength_emoji = "\u26a0\ufe0f"
        strength_label = "MODERATE — دخول بحجم صغير"
    else:
        strength = None
        strength_emoji = "\u274c"
        strength_label = "تجاهل"

    # 🔮 Pre-Pump Detector — رصد الصعود قبل حدوثه
    prepump = eval_prepump_detector(trades, ob, kl15m, current_price, volume_24h)

    # تأكيد إلزامي للفوليم/الشراء
    confirmed, confirm_reason = has_strong_confirmation(trades, kl15m)

    # v11: أهداف ديناميكية مبنية على ATR + الزخم (Pre-Pump score)
    targets = calc_targets_and_stop(current_price, kl1h, kl15m,
                                     momentum_score=prepump["score"])

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
        "target":     targets["target"],
        "breakeven":  targets["breakeven"],
        "rr_ratio":   targets["rr_ratio"],
        "atr_pct":    targets["atr_pct"],
        "trail_pct":  targets.get("trail_pct", 2.0),
        "sr_based":   targets.get("sr_based", False),
        "prepump":    prepump,
        "confirmed":  confirmed,
        "confirm_reason": confirm_reason,
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
            "first_3min":       r11,
            "early_surge":      r12,
            "vol_price_conf":   r13,
            "buysell_press":    r14,
        },
        "filters": {
            "wash":               False,
            "spread_ok":          spread_ok,
            "spread_pct":         spread_pct,
            "ema50_above":        ema50_above,
            "ema50_val":          ema50_val,
            "confluence_penalty": confluence_penalty,
            "prepump_bonus":      PREPUMP_BONUS_PCT if prepump["score"] >= PREPUMP_STRONG_THRESHOLD else 0,
        },
    }


def find_sr_levels(candles, current_price, lookback=48):
    """
    v10 — إيجاد مستويات الدعم والمقاومة الحقيقية من الشارت.
    Pivot High = مقاومة، Pivot Low = دعم.
    نرجع: (supports: list, resistances: list) مرتبة تصاعدياً.
    """
    if not candles or len(candles) < 10:
        return [], []
    candles = candles[-lookback:]
    supports, resistances = [], []
    n = len(candles)
    for i in range(2, n - 2):
        h = candles[i]["high"]
        l = candles[i]["low"]
        # Pivot High
        if (h > candles[i-1]["high"] and h > candles[i-2]["high"] and
                h > candles[i+1]["high"] and h > candles[i+2]["high"]):
            if h > current_price:
                resistances.append(h)
        # Pivot Low
        if (l < candles[i-1]["low"] and l < candles[i-2]["low"] and
                l < candles[i+1]["low"] and l < candles[i+2]["low"]):
            if l < current_price:
                supports.append(l)
    supports.sort()
    resistances.sort()
    return supports, resistances


def calc_targets_and_stop(current_price, candles_1h, candles_15m=None, momentum_score=0):
    """
    v11 — أهداف واستوب ديناميكية بالكامل، متكيّفة مع قوة الحركة:
    - ATR حقيقي (التقلب) + الزخم الحالي (momentum_score 0-100)
    - كل ما الزخم أقوى، الأهداف أبعد (نمسك الصعود الكبير)
    - الاستوب أضيق في الزخم القوي (السعر مش المفروض يرجع)
    - مستويات S/R الحقيقية كسقف منطقي
    Returns: {"stop_loss","target","breakeven","rr_ratio","atr_pct","sr_based","trail_pct"}
    """
    fallback = {
        "stop_loss":  current_price * 0.97,
        "target":     current_price * 1.08,
        "breakeven":  current_price * 1.04,
        "rr_ratio":   2.0,
        "atr_pct":    3.0,
        "sr_based":   False,
        "trail_pct":  2.0,
    }
    if not candles_1h or len(candles_1h) < 15 or current_price <= 0:
        return fallback

    # ── 1) ATR على آخر 14 شمعة (1h) ──
    last = candles_1h[-15:]
    trs = []
    for i in range(1, len(last)):
        h, l, pc = last[i]["high"], last[i]["low"], last[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs) / len(trs) if trs else current_price * 0.01
    atr_pct = max(1.0, min((atr / current_price * 100), 10.0))
    atr = current_price * atr_pct / 100

    # ── 2) ATR قصير المدى (15m) لقياس التسارع اللحظي ──
    atr15_pct = atr_pct
    if candles_15m and len(candles_15m) >= 8:
        last15 = candles_15m[-8:]
        trs15 = []
        for i in range(1, len(last15)):
            h, l, pc = last15[i]["high"], last15[i]["low"], last15[i-1]["close"]
            trs15.append(max(h - l, abs(h - pc), abs(l - pc)))
        if trs15:
            atr15 = sum(trs15) / len(trs15)
            atr15_pct = max(0.5, min((atr15 / current_price * 100), 10.0))

    # ── 3) معامل الزخم: 0 (ضعيف) → 1 (انفجاري) ──
    # momentum_score من 0-100، نحوله لمعامل 0.5-2.0
    mom = max(0, min(momentum_score, 100)) / 100.0
    # كل ما الزخم أعلى، الأهداف أبعد (1.0x → 2.5x)
    target_mult = 1.0 + (mom * 1.5)

    # ── 4) مستويات S/R ──
    supports, resistances = find_sr_levels(candles_1h, current_price)

    # ── 5) الاستوب الديناميكي ──
    # في الزخم القوي: استوب أضيق (1.2x ATR). في الزخم الضعيف: أوسع (2x ATR)
    stop_atr_mult = 2.0 - (mom * 0.8)   # 2.0 → 1.2
    stop_by_atr = current_price - (atr * stop_atr_mult)
    if supports:
        nearest_support = supports[-1]
        stop_by_sr = nearest_support - (atr * 0.25)
        # نأخذ الأعلى (الأضيق) بين الاتنين عشان منخسرش كتير
        stop_loss = max(stop_by_atr, stop_by_sr)
    else:
        stop_loss = stop_by_atr
    # حدود أمان
    stop_loss = max(stop_loss, current_price * 0.92)   # أقصى خسارة 8%
    stop_loss = min(stop_loss, current_price * 0.985)   # مش قريب أوي

    risk = current_price - stop_loss
    if risk <= 0:
        risk = atr

    # ── 6) الهدف الواحد: ~3.5x ATR معدّل بالزخم ──
    # base = 3.5x ATR، يزيد مع الزخم حتى ~5x
    target_dist = atr * (3.5 * target_mult / 1.0)
    # نطبّق target_mult بشكل معتدل: 3.5x في الزخم الضعيف → ~5x في القوي
    target_dist = atr * (3.5 + mom * 1.5)
    target = current_price + target_dist

    # ── 7) تعديل بالمقاومة القوية (لا نضع الهدف فوق مقاومة كبيرة) ──
    sr_based = False
    breakeven = None
    if resistances:
        res_above = [r for r in resistances if r > current_price * 1.005]
        if res_above:
            sr_based = True
            # نقطة التأمين = أول مقاومة حقيقية
            breakeven = res_above[0]
            # الهدف: لو في مقاومة تانية قوية قريبة من هدفنا، نخليها الهدف
            # غير كده نسيب الهدف المحسوب بس منخليهوش بعيد جداً عن آخر مقاومة
            far_res = [r for r in res_above if r > target * 0.95]
            if len(res_above) >= 2:
                # الهدف عند المقاومة الثانية لو كانت أقرب من هدفنا المحسوب
                second = res_above[1]
                if second < target:
                    target = second * 0.998
            # تأكيد إن الهدف فوق نقطة التأمين
            if breakeven and target <= breakeven:
                target = breakeven * 1.015

    # لو مفيش مقاومات، نقطة التأمين = نص الطريق للهدف
    if breakeven is None:
        breakeven = current_price + (target - current_price) * 0.5

    rr_ratio = (target - current_price) / risk if risk > 0 else 1.5

    # ── 8) نسبة الـ Trailing Stop (للزخم القوي = trail أضيق) ──
    trail_pct = round(max(1.0, atr15_pct * (1.5 - mom * 0.5)), 2)

    return {
        "stop_loss":  stop_loss,
        "target":     target,
        "breakeven":  breakeven,
        "rr_ratio":   rr_ratio,
        "atr_pct":    atr_pct,
        "sr_based":   sr_based,
        "trail_pct":  trail_pct,
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
    تنسيق الإشارة — 12 شرط + هدف/استوب ديناميكي + spoiler للشروط
    يستخدم Telegram MarkdownV2 — الشروط مخفية داخل ||spoiler|| تتكشف بالضغط.
    """
    c = result["conditions"]
    sym = result["symbol"]
    price = result["price"]
    sl = result["stop_loss"]
    tgt = result["target"]
    be = result.get("breakeven", price)
    sl_pct = (sl - price) / price * 100
    tgt_pct = (tgt - price) / price * 100
    be_pct = (be - price) / price * 100
    rr = result.get("rr_ratio", 2.0)
    atr_pct = result.get("atr_pct", 3.0)
    trail_pct = result.get("trail_pct", 2.0)
    prepump = result.get("prepump", {"score": 0, "label": "", "signals": {}})

    e = _md2_escape  # اختصار

    # ───── الجزء الظاهر (ملخص فقط) ─────
    # النسبة بـ 4 مستويات للأساسيين:
    # كل أساسي: tier0=0% / tier1=5% / tier2=10% / tier3=15% (المجموع 60%)
    # كل فرعي: pass=4% / fail=0% (10 فرعية × 4% = 40%)
    core_keys = ["funding_rate", "cvd_divergence", "taker_buy_ratio", "ob_imbalance"]
    supp_keys = ["vol_accel", "bid_wall", "whale_accum", "ema21_cross",
                 "mtf_buy", "short_liq", "first_3min", "early_surge",
                 "vol_price_conf", "buysell_press"]
    W_CORE_MAX = 6   # الوزن الأقصى لكل أساسي
    core_pct = sum(
        round(result["conditions"][k]["score"] / W_CORE_MAX * 15)
        for k in core_keys
    )
    supp_pct = sum(4 for k in supp_keys if result["conditions"][k]["pass"])
    # خصومات الدقة والمكافآت
    filters = result.get("filters", {})
    penalty = filters.get("confluence_penalty", 0) + filters.get("history_penalty", 0)
    prepump_bonus = filters.get("prepump_bonus", 0)
    spread_warn = "" if filters.get("spread_ok", True) else f" ⚠️spread {filters.get('spread_pct',0)*100:.2f}%"
    ema50_warn  = "" if filters.get("ema50_above", True) else " ⚠️تحت EMA50/4h"
    score_pct = min(100, max(0, core_pct + supp_pct + prepump_bonus - penalty))

    def _fmt_vol(v):
        if v >= 1_000_000_000:
            return f"${v/1_000_000_000:.2f}B"
        if v >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        return f"${v/1_000:.0f}K"

    cmc_vol  = result.get("volume_cmc_total", 0)
    gate_vol = result.get("volume_24h", 0)
    if cmc_vol > 0:
        vol_cmc_str = f"\n🌐 *فوليم كل المنصات:* `{e(_fmt_vol(cmc_vol))}`"
    elif gate_vol > 0:
        # CMC غير متاح — نعرض فوليم Gate.io كبديل
        vol_cmc_str = f"\n📡 *فوليم Gate\\.io:* `{e(_fmt_vol(gate_vol))}` \\(الإجمالي غير متاح\\)"
    else:
        vol_cmc_str = ""

    # سطر Pre-Pump Detector
    prepump_str = ""
    if prepump["score"] >= PREPUMP_STRONG_THRESHOLD:
        prepump_str = f"\n{e(prepump['label'])}"

    header_lines = [
        f"{result['strength_emoji']} *إشارة بامب محتملة*",
        "━" * 18,
        f"💎 *العملة:* `{e(sym)}USDT`",
        f"💰 *السعر:* `{e(fmt_price(price))}`",
        f"⭐ *الأساسية:* {result['core_passed']}/4",
        f"📊 *النسبة:* {score_pct}% \\({core_pct}% أساسية \\+ {supp_pct}% فرعية" + (f" \\+ {prepump_bonus}% مبكر" if prepump_bonus else "") + f"{e(spread_warn)}{e(ema50_warn)}\\)",
        f"🎯 *القوة:* {e(result['strength_label'])}",
        f"🔮 *Pre\\-Pump:* {prepump['score']}/100",
        f"✅ *تأكيد:* {e(result.get('confirm_reason', '—'))}",
        vol_cmc_str,
        "",
        "━━━ 📍 *الدخول والخروج* ━━━",
        f"🟢 *الدخول:* `{e(fmt_price(price))}`",
        f"🔒 *نقطة التأمين:* `{e(fmt_price(be))}` \\({e(f'{be_pct:+.2f}%')}\\)" + (" 📌مقاومة" if result.get('sr_based') else ""),
        f"      ↳ عند الوصول، حرّك الاستوب للدخول \\(صفر خسارة\\)",
        f"🎯 *الهدف:* `{e(fmt_price(tgt))}` \\({e(f'{tgt_pct:+.2f}%')}\\)",
        f"🛑 *الاستوب:* `{e(fmt_price(sl))}` \\({e(f'{sl_pct:+.2f}%')}\\)",
        f"📈 *Trailing:* `{e(f'{trail_pct:.1f}%')}` \\(استوب متحرك بعد التأمين\\)",
        f"⚖️ *R:R:* `{e(f'{rr:.2f}')}` \\| *ATR:* `{e(f'{atr_pct:.1f}%')}`",
        "",
    ]

    # ───── الجزء المخفي (spoiler) — تفاصيل الشروط ─────
    items = [
        ("⭐", "Funding Rate",       c["funding_rate"]),
        ("⭐", "CVD Divergence",     c["cvd_divergence"]),
        ("⭐", "Taker Buy Ratio",    c["taker_buy_ratio"]),
        ("⭐", "Order Book Imb\\.",  c["ob_imbalance"]),
        ("",   "Volume Accel\\.",    c["vol_accel"]),
        ("",   "Bid Wall",            c["bid_wall"]),
        ("",   "Whale Accum\\.",     c["whale_accum"]),
        ("",   "RSI Momentum 📈",   c["ema21_cross"]),
        ("",   "Higher Lows 📐",    c["mtf_buy"]),
        ("",   "Liquidity Grab 🎯",  c["short_liq"]),
        ("",   "Candle Momentum 🕯️", c["first_3min"]),
        ("",   "Early Surge 📈",    c["early_surge"]),
        ("",   "Vol/Price Conf ✅",  c["vol_price_conf"]),
        ("",   "Buy/Sell Press ⚖️", c["buysell_press"]),
    ]
    detail_lines = ["📋 الشروط بالتفصيل:", ""]
    for marker, name, r in items:
        icon = "✅" if r["pass"] else "❌"
        lbl = e(r.get("label", ""))
        pts = r.get("score", 0)
        prefix = f"{icon} {marker} " if marker else f"{icon} "
        detail_lines.append(f"{prefix}{name} \\({pts}p\\): {lbl}")
    detail_lines.append("")
    detail_lines.append("⭐ \\= شرط أساسي")
    # تفاصيل Pre-Pump Detector
    pp_sig = prepump.get("signals", {})
    if pp_sig:
        detail_lines.append("")
        detail_lines.append(f"🔮 Pre\\-Pump \\({prepump['score']}/100\\):")
        if "whales" in pp_sig:
            detail_lines.append(f"  🐋 صفقات كبيرة: {pp_sig['whales']}")
        if "wall_ratio" in pp_sig:
            detail_lines.append(f"  🧱 جدار شراء: {e(str(pp_sig['wall_ratio']))}x")
        if "vol_surge" in pp_sig:
            detail_lines.append(f"  📊 انفجار فوليم: {e(str(pp_sig['vol_surge']))}x")
        if "buy_accel" in pp_sig:
            detail_lines.append(f"  ⚡ تسارع شراء: {e(str(pp_sig['buy_accel']))}")
    detail_text = "\n".join(detail_lines)
    # نلف الجزء كله في spoiler واحد
    spoiler_block = f"👁 *اضغط لإظهار التفاصيل:*\n||{detail_text}||"

    # ───── التذييل ─────
    # حالة BTC الكاملة (تظهر مع كل توصية)
    btc_st = result.get("btc_status_full")
    btc_block = ""
    if btc_st:
        emoji_map = {
            "BULLISH": "🟢", "NEUTRAL": "🟢", "BEARISH_LIGHT": "🟡",
            "HIGH_VOL": "🟡", "BEARISH_STRONG": "🔴", "CRASH": "🚨", "UNKNOWN": "❓",
        }
        name_map = {
            "BULLISH": "Bullish", "NEUTRAL": "Neutral", "BEARISH_LIGHT": "Bearish خفيف",
            "HIGH_VOL": "تقلب عالي", "BEARISH_STRONG": "Bearish قوي",
            "CRASH": "Crash", "UNKNOWN": "غير معروف",
        }
        bem = emoji_map.get(btc_st["status"], "❓")
        bnm = name_map.get(btc_st["status"], "?")
        ch1 = f"{btc_st['change_1h']:+.2f}%"
        ch4 = f"{btc_st['change_4h']:+.2f}%"
        btc_block = (f"\n{bem} *BTC:* {e(bnm)} "
                     f"\\(1h {e(ch1)} \\| 4h {e(ch4)}\\)")

    btc_warn = result.get("btc_warning")
    btc_warn_line = f"\n⚠️ {e(btc_warn)}" if btc_warn else ""
    footer = [
        "",
        "━" * 18,
        f"⏰ {e(datetime.now().strftime('%H:%M:%S'))} \\| 📡 Gate\\.io{btc_block}{btc_warn_line}",
    ]

    header_lines_final = [l for l in header_lines if l is not None]
    return "\n".join(header_lines_final + [spoiler_block] + footer)


# ════════════════════════════════════════════════════════════════════
# ✅ v8.0 — فحص إشارات البامب (الـ 12 شرط)
# ════════════════════════════════════════════════════════════════════

def prescan_filter(coins):
    """
    المرحلة 1 — فلتر مسبق سريع بدون طلبات إضافية.
    بيستخدم بيانات الـ ticker فقط (موجودة مجاناً).
    الهدف: تقليل العملات من 2500 لـ ~200 نشطة فعلاً.

    معايير الإبقاء:
    - فوليم ≥ $3M → تتفحص دايماً (عملة كبيرة)
    - تغيّر 24h بين -8% و+25% (مش انهيار ومش فات القطار)
    - range_24h / price ≥ 0.3% (في حركة فعلية)
    """
    passed, skipped = [], 0
    for d in coins:
        vol   = d.get("volume_24h", 0)
        chg   = d.get("price_change_24h", 0)
        price = d.get("price", 0)
        high  = d.get("high_24h", price)
        low   = d.get("low_24h", price)

        # دايماً نفحص العملات الكبيرة
        if vol >= PRESCAN_LARGE_VOL:
            passed.append(d)
            continue

        # فلتر الانهيار والقطار الفات
        if chg <= PRESCAN_MIN_CHANGE_24H or chg >= PRESCAN_MAX_CHANGE_24H:
            skipped += 1
            continue

        # فلتر "البامب وراح": لو القمة أعلى من السعر الحالي بكتير
        # يعني العملة طلعت ونزلت = فات القطار حتى لو التغيّر 24h صغير
        if price > 0 and high > price:
            pullback_pct = (high - price) / price * 100
            if pullback_pct > PRESCAN_MAX_PULLBACK:
                skipped += 1
                continue

        # فلتر العملات الميتة (range صغير جداً)
        if price > 0:
            range_pct = (high - low) / price * 100
            if range_pct < PRESCAN_MIN_ACTIVITY:
                skipped += 1
                continue

        passed.append(d)

    logger.info(
        f"🔍 Pre-scan: {len(coins)} عملة → {len(passed)} نشطة "
        f"(تم تخطي {skipped} ميتة/انهيار/فات)"
    )
    return passed

async def check_signals(bot: Bot, target_chat: int = None):
    global previous_signals, btc_crashed
    logger.info("🚀 فحص إشارات البامب (Pump Detection v9.0)...")
    chat_target = target_chat if target_chat else int(ADMIN_CHAT_ID)

    async with aiohttp.ClientSession() as session:
        # 0️⃣ فلتر البيتكوين
        btc_info = {"status": "UNKNOWN", "warning": None, "change_1h": 0, "change_4h": 0, "atr_pct": 0}
        if BTC_FILTER_ENABLED:
            btc_info = await fetch_btc_status(session)
            logger.info(f"📡 BTC: status={btc_info['status']} | 1h={btc_info['change_1h']:.2f}% | 4h={btc_info['change_4h']:.2f}%")

            # استئناف تلقائي من Crash
            if btc_crashed and btc_info["change_1h"] >= BTC_RECOVERY_1H:
                btc_crashed = False
                logger.info("▶️ BTC تعافى — استئناف الفحص تلقائياً")
                try:
                    await bot.send_message(chat_id=chat_target,
                        text="▶️ *BTC تعافى* — استئناف فحص الإشارات تلقائياً",
                        parse_mode="Markdown")
                except Exception: pass

            # Crash جديد
            if btc_info["status"] == "CRASH":
                if not btc_crashed:
                    btc_crashed = True
                    logger.warning("⏸️ BTC Crash — إيقاف الفحص")
                    try:
                        crash_msg = (f"⏸️ *BTC Crash* — {btc_info['warning']}\n"
                                     f"الفحص موقوف حتى التعافي (>= {BTC_RECOVERY_1H}% في 1h)")
                        await bot.send_message(chat_id=chat_target,
                            text=crash_msg,
                            parse_mode="Markdown")
                    except Exception: pass
                return

            # Bearish قوي → رفض كل الإشارات
            if btc_info["status"] == "BEARISH_STRONG":
                logger.warning(f"🔴 BTC Bearish قوي — رفض الإشارات")
                try:
                    bearish_msg = (f"🔴 *BTC Bearish قوي* — {btc_info['warning']}\n"
                                   f"تم تخطي دورة الفحص")
                    await bot.send_message(chat_id=chat_target,
                        text=bearish_msg,
                        parse_mode="Markdown")
                except Exception: pass
                return

        # 1️⃣ جلب كل عملات Gate.io USDT
        gate_tickers = await fetch_gate_tickers(session)
        if not gate_tickers:
            logger.error("❌ فشل جلب tickers من Gate.io")
            return

        # 2️⃣ فلتر العملات — المرحلة 1: تحويل وفلتر أساسي
        raw_coins = []
        for t in gate_tickers:
            d = parse_gate_ticker(t)
            if not d: continue
            if d["symbol"] in EXCLUDED_SYMBOLS: continue
            if normalize_symbol(d["symbol"]) in HARAM_SYMBOLS:
                logger.debug(f"🚫 {d['symbol']} محرمة — تم تخطيها")
                continue
            if is_leveraged_token(d["symbol"]):
                continue   # توكن رافعة مالية — خطير
            if d["volume_24h"] < PRESCAN_MIN_VOL_24H: continue
            if d["price"] <= 0: continue
            raw_coins.append(d)

        # المرحلة 2: Pre-scan — يشيل العملات الميتة والانهيارات والفات قطارها
        candidates = prescan_filter(raw_coins)
        candidates = candidates[:GATE_MAX_CANDIDATES]

        # إثراء من CMC للحصول على الاسم الكامل والـ tags وإجمالي فوليم كل المنصات
        try:
            cmc_raw = await fetch_cmc(session, limit=CMC_LIMIT)
            cmc_by_sym = {c.get("symbol", "").upper(): c for c in (cmc_raw or [])}
            for d in candidates:
                cmc = cmc_by_sym.get(d["symbol"].upper())
                if cmc:
                    d["name"] = cmc.get("name", d.get("name", ""))
                    d["tags"] = cmc.get("tags", [])
                    # إجمالي فوليم عبر كل المنصات من CMC
                    quote = cmc.get("quote", {}).get("USD", {})
                    d["volume_cmc_total"] = float(quote.get("volume_24h", 0) or 0)
                else:
                    # العملة مش في الـ top CMC — نعلّمها لجلب فوليمها مباشرة لاحقاً
                    d["volume_cmc_total"] = 0
        except Exception as e:
            logger.warning(f"إثراء CMC فشل: {e} — نكمل بالأسماء من Gate فقط")
            for d in candidates:
                d["volume_cmc_total"] = 0

        logger.info(f"📋 سيتم التحليل الكامل لـ {len(candidates)} عملة من أصل {len(raw_coins)} (بعد Pre-scan)")

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
                    result["price_change_24h"] = coin["price_change_24h"]
                    result["volume_cmc_total"] = coin.get("volume_cmc_total", 0)
                    # حساب النسبة المئوية الثابتة
                    core_ks = ["funding_rate", "cvd_divergence", "taker_buy_ratio", "ob_imbalance"]
                    supp_ks = ["vol_accel", "bid_wall", "whale_accum", "ema21_cross",
                               "mtf_buy", "short_liq", "first_3min", "early_surge",
                               "vol_price_conf", "buysell_press"]
                    conds = result["conditions"]
                    W_CORE_MAX = 6
                    core_p = sum(round(conds[k]["score"] / W_CORE_MAX * 15) for k in core_ks)
                    supp_p = sum(4 for k in supp_ks if conds[k]["pass"])
                    # منع التكرار: الـ Pre-Pump بيستخدم whale/bid_wall/early_surge
                    prepump_active = result["filters"].get("prepump_bonus", 0) > 0
                    if prepump_active:
                        overlap_keys = ["whale_accum", "bid_wall", "early_surge"]
                        overlap_dbl = sum(4 for k in overlap_keys if conds[k]["pass"])
                        supp_p -= overlap_dbl // 2
                    # Score History Penalty: لو سبق إرسالها وما تحركتش
                    hist_penalty = 0
                    sym = coin["symbol"]
                    if sym in seen_signals:
                        entry = seen_signals[sym]
                        if isinstance(entry, tuple) and len(entry) >= 2:
                            last_time = entry[0]
                            elapsed_h = (datetime.now() - last_time).total_seconds() / 3600
                            # لو في آخر 6 ساعات وما تحركتش = خصم
                            price_then = entry[3] if len(entry) >= 4 else None
                            if price_then and elapsed_h < 6:
                                price_chg = abs(coin["price"] - price_then) / price_then
                                if price_chg < HISTORY_FAIL_THRESHOLD:
                                    hist_penalty = HISTORY_PENALTY_PCT
                    result["filters"]["history_penalty"] = hist_penalty
                    prepump_bonus = result["filters"].get("prepump_bonus", 0)
                    result["score_pct"]  = min(100, max(0, core_p + supp_p
                                               + prepump_bonus
                                               - result["filters"].get("confluence_penalty", 0)
                                               - hist_penalty))
                    result["core_pct"]   = core_p
                    result["supp_pct"]   = supp_p
                    return result
                except Exception as e:
                    logger.warning(f"خطأ تحليل {coin['symbol']}: {e}")
                    return None

        tasks   = [analyze(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # 4️⃣ فلترة: نحتفظ بالإشارات MODERATE+ فقط (لا Early Warning)
    all_results     = [r for r in results if r and not isinstance(r, Exception)]
    main_signals    = [r for r in all_results if r["strength"] in ("STRONG", "MODERATE")
                       and r.get("score_pct", 0) >= MIN_SCORE
                       and (not CONFIRM_REQUIRED or r.get("confirmed", False))]

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
    fresh_main.sort(key=lambda x: x.get("score_pct", 0), reverse=True)

    if not fresh_main:
        logger.info(f"✅ لا توجد إشارات بامب جديدة (فحص {len(candidates)} عملة)")
        return

    # 7️⃣ إرسال الإشارات (كل الإشارات بدون حد)
    sent_count = 0
    # تحضير تحذير BTC (يضاف لكل إشارة في حالة Bearish خفيف أو تقلب عالي)
    btc_warn_text = btc_info.get("warning") if btc_info else None

    for r in fresh_main:
        try:
            # لو الفوليم الإجمالي مش متاح (العملة خارج top CMC) نجيبه مباشرة
            if not r.get("volume_cmc_total", 0):
                try:
                    q = await fetch_cmc_quote(session, r["symbol"])
                    if q and q.get("volume_24h", 0) > 0:
                        r["volume_cmc_total"] = q["volume_24h"]
                except Exception:
                    pass
            r["btc_warning"] = btc_warn_text
            r["btc_status_full"] = btc_info if btc_info else None
            msg = format_pump_signal_message(r)
            await bot.send_message(chat_id=chat_target, text=msg,
                                    parse_mode="MarkdownV2",
                                    disable_web_page_preview=True)
            # نخزن الوقت + النقاط + القوة (للسماح بإعادة الإرسال لو زادت أو ترقّت)
            seen_signals[r["symbol"]] = (datetime.now(), r["score"], r["strength"], r["price"])
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
        "🚀 Pump Detection Bot v8.0 — Gate.io\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "نظام كشف البامب — 12 شرط قوية:\n\n"
        "⭐ الشروط الأساسية (الأهم):\n"
        f"1️⃣ Funding Rate Anomaly     ({PUMP_W_FUNDING_RATE} pts)\n"
        f"2️⃣ CVD Divergence            ({PUMP_W_CVD_DIVERGENCE} pts)\n"
        f"3️⃣ Taker Buy Ratio           ({PUMP_W_TAKER_BUY_RATIO} pts)\n"
        f"4️⃣ Order Book Imbalance      ({PUMP_W_OB_IMBALANCE} pts)\n\n"
        "📊 الشروط التكميلية:\n"
        f"5️⃣ Volume Acceleration       ({PUMP_W_VOL_ACCEL} pts)\n"
        f"6️⃣ Bid Wall (دعم قوي)         ({PUMP_W_BID_WALL} pts)\n"
        f"7️⃣ Whale Accumulation 🐋      ({PUMP_W_WHALE_ACCUM} pts)\n"
        f"8️⃣ RSI Momentum 📈           ({PUMP_W_EMA21_CROSS} pts)\n"
        f"9️⃣ Higher Lows 📐            ({PUMP_W_MTF_BUY} pts)\n"
        f"🔟 Liquidity Grab 🎯         ({PUMP_W_SHORT_LIQ} pts)\n"
        f"1️⃣1️⃣ Candle Momentum 🕯️       ({PUMP_W_CANDLE_MOM} pt)\n"
        f"1️⃣2️⃣ Early Volume Surge 📈  ({PUMP_W_EARLY_SURGE} pt)\n\n"
        f"📊 كل أساسي = 15% | كل فرعي = 5%\n"
        f"✅ حد الإرسال: >= {MIN_SCORE}%\n"
        f"✅ شرط الإرسال: 3/4 أساسية على الأقل\n\n"
        f"🌐 المصدر: كل عملات Gate.io USDT\n"
        f"   فلتر: فوليم 24h ≥ ${MIN_VOL_FOR_SIGNAL/1_000_000:.1f}M\n"
        f"🔄 سكان مستمر — فاصل {SIGNAL_LOOP_GAP_SECONDS}ث\n"
        f"⏱ Cooldown: {PUMP_SIGNAL_COOLDOWN_MIN}m (إلا لو النقاط زادت)\n\n"
        "الأوامر:\n"
        "/status      — حالة البوت\n"
        "/chatid      — معرفة الـ Chat ID"
    )





async def cmd_gainers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /gainers — أعلى 20 عملة رابحة على Gate.io (USDT)"""
    await update.message.reply_text("⏳ جاري جلب أعلى العملات ربحاً...")
    try:
        async with aiohttp.ClientSession() as session:
            gate_tickers = await fetch_gate_tickers(session)
        if not gate_tickers:
            await update.message.reply_text("❌ فشل جلب البيانات من Gate.io")
            return

        coins = []
        for t in gate_tickers:
            d = parse_gate_ticker(t)
            if not d: continue
            if d["symbol"] in EXCLUDED_SYMBOLS: continue
            if normalize_symbol(d["symbol"]) in HARAM_SYMBOLS: continue
            if is_leveraged_token(d["symbol"]): continue   # توكن رافعة
            if d["price"] <= 0: continue
            # نتجاهل العملات الميتة (فوليم أقل من الحد)
            if d["volume_24h"] < MIN_VOL_FOR_SIGNAL: continue
            coins.append(d)

        # ترتيب تنازلي حسب التغيّر 24h
        coins.sort(key=lambda x: x["price_change_24h"], reverse=True)
        top = coins[:20]

        if not top:
            await update.message.reply_text("لا توجد عملات مطابقة.")
            return

        def fmt_v(v):
            if v >= 1_000_000:
                return f"${v/1_000_000:.1f}M"
            return f"${v/1_000:.0f}K"

        lines = ["🚀 أعلى 20 عملة رابحة (Gate.io)", "━━━━━━━━━━━━━━━━━━━━"]
        for i, c in enumerate(top, 1):
            lines.append(
                f"{i}. {c['symbol']}USDT  "
                f"+{c['price_change_24h']:.1f}%  "
                f"| {fmt_v(c['volume_24h'])}"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("⚠️ نسبة ربح عالية = ممكن القطار فات")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /volume SYMBOL — يعرض الفوليم الإجمالي لعملة عبر كل المنصات"""
    args = context.args
    if not args:
        await update.message.reply_text(
            "اكتب رمز العملة بعد الأمر.\nمثال: /volume BTC أو /volume PEPE"
        )
        return
    sym = args[0].upper().replace("USDT", "").replace("_", "").strip()
    await update.message.reply_text(f"⏳ جاري جلب فوليم {sym}...")
    try:
        async with aiohttp.ClientSession() as session:
            # الفوليم الإجمالي من CMC (كل المنصات)
            cmc = await fetch_cmc_quote(session, sym)
            # فوليم Gate.io فقط
            gate_vol = 0.0
            gate_tickers = await fetch_gate_tickers(session)
            for t in (gate_tickers or []):
                if t.get("currency_pair", "") == f"{sym}_USDT":
                    gate_vol = float(t.get("quote_volume", 0) or 0)
                    break

        def fmt_v(v):
            if v >= 1_000_000_000:
                return f"${v/1_000_000_000:.2f}B"
            if v >= 1_000_000:
                return f"${v/1_000_000:.2f}M"
            if v >= 1_000:
                return f"${v/1_000:.1f}K"
            return f"${v:.0f}"

        lines = [f"📊 فوليم {sym}", "━━━━━━━━━━━━━━━━━━━━"]
        if cmc:
            lines += [
                f"🪙 الاسم:  {cmc['name']}",
                f"💰 السعر:  ${cmc['price']:.6f}".rstrip("0").rstrip("."),
                f"📈 تغيّر 24h:  {cmc['change_24h']:+.2f}%",
                "━━━━━━━━━━━━━━━━━━━━",
                f"🌐 فوليم كل المنصات:  {fmt_v(cmc['volume_24h'])}",
                f"   (عبر {cmc['num_pairs']} زوج تداول)",
            ]
        else:
            lines.append("⚠️ العملة غير موجودة في CMC")
        if gate_vol > 0:
            lines.append(f"📡 فوليم Gate.io:  {fmt_v(gate_vol)}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_haram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /haram — عرض/إضافة/حذف العملات المحرمة (محفوظة في ملف)"""
    args = context.args
    if args:
        action = args[0].lower()
        # حذف: /haram del SYMBOL
        if action in ("del", "delete", "remove", "حذف") and len(args) >= 2:
            sym = normalize_symbol(args[1])
            if sym in HARAM_SYMBOLS:
                HARAM_SYMBOLS.discard(sym)
                save_haram_symbols()
                await update.message.reply_text(f"✅ تم حذف {sym} من المحرمة.")
            else:
                await update.message.reply_text(f"⚠️ {sym} مش موجودة في القائمة.")
            return
        # إضافة (عملة واحدة أو أكتر): /haram SYM1 SYM2 ...
        added = []
        for a in args:
            sym = normalize_symbol(a)
            if sym and sym not in ("DEL","DELETE","REMOVE"):
                HARAM_SYMBOLS.add(sym)
                added.append(sym)
        if added:
            save_haram_symbols()
            await update.message.reply_text(
                f"✅ تم إضافة: {', '.join(added)}\nإجمالي المحرمة: {len(HARAM_SYMBOLS)}"
            )
        return
    # عرض القائمة
    if not HARAM_SYMBOLS:
        await update.message.reply_text("القائمة فارغة.")
        return
    lines = [f"🚫 *العملات المحرمة* ({len(HARAM_SYMBOLS)}):", "━━━━━━━━━━━━━━━━━━━━"]
    for s in sorted(HARAM_SYMBOLS):
        lines.append(f"  • {s}USDT")
    lines += ["━━━━━━━━━━━━━━━━━━━━",
              "➕ إضافة: /haram SYMBOL",
              "➖ حذف: /haram del SYMBOL"]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /btc — يعرض حالة البيتكوين الحالية وقرار الفلتر"""
    await update.message.reply_text("⏳ جاري جلب بيانات BTC...")
    try:
        async with aiohttp.ClientSession() as session:
            info = await fetch_btc_status(session)

        status_map = {
            "BULLISH":        "🟢 Bullish — سماح كامل",
            "NEUTRAL":        "🟢 Neutral — سماح كامل",
            "BEARISH_LIGHT":  "🟡 Bearish خفيف — سماح + تحذير",
            "HIGH_VOL":       "🟡 تقلب عالي — سماح + تحذير",
            "BEARISH_STRONG": "🔴 Bearish قوي — رفض الإشارات",
            "CRASH":          "🚨 Crash — الفحص موقوف",
            "UNKNOWN":        "❓ غير معروف",
        }
        decision = status_map.get(info["status"], "❓")
        crash_note = ("\n⏸️ الفحص موقوف حالياً (في انتظار تعافي BTC)" if btc_crashed else "")

        lines = [
            "📡 حالة Bitcoin",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📊 التغيّر 1h:  {info['change_1h']:+.2f}%",
            f"📊 التغيّر 4h:  {info['change_4h']:+.2f}%",
            f"📈 ATR (4h):   {info['atr_pct']:.2f}%",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🎯 الحالة:  {decision}{crash_note}",
            "━━━━━━━━━━━━━━━━━━━━",
            "المعايير:",
            "  🟢 Bullish:        4h >= +1%",
            "  🟢 Neutral:        4h بين -1% و+1%",
            "  🟡 Bearish خفيف:   4h بين -2% و-1%",
            f"  🟡 تقلب عالي:      ATR >= {BTC_HIGH_ATR_PCT}%",
            "  🔴 Bearish قوي:    4h < -2%",
            f"  🚨 Crash:          1h < {BTC_CRASH_1H}%",
            f"  ✅ تعافي:          1h >= {BTC_RECOVERY_1H}%",
        ]
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب بيانات BTC: {e}")

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
    await update.message.reply_text(
        f"✅ Pump Detection Bot — v11.0 (Pre-Pump)\n\n"
        f"🌐 المصدر: كل Gate.io USDT\n"
        f"   فلتر 1: فوليم >= ${PRESCAN_MIN_VOL_24H/1_000:.0f}K\n"
        f"   فلتر 2: تغيّر بين {PRESCAN_MIN_CHANGE_24H}% و+{PRESCAN_MAX_CHANGE_24H}%\n"
        f"   فلتر 3: عملات $3M+ تتفحص دايماً\n"
        f"   📡 فلتر BTC: {'نشط' if BTC_FILTER_ENABLED else 'متوقف'}\n"
        f"   توازي: {GATE_PARALLEL_LIMIT} طلب\n\n"
        f"🚀 سكان البامب: {scanner_status}\n"
        f"   فاصل: {SIGNAL_LOOP_GAP_SECONDS}ث\n"
        f"   آخر دورة: {last_str}\n\n"
        f"📊 نظام النسب المئوية:\n"
        f"   ⭐ كل شرط أساسي = 15%\n"
        f"   📊 كل شرط فرعي  = 5%\n"
        f"   حد الإرسال: >= {MIN_SCORE}%\n"
        f"   Cooldown: {PUMP_SIGNAL_COOLDOWN_MIN} دقيقة\n\n"
        f"🔬 الشروط النشطة (12):\n"
        f"   ⭐ الأساسية:\n"
        f"   1. Funding Rate Anomaly\n"
        f"   2. CVD Divergence\n"
        f"   3. Taker Buy Ratio\n"
        f"   4. Order Book Imbalance\n"
        f"   📊 التكميلية:\n"
        f"   5. Volume Acceleration\n"
        f"   6. Bid Wall (دعم شراء قوي)\n"
        f"   7. Whale Accumulation 🐋\n"
        f"   8. RSI Momentum 📈\n"
        f"   9. Higher Lows 📐\n"
        f"   10. Liquidity Grab 🎯\n"
        f"   11. Candle Momentum 🕯️\n"
        f"   12. Early Volume Surge 📈\n\n"
        f"✅ شرط الإرسال: 3/4 أساسية على الأقل\n"
        f"🎯 أهداف مبنية على S/R حقيقية\n"
        f"🔒 Anti-Wash Trading نشط\n"
        f"📐 Spread Filter: < {SPREAD_MAX_PCT*100:.1f}%\n"
        f"📈 EMA50/4h Trend Filter نشط\n"
        f"⚡ Confluence Check نشط\n"
        f"📊 Score History Penalty: {HISTORY_PENALTY_PCT}%\n"
        f"🔮 Pre-Pump Engine نشط (رصد مبكر)\n"
        f"🎯 أهداف/استوب ديناميكية حسب الزخم\n"
        f"📈 Trailing Stop متكيّف"
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
                "🟢 *Pump Detection Bot v11.0 — Gate.io*\n"
                f"🚀 السكان المستمر: شغال (فاصل {SIGNAL_LOOP_GAP_SECONDS}ث)\n"
                f"🌐 يفحص كل عملات Gate.io USDT (2500+ عملة)\n"
        f"⚡ Pre-scan سريع → تحليل كامل للنشطة فقط\n"
                f"⚡ 12 شرط نشطة | المجموع: {PUMP_MAX_SCORE} نقاط\n"
                f"🚀 STRONG ≥ {PUMP_SCORE_STRONG} | ⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE}"
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
    app.add_handler(CommandHandler("btc",     cmd_btc))
    app.add_handler(CommandHandler("haram",   cmd_haram))
    app.add_handler(CommandHandler("volume",  cmd_volume))
    app.add_handler(CommandHandler("gainers", cmd_gainers))

    load_seen_coins()
    load_seen_signals()   # ✅ v6.4
    load_haram_symbols()  # ✅ v11 — تحميل المحرمة المحفوظة

    # ✅ التأكد من إضافة الـ jobs مرة واحدة فقط
    jq = app.job_queue
    # إزالة أي jobs قديمة بنفس الاسم (احتياط)
    for j in list(jq.jobs()):
        try: j.schedule_removal()
        except: pass

    # ✅ v5.0 — السكان المستمر فقط (تم حذف تقرير الفوليوم)
    # السكان يبدأ من post_init كـ background task

    print("="*60)
    print("🚀 Pump Detection Bot v11.0 — Gate.io Edition (Pre-Pump Engine)")
    print(f"🌐 المصدر: كل Gate.io USDT (2500+ عملة)")
    print(f"   المرحلة 1 — Pre-scan: فوليم >= ${PRESCAN_MIN_VOL_24H/1_000:.0f}K، تغيّر {PRESCAN_MIN_CHANGE_24H}% ~ +{PRESCAN_MAX_CHANGE_24H}%")
    print(f"   المرحلة 2 — تحليل كامل (7 طلبات/عملة) على النشطة فقط")
    print(f"   توازي: {GATE_PARALLEL_LIMIT} طلب")
    print(f"")
    print(f"🚨 نظام البامب (12 شرط):")
    print(f"   ⭐ الأساسية:")
    print(f"   1. Funding Rate Anomaly      ({PUMP_W_FUNDING_RATE} pts)")
    print(f"   2. CVD Divergence             ({PUMP_W_CVD_DIVERGENCE} pts)")
    print(f"   3. Taker Buy Ratio            ({PUMP_W_TAKER_BUY_RATIO} pts)")
    print(f"   4. Order Book Imbalance       ({PUMP_W_OB_IMBALANCE} pts)")
    print(f"   📊 التكميلية:")
    print(f"   5. Volume Acceleration        ({PUMP_W_VOL_ACCEL} pts)")
    print(f"   6. Bid Wall                   ({PUMP_W_BID_WALL} pts)")
    print(f"   7. Whale Accumulation         ({PUMP_W_WHALE_ACCUM} pts)")
    print(f"   8. RSI Momentum               ({PUMP_W_EMA21_CROSS} pts)")
    print(f"   9. Multi-TF Buy Pressure      ({PUMP_W_MTF_BUY} pts)")
    print(f"   10. Liquidity Grab            ({PUMP_W_SHORT_LIQ} pts)")
    print(f"   11. Candle Momentum          ({PUMP_W_CANDLE_MOM} pt)")
    print(f"   12. Early Volume Surge     ({PUMP_W_EARLY_SURGE} pt)")
    print(f"   ───────────────────────────")
    print(f"   المجموع: {PUMP_MAX_SCORE} نقاط")
    print(f"   🚀 STRONG ≥ {PUMP_SCORE_STRONG}  |  ⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE}")
    print(f"   ✅ شرط الإرسال: 3/4 أساسية على الأقل")
    print(f"")
    print(f"🔄 السكان المستمر: فاصل {SIGNAL_LOOP_GAP_SECONDS}ث بين الدورات")
    print(f"   Cooldown لكل عملة: {PUMP_SIGNAL_COOLDOWN_MIN} دقيقة (إلا لو النقاط زادت)")
    print(f"🔔 الإرسال: الأدمن فقط")
    print(f"🔒 Lock نشط ضد الإرسال المزدوج")
    print("="*60)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
