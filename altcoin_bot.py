"""
🚀 Pump Detection Bot v6.0 — Gate.io Edition
نظام كشف البامب بـ 7 شروط فقط (بنفس المدخلات الأصلية):
  ⭐ الأساسية: Funding Rate, CVD Divergence, Taker Buy Ratio, Order Book Imbalance
  📊 التكميلية: Volume Acceleration, Sustained Buy Pressure, Bid Wall
السكان المستمر يفحص كل عملات Gate.io USDT ويرسل الإشارات للأدمن.
الأوامر: /start, /status, /chatid
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
MIN_VOL_FOR_SIGNAL = 2_000_000

# ✅ جديد v3.1: سكان البامب المستمر
SIGNAL_LOOP_GAP_SECONDS = 120     # ✅ v4.1: 120ث بدل 90 (لأن الفحص الآن أكبر)
SIGNAL_LOOP_ERR_GAP     = 30      # فاصل بعد خطأ
SIGNAL_COOLDOWN_HOURS     = 6     # كان 24h — قللناه عشان السكان المستمر
GATE_MAX_CANDIDATES       = 1500       # سقف عدد العملات في الفحص الواحد
GATE_PARALLEL_LIMIT       = 25         # طلبات كلاينز متوازية (زدناها لـ 25)

# ════════════════════════════════════════════════════════════════════
# ✅ v6.0 — PUMP DETECTION (7 شروط قوية — Gate.io)
# ════════════════════════════════════════════════════════════════════
# الـ 4 شروط الأساسية (طلب المستخدم): Funding + CVD + Taker + OB Imbalance
# + 3 شروط تكميلية قوية تأكد الجودة
# لا "قيد المراقبة" — فقط فرص جاهزة
# الإشارة لا تتكرر إلا لو النقاط زادت
# ════════════════════════════════════════════════════════════════════

# ───── الشروط الـ 4 الأساسية ─────
PUMP_W_FUNDING_RATE      = 3   # 1) ⭐ Funding Rate Anomaly
PUMP_W_CVD_DIVERGENCE    = 4   # 2) ⭐ CVD Divergence (الأهم)
PUMP_W_TAKER_BUY_RATIO   = 3   # 3) ⭐ Taker Buy Ratio
PUMP_W_OB_IMBALANCE      = 3   # 4) ⭐ Order Book Imbalance

# ───── الشروط الـ 3 الجديدة (تكميلية) ─────
PUMP_W_VOL_ACCEL         = 3   # 5) Volume Acceleration
PUMP_W_SUSTAINED_BUY     = 3   # 6) Sustained Buy Pressure
PUMP_W_BID_WALL          = 3   # 7) Bid Wall (دعم شراء قوي)

PUMP_MAX_SCORE           = 22  # المجموع الأقصى
PUMP_SCORE_STRONG        = 15  # 🚀 STRONG (≥ 68%)
PUMP_SCORE_MODERATE      = 11  # ⚠️ MODERATE (≥ 50%)
PUMP_SIGNAL_COOLDOWN_MIN = 180 # ✅ v6.4 — 3 ساعات بدل ساعة
PUMP_RESEND_MIN_INCREASE = 3   # ✅ v6.4 — لازم النقاط تزيد 3+ لإعادة الإرسال
PUMP_RESEND_ON_UPGRADE   = True # ✅ v6.4 — إعادة الإرسال لو ترقّى من MODERATE لـ STRONG


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

# ───── الشروط الجديدة ─────
PUMP_VOL_ACCEL_MIN       = 1.5       # 1.5x = 2 نقاط
PUMP_VOL_ACCEL_STRONG    = 2.5       # 2.5x = 3 نقاط
PUMP_SUSTAINED_CANDLES   = 3         # 3 شموع متتالية
PUMP_BID_WALL_RANGE      = 0.015     # ±1.5% من السعر
PUMP_BID_WALL_MIN_RATIO  = 2.0       # bid wall ≥ 2x متوسط الـ asks
PUMP_BID_WALL_STRONG     = 4.0       # ≥ 4x = ⭐ قوي جداً

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


# ════════════════════════════════════════════════════════════════════
# ✅ v6.3 — فلتر شرعي شامل (Haram Filter)
# ════════════════════════════════════════════════════════════════════
# نستبعد العملات اللي طبيعة عملها محرمة:
# 1. الإقراض بالفائدة (Lending / Borrowing)
# 2. القمار والمراهنات (Gambling / Betting / Casino)
# 3. المحتوى الإباحي (Adult / NSFW)
# 4. الكحول والمخدرات
# 5. التأمين التجاري والمشتقات
# 6. الأشياء غير اللائقة دينياً

# ───── 1) Lending / Borrowing (الإقراض بالفائدة) ─────
HARAM_LENDING_SYMBOLS = {
    "AAVE", "COMP", "MKR", "DAI", "SDAI",
    "CRV", "CVX",
    "MORPHO", "EUL", "BENQI", "QI",
    "JST", "JUSTLEND",
    "RDNT", "RADIANT",
    "VENUS", "XVS", "VAI",
    "SPELL", "ICE", "MIM",
    "ALPHA", "ALCX",
    "TRU", "MPL",
    "FOLD", "REQ",
    "CREAM", "ANC",
    "BIFI", "AUTO",
    "TND", "FOX",
    "FRAX", "FXS",
    "GRO", "ALPACA",
    "ARTH", "MAHA",
    "SDT",
    "BANK",
}

# ───── 2) Gambling / Betting / Casino / Lottery ─────
HARAM_GAMBLING_SYMBOLS = {
    "FUN", "FUNTOKEN",
    "ROLL", "WINK", "WIN",
    "EDG", "EDGELESS",
    "CHP", "CHIPZ",
    "DICE", "DICEROLL",
    "BET", "BETKING", "BETSWAP",
    "CASINO", "CSC",
    "BNKR", "POKER", "POKERFI",
    "STAKE",
    "ZKB",
    "TGT", "BLOK",
    "MEGA", "MILLIONS",
    "POOL", "POOLTOGETHER",
    "FAIRY", "LOTTO",
    "LUCK", "LUCKY", "JACKPOT",
}

# ───── 3) Adult Content / NSFW ─────
HARAM_ADULT_SYMBOLS = {
    "VID", "PORN", "SEX", "SEXY", "XXX",
    "ADULT", "NSFW", "MILF",
    "PUSSY", "DICK", "COCK", "BOOB",
    "STRIPPER", "STRIPCHAIN", "STRIP",
    "ONLYFANS", "ONLYFAN",
    "CAMS", "CAMGIRL", "CAM",
    "EROS", "EROTIC", "LUST",
    "HOOKER", "HOE",
    "FUCK", "WHORE", "SLUT", "BDSM",
    "REDLIGHT",
}

# ───── 4) Alcohol / Drugs ─────
HARAM_ALCOHOL_SYMBOLS = {
    "BEER", "WINE", "WHISKEY", "VODKA", "RUM",
    "ALCOHOL", "BOOZE", "TEQUILA", "GIN",
    "CANNABIS", "WEED", "GANJA", "MARIJUANA",
    "HASH", "BLAZE", "BLUNT", "HEMP",
    "COCAINE", "METH", "MDMA", "LSD",
    "OPIUM", "HEROIN", "DRUG", "DRUGS",
    "POTCOIN", "DOPECOIN",
}

# ───── 5) Inappropriate / Anti-Religion ─────
HARAM_INAPPROPRIATE_SYMBOLS = {
    "JESUS", "CHRIST", "DEVIL", "SATAN",
    "DEMON", "DAEMON", "HELL", "LUCIFER",
    "666", "ANTICHRIST", "PAGAN",
}

# ───── Tags المحرمة من CMC ─────
HARAM_TAGS = {
    "lending-borrowing", "lending", "yield-farming",
    "yield-aggregator", "interest-bearing-tokens",
    "gambling", "betting", "casino",
    "prediction-markets", "lottery",
    "adult", "nsfw", "alcohol", "cannabis", "drug",
    "insurance", "decentralized-insurance",
    "derivatives", "synthetic-issuer", "perpetuals",
    "leveraged-tokens", "options", "binary-options",
}

# ───── Keywords في الاسم ─────
HARAM_NAME_KEYWORDS = {
    # Lending / Interest (يكتفي وجودها في الاسم)
    "lending", "borrow", "loan", "credit", "yield", "apy", "interest",
    "mortgage", "lender",
    # Gambling
    "casino", "gambling", "betting", "betswap", "betfury",
    "poker", "roulette", "blackjack", "jackpot", "slot",
    "lottery", "lotto", "wager",
    # Adult
    "porn", "xxx", "sexy", "erotic", "nsfw",
    "onlyfans", "camgirl",
    # Drugs / Alcohol
    "cannabis", "marijuana", "alcohol", "whiskey", "vodka",
    # Insurance / Derivatives
    "insurance", "perpetual", "synthetic", "leveraged",
    "derivative",
}

# Short keywords محتاجة padding لتجنب false positives
HARAM_SHORT_KEYWORDS = {"bet", "sex", "weed", "drug", "option", "beer", "wine", "adult"}


def is_haram_token(symbol, name, tags):
    """
    ✅ v6.3 — فحص شرعي شامل
    يرجع (is_haram: bool, reason: str | None)
    """
    sym = (symbol or "").upper().strip()
    nm  = (name or "").lower().strip()

    # 1) فحص الـ symbols
    if sym in HARAM_LENDING_SYMBOLS:        return True, "lending/interest"
    if sym in HARAM_GAMBLING_SYMBOLS:       return True, "gambling"
    if sym in HARAM_ADULT_SYMBOLS:          return True, "adult"
    if sym in HARAM_ALCOHOL_SYMBOLS:        return True, "alcohol/drugs"
    if sym in HARAM_INAPPROPRIATE_SYMBOLS:  return True, "inappropriate"

    # 2) فحص الـ tags من CMC
    if tags:
        tags_lower = {t.lower() if isinstance(t, str) else "" for t in tags}
        for tag in HARAM_TAGS:
            if tag in tags_lower:
                return True, f"tag:{tag}"

    # 3) فحص الـ keywords الطويلة (substring match مباشر)
    for kw in HARAM_NAME_KEYWORDS:
        if kw in nm:
            return True, f"name:{kw}"

    # 4) فحص الـ keywords القصيرة (لازم تكون كلمة منفصلة أو بداية/نهاية)
    nm_padded = f" {nm} "
    for kw in HARAM_SHORT_KEYWORDS:
        # match: " bet ", "bet ", " bet", or starts/ends with kw
        if (f" {kw} " in nm_padded or
            f" {kw}s " in nm_padded or
            f"-{kw}" in nm or f"{kw}-" in nm or
            nm.endswith(kw) or nm.startswith(f"{kw} ")):
            return True, f"name:{kw}"

    return False, None

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
# ✅ v5.0 — Gate.io Pump Detection Data Fetchers
# ════════════════════════════════════════════════════════════════════

async def fetch_gate_funding_rate(session, symbol):
    """
    الشرط 1: Gate.io futures funding rate
    Returns: float (e.g. -0.0012 لـ -0.12%) أو None
    """
    url = "https://api.gateio.ws/api/v4/futures/usdt/funding_rate"
    params = {"contract": f"{symbol}_USDT", "limit": 1}
    try:
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status != 200: return None
            data = await r.json()
        if not data or not isinstance(data, list): return None
        return float(data[0].get("r", 0))
    except Exception:
        return None


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
# ✅ v5.0 — تقييم الـ 7 شروط (8 - 1 ملغى = 7)
# ════════════════════════════════════════════════════════════════════

def eval_funding_rate(funding_rate):
    """
    الشرط 1 — Funding Rate Anomaly (max 3 pts)
    -0.05% → 2 نقاط، -0.10% → 3 نقاط
    """
    if funding_rate is None:
        return {"pass": False, "score": 0, "value": None, "label": "غير متاح (spot)"}
    pts = 0
    if funding_rate < PUMP_FUNDING_RATE_VLOW:
        pts = PUMP_W_FUNDING_RATE  # 3
    elif funding_rate < PUMP_FUNDING_RATE_LOW:
        pts = 2
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
    # ✅ v6.0 — tiered: divergence أقوى = نقاط أكثر
    price_ok      = abs(price_change_pct) < PUMP_PRICE_CHANGE_PCT
    is_strong     = cvd_change_pct > PUMP_CVD_STRONG_PCT and price_ok
    is_divergence = cvd_change_pct > PUMP_CVD_CHANGE_PCT and price_ok

    if is_strong:
        pts = PUMP_W_CVD_DIVERGENCE  # 4
        passed = True
    elif is_divergence:
        pts = 3
        passed = True
    else:
        pts = 0
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
    # ✅ v6.0 — منطق tiered ومُصحَّح
    # نشترط: المتوسط ≥ العتبة + 2 على الأقل من الـ 3 شرائح ≥ العتبة
    above_count = sum(1 for r in ratios if r >= PUMP_TAKER_RATIO_MIN)
    strong_avg  = avg_ratio >= PUMP_TAKER_RATIO_STRONG and above_count >= 2
    pass_avg    = avg_ratio >= PUMP_TAKER_RATIO_MIN and above_count >= 2

    if strong_avg:
        pts = PUMP_W_TAKER_BUY_RATIO  # 3
        passed = True
    elif pass_avg:
        pts = 2
        passed = True
    else:
        pts = 0
        passed = False

    return {
        "pass":  passed,
        "score": pts,
        "value": avg_ratio,
        "label": f"{avg_ratio*100:.1f}% (متوسط 3 شرائح، {above_count}/3 ≥ {PUMP_TAKER_RATIO_MIN*100:.0f}%)",
    }


def eval_orderbook_imbalance(ob, current_price):
    """
    الشرط 4 — Order Book Imbalance (max 3 pts) — tiered
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
        pts, passed = PUMP_W_OB_IMBALANCE, True   # 3
    elif imbalance >= PUMP_OB_IMBALANCE_MIN:
        pts, passed = 2, True
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


def eval_sustained_buy_pressure(candles_1h):
    """
    الشرط 6 — Sustained Buy Pressure (max 3 pts)
    3 شموع متتالية فيها:
      - شمعة خضراء (close > open)
      - الفوليوم الشرائي ≥ 55% (تقريبي: شمعة خضراء = 100% buy، حمراء = 0%)
    لا نملك tick-by-tick بيانات داخل الشمعة من /spot/candlesticks،
    لذا نستخدم منطق: شمعة خضراء قوية + range > 0.3% = ضغط شراء حقيقي
    """
    if not candles_1h or len(candles_1h) < PUMP_SUSTAINED_CANDLES + 1:
        return {"pass": False, "score": 0, "value": 0, "label": "كلاينز غير كافية"}
    last = candles_1h[-PUMP_SUSTAINED_CANDLES:]
    sustained_count = 0
    for c in last:
        if c["open"] <= 0: continue
        body_pct = (c["close"] - c["open"]) / c["open"] * 100
        rng = c["high"] - c["low"]
        if rng <= 0: continue
        body = abs(c["close"] - c["open"])
        body_ratio = body / rng  # حجم الجسم vs المدى الكلي
        # شمعة خضراء + body كبير (مش doji) + حركة محسوسة
        is_strong = c["close"] > c["open"] and body_ratio > 0.5 and body_pct > 0.2
        if is_strong:
            sustained_count += 1
    is_pass = sustained_count >= PUMP_SUSTAINED_CANDLES
    return {
        "pass":  is_pass,
        "score": PUMP_W_SUSTAINED_BUY if is_pass else (2 if sustained_count >= 2 else 0),
        "value": sustained_count,
        "label": f"{sustained_count}/{PUMP_SUSTAINED_CANDLES} شموع خضراء قوية متتالية",
    }


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


# ════════════════════════════════════════════════════════════════════
# ✅ v6.0 — المحرك الرئيسي للبامب (7 شروط)
# ════════════════════════════════════════════════════════════════════

async def evaluate_pump_signal(session, symbol, current_price):
    """
    يقيم الـ 7 شروط الجديدة على عملة واحدة
    """
    # جلب البيانات بالتوازي
    funding, trades, ob, kl1h = await asyncio.gather(
        fetch_gate_funding_rate(session, symbol),
        fetch_gate_recent_trades(session, symbol, limit=1000),
        fetch_gate_orderbook(session, symbol, limit=30),
        fetch_klines(session, symbol, interval="1h", limit=72),
        return_exceptions=True
    )
    if isinstance(funding, Exception): funding = None
    if isinstance(trades, Exception):  trades  = []
    if isinstance(ob, Exception):      ob      = None
    if isinstance(kl1h, Exception):    kl1h    = []

    # تقييم الشروط
    r1 = eval_funding_rate(funding)                           # 1) Funding (3 pts)
    r2 = eval_cvd_divergence(trades, kl1h)                    # 2) CVD (4 pts)
    r3 = eval_taker_buy_ratio(trades)                         # 3) Taker (3 pts)
    r4 = eval_orderbook_imbalance(ob, current_price)          # 4) OB Imbalance (3 pts)
    r5 = eval_volume_acceleration(kl1h)                       # 5) Vol Accel (3 pts)
    r6 = eval_sustained_buy_pressure(kl1h)                    # 6) Sustained (3 pts)
    r7 = eval_bid_wall(ob, current_price)                     # 7) Bid Wall (3 pts)

    total = r1["score"] + r2["score"] + r3["score"] + r4["score"] + r5["score"] + r6["score"] + r7["score"]

    # ───── شرط الـ core الإلزامي ─────
    core_passed = sum(1 for r in [r1, r2, r3, r4] if r["pass"])
    core_ok = core_passed >= 2

    # ───── ✅ v6.2 — Override: 3+ من 4 أساسية = إشارة دخول STRONG فورية ─────
    core_override = core_passed >= 3

    # ───── تصنيف القوة ─────
    if core_override:
        # 3 أو 4 من الأساسية متفعلين = إشارة دخول STRONG (مهما كانت النقاط)
        strength = "STRONG"
        strength_emoji = "\U0001f680"
        if core_passed == 4:
            strength_label = "STRONG — 4/4 أساسية متفعلة 🔥🔥 إشارة مثالية"
        else:
            strength_label = "STRONG — 3/4 أساسية متفعلة 🔥 إشارة دخول"
    elif total >= PUMP_SCORE_STRONG and core_ok:
        strength = "STRONG"
        strength_emoji = "\U0001f680"
        strength_label = "STRONG — نقاط عالية + أساسية كافية"
    elif total >= PUMP_SCORE_MODERATE and core_ok:
        strength = "MODERATE"
        strength_emoji = "\u26a0\ufe0f"
        strength_label = "MODERATE — دخول بحجم صغير"
    else:
        strength = None
        strength_emoji = "\u274c"
        strength_label = "تجاهل"

    stop_loss = current_price * 0.97  # -3%

    return {
        "symbol":     symbol,
        "price":      current_price,
        "score":      total,
        "max_score":  PUMP_MAX_SCORE,
        "strength":   strength,
        "strength_emoji": strength_emoji,
        "strength_label": strength_label,
        "core_passed": core_passed,
        "stop_loss":  stop_loss,
        "conditions": {
            "funding_rate":     r1,
            "cvd_divergence":   r2,
            "taker_buy_ratio":  r3,
            "ob_imbalance":     r4,
            "vol_accel":        r5,
            "sustained_buy":    r6,
            "bid_wall":         r7,
        },
    }


def format_pump_signal_message(result):
    """
    تنسيق الإشارة على نمط الـ prompt — 7 شروط
    """
    c = result["conditions"]
    sym = result["symbol"]
    sl_pct = (result["stop_loss"] - result["price"]) / result["price"] * 100

    lines = [
        "\u2501" * 20,
        f"{result['strength_emoji']} إشارة بامب محتملة",
        "\u2501" * 20,
        f"العملة    : {sym}USDT",
        f"السعر     : {fmt_price(result['price'])}",
        f"النقاط    : {result['score']} / {result['max_score']}",
        f"القوة     : {result['strength_emoji']} {result['strength_label']}",
        f"الأساسية  : {result['core_passed']}/4 شروط أساسية متفعلة",
        "",
        "الشروط:",
    ]
    items = [
        ("\u2b50", "Funding Rate",       c["funding_rate"]),
        ("\u2b50", "CVD Divergence",     c["cvd_divergence"]),
        ("\u2b50", "Taker Buy Ratio",    c["taker_buy_ratio"]),
        ("\u2b50", "Order Book Imb.",    c["ob_imbalance"]),
        ("",        "Volume Accel.",      c["vol_accel"]),
        ("",        "Sustained Buy",      c["sustained_buy"]),
        ("",        "Bid Wall",           c["bid_wall"]),
    ]
    for marker, name, r in items:
        icon = "\u2705" if r["pass"] else "\u274c"
        lbl = r.get("label", "")
        pts = r.get("score", 0)
        lines.append(f"{icon} {marker} {name} ({pts}p) : {lbl}")
    lines += [
        "",
        f"Stop Loss : {fmt_price(result['stop_loss'])} ({sl_pct:.1f}%)",
        f"الوقت     : {datetime.now().strftime('%H:%M:%S')} Gate.io",
        "\u2501" * 20,
        "\u2b50 = شرط أساسي",
    ]
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
# ✅ v5.0 — فحص إشارات البامب (الـ 7 شروط من ملف prompt)
# ════════════════════════════════════════════════════════════════════
async def check_signals(bot: Bot, target_chat: int = None):
    global previous_signals
    logger.info("🚀 فحص إشارات البامب (Pump Detection v6.0)...")
    chat_target = target_chat if target_chat else int(ADMIN_CHAT_ID)

    async with aiohttp.ClientSession() as session:
        # 1️⃣ جلب كل عملات Gate.io USDT
        gate_tickers = await fetch_gate_tickers(session)
        if not gate_tickers:
            logger.error("❌ فشل جلب tickers من Gate.io")
            return

        # 2️⃣ فلتر العملات: فوليم 24h ≥ MIN + symbol/name حلال
        candidates = []
        for t in gate_tickers:
            d = parse_gate_ticker(t)
            if not d: continue
            if d["symbol"] in EXCLUDED_SYMBOLS: continue
            if d["volume_24h"] < MIN_VOL_FOR_SIGNAL: continue
            if d["price"] <= 0: continue
            # ✅ v6.3 — فلتر شرعي بدائي على الـ symbol والـ name (بدون tags)
            haram, reason = is_haram_token(d["symbol"], d.get("name", ""), [])
            if haram:
                continue
            candidates.append(d)
        candidates = candidates[:GATE_MAX_CANDIDATES]

        # ✅ v6.3 — إثراء من CMC للحصول على tags ومضاعفة الفلتر الشرعي
        try:
            cmc_raw = await fetch_cmc(session, limit=CMC_LIMIT)
            cmc_by_sym = {c.get("symbol", "").upper(): c for c in (cmc_raw or [])}
            haram_filtered = 0
            enriched = []
            for d in candidates:
                cmc = cmc_by_sym.get(d["symbol"].upper())
                if cmc:
                    tags = cmc.get("tags", [])
                    cmc_name = cmc.get("name", d.get("name", ""))
                    # فحص شرعي ثاني مع الـ tags
                    haram, reason = is_haram_token(d["symbol"], cmc_name, tags)
                    if haram:
                        haram_filtered += 1
                        continue
                    d["name"] = cmc_name
                    d["tags"] = tags
                enriched.append(d)
            candidates = enriched
            logger.info(f"🚫 فلتر شرعي: استبعد {haram_filtered} عملة من CMC tags")
        except Exception as e:
            logger.warning(f"إثراء CMC فشل: {e} — نكمل بالـ symbol/name فقط")

        logger.info(f"📋 سيتم فحص {len(candidates)} عملة (فوليم ≥ ${MIN_VOL_FOR_SIGNAL/1_000_000:.1f}M)")

        # 3️⃣ تقييم الـ 7 شروط لكل عملة بالتوازي
        sem = asyncio.Semaphore(GATE_PARALLEL_LIMIT)
        async def analyze(coin):
            async with sem:
                try:
                    result = await evaluate_pump_signal(session, coin["symbol"], coin["price"])
                    # نضيف معلومات العملة
                    result["name"]            = coin.get("name", coin["symbol"])
                    result["volume_24h"]      = coin["volume_24h"]
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

    if not fresh_main:
        logger.info(f"✅ لا توجد إشارات بامب جديدة (فحص {len(candidates)} عملة)")
        return

    # 7️⃣ إرسال الإشارات
    sent_count = 0
    MAX_SIGNALS = 10
    for r in fresh_main[:MAX_SIGNALS]:
        try:
            msg = format_pump_signal_message(r)
            await bot.send_message(chat_id=chat_target, text=msg,
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
        "🚀 Pump Detection Bot v6.0 — Gate.io\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "نظام كشف البامب — 7 شروط قوية:\n\n"
        "⭐ الشروط الأساسية (الأهم):\n"
        f"1️⃣ Funding Rate Anomaly     ({PUMP_W_FUNDING_RATE} pts)\n"
        f"2️⃣ CVD Divergence            ({PUMP_W_CVD_DIVERGENCE} pts)\n"
        f"3️⃣ Taker Buy Ratio           ({PUMP_W_TAKER_BUY_RATIO} pts)\n"
        f"4️⃣ Order Book Imbalance      ({PUMP_W_OB_IMBALANCE} pts)\n\n"
        "📊 الشروط التكميلية:\n"
        f"5️⃣ Volume Acceleration       ({PUMP_W_VOL_ACCEL} pts)\n"
        f"6️⃣ Sustained Buy Pressure    ({PUMP_W_SUSTAINED_BUY} pts)\n"
        f"7️⃣ Bid Wall (دعم قوي)         ({PUMP_W_BID_WALL} pts)\n\n"
        f"🚀 STRONG ≥ {PUMP_SCORE_STRONG}/{PUMP_MAX_SCORE} نقاط\n"
        f"⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE}/{PUMP_MAX_SCORE} نقاط\n"
        f"⭐ Override: 3/4 أساسية = إشارة فورية\n\n"
        f"🌐 المصدر: كل عملات Gate.io USDT\n"
        f"   فلتر: فوليم 24h ≥ ${MIN_VOL_FOR_SIGNAL/1_000_000:.1f}M\n"
        f"🔄 سكان مستمر — فاصل {SIGNAL_LOOP_GAP_SECONDS}ث\n"
        f"⏱ Cooldown: {PUMP_SIGNAL_COOLDOWN_MIN}m (إلا لو النقاط زادت)\n\n"
        "الأوامر:\n"
        "/status      — حالة البوت\n"
        "/chatid      — معرفة الـ Chat ID"
    )

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
        f"✅ Pump Detection Bot — v5.0\n\n"
        f"🌐 المصدر: كل Gate.io USDT\n"
        f"   فلتر: فوليم ≥ ${MIN_VOL_FOR_SIGNAL/1_000_000:.1f}M\n"
        f"   توازي: {GATE_PARALLEL_LIMIT} طلب\n\n"
        f"🚀 سكان البامب: {scanner_status}\n"
        f"   فاصل: {SIGNAL_LOOP_GAP_SECONDS}ث\n"
        f"   آخر دورة: {last_str}\n\n"
        f"📊 نظام النقاط (المجموع: {PUMP_MAX_SCORE}):\n"
        f"   🚀 STRONG ≥ {PUMP_SCORE_STRONG} نقاط\n"
        f"   ⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE} نقاط\n"
        f"   Cooldown: {PUMP_SIGNAL_COOLDOWN_MIN} دقيقة\n\n"
        f"🔬 الشروط النشطة (7):\n"
        f"   ⭐ الأساسية:\n"
        f"   1. Funding Rate Anomaly\n"
        f"   2. CVD Divergence\n"
        f"   3. Taker Buy Ratio\n"
        f"   4. Order Book Imbalance\n"
        f"   📊 التكميلية:\n"
        f"   5. Volume Acceleration\n"
        f"   6. Sustained Buy Pressure\n"
        f"   7. Bid Wall (دعم شراء قوي)\n\n"
        f"⭐ Override: 3/4 أساسية = إشارة فورية\n"
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
                "🟢 *Pump Detection Bot v6.0 — Gate.io*\n"
                f"🚀 السكان المستمر: شغال (فاصل {SIGNAL_LOOP_GAP_SECONDS}ث)\n"
                f"🌐 يفحص كل عملات Gate.io USDT (فوليم ≥ ${MIN_VOL_FOR_SIGNAL/1_000_000:.1f}M)\n"
                f"⚡ 7 شروط نشطة | المجموع: {PUMP_MAX_SCORE} نقاط\n"
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
    print("🚀 Pump Detection Bot v6.0 — Gate.io Edition")
    print(f"🌐 المصدر: كل Gate.io USDT (~{GATE_MAX_CANDIDATES} عملة)")
    print(f"   فلتر أولي: فوليم 24h ≥ ${MIN_VOL_FOR_SIGNAL/1_000_000:.1f}M")
    print(f"   توازي: {GATE_PARALLEL_LIMIT} طلب")
    print(f"")
    print(f"🚨 نظام البامب (7 شروط):")
    print(f"   ⭐ الأساسية:")
    print(f"   1. Funding Rate Anomaly      ({PUMP_W_FUNDING_RATE} pts)")
    print(f"   2. CVD Divergence             ({PUMP_W_CVD_DIVERGENCE} pts)")
    print(f"   3. Taker Buy Ratio            ({PUMP_W_TAKER_BUY_RATIO} pts)")
    print(f"   4. Order Book Imbalance       ({PUMP_W_OB_IMBALANCE} pts)")
    print(f"   📊 التكميلية:")
    print(f"   5. Volume Acceleration        ({PUMP_W_VOL_ACCEL} pts)")
    print(f"   6. Sustained Buy Pressure     ({PUMP_W_SUSTAINED_BUY} pts)")
    print(f"   7. Bid Wall                   ({PUMP_W_BID_WALL} pts)")
    print(f"   ───────────────────────────")
    print(f"   المجموع: {PUMP_MAX_SCORE} نقاط")
    print(f"   🚀 STRONG ≥ {PUMP_SCORE_STRONG}  |  ⚠️ MODERATE ≥ {PUMP_SCORE_MODERATE}")
    print(f"   ⭐ Override: 3/4 أساسية = إشارة فورية")
    print(f"")
    print(f"🔄 السكان المستمر: فاصل {SIGNAL_LOOP_GAP_SECONDS}ث بين الدورات")
    print(f"   Cooldown لكل عملة: {PUMP_SIGNAL_COOLDOWN_MIN} دقيقة (إلا لو النقاط زادت)")
    print(f"🔔 الإرسال: الأدمن فقط")
    print(f"🔒 Lock نشط ضد الإرسال المزدوج")
    print("="*60)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
