"""
🚀 Altcoin Smart Scanner Bot - Ultimate Edition v3
التعديلات الجديدة:
1. ✅ شروط بامب متطورة جداً (RSI Divergence, CVD, Order Flow, Wyckoff, Smart Money)
2. ✅ الحد الأدنى للإشارة = 80 نقطة (مش 75)
3. ✅ الشروط منظمة تحت بعض في الرسالة (مش جنب بعض)
4. ✅ حل مشكلة الإرسال المزدوج (lock + check duplicate jobs)
"""

import asyncio
import aiohttp
import logging
import sys
import math
import json
import os
from datetime import datetime, timedelta
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==================== الاعدادات ====================
TELEGRAM_TOKEN = "8608851079:AAErIr1R1l7zl4odFE1AH8uUUOHQjxiwYwI"
ADMIN_CHAT_ID  = "6914157653"
CMC_API_KEY    = "7eeaf1fd132e416ab49279ee21cc6ce0"

# ==================== اعدادات التقرير الدوري ====================
SCAN_INTERVAL_MINUTES = 240
TOP_DISPLAY           = 50
CMC_LIMIT             = 500

# ==================== اعدادات الاشارات ====================
MIN_SCORE          = 80       # ✅ تم رفعه من 75 إلى 80
MIN_RVOL           = 2.5
MAX_PREV_PUMP      = 12.0
MIN_VOL_FOR_SIGNAL = 2_000_000

# ==================== اعدادات الفلترة ====================
MAX_MARKET_CAP            = 2_000_000_000
MIN_VOLUME_REPORT         = 5_000_000
MIN_VOL_CHANGE_FOR_REPORT = 20.0
# ✅ جديد v3.1: سكان البامب المستمر
SIGNAL_LOOP_GAP_SECONDS = 120     # ✅ v4.1: 120ث بدل 90 (لأن الفحص الآن أكبر)
SIGNAL_LOOP_ERR_GAP     = 30      # فاصل بعد خطأ
# ✅ جديد v3.1: فلتر تقرير الفوليوم
MIN_FLOW_SCORE_FOR_REPORT = 70.0  # يبعث القوي والقوي جداً فقط (>=70%)
# ✅ جديد v3.2: فلاتر الشراء + cooldown أقصر للسكان المستمر
MIN_BUY_DOMINANCE         = 55.0  # نسبة الفوليوم الشرائي من الإجمالي (شراء غالب)
SIGNAL_COOLDOWN_HOURS     = 6     # كان 24h — قللناه عشان السكان المستمر
# ✅ جديد v4.1 — كل عملات Gate.io
USE_FULL_GATE_SCAN        = True       # True = فحص كل Gate.io | False = CMC top 500
GATE_MIN_VOLUME_USD       = 1_000_000  # ✅ تم رفعه من 500K إلى 1M (تجاهل العملات الميتة)
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
PUMP_SIGNAL_COOLDOWN_MIN = 1440 # ✅ تعديل المستخدم — 24 ساعة لنفس العملة
PUMP_RESEND_MIN_INCREASE = 1   # ✅ تعديل المستخدم — أي زيادة في النقاط (1+) تسمح بإعادة الإرسال
PUMP_RESEND_ON_UPGRADE   = False # ✅ تعديل المستخدم — لا إعادة إرسال إلا بزيادة النقاط فقط

# الشرط الإلزامي: لازم core_indicators يكون متفعل
PUMP_REQUIRE_CORE        = True

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
PUMP_SUSTAINED_BUY_PCT   = 0.55      # 55% buy volume per candle
PUMP_BID_WALL_RANGE      = 0.015     # ±1.5% من السعر
PUMP_BID_WALL_MIN_RATIO  = 2.0       # bid wall ≥ 2x متوسط الـ asks
PUMP_BID_WALL_STRONG     = 4.0       # ≥ 4x = ⭐ قوي جداً

# ═══════════════════════════════════════════════════════════════
# ✅ v5.0 — نظام الـ 15 شرط (Pro Trader System)
# مبني على معايير المتداولين المحترفين
# ═══════════════════════════════════════════════════════════════
PRO_HIGH_LIQUIDITY        = 5    # 1) السيولة العالية (vol 24h ≥ $5M)
PRO_STRONG_VOLUME         = 8    # 2) حجم تداول قوي (RVOL ≥ 2.5x)
PRO_CLEAR_TREND           = 7    # 3) وضوح الاتجاه (EMA20>EMA50>EMA200)
PRO_TA_RESPECT            = 6    # 4) احترام التحليل (R² ≥ 0.7)
PRO_VOLATILITY            = 5    # 5) قوة الحركة السعرية (ATR-normalized)
PRO_RISK_REWARD           = 7    # 6) Risk/Reward ≥ 2:1
PRO_LIQUIDITY_INFLOW      = 8    # 7) سيولة داخلة (CVD↑ + buy_dom ≥ 60%)
PRO_STRONG_SR             = 6    # 8) دعوم/مقاومات قوية (touch count ≥ 3)
PRO_VOLUME_CONFIRM        = 6    # 9) تأكيد بالـ Volume (شموع خضراء + vol↑)
PRO_MARKET_STRUCTURE      = 7    # 10) HH + HL واضحين
PRO_BTC_ALIGNMENT         = 5    # 11) توافق مع BTC
PRO_BREAKOUT_RETEST       = 8    # 12) Breakout أو Retest محترم
PRO_MOMENTUM              = 6    # 13) قوة الزخم (RSI 50-70 + MACD bullish)
PRO_LIQUIDITY_ZONES       = 5    # 14) مناطق سيولة (Equal Highs/Lows)
PRO_TIMING                = 6    # 15) التوقيت (sideways قبل التحرك)
PRO_MAX                   = 95   # المجموع الأقصى

PRO_MIN_SCORE             = 80   # حد الإشارة
# الشروط الإلزامية (لازم كلهم متفعلين)
PRO_MANDATORY             = ["liquidity", "volume", "inflow", "structure"]
# ✅ v4.0 — VIP markers
VIP_FLOW_SCORE_MIN       = 70   # قوة سير الشراء
VIP_BUY_DOMINANCE_MIN    = 60   # هيمنة الشراء
VIP_BUY_TREND_HOURS      = 3    # ساعات متتالية من تصاعد الشراء

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("altcoin_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

previous_report:  list = []
previous_signals: dict = {}
seen_coins:       dict = {}
seen_signals:     dict = {}

# ==================== ✅ منع الإرسال المزدوج ====================
job_locks = {
    "volume_report": asyncio.Lock(),
    "check_signals": asyncio.Lock(),
}
last_job_run = {
    "volume_report": None,
    "check_signals": None,
}
MIN_JOB_GAP_SECONDS = 60

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

MEME_SYMBOLS = {
    "PEPE","FLOKI","BONK","WIF","MEME","SLERF","BOME","POPCAT",
    "MOG","TURBO","BRETT","TOSHI","WOJAK","LADYS","AIDOGE","BABYDOGE",
    "SAITAMA","DOGELON","KISHU","AKITA","HOGE","SAMO","CHEEMS",
    "CATGIRL","MINIDOGE","PITBULL","LEASH","BONE","RYOSHI",
    "ELONGATE","SAFEMOON","SAFEMARS","MYRO","PONKE","SILLY","MICHI",
    "DOG","NEIRO","HAMSTER","PNUT","GOAT","MOODENG","FWOG","GIGA",
    "ACT","CHILLGUY","KEKIUS","FARTCOIN","DEGEN","HIGHER","HARAMBE",
    "WALTER","DUKO","WEN","CHAD","NORMIE","COQ","SIGMA","VINE",
    "BITCOIN","ELON","VOLT","PIT","DOGGY","MOONSHOT","CUMROCKET",
}

MEME_KEYWORDS = {
    "inu","doge","shib","pepe","moon","safe","baby","elon","musk",
    "floki","wojak","meme","fart","bonk","wif","giga","turbo","brett",
    "toshi","popcat","neiro","pnut","hamster","goat","rug","wagmi",
    "ngmi","chimp","squirrel","chillguy","slerf","bome",
}

MEME_TAGS = {
    "memes","meme-token","dog-themed","cat-themed","frog-themed",
    "animal-racing","dog","cat","anime","fan-token",
}

STOCK_TAGS = {
    "equity-token","tokenized-stock","stock","securities","asset-backed",
    "real-world-assets","rwa","commodities","tokenized-gold",
    "tokenized-silver","etf","index","fund",
}

STOCK_KEYWORDS = {
    "stock","share","equity","aapl","tsla","amzn","googl","msft",
    "nvda","meta","nflx","spy","qqq","index","fund","etf",
}

MIN_PRICE_CHANGE_7D  = 1.0
MIN_PRICE_CHANGE_24H = 0.3

EXCLUDED_KEYWORDS_IN_SYMBOL = {
    "wbnb","weth","wbtc","wmatic","wavax","wsol","wftm","wone","wxdai",
    "btcb","btcst","hbtc","renbtc","sbtc","tbtc","vbtc","anybtc",
    "vbnb","veth","vbtc","vusdt","vusdc","vbusd","vdai","vxvs",
    "usd","usdt","usdc","busd","dai","tusd","usdp","usdd","fdusd",
    "usde","pyusd","gusd","lusd","frax","susd","eurc","usds","usdx",
    "cusd","musd","husd","usdj","xusd","zusd","dusd","nusd","pusd",
    "rusd","rlusd","usad","usd1","ust","vai","dola","crvusd","bean",
    "xaut","paxg","xagc","dgx","cache","gold","silver",
    "steth","cbeth","reth","wsteth","weeth","frxeth","sfrxeth",
    "ankrbnb","bnbx","stkbnb","snbnb","beth","abnbb",
}

EXCLUDED_SUBSTRINGS = ("usd", "btc", "eth", "bnb", "xau", "xag", "gold", "silver")


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


# ==================== أدوات أساسية ====================
def is_coin_cooldown(symbol: str) -> bool:
    if symbol not in seen_coins:
        return False
    elapsed = (datetime.now() - seen_coins[symbol]).total_seconds()
    return elapsed < 86400


def is_excluded_token(symbol, name, tags):
    sym = symbol.lower()
    nm  = name.lower()
    if symbol in MEME_SYMBOLS: return True
    if tags and any(t in MEME_TAGS for t in tags): return True
    for kw in MEME_KEYWORDS:
        if kw in sym or kw in nm: return True
    for sub in EXCLUDED_SUBSTRINGS:
        if sub in sym: return True
    if sym in EXCLUDED_KEYWORDS_IN_SYMBOL: return True
    excluded_name_keywords = {
        "wrapped","bridged","synthetic","pegged","staked","liquid staking",
        "vault token","receipt token","interest bearing","lp token",
        "usd coin","tether","binance usd","venus","compound","aave token",
        "dollar","gold token","silver token","gold coin",
    }
    for kw in excluded_name_keywords:
        if kw in nm: return True
    excluded_lower = {s.lower() for s in EXCLUDED_SYMBOLS}
    if len(sym) >= 3:
        for prefix in ("v","w","b","r","s","h"):
            if sym.startswith(prefix) and sym[1:] in excluded_lower:
                return True
    return False


def is_stock_token(symbol, name, tags):
    if tags and any(t in STOCK_TAGS for t in tags):
        return True
    sym = symbol.lower()
    nm  = name.lower()
    for kw in STOCK_KEYWORDS:
        if kw in sym or kw in nm:
            return True
    return False


def is_dead_coin(coin_data: dict) -> bool:
    pc24 = abs(coin_data.get("price_change_24h", 0) or 0)
    pc7d = abs(coin_data.get("price_change_7d", 0) or 0)
    vol  = coin_data.get("volume_24h", 0) or 0
    if pc7d < MIN_PRICE_CHANGE_7D and pc24 < MIN_PRICE_CHANGE_24H:
        return True
    if vol < 100_000:
        return True
    return False


def is_meme_coin(symbol, name, tags):
    return is_excluded_token(symbol, name, tags)

def fmt_vol(v):
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.2f}B$"
    if v >= 1_000_000:     return f"{v/1_000_000:.2f}M$"
    return f"{v/1_000:.1f}K$"

def fmt_price(p):
    if p >= 1:     return f"${p:.4f}"
    if p >= 0.001: return f"${p:.6f}"
    return f"${p:.8f}"

def escape_md(text):
    for ch in ['_','*','[',']','`']: text = text.replace(ch,'')
    return text


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


async def fetch_cmc_single(session, symbol):
    url     = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}
    params  = {"limit": 2000, "convert": "USD", "sort": "market_cap"}
    try:
        async with session.get(url, headers=headers, params=params,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
        coins = data.get("data", [])
        return next((c for c in coins if c.get("symbol") == symbol), None)
    except Exception as e:
        logger.error(f"CMC single error: {e}"); return None


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


async def build_all_gate_candidates(session, min_volume_usd=1_000_000):
    """
    ✅ v4.1 — يبني قائمة كل عملات Gate.io USDT النشطة
    - يجلب tickers من Gate (طلب واحد)
    - يفلتر بحد أدنى للفوليوم لتوفير الوقت
    - يجلب CMC ويُثري البيانات للعملات المتطابقة
    """
    gate_tickers = await fetch_gate_tickers(session)
    if not gate_tickers:
        return []

    # تحويل + prefilter بالفوليوم لتقليل الحمل
    candidates = []
    for t in gate_tickers:
        d = parse_gate_ticker(t)
        if not d: continue
        if d["volume_24h"] < min_volume_usd: continue  # عملات ميتة
        if d["price"] <= 0: continue
        candidates.append(d)
    logger.info(f"Gate بعد فلتر الفوليم ≥ ${min_volume_usd/1000:.0f}K: {len(candidates)} عملة")

    # إثراء البيانات من CMC (للعملات المتطابقة فقط)
    cmc_raw = await fetch_cmc(session, limit=CMC_LIMIT)
    cmc_by_sym = {c.get("symbol"): c for c in cmc_raw} if cmc_raw else {}
    enriched_count = 0
    for d in candidates:
        cmc = cmc_by_sym.get(d["symbol"])
        if cmc:
            parsed = parse_coin(cmc)
            d["name"]             = parsed["name"]
            d["price_change_1h"]  = parsed["price_change_1h"]
            d["price_change_7d"]  = parsed["price_change_7d"]
            d["volume_change"]    = parsed["volume_change"]
            d["num_market_pairs"] = parsed["num_market_pairs"]
            d["rank"]             = parsed["rank"]
            d["market_cap"]       = parsed["market_cap"]
            d["tags"]             = [t.lower() for t in cmc.get("tags", [])]
            d["source"]           = "gate+cmc"
            enriched_count += 1
    logger.info(f"إثراء من CMC: {enriched_count} عملة (الباقي {len(candidates)-enriched_count} من Gate فقط)")
    return candidates


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
    # ✅ تعديل المستخدم: لازم 3 من 4 شروط أساسية على الأقل لإرسال أي إشارة
    core_ok = core_passed >= 3

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
        # أقل من 3 شروط أساسية = تجاهل (مهما كانت النقاط)
        strength = None
        strength_emoji = "\u274c"
        strength_label = "تجاهل — أقل من 3/4 شروط أساسية"

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



# ==================== الحسابات الأساسية ====================
def calc_rvol(c):
    if len(c) < 5: return 1.0
    vols = [x["volume"] for x in c]
    avg  = sum(vols[:-1]) / len(vols[:-1])
    return vols[-1] / avg if avg > 0 else 1.0

def calc_atr(c, p=14):
    if len(c) < p+1: return 0.0, "unknown"
    trs = [max(c[i]["high"]-c[i]["low"],
               abs(c[i]["high"]-c[i-1]["close"]),
               abs(c[i]["low"] -c[i-1]["close"])) for i in range(1,len(c))]
    if len(trs) < p: return 0.0, "unknown"
    now  = sum(trs[-p:]) / p
    prev = sum(trs[-p*2:-p]) / p if len(trs) >= p*2 else now
    return now, ("rising" if now > prev*1.1 else "falling" if now < prev*0.9 else "flat")

def calc_bb(c, p=20):
    if len(c) < p: return {"width": 999, "squeeze": False}
    cl  = [x["close"] for x in c[-p:]]
    mid = sum(cl)/p
    std = math.sqrt(sum((x-mid)**2 for x in cl)/p)
    w   = (mid+2*std - (mid-2*std)) / mid * 100 if mid > 0 else 999
    return {"width": w, "squeeze": w < 5.0}

def calc_breakout(c, lb=20):
    if len(c) < lb+1: return False
    return c[-1]["close"] > max(x["high"] for x in c[-(lb+1):-1]) * 1.005

def calc_sideways(c, lb=20):
    if len(c) < lb: return False
    s = c[-lb:-1]
    r = (max(x["high"] for x in s) - min(x["low"] for x in s)) / min(x["low"] for x in s) * 100
    return r < 15.0

def calc_absorption(c):
    if len(c) < 5: return False
    return sum(1 for x in c[-5:]
               if abs(x["close"]-x["open"]) > 0 and
               min(x["open"],x["close"])-x["low"] > abs(x["close"]-x["open"])*1.5) >= 2

def calc_vol_trend(c):
    if len(c) < 5: return False
    v = [x["volume"] for x in c[-5:]]
    return sum(1 for i in range(1,len(v)) if v[i]>v[i-1]) >= 3

def calc_prev_pump(c):
    if len(c) < 3: return 0.0
    return max((c[i]["close"]-c[i-1]["close"])/c[i-1]["close"]*100
               for i in range(1,min(20,len(c))))

def calc_vol_surge(c):
    if len(c) < 10: return False, 0.0
    avg_vol = sum(x["volume"] for x in c[-11:-1]) / 10
    last_vol = c[-1]["volume"]
    ratio = last_vol / avg_vol if avg_vol > 0 else 0
    return ratio >= 3.0, ratio

def calc_higher_lows(c, periods=6):
    if len(c) < periods: return False
    lows = [x["low"] for x in c[-periods:]]
    return all(lows[i] >= lows[i-1] for i in range(1, len(lows)))

def calc_price_above_ma(c, period=20):
    if len(c) < period: return False
    ma = sum(x["close"] for x in c[-period:]) / period
    return c[-1]["close"] > ma

def calc_decreasing_sell_pressure(c):
    if len(c) < 8: return False
    first_half_red  = sum(1 for x in c[-8:-4] if x["close"] < x["open"])
    second_half_red = sum(1 for x in c[-4:]   if x["close"] < x["open"])
    return second_half_red < first_half_red

def calc_candle_size_increase(c):
    if len(c) < 6: return False
    green = [abs(x["close"]-x["open"]) for x in c[-6:] if x["close"] > x["open"]]
    if len(green) < 3: return False
    return green[-1] > green[0] * 1.2

def calc_vwap_cross(c):
    if len(c) < 10: return False
    total_vol = sum(x["volume"] for x in c[-10:])
    if total_vol == 0: return False
    vwap = sum(((x["high"]+x["low"]+x["close"])/3) * x["volume"]
               for x in c[-10:]) / total_vol
    prev_below = c[-2]["close"] < vwap
    curr_above = c[-1]["close"] > vwap
    return prev_below and curr_above


# ============================================================
# ✅ v4.0 — مؤشرات جديدة للمحركات المُدمَجة
# ============================================================

def calc_ema(values, period):
    """EMA على قائمة قيم"""
    if not values or len(values) < period: return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def calc_macd(c, fast=12, slow=26, signal=9):
    """
    MACD: يرجع (macd_line, signal_line, histogram, bullish)
    bullish = MACD فوق Signal وارتفع آخر شمعة
    """
    if len(c) < slow + signal + 5:
        return None
    closes = [x["close"] for x in c]
    # احسب EMA لكل قيمة
    def ema_series(vals, p):
        if len(vals) < p: return []
        k = 2 / (p + 1)
        s = sum(vals[:p]) / p
        out = [None] * (p - 1) + [s]
        for v in vals[p:]:
            s = v * k + s * (1 - k)
            out.append(s)
        return out
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    if not ema_fast[-1] or not ema_slow[-1]: return None
    macd_line = [(f - s) if (f is not None and s is not None) else None
                 for f, s in zip(ema_fast, ema_slow)]
    macd_valid = [m for m in macd_line if m is not None]
    if len(macd_valid) < signal + 2: return None
    sig_series = ema_series(macd_valid, signal)
    if not sig_series[-1]: return None
    macd_now    = macd_valid[-1]
    macd_prev   = macd_valid[-2]
    sig_now     = sig_series[-1]
    sig_prev    = sig_series[-2] if sig_series[-2] else sig_now
    hist_now    = macd_now - sig_now
    hist_prev   = macd_prev - sig_prev
    bullish_cross   = macd_prev <= sig_prev and macd_now > sig_now
    bullish_rising  = macd_now > sig_now and hist_now > hist_prev
    bullish         = bullish_cross or bullish_rising
    return {
        "macd": macd_now, "signal": sig_now, "hist": hist_now,
        "bullish": bullish, "cross": bullish_cross, "rising": bullish_rising
    }


def calc_stochastic(c, k_period=14, d_period=3):
    """
    Stochastic %K + %D، يكتشف bullish crossover من oversold
    """
    if len(c) < k_period + d_period + 2: return None
    k_values = []
    for i in range(k_period - 1, len(c)):
        window = c[i - k_period + 1: i + 1]
        hh = max(x["high"] for x in window)
        ll = min(x["low"]  for x in window)
        rng = hh - ll
        k = ((c[i]["close"] - ll) / rng * 100) if rng > 0 else 50
        k_values.append(k)
    if len(k_values) < d_period + 1: return None
    d_values = [sum(k_values[i-d_period+1:i+1])/d_period
                for i in range(d_period-1, len(k_values))]
    if len(d_values) < 2: return None
    k_now  = k_values[-1]
    k_prev = k_values[-2]
    d_now  = d_values[-1]
    d_prev = d_values[-2]
    bullish_cross    = k_prev <= d_prev and k_now > d_now
    bullish_from_low = k_prev < 30 and k_now > k_prev
    bullish          = (bullish_cross and k_now < 60) or bullish_from_low
    return {"k": k_now, "d": d_now, "bullish": bullish, "oversold_recovery": bullish_from_low}


def calc_buy_volume_trend(c, hours=3):
    """
    هل الفوليوم الشرائي صاعد لـ N ساعات متتالية؟ (للـ VIP marker)
    """
    if len(c) < hours + 1: return False, 0
    buy_vols = []
    for x in c[-hours-1:]:
        bv = x["volume"] if x["close"] >= x["open"] else 0
        buy_vols.append(bv)
    rising = sum(1 for i in range(1, len(buy_vols)) if buy_vols[i] > buy_vols[i-1])
    return rising >= hours, rising


def calc_vwap_value(c, period=20):
    """قيمة VWAP الحالية"""
    if len(c) < period: return None
    sub = c[-period:]
    tot_vol = sum(x["volume"] for x in sub)
    if tot_vol == 0: return None
    return sum(((x["high"]+x["low"]+x["close"])/3) * x["volume"] for x in sub) / tot_vol


def calc_velocity(c, period=5):
    """
    سرعة الحركة = نسبة التغير في السعر مقسومة على الـ ATR (تطبيع)
    قيمة عالية = حركة سريعة، قيمة منخفضة = حركة بطيئة
    """
    if len(c) < period + 14: return 0.0
    price_now = c[-1]["close"]
    price_old = c[-period]["close"]
    change_pct = (price_now - price_old) / price_old * 100 if price_old > 0 else 0
    atr, _ = calc_atr(c)
    if atr <= 0 or price_now <= 0: return abs(change_pct)
    atr_pct = atr / price_now * 100
    # velocity = حركة السعر بالنسبة للتقلب الطبيعي
    return change_pct / atr_pct if atr_pct > 0 else 0


def calc_trend_quality(c, period=20):
    """
    احترام الاتجاه = مدى نظافة الاتجاه الصاعد
    نقيس: كم شمعة فوق MA20 + كم higher highs/lows + R² للانحدار
    يرجع 0-100
    """
    if len(c) < period + 5: return 50.0
    sub = c[-period:]
    closes = [x["close"] for x in sub]
    # 1) نسبة الشموع فوق MA20
    ma = sum(closes) / len(closes)
    above_pct = sum(1 for cl in closes if cl > ma) / len(closes) * 100
    # 2) R² للانحدار الخطي
    n = len(closes)
    mean_x = (n - 1) / 2
    mean_y = sum(closes) / n
    num   = sum((i - mean_x) * (closes[i] - mean_y) for i in range(n))
    den_x = sum((i - mean_x)**2 for i in range(n))
    den_y = sum((closes[i] - mean_y)**2 for i in range(n))
    if den_x == 0 or den_y == 0:
        r2 = 0
    else:
        slope = num / den_x
        ss_total = den_y
        ss_res   = sum((closes[i] - (mean_y + slope*(i - mean_x)))**2 for i in range(n))
        r2 = max(0, 1 - ss_res/ss_total) if ss_total > 0 else 0
    # 3) higher lows count
    lows = [x["low"] for x in sub]
    hl_count = sum(1 for i in range(1, len(lows)) if lows[i] >= lows[i-1])
    hl_pct   = hl_count / (len(lows)-1) * 100 if len(lows) > 1 else 0
    # المجموع المرجح
    quality = (above_pct * 0.30) + (r2 * 100 * 0.40) + (hl_pct * 0.30)
    return min(100.0, max(0.0, quality))


def calc_liquidity_depth(coin_data, candles):
    """
    وجود السيولة = مزيج من فوليوم 24h + عدد الأسواق + استمرارية الفوليوم
    يرجع 0-100
    """
    vol_24h = coin_data.get("volume_24h", 0)
    pairs   = coin_data.get("num_market_pairs", 0)
    # درجة الفوليوم: log-scale
    if vol_24h <= 0:
        vol_score = 0
    else:
        # 1M=20, 10M=50, 100M=80, 1B=100
        vol_score = min(100, max(0, (math.log10(vol_24h) - 5) * 25))
    # درجة الأسواق
    pairs_score = min(100, pairs * 1.5)  # 67 سوق = 100
    # استمرارية الفوليوم: تباين أقل = استقرار أكثر
    if candles and len(candles) >= 24:
        vols = [x["volume"] for x in candles[-24:]]
        avg_v = sum(vols) / 24
        if avg_v > 0:
            std_v = math.sqrt(sum((v - avg_v)**2 for v in vols) / 24)
            cv = std_v / avg_v  # coefficient of variation
            # cv < 0.5 = مستقر جداً، cv > 2 = متذبذب
            consist_score = max(0, min(100, 100 - cv * 40))
        else:
            consist_score = 0
    else:
        consist_score = 50
    return (vol_score * 0.50) + (pairs_score * 0.20) + (consist_score * 0.30)


# ============================================================
# ✅ المؤشرات المتطورة الجديدة (Advanced Indicators)
# ============================================================

def calc_rsi(c, period=14):
    """مؤشر RSI"""
    if len(c) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, len(c)):
        diff = c[i]["close"] - c[i-1]["close"]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_rsi_divergence(c, period=14, lookback=10):
    """
    Bullish RSI Divergence:
    السعر بيعمل Lower Low بس RSI بيعمل Higher Low → إشارة انعكاس قوية قبل البامب
    """
    if len(c) < period + lookback + 5: return False
    rsi_values = []
    for i in range(len(c) - lookback, len(c)):
        sub = c[:i+1]
        if len(sub) >= period + 1:
            rsi_values.append(calc_rsi(sub, period))
        else:
            rsi_values.append(50.0)
    if len(rsi_values) < lookback: return False
    lows = [x["low"] for x in c[-lookback:]]
    sorted_low_idx = sorted(range(len(lows)), key=lambda i: lows[i])[:2]
    if len(sorted_low_idx) < 2: return False
    i1, i2 = sorted(sorted_low_idx)
    if i2 - i1 < 3: return False
    price_lower_low = lows[i2] < lows[i1]
    rsi_higher_low  = rsi_values[i2] > rsi_values[i1]
    rsi_recovering  = rsi_values[-1] > rsi_values[i2] and rsi_values[i2] < 40
    return price_lower_low and rsi_higher_low and rsi_recovering


def calc_cvd(c):
    """
    Cumulative Volume Delta:
    شمعة خضرا → +volume، شمعة حمرا → -volume
    لو الـ CVD صاعد في آخر شموع → تجميع شراء (Smart Money)
    """
    if len(c) < 10: return False, 0.0
    cvd = 0
    cvd_series = []
    for x in c:
        if x["close"] > x["open"]:
            cvd += x["volume"]
        elif x["close"] < x["open"]:
            cvd -= x["volume"]
        cvd_series.append(cvd)
    if len(cvd_series) < 10: return False, 0.0
    recent_avg = sum(cvd_series[-5:]) / 5
    older_avg  = sum(cvd_series[-10:-5]) / 5
    if older_avg == 0:
        positive = recent_avg > 0
        return positive, recent_avg
    growth = (recent_avg - older_avg)
    positive = recent_avg > older_avg and cvd_series[-1] > 0
    return positive, growth


def calc_order_flow_imbalance(c):
    """
    Order Flow Imbalance:
    لو الشموع الخضرا فوليمها أعلى بكتير من الحمرا → ضغط شراء قوي
    """
    if len(c) < 10: return False, 0.0
    green_vol = sum(x["volume"] for x in c[-10:] if x["close"] > x["open"])
    red_vol   = sum(x["volume"] for x in c[-10:] if x["close"] < x["open"])
    total = green_vol + red_vol
    if total == 0: return False, 0.0
    buy_pressure = green_vol / total
    return buy_pressure >= 0.65, buy_pressure


def calc_wyckoff_accumulation(c):
    """
    Wyckoff Accumulation Pattern:
    1. نطاق جانبي طويل
    2. Spring (كسر كاذب + استعادة)
    3. زيادة فوليم على الشموع الخضرا
    """
    if len(c) < 20: return False
    last_20 = c[-20:]
    high_max = max(x["high"] for x in last_20[:-3])
    low_min  = min(x["low"]  for x in last_20[:-3])
    range_pct = (high_max - low_min) / low_min * 100 if low_min > 0 else 100
    if range_pct > 20: return False
    spring = False
    for i in range(-5, -1):
        if c[i]["low"] < low_min * 0.99 and c[i]["close"] > low_min:
            spring = True
            break
    last_3 = c[-3:]
    green_count = sum(1 for x in last_3 if x["close"] > x["open"])
    avg_recent_vol = sum(x["volume"] for x in c[-3:]) / 3
    avg_old_vol    = sum(x["volume"] for x in c[-20:-3]) / 17
    strong_close   = green_count >= 2 and avg_recent_vol > avg_old_vol * 1.3
    return spring and strong_close


def calc_smart_money_footprint(c):
    """
    Smart Money Footprint:
    شموع بفوليم عالي + جسم صغير + shadow سفلية كبيرة = تجميع
    """
    if len(c) < 10: return False
    avg_vol = sum(x["volume"] for x in c[-10:-1]) / 9
    footprints = 0
    for x in c[-5:]:
        if x["volume"] > avg_vol * 2:
            body = abs(x["close"] - x["open"])
            full_range = x["high"] - x["low"]
            if full_range == 0: continue
            body_ratio = body / full_range
            lower_wick = min(x["open"], x["close"]) - x["low"]
            lower_wick_ratio = lower_wick / full_range
            if body_ratio < 0.4 and lower_wick_ratio > 0.4:
                footprints += 1
    return footprints >= 2


def calc_liquidity_grab(c):
    """
    Liquidity Grab + Reversal:
    كسر تحت أدنى نقطة سابقة + ارتداد فوق المستوى المكسور
    """
    if len(c) < 10: return False
    prev_low = min(x["low"] for x in c[-10:-3])
    last_3_lows  = [x["low"]   for x in c[-3:]]
    last_3_close = [x["close"] for x in c[-3:]]
    grabbed   = any(low < prev_low for low in last_3_lows)
    recovered = last_3_close[-1] > prev_low * 1.005
    return grabbed and recovered


def calc_ema(values, period):
    if len(values) < period: return None
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
    return ema


def calc_ema_cross(c):
    """EMA 9 / 21 Bullish Cross"""
    if len(c) < 25: return False
    closes = [x["close"] for x in c]
    ema9_prev  = calc_ema(closes[:-1], 9)
    ema21_prev = calc_ema(closes[:-1], 21)
    ema9_now   = calc_ema(closes, 9)
    ema21_now  = calc_ema(closes, 21)
    if not all([ema9_prev, ema21_prev, ema9_now, ema21_now]): return False
    return ema9_prev <= ema21_prev and ema9_now > ema21_now


# ============================================================
# ✅ v4.0 — Confluence Engines (3 محركات مدمجة)
# ============================================================

def evaluate_confluence_engines(candles, details):
    """
    يقيم 3 محركات تعمل بالـ confluence:
      1) Momentum     = RSI + MACD + Stochastic (3/3)
      2) Smart Money  = CVD + Order Flow + Wyckoff + Smart Money (3/4)
      3) Breakout     = BB Squeeze + Vol Surge + Above MA + Higher Lows (3/4)
    يرجع dict بحالة كل محرك + تفاصيل + bonus_points
    """
    if not candles or len(candles) < 30:
        return {
            "momentum": {"pass": False, "score": 0, "checks": []},
            "smart":    {"pass": False, "score": 0, "checks": []},
            "breakout": {"pass": False, "score": 0, "checks": []},
            "engines_passed": 0,
            "bonus_points":   0,
        }

    # ───── Engine 1: MOMENTUM ─────
    rsi_val = calc_rsi(candles)
    rsi_recovery = (rsi_val > 50 and rsi_val < 70 and  # خرج من oversold بس لسه مش مشتعل
                    calc_rsi(candles[:-3]) < rsi_val)
    macd = calc_macd(candles)
    macd_ok = bool(macd and macd["bullish"])
    stoch = calc_stochastic(candles)
    stoch_ok = bool(stoch and stoch["bullish"])
    mom_checks = [
        ("RSI خرج من oversold",  rsi_recovery),
        ("MACD bullish/cross",   macd_ok),
        ("Stochastic bullish",   stoch_ok),
    ]
    mom_passed = sum(1 for _, ok in mom_checks if ok)
    mom_pass   = mom_passed >= CONFLUENCE_MOMENTUM_REQ

    # ───── Engine 2: SMART MONEY ─────
    smart_checks = [
        ("CVD صاعد (تجميع)",         details.get("cvd_pos", False)),
        ("Order Flow ≥ 65%",          details.get("order_flow", False)),
        ("Wyckoff Accumulation",      details.get("wyckoff", False)),
        ("Smart Money Footprint",     details.get("smart_money", False)),
    ]
    smart_passed = sum(1 for _, ok in smart_checks if ok)
    smart_pass   = smart_passed >= CONFLUENCE_SMART_REQ

    # ───── Engine 3: BREAKOUT READINESS ─────
    brk_checks = [
        ("BB Squeeze نشط",            details.get("squeeze", False) or details.get("bb_width", 999) < 8),
        ("Volume Surge ≥ 2.5x",       details.get("vol_surge", False) or details.get("surge_ratio", 0) >= 2.5),
        ("سعر فوق MA20",              details.get("above_ma", False)),
        ("Higher Lows",               details.get("higher_lows", False)),
    ]
    brk_passed = sum(1 for _, ok in brk_checks if ok)
    brk_pass   = brk_passed >= CONFLUENCE_BREAKOUT_REQ

    # ───── Total ─────
    engines_passed = int(mom_pass) + int(smart_pass) + int(brk_pass)
    bonus_points   = engines_passed * SCORE_CONFLUENCE_BONUS

    return {
        "momentum": {"pass": mom_pass,   "score": mom_passed,   "checks": mom_checks,
                     "rsi": round(rsi_val, 1),
                     "macd_hist": round(macd["hist"], 4) if macd else None,
                     "stoch_k":   round(stoch["k"], 1) if stoch else None},
        "smart":    {"pass": smart_pass, "score": smart_passed, "checks": smart_checks},
        "breakout": {"pass": brk_pass,   "score": brk_passed,   "checks": brk_checks},
        "engines_passed": engines_passed,
        "bonus_points":   bonus_points,
    }


def evaluate_vip_status(candles, flow):
    """
    العملة تستحق علامة 💎 VIP إذا:
      - قوة سير الشراء >= 70%
      - هيمنة الشراء >= 60%
      - الفوليوم الشرائي صاعد لمدة 3 ساعات متتالية
      - السعر فوق VWAP
    """
    if not flow or not candles or len(candles) < 24:
        return False, []
    checks = []
    # 1) قوة السير
    c1 = flow.get("score", 0) >= VIP_FLOW_SCORE_MIN
    checks.append(("قوة سير شرائي ≥ 70%", c1))
    # 2) هيمنة الشراء
    c2 = flow.get("buy_dominance", 0) >= VIP_BUY_DOMINANCE_MIN
    checks.append(("هيمنة الشراء ≥ 60%", c2))
    # 3) شراء صاعد 3 ساعات
    rising, _ = calc_buy_volume_trend(candles, hours=VIP_BUY_TREND_HOURS)
    checks.append(("شراء صاعد 3 ساعات متتالية", rising))
    # 4) فوق VWAP
    vwap = calc_vwap_value(candles)
    above_vwap = bool(vwap and candles[-1]["close"] > vwap)
    checks.append(("السعر فوق VWAP", above_vwap))
    is_vip = all(ok for _, ok in checks)
    return is_vip, checks


# ==================== ✅ نظام النقاط المتطور ====================
def score_coin(candles, cmc):
    sc, rs, dt = 0, [], {}
    vc   = cmc.get("volume_change", 0)
    pc   = cmc.get("price_change_24h", 0)

    have_candles = candles and len(candles) >= 20

    # ═══════════════ 1. الفوليم والـ RVOL ═══════════════
    rv = calc_rvol(candles) if candles and len(candles) >= 5 else max(1.0, 1+vc/100)
    if rv >= 3.0:
        sc += SCORE_RVOL; rs.append(f"RVOL قوي جداً {rv:.1f}x")
    elif rv >= MIN_RVOL:
        sc += int(SCORE_RVOL * 0.75); rs.append(f"RVOL {rv:.1f}x")
    elif rv >= 1.5:
        sc += int(SCORE_RVOL * 0.4); rs.append(f"RVOL متوسط {rv:.1f}x")
    elif vc >= 100:
        sc += int(SCORE_RVOL * 0.75); rs.append(f"فوليم +{vc:.0f}%")
    elif vc >= 50:
        sc += int(SCORE_RVOL * 0.4); rs.append(f"فوليم +{vc:.0f}%")

    # ═══════════════ 2. قفزة الفوليم المفاجئة ═══════════════
    surge, surge_ratio = calc_vol_surge(candles) if candles and len(candles) >= 10 else (False, 0)
    if surge:
        sc += SCORE_VOL_SURGE; rs.append(f"قفزة فوليم {surge_ratio:.1f}x")
    elif surge_ratio >= 2.0:
        sc += int(SCORE_VOL_SURGE * 0.5); rs.append(f"زيادة فوليم {surge_ratio:.1f}x")

    # ═══════════════ 3. فوليم متصاعد ═══════════════
    vt = calc_vol_trend(candles) if candles and len(candles) >= 5 else False
    if vt:
        sc += SCORE_VOL_TREND; rs.append("فوليم متصاعد")

    # ═══════════════ 4. Bollinger Squeeze ═══════════════
    bb_width = 999
    side = False
    if have_candles:
        bb = calc_bb(candles)
        bb_width = bb["width"]
        side = calc_sideways(candles)
        if bb["squeeze"]:
            sc += SCORE_BB_SQUEEZE; rs.append(f"Squeeze قوي BB {bb_width:.1f}%")
        elif bb_width < 8:
            sc += int(SCORE_BB_SQUEEZE * 0.7); rs.append(f"BB ضيق {bb_width:.1f}%")
        elif bb_width < 12 and side:
            sc += int(SCORE_BB_SQUEEZE * 0.5); rs.append(f"BB ضيق + Sideways")
        if side:
            sc += SCORE_SIDEWAYS; rs.append("نطاق Sideways")
    else:
        if abs(pc) < 3:
            sc += int(SCORE_BB_SQUEEZE * 0.4); rs.append("حركة سعر هادئة")

    # ═══════════════ 5. Breakout ═══════════════
    brk = calc_breakout(candles) if candles and len(candles) >= 21 else False
    if brk:
        sc += SCORE_BREAKOUT; rs.append("اختراق للأعلى Breakout")

    # ═══════════════ 6. امتصاص البيع ═══════════════
    abso = calc_absorption(candles) if candles and len(candles) >= 5 else False
    if abso:
        sc += SCORE_ABSORPTION; rs.append("امتصاص بيع قوي")

    # ═══════════════ 7. Higher Lows ═══════════════
    hl = calc_higher_lows(candles) if candles and len(candles) >= 6 else False
    if hl:
        sc += SCORE_HIGHER_LOWS; rs.append("Higher Lows صاعد")

    # ═══════════════ 8. السعر فوق MA20 ═══════════════
    above_ma = calc_price_above_ma(candles) if candles and len(candles) >= 20 else False
    if above_ma:
        sc += SCORE_ABOVE_MA; rs.append("سعر فوق MA20")

    # ═══════════════ 9. ✅ RSI Divergence ═══════════════
    rsi_div = calc_rsi_divergence(candles) if candles and len(candles) >= 25 else False
    if rsi_div:
        sc += SCORE_RSI_DIVERGENCE; rs.append("تباعد RSI إيجابي")

    # ═══════════════ 10. ✅ CVD ═══════════════
    cvd_pos, _ = calc_cvd(candles) if candles and len(candles) >= 10 else (False, 0)
    if cvd_pos:
        sc += SCORE_CVD_POSITIVE; rs.append("CVD صاعد - تجميع شراء")

    # ═══════════════ 11. ✅ Order Flow ═══════════════
    of_imb, buy_pressure = calc_order_flow_imbalance(candles) if candles and len(candles) >= 10 else (False, 0)
    if of_imb:
        sc += SCORE_ORDER_FLOW; rs.append(f"ضغط شراء {buy_pressure*100:.0f}%")

    # ═══════════════ 12. ✅ Wyckoff ═══════════════
    wyckoff = calc_wyckoff_accumulation(candles) if candles and len(candles) >= 20 else False
    if wyckoff:
        sc += SCORE_WYCKOFF; rs.append("نمط Wyckoff تجميع")

    # ═══════════════ 13. ✅ Smart Money ═══════════════
    smart_money = calc_smart_money_footprint(candles) if candles and len(candles) >= 10 else False
    if smart_money:
        sc += SCORE_SMART_MONEY; rs.append("بصمة Smart Money")

    # ═══════════════ 14. ✅ Liquidity Grab ═══════════════
    liq_grab = calc_liquidity_grab(candles) if candles and len(candles) >= 10 else False
    if liq_grab:
        sc += SCORE_LIQUIDITY_GRAB; rs.append("صيد سيولة + ارتداد")

    # ═══════════════ 15. ✅ EMA Cross ═══════════════
    ema_cross = calc_ema_cross(candles) if candles and len(candles) >= 25 else False
    if ema_cross:
        sc += SCORE_EMA_CROSS; rs.append("EMA 9/21 Bullish Cross")

    # ═══════════════ 16. VWAP Cross ═══════════════
    vwap = calc_vwap_cross(candles) if candles and len(candles) >= 10 else False
    if vwap:
        sc += SCORE_VWAP_CROSS; rs.append("اختراق VWAP")

    # ═══════════════ 17. ضغط البيع ينخفض ═══════════════
    dec_sell = calc_decreasing_sell_pressure(candles) if candles and len(candles) >= 8 else False
    if dec_sell:
        sc += SCORE_DEC_SELL; rs.append("ضغط بيع ينخفض")

    # ═══════════════ 18. شموع الشراء بتكبر ═══════════════
    growing_candles = calc_candle_size_increase(candles) if candles and len(candles) >= 6 else False
    if growing_candles:
        sc += SCORE_CANDLE_GROWTH; rs.append("شموع شراء تتضخم")

    dt = {
        "rvol":         rv,
        "vol_surge":    surge,
        "surge_ratio":  surge_ratio,
        "vol_trend":    vt,
        "squeeze":      bb_width < 5.0,
        "bb_width":     bb_width,
        "sideways":     side,
        "breakout":     brk,
        "absorption":   abso,
        "higher_lows":  hl,
        "above_ma":     above_ma,
        "rsi_div":      rsi_div,
        "cvd_pos":      cvd_pos,
        "order_flow":   of_imb,
        "buy_pressure": buy_pressure,
        "wyckoff":      wyckoff,
        "smart_money":  smart_money,
        "liq_grab":     liq_grab,
        "ema_cross":    ema_cross,
        "vwap_cross":   vwap,
        "dec_sell":     dec_sell,
        "candle_grow":  growing_candles,
    }

    # ═══════════════ ✅ v4.0 — تطبيق المحركات المُدمَجة ═══════════════
    confluence = evaluate_confluence_engines(candles, dt)
    sc += confluence["bonus_points"]
    if confluence["momentum"]["pass"]:
        rs.append(f"⚙️ محرك Momentum ({confluence['momentum']['score']}/3)")
    if confluence["smart"]["pass"]:
        rs.append(f"💰 محرك Smart Money ({confluence['smart']['score']}/4)")
    if confluence["breakout"]["pass"]:
        rs.append(f"🚀 محرك Breakout ({confluence['breakout']['score']}/4)")

    dt["confluence"] = confluence
    # نضع علم confluence_passed لاستخدامه في الفلتر
    dt["confluence_passed"] = confluence["engines_passed"] >= CONFLUENCE_ENGINES_REQ

    # الـ raw score القصوى = 130 (المؤشرات الأساسية) + 24 (3 محركات × 8 bonus) = 154
    final_score = min(int(sc * 100 / 154), 100)
    return {"score": final_score, "raw_score": sc, "reasons": rs, "details": dt}


# ==================== قوة سير الفوليوم (Volume Flow Strength) ====================
# v3.2: نحسب من الفوليوم الشرائي فقط (الشموع الخضراء: close >= open)
# معيار مرجّح: لحظي (40%) + اتجاه (35%) + تسارع (25%)
def _buy_volume(candle):
    """فوليوم شرائي للشمعة: لو الشمعة خضراء (close>=open) نأخذ الفوليوم كاملاً، لو حمراء = 0"""
    return candle["volume"] if candle["close"] >= candle["open"] else 0.0


def calc_volume_flow_strength(candles):
    """
    حساب قوة سير الفوليوم الشرائي كنسبة مئوية 0-150% من 3 مكونات:
    - لحظي: نسبة فوليوم شرائي آخر ساعة vs متوسط الفوليوم الشرائي 24 ساعة
    - اتجاه: ميل خط انحدار الفوليوم الشرائي على آخر 12 ساعة
    - تسارع: مقارنة آخر 4 ساعات شرائي بالـ 20 ساعة شرائي قبلها
    """
    if not candles or len(candles) < 24:
        return None  # بيانات غير كافية

    # ✅ نأخذ الفوليوم الشرائي فقط (الشموع الخضراء)
    buy_vols = [_buy_volume(c) for c in candles]
    n = len(buy_vols)

    # ملاحظة: لو كل الفوليوم بيعي تماماً (نادر جداً) المجاميع تساوي صفر — نُعيد None
    if sum(buy_vols) == 0:
        return None

    # --- 1) لحظي: RVOL آخر ساعة شرائي (40%) ---
    last_hour = buy_vols[-1]
    avg_24h = sum(buy_vols[-24:-1]) / 23 if n >= 24 else (sum(buy_vols[:-1]) / max(1, n-1))
    inst_ratio = (last_hour / avg_24h) if avg_24h > 0 else (1.0 if last_hour == 0 else 3.0)
    # تحويل لنسبة 0-150: 0.2x=0, 1.0x=50, 2.0x=112, 3.0x+=150 (سقف)
    inst_score = min(150.0, max(0.0, (inst_ratio - 0.2) * 62.5))

    # --- 2) اتجاه: ميل الانحدار على آخر 12 ساعة (35%) ---
    window = buy_vols[-12:] if n >= 12 else buy_vols
    m = len(window)
    if m >= 3 and sum(window) > 0:
        avg_w = sum(window) / m
        mean_i = (m - 1) / 2
        num = sum((i - mean_i) * (v - avg_w) for i, v in enumerate(window))
        den = sum((i - mean_i) ** 2 for i in range(m))
        slope = num / den if den > 0 else 0
        slope_pct = (slope / avg_w * 100) if avg_w > 0 else 0
        trend_score = min(150.0, max(0.0, 50 + slope_pct * 5))
    else:
        trend_score = 50.0

    # --- 3) تسارع: آخر 4 ساعات vs الـ 20 ساعة قبلها (25%) ---
    if n >= 24:
        recent_4 = sum(buy_vols[-4:]) / 4
        older_20 = sum(buy_vols[-24:-4]) / 20
        accel_ratio = (recent_4 / older_20) if older_20 > 0 else (1.0 if recent_4 == 0 else 3.0)
    elif n >= 8:
        half = n // 2
        recent_h = sum(buy_vols[-half:]) / half
        older_h = sum(buy_vols[:-half]) / max(1, n - half)
        accel_ratio = (recent_h / older_h) if older_h > 0 else (1.0 if recent_h == 0 else 3.0)
    else:
        accel_ratio = 1.0
    accel_score = min(150.0, max(0.0, (accel_ratio - 0.2) * 62.5))

    # --- نسبة الفوليوم الشرائي من الإجمالي (مؤشر إضافي) ---
    total_vols = [c["volume"] for c in candles[-24:]] if n >= 24 else [c["volume"] for c in candles]
    total_24 = sum(total_vols)
    buy_24 = sum(buy_vols[-24:]) if n >= 24 else sum(buy_vols)
    buy_dominance = (buy_24 / total_24 * 100) if total_24 > 0 else 0  # نسبة الشراء %

    # --- المجموع المرجّح ---
    final = (inst_score * 0.40) + (trend_score * 0.35) + (accel_score * 0.25)

    return {
        "score":         round(final, 1),
        "instant":       round(inst_score, 1),
        "trend":         round(trend_score, 1),
        "accel":         round(accel_score, 1),
        "inst_ratio":    round(inst_ratio, 2),
        "accel_ratio":   round(accel_ratio, 2),
        "buy_dominance": round(buy_dominance, 1),  # ✅ نسبة الفوليوم الشرائي
    }


def classify_flow_strength(score):
    """تصنيف قوة السير حسب النسبة المرجحة"""
    if score is None:        return ("❓ غير متاح",  "unknown")
    if score >= 90:          return ("🔥 قوي جداً",   "very_strong")
    if score >= 70:          return ("⚡ قوي",        "strong")
    if score >= 50:          return ("📊 متوسط",      "medium")
    if score >= 30:          return ("📉 ضعيف",       "weak")
    return                          ("💤 ضعيف جداً",  "very_weak")


# ==================== تحويل بيانات CMC ====================
def parse_coin(coin):
    q = coin.get("quote",{}).get("USD",{})
    return {
        "id":               coin.get("id"),
        "name":             coin.get("name",""),
        "symbol":           coin.get("symbol",""),
        "price":            float(q.get("price",0) or 0),
        "market_cap":       float(q.get("market_cap",0) or 0),
        "volume_24h":       float(q.get("volume_24h",0) or 0),
        "volume_change":    float(q.get("volume_change_24h",0) or 0),
        "price_change_1h":  float(q.get("percent_change_1h",0) or 0),
        "price_change_24h": float(q.get("percent_change_24h",0) or 0),
        "price_change_7d":  float(q.get("percent_change_7d",0) or 0),
        "rank":             coin.get("cmc_rank",999),
        "num_market_pairs": coin.get("num_market_pairs",0),
        "tags":             [t.lower() for t in coin.get("tags",[])],
    }


# ============================================================
# الوظيفة 1: التقرير الدوري — أعلى 50 عملة زادت سيولتها
# ============================================================
async def send_volume_report(bot: Bot, target_chat: int = None):
    global previous_report
    logger.info("التقرير الدوري...")
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    chat_target = target_chat if target_chat else int(ADMIN_CHAT_ID)

    async with aiohttp.ClientSession() as session:
        # ✅ v4.1 — استخدام Gate.io الكامل بدل CMC top 500
        if USE_FULL_GATE_SCAN:
            candidates_raw = await build_all_gate_candidates(
                session, min_volume_usd=GATE_MIN_VOLUME_USD
            )
            if not candidates_raw:
                logger.warning("Gate.io رجع فاضي — fallback لـ CMC")
                cmc_raw = await fetch_cmc(session, limit=CMC_LIMIT)
                candidates_raw = [parse_coin(c) for c in (cmc_raw or [])]
        else:
            cmc_raw = await fetch_cmc(session, limit=CMC_LIMIT)
            if not cmc_raw:
                await bot.send_message(chat_id=chat_target, text="فشل جلب البيانات من CMC")
                return
            candidates_raw = [parse_coin(c) for c in cmc_raw]

    if not candidates_raw:
        await bot.send_message(chat_id=chat_target, text="فشل جلب البيانات")
        return

    coins = []
    for d in candidates_raw:
        symbol = d.get("symbol","")
        name   = d.get("name","")
        tags   = d.get("tags", [])
        if symbol in EXCLUDED_SYMBOLS: continue
        if is_meme_coin(symbol, name, tags): continue
        if is_stock_token(symbol, name, tags): continue
        if d["volume_24h"]    < MIN_VOLUME_REPORT:          continue
        # ملاحظة v4.1: العملات بدون بيانات CMC قد لا تملك volume_change
        # لذا نتغاضى عن هذا الفلتر للعملات المصدرها Gate فقط
        if d.get("source") == "gate+cmc" and d["volume_change"] < MIN_VOL_CHANGE_FOR_REPORT:
            continue
        if is_dead_coin(d): continue
        coins.append(d)
    logger.info(f"📋 {len(coins)} عملة بعد فلاتر التقرير")

    # الترتيب: لو من CMC نرتب بـ volume_change، لو من Gate نرتب بالـ volume_24h
    coins.sort(key=lambda x: (x.get("volume_change", 0), x.get("volume_24h", 0)), reverse=True)

    fresh = [c for c in coins if not is_coin_cooldown(c["symbol"])]
    old_c = [c for c in coins if is_coin_cooldown(c["symbol"])]

    if len(fresh) >= TOP_DISPLAY:
        top50 = fresh[:TOP_DISPLAY]
    else:
        needed = TOP_DISPLAY - len(fresh)
        top50  = fresh + old_c[:needed]

    for c in top50:
        if not is_coin_cooldown(c["symbol"]):
            seen_coins[c["symbol"]] = datetime.now()
    save_seen_coins()
    previous_report = top50

    # ===== جلب الكلاينز بالتوازي وحساب قوة سير الفوليوم لكل عملة =====
    logger.info(f"جلب كلاينز قوة سير الفوليوم لـ {len(top50)} عملة...")
    async with aiohttp.ClientSession() as session2:
        async def _fetch_flow(coin):
            try:
                kl = await fetch_klines(session2, coin["symbol"], interval="1h", limit=48)
                coin["candles"] = kl
                coin["flow"] = calc_volume_flow_strength(kl)
                # ✅ v4.0 — VIP evaluation
                is_vip, vip_checks = evaluate_vip_status(kl, coin["flow"])
                coin["is_vip"]     = is_vip
                coin["vip_checks"] = vip_checks
            except Exception:
                coin["flow"] = None
                coin["is_vip"] = False
                coin["vip_checks"] = []
            return coin
        # توازي بسقف معقول
        sem = asyncio.Semaphore(GATE_PARALLEL_LIMIT)
        async def _with_sem(c):
            async with sem:
                return await _fetch_flow(c)
        await asyncio.gather(*[_with_sem(c) for c in top50], return_exceptions=True)

    # ✅ v4.2 — لا نستبعد، نُصنّف فقط
    # نحتفظ بكل الـ top 50 من حيث الفوليم، ونعطي كل عملة تصنيفها الحقيقي
    # العملات بدون كلاينز (مش في Gate.io) تبقى في القائمة بدون قوة سير
    for c in top50:
        flow = c.get("flow")
        if flow:
            score = flow.get("score", 0)
            buy_d = flow.get("buy_dominance", 0)
            # التصنيف:
            if score >= MIN_FLOW_SCORE_FOR_REPORT and buy_d >= MIN_BUY_DOMINANCE:
                c["category"] = "strong_buy"   # 🔥 شراء قوي
            elif buy_d >= MIN_BUY_DOMINANCE:
                c["category"] = "buy_dominant" # 🟢 شراء غالب لكن السير متوسط
            elif score >= MIN_FLOW_SCORE_FOR_REPORT:
                c["category"] = "high_flow"    # 📈 سير عالي لكن ليس شراء غالب
            else:
                c["category"] = "neutral"      # 📊 عادي
        else:
            c["category"] = "no_data"          # ❓ بيانات غير متاحة

    # ✅ v4.0 — الترتيب: VIP → شراء قوي → باقي حسب الفوليم
    category_rank = {"strong_buy": 4, "buy_dominant": 3, "high_flow": 2, "neutral": 1, "no_data": 0}
    top50.sort(
        key=lambda x: (
            x.get("is_vip", False),
            category_rank.get(x.get("category", "no_data"), 0),
            x.get("flow", {}).get("score", 0) if x.get("flow") else 0,
            x.get("volume_change", 0),
            x.get("volume_24h", 0),
        ),
        reverse=True
    )
    vip_count        = sum(1 for c in top50 if c.get("is_vip"))
    strong_buy_count = sum(1 for c in top50 if c.get("category") == "strong_buy")
    logger.info(f"تقرير الفوليم: {len(top50)} عملة | 💎 VIP: {vip_count} | 🔥 شراء قوي: {strong_buy_count}")

    if not top50:
        try:
            await bot.send_message(
                chat_id=chat_target,
                text=f"📊 لا توجد عملات تجاوزت فلاتر الفوليم الأساسية\n⏰ {scan_time}",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"خطأ ارسال تقرير فارغ: {e}")
        logger.info("لا توجد عملات بعد فلتر الفوليم")
        return

    chunk_size = 10
    chunks = [top50[i:i+chunk_size] for i in range(0, len(top50), chunk_size)]

    # شارات التصنيف
    cat_badge = {
        "strong_buy":   "🔥 شراء قوي",
        "buy_dominant": "🟢 شراء غالب",
        "high_flow":    "📈 سير عالي",
        "neutral":      "📊 عادي",
        "no_data":      "❓ بدون كلاينز",
    }

    for idx, chunk in enumerate(chunks, 1):
        lines = []
        if idx == 1:
            lines += [
                f"📊 أعلى Altcoin بالفوليم — 24 ساعة",
                f"⏰ {scan_time}",
                f"📡 المصدر: Gate.io + CMC",
                f"✅ {len(top50)} عملة | 💎 VIP: {vip_count} | 🔥 شراء قوي: {strong_buy_count}",
                f"━━━ التصنيفات ━━━",
                f"🔥 شراء قوي = قوة ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}% + هيمنة ≥ {MIN_BUY_DOMINANCE:.0f}%",
                f"🟢 شراء غالب = هيمنة ≥ {MIN_BUY_DOMINANCE:.0f}% (سير متوسط)",
                f"📈 سير عالي = قوة ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}% (هيمنة أقل)",
                f"💎 VIP = شراء مستمر 3h+ + فوق VWAP",
                "━━━━━━━━━━━━━━━━━━━━", ""
            ]

        for i, c in enumerate(chunk, (idx-1)*chunk_size + 1):
            pc  = c["price_change_24h"]
            vc  = c.get("volume_change", 0)
            p1h = c.get("price_change_1h", 0)
            arrow = "🟢" if pc > 0 else "🔴"
            vip_badge = " 💎 VIP" if c.get("is_vip") else ""
            category  = c.get("category", "no_data")
            cat_lbl   = cat_badge.get(category, "")
            if vc >= 200:   vol_icon = "🔥🔥🔥"
            elif vc >= 100: vol_icon = "🔥🔥"
            elif vc >= 50:  vol_icon = "🔥"
            else:           vol_icon = "📈"

            lines.append(f"{i}. {arrow} {c['symbol']}{vip_badge} — {escape_md(c['name'])}")
            lines.append(f"   🏷  {cat_lbl}")
            lines.append(f"   💵 {fmt_price(c['price'])}  ({pc:+.1f}%)  |  1h: {p1h:+.1f}%")
            lines.append(f"   💰 فوليم 24h: {fmt_vol(c['volume_24h'])}")
            if vc != 0:  # لو متاح (من CMC فقط)
                lines.append(f"   {vol_icon} زيادة الفوليم: {vc:+.0f}%")
            # ===== قوة السير الشرائي + هيمنة الشراء =====
            flow = c.get("flow")
            if flow:
                label, _ = classify_flow_strength(flow["score"])
                lines.append(f"   📡 قوة سير الشراء: {flow['score']:.0f}%  {label}")
                lines.append(f"   🟢 هيمنة الشراء: {flow['buy_dominance']:.0f}%")
            else:
                lines.append(f"   📡 قوة سير الشراء: ❓ بيانات غير متاحة")
            # rank لو من CMC
            rank_str = f"CMC #{c['rank']}" if c.get('rank', 999999) < 999999 else "Gate-only"
            lines.append(f"   🌐 {c.get('num_market_pairs', '?')} منصة  |  {rank_str}")
            lines.append("")

        if idx == len(chunks):
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("💡 /coin SYMBOL  — تحليل شامل احترافي")
            lines.append("💡 /check SYMBOL — تقييم القوة و السيولة")
            lines.append("💡 /vol SYMBOL   — حجم عملة")

        try:
            await bot.send_message(
                chat_id=chat_target,
                text="\n".join(lines),
                disable_web_page_preview=True
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"خطأ ارسال تقرير: {e}")

    logger.info(f"تم إرسال التقرير: {len(top50)} عملة")


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

    # 5️⃣ إزالة المكررات + إعادة إرسال فقط لو النقاط زادت (خلال 24 ساعة)
    # ✅ تعديل المستخدم:
    #    - نفس العملة خلال 24 ساعة لا تُرسل مرة أخرى
    #    - الاستثناء الوحيد: لو نقاط الدخول زادت (مثال 11 → 13) تُرسل
    #    - لو النقاط نفسها → تجاهل
    #    - لو النقاط أقل → تجاهل
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
            within_cooldown = elapsed < PUMP_SIGNAL_COOLDOWN_MIN * 60  # 24 ساعة

            # ✅ الاستثناء الوحيد خلال الـ 24 ساعة: زيادة في نقاط الدخول
            points_increased = (r["score"] - last_score) >= PUMP_RESEND_MIN_INCREASE

            if within_cooldown and not points_increased:
                # نفس النقاط أو أقل خلال 24 ساعة → تجاهل
                logger.info(f"تخطي {sym} — نفس العملة خلال 24س "
                            f"(score={r['score']} vs آخر={last_score}, "
                            f"منذ {int(elapsed/3600)}س) — لا زيادة في النقاط")
                continue
            if within_cooldown and points_increased:
                logger.info(f"📈 {sym} — النقاط زادت {last_score}→{r['score']} "
                            f"(+{r['score']-last_score}) خلال 24س — إرسال")
            else:
                logger.info(f"🔄 {sym} — مرّت 24 ساعة — إرسال عادي")
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


# ============================================================
# /info — التوكنوميكس
# ============================================================
async def get_token_info(symbol: str) -> str:
    symbol = symbol.upper().strip()
    results = {}

    async with aiohttp.ClientSession() as session:
        cmc_coin = await fetch_cmc_single(session, symbol)
        if cmc_coin:
            q = cmc_coin.get("quote",{}).get("USD",{})
            results["price"]         = float(q.get("price",0) or 0)
            results["pc24"]          = float(q.get("percent_change_24h",0) or 0)
            results["volume_24h"]    = float(q.get("volume_24h",0) or 0)
            results["market_cap"]    = float(q.get("market_cap",0) or 0)
            results["rank"]          = cmc_coin.get("cmc_rank",999)
            results["name"]          = cmc_coin.get("name","")
            results["circulating"]   = float(cmc_coin.get("circulating_supply",0) or 0)
            results["total_supply"]  = float(cmc_coin.get("total_supply",0) or 0)
            results["max_supply"]    = cmc_coin.get("max_supply")
            results["pairs"]         = cmc_coin.get("num_market_pairs",0)
            results["date_added"]    = cmc_coin.get("date_added","")[:10]

        try:
            cg_url = f"https://api.coingecko.com/api/v3/search?query={symbol}"
            async with session.get(cg_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                cg_data = await r.json()
            coins_list = cg_data.get("coins",[])
            cg_id = next((c["id"] for c in coins_list
                          if c.get("symbol","").upper() == symbol), None)
            if cg_id:
                detail_url = f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false&market_data=true&community_data=true&developer_data=false"
                async with session.get(detail_url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                    detail = await r.json()
                community = detail.get("community_data",{})
                results["twitter_followers"]  = community.get("twitter_followers",0) or 0
                results["reddit_subscribers"] = community.get("reddit_subscribers",0) or 0
                if results.get("total_supply",0) > 0 and results.get("circulating",0) > 0:
                    results["circ_pct"] = results["circulating"] / results["total_supply"] * 100
        except Exception as e:
            logger.debug(f"CoinGecko error: {e}")

    if not results.get("name"):
        return f"العملة {symbol} مش موجودة في CMC"

    def fmt_supply(v):
        if not v or v == 0: return "غير محدد"
        if v >= 1_000_000_000: return f"{v/1_000_000_000:.2f}B"
        if v >= 1_000_000:     return f"{v/1_000_000:.2f}M"
        return f"{v/1_000:.1f}K"

    arrow = "🟢" if results.get("pc24",0) > 0 else "🔴"
    lines = [
        f"📋 توكنوميكس {symbol} — {escape_md(results.get('name',''))}",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"{arrow} السعر: {fmt_price(results.get('price',0))}  ({results.get('pc24',0):+.2f}%)",
        f"💰 فوليم 24h: {fmt_vol(results.get('volume_24h',0))}",
        f"💎 Market Cap: {fmt_vol(results.get('market_cap',0))}",
        f"📊 رانك CMC: #{results.get('rank',999)}",
        f"",
        f"🪙 التوكنوميكس:",
        f"   العملات المتداولة: {fmt_supply(results.get('circulating',0))}",
        f"   Total Supply: {fmt_supply(results.get('total_supply',0))}",
        f"   Max Supply: {fmt_supply(results.get('max_supply',0)) if results.get('max_supply') else 'غير محدود'}",
    ]
    if results.get("circ_pct"):
        pct = results["circ_pct"]
        bar_filled = int(pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(f"   نسبة المتداول: {pct:.1f}% [{bar}]")
    if results.get("twitter_followers",0) > 0 or results.get("reddit_subscribers",0) > 0:
        lines.append(f"")
        lines.append(f"👥 المجتمع:")
        if results.get("twitter_followers",0) > 0:
            lines.append(f"   Twitter: {results['twitter_followers']:,}")
        if results.get("reddit_subscribers",0) > 0:
            lines.append(f"   Reddit: {results['reddit_subscribers']:,}")
    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    return "\n".join(lines)


# ============================================================
# /vol — حجم أي عملة
# ============================================================
async def get_vol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    async with aiohttp.ClientSession() as session:
        coin = await fetch_cmc_single(session, symbol)
        if not coin:
            return f"العملة {symbol} مش موجودة في CMC"
        q     = coin.get("quote",{}).get("USD",{})
        vol   = float(q.get("volume_24h",0) or 0)
        vc    = float(q.get("volume_change_24h",0) or 0)
        price = float(q.get("price",0) or 0)
        pc24  = float(q.get("percent_change_24h",0) or 0)
        pc1h  = float(q.get("percent_change_1h",0) or 0)
        pc7d  = float(q.get("percent_change_7d",0) or 0)
        mc    = float(q.get("market_cap",0) or 0)
        pairs = coin.get("num_market_pairs",0)
        rank  = coin.get("cmc_rank",999)
        name  = coin.get("name","")
        arrow = "🟢" if pc24 > 0 else "🔴"
        return (
            f"📊 {symbol} — {escape_md(name)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{arrow} السعر: {fmt_price(price)}  ({pc24:+.2f}%)\n"
            f"⏱ 1h: {pc1h:+.2f}%  |  7d: {pc7d:+.2f}%\n\n"
            f"💰 حجم التداول 24h الكلي:\n"
            f"   {fmt_vol(vol)}\n"
            f"   زيادة الفوليم: {vc:+.1f}%\n\n"
            f"🌐 عدد المنصات: {pairs}\n"
            f"💎 Market Cap: {fmt_vol(mc)}\n"
            f"📊 رانك CMC: #{rank}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"📡 CoinMarketCap"
        )


# ============================================================
# /coin — تحليل شامل بكل المؤشرات
# ============================================================
async def get_coin_analysis(symbol: str) -> str:
    """
    ✅ v4.0 — تحليل شامل احترافي multi-timeframe
    يجمع: CMC + Gate.io (1h و 4h) + كل المؤشرات + المحركات + توصية واضحة
    """
    symbol = symbol.upper().strip()
    async with aiohttp.ClientSession() as session:
        coin = await fetch_cmc_single(session, symbol)
        if not coin:
            return f"العملة {symbol} مش موجودة في CMC"
        d = parse_coin(coin)
        # ✅ multi-timeframe
        candles_1h = await fetch_klines(session, symbol, interval="1h", limit=72)
        candles_4h = await fetch_klines(session, symbol, interval="4h", limit=42)

        arrow = "🟢" if d["price_change_24h"] > 0 else "🔴"
        lines = [
            f"📋 التحليل الشامل — {symbol}",
            f"   ({escape_md(d['name'])})",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"💵 السعر الحالي",
            f"   {arrow} {fmt_price(d['price'])}",
            f"   • 24h:  {d['price_change_24h']:+.2f}%",
            f"   • 1h :  {d['price_change_1h']:+.2f}%",
            f"   • 7d :  {d['price_change_7d']:+.2f}%",
            f"",
            f"📊 معلومات السوق",
            f"   • فوليم 24h:   {fmt_vol(d['volume_24h'])}  ({d['volume_change']:+.0f}%)",
            f"   • Market Cap: {fmt_vol(d['market_cap'])}",
            f"   • CMC Rank:   #{d['rank']}",
            f"   • المنصات:    {d['num_market_pairs']}",
            f"",
        ]

        # ═══════ التحليل الفني الشامل ═══════
        if candles_1h and len(candles_1h) >= 30:
            res = score_coin(candles_1h, d)
            sc  = res["score"]
            dt  = res["details"]
            conf = dt.get("confluence", {})
            flow = calc_volume_flow_strength(candles_1h)
            is_vip, vip_checks = evaluate_vip_status(candles_1h, flow)

            # ═══ الحكم الإجمالي ═══
            engines = conf.get("engines_passed", 0)
            lines.append(f"🎯 الحكم الإجمالي")
            lines.append(f"   • النقاط: {sc}/100")
            lines.append(f"   • محركات الـ Confluence: {engines}/3")
            if sc >= MIN_SCORE and engines >= CONFLUENCE_ENGINES_REQ:
                verdict = "🚀 إشارة مؤكدة — قابلة للإرسال"
            elif sc >= MIN_SCORE:
                verdict = "⚠️ نقاط جيدة لكن المحركات ضعيفة"
            elif engines >= CONFLUENCE_ENGINES_REQ:
                verdict = "⚠️ محركات جيدة لكن النقاط أقل من 80"
            elif sc >= 60:
                verdict = "👁 تستحق المراقبة"
            else:
                verdict = "😴 لا توجد إشارة"
            lines.append(f"   • التقييم: {verdict}")
            if is_vip:
                lines.append(f"   • 💎 VIP — سيولة شراء مستمرة")
            lines.append("")

            # ═══ المحركات الثلاثة بالتفصيل ═══
            lines.append("⚙️ محركات الـ Confluence (تفاصيل)")
            for engine_name, engine_key, total in [
                ("Momentum",    "momentum", 3),
                ("Smart Money", "smart",    4),
                ("Breakout",    "breakout", 4),
            ]:
                e = conf.get(engine_key, {})
                icon = "✅" if e.get("pass") else "❌"
                lines.append(f"   {icon} {engine_name} ({e.get('score',0)}/{total})")
                for nm, ok in e.get("checks", []):
                    sub_icon = "✓" if ok else "✗"
                    lines.append(f"      {sub_icon} {nm}")
            lines.append("")

            # ═══ المؤشرات الفنية ═══
            mom = conf.get("momentum", {})
            lines.append("📈 مؤشرات الزخم")
            if mom.get("rsi") is not None:
                rsi = mom["rsi"]
                rsi_state = "🔴 oversold" if rsi < 30 else "🟡 محايد" if rsi < 60 else "🟢 صاعد" if rsi < 70 else "🔥 مشتعل/overbought"
                lines.append(f"   • RSI(14): {rsi:.1f}  {rsi_state}")
            if mom.get("stoch_k") is not None:
                lines.append(f"   • Stochastic %K: {mom['stoch_k']:.1f}")
            if mom.get("macd_hist") is not None:
                macd_state = "🟢 موجب" if mom["macd_hist"] > 0 else "🔴 سالب"
                lines.append(f"   • MACD Histogram: {mom['macd_hist']:.4f}  {macd_state}")
            lines.append("")

            # ═══ السيولة الشرائية ═══
            lines.append("💧 السيولة الشرائية")
            lines.append(f"   • RVOL: {dt['rvol']:.2f}x")
            if dt.get("vol_surge"):
                lines.append(f"   • قفزة فوليم: {dt.get('surge_ratio',0):.1f}x ⚡")
            if flow:
                label, _ = classify_flow_strength(flow["score"])
                lines.append(f"   • قوة سير الشراء: {flow['score']:.0f}%  {label}")
                lines.append(f"   • هيمنة الشراء: {flow['buy_dominance']:.0f}%")
                lines.append(f"      └ لحظي: {flow['instant']:.0f}%  |  اتجاه: {flow['trend']:.0f}%  |  تسارع: {flow['accel']:.0f}%")
            lines.append("")

            # ═══ Price Action ═══
            lines.append("🎨 Price Action")
            lines.append(f"   • Bollinger Width: {dt['bb_width']:.2f}%  " +
                         ("🎯 Squeeze!" if dt['squeeze'] else ("ضيق" if dt['bb_width']<8 else "")))
            lines.append(f"   • Breakout: {'✅' if dt['breakout'] else '❌'}")
            lines.append(f"   • Higher Lows: {'✅' if dt['higher_lows'] else '❌'}")
            lines.append(f"   • فوق MA20: {'✅' if dt['above_ma'] else '❌'}")
            lines.append(f"   • VWAP Cross: {'✅' if dt['vwap_cross'] else '❌'}")
            lines.append(f"   • Sideways/تجميع: {'✅' if dt['sideways'] else '❌'}")
            lines.append("")

            # ═══ Smart Money Footprints ═══
            lines.append("💎 بصمات المال الذكي")
            lines.append(f"   • CVD (تجميع شراء): {'✅' if dt['cvd_pos'] else '❌'}")
            lines.append(f"   • Order Flow: {'✅ ' + str(int(dt['buy_pressure']*100)) + '%' if dt['order_flow'] else '❌'}")
            lines.append(f"   • Wyckoff Accumulation: {'✅' if dt['wyckoff'] else '❌'}")
            lines.append(f"   • Smart Money Footprint: {'✅' if dt['smart_money'] else '❌'}")
            lines.append(f"   • Liquidity Grab: {'✅' if dt['liq_grab'] else '❌'}")
            lines.append(f"   • RSI Divergence: {'✅' if dt['rsi_div'] else '❌'}")
            lines.append(f"   • EMA 9/21 Cross: {'✅' if dt['ema_cross'] else '❌'}")
            lines.append(f"   • امتصاص بيع: {'✅' if dt['absorption'] else '❌'}")
            lines.append("")

            # ═══ تحليل الـ 4h ═══
            if candles_4h and len(candles_4h) >= 26:
                res4h = score_coin(candles_4h, d)
                conf4h = res4h["details"].get("confluence", {})
                lines.append("⏳ التأكيد على Timeframe الـ 4h")
                lines.append(f"   • النقاط (4h): {res4h['score']}/100")
                lines.append(f"   • محركات (4h): {conf4h.get('engines_passed',0)}/3")
                if conf4h.get("engines_passed", 0) >= 2 and conf.get("engines_passed", 0) >= 2:
                    lines.append(f"   ✅ تأكيد مزدوج (1h + 4h)")
                lines.append("")

            # ═══ Velocity & Trend Quality ═══
            velocity = calc_velocity(candles_1h)
            tq = calc_trend_quality(candles_1h)
            liq_depth = calc_liquidity_depth(d, candles_1h)
            lines.append("⚡ مقاييس الحركة")
            lines.append(f"   • سرعة الحركة: {velocity:+.2f} (ATR normalized)")
            lines.append(f"   • جودة الاتجاه: {tq:.0f}/100")
            lines.append(f"   • عمق السيولة: {liq_depth:.0f}/100")
            lines.append("")

            # ═══ المخاطر ═══
            prev_pump = calc_prev_pump(candles_1h)
            lines.append("⚠️ تقييم المخاطر")
            if prev_pump > MAX_PREV_PUMP:
                lines.append(f"   ❌ بامب سابق {prev_pump:.1f}% — مخاطر شراء قمة!")
            elif prev_pump > 6:
                lines.append(f"   ⚠️ ارتفع {prev_pump:.1f}% خلال آخر فترة")
            else:
                lines.append(f"   ✅ لم تشهد بامب كبير مؤخراً ({prev_pump:.1f}%)")
            if dt['rvol'] > 5:
                lines.append(f"   ⚠️ RVOL مرتفع جداً ({dt['rvol']:.1f}x) — احتمال نهاية موجة")
            lines.append("")

            # ═══ التوصية النهائية ═══
            lines.append("🎯 التوصية النهائية")
            if sc >= 85 and engines >= 2 and is_vip:
                lines.append("   🔥🔥 إشارة قوية + VIP — تستحق دخول")
            elif sc >= 80 and engines >= 2:
                lines.append("   🔥 إشارة قابلة للتنفيذ")
            elif sc >= 70 and engines >= 1:
                lines.append("   👁 راقب — قد تتحول لإشارة")
            elif sc >= 60:
                lines.append("   ⏳ ضعيفة — لا تدخل الآن")
            else:
                lines.append("   ❌ لا توصية بالدخول")
            lines.append("")

        lines += [
            f"🔗 https://www.tradingview.com/chart/?symbol=GATEIO:{symbol}_USDT",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        return "\n".join(lines)


async def get_coin_check(symbol: str) -> str:
    """
    ✅ v4.0 — أمر /check
    يعطي 4 مقاييس رئيسية:
       💪 قوة العملة (Strength Score)
       📐 احترام التحليل (Trend Quality / Respect)
       💧 وجود السيولة (Liquidity Depth)
       ⚡ سرعة الحركة (Velocity)
    """
    symbol = symbol.upper().strip()
    async with aiohttp.ClientSession() as session:
        coin = await fetch_cmc_single(session, symbol)
        if not coin:
            return f"العملة {symbol} مش موجودة في CMC"
        d = parse_coin(coin)
        candles = await fetch_klines(session, symbol, interval="1h", limit=72)

        if not candles or len(candles) < 25:
            return f"⚠️ بيانات الكلاينز غير كافية لـ {symbol} (موجودة في CMC، ربما غير مدرجة في Gate.io)"

        # احسب الـ 4 مقاييس
        res        = score_coin(candles, d)
        strength   = res["score"]                                       # قوة العملة
        trend_q    = calc_trend_quality(candles)                        # احترام التحليل
        liq_depth  = calc_liquidity_depth(d, candles)                   # وجود السيولة
        velocity   = calc_velocity(candles)                             # سرعة الحركة
        flow       = calc_volume_flow_strength(candles)
        is_vip, _  = evaluate_vip_status(candles, flow)

        # تصنيف كل مقياس
        def grade(score):
            if score >= 85: return "🔥 ممتاز جداً", "very_strong"
            if score >= 70: return "✅ قوي",        "strong"
            if score >= 55: return "📊 متوسط",      "medium"
            if score >= 40: return "📉 ضعيف",       "weak"
            return                "💤 ضعيف جداً",   "very_weak"

        s_lbl, _   = grade(strength)
        t_lbl, _   = grade(trend_q)
        l_lbl, _   = grade(liq_depth)
        # velocity تختلف: قد تكون سالبة (نزول) أو موجبة (صعود)
        vel_abs    = abs(velocity)
        if vel_abs >= 2.5:   v_lbl = "⚡⚡ سريعة جداً"
        elif vel_abs >= 1.5: v_lbl = "⚡ سريعة"
        elif vel_abs >= 0.5: v_lbl = "🚶 متوسطة"
        else:                v_lbl = "🐢 بطيئة"
        v_dir = "🟢 صاعدة" if velocity > 0 else "🔴 هابطة" if velocity < 0 else "➖ ثابتة"

        # الـ progress bar
        def bar(score, width=10):
            filled = int(score / 100 * width)
            return "█" * filled + "░" * (width - filled)

        arrow = "🟢" if d["price_change_24h"] > 0 else "🔴"
        vip_badge = " 💎 VIP" if is_vip else ""

        lines = [
            f"📊 تقييم {symbol}{vip_badge}",
            f"   ({escape_md(d['name'])})",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"{arrow} السعر: {fmt_price(d['price'])}  ({d['price_change_24h']:+.2f}%)",
            f"",
            f"💪 قوة العملة",
            f"   {bar(strength)} {strength}/100",
            f"   {s_lbl}",
            f"",
            f"📐 احترام التحليل (Trend Quality)",
            f"   {bar(trend_q)} {trend_q:.0f}/100",
            f"   {t_lbl}",
            f"   ← مدى نظافة الاتجاه: شموع فوق MA + R² + Higher Lows",
            f"",
            f"💧 وجود السيولة (Liquidity Depth)",
            f"   {bar(liq_depth)} {liq_depth:.0f}/100",
            f"   {l_lbl}",
            f"   ← فوليم 24h + عدد منصات + استمرارية",
            f"",
            f"⚡ سرعة الحركة (Velocity)",
            f"   القوة: {v_lbl}",
            f"   الاتجاه: {v_dir}  ({velocity:+.2f} ATR)",
            f"   ← حركة السعر مقسومة على التقلب الطبيعي",
            f"",
        ]

        # حكم سريع
        avg = (strength + trend_q + liq_depth + min(100, vel_abs*30)) / 4
        if avg >= 75:
            lines.append("🎯 الحكم السريع: 🔥 ممتازة من كل النواحي")
        elif avg >= 60:
            lines.append("🎯 الحكم السريع: ✅ جيدة")
        elif avg >= 45:
            lines.append("🎯 الحكم السريع: 📊 متوسطة")
        else:
            lines.append("🎯 الحكم السريع: ⚠️ ضعيفة")

        lines += [
            f"",
            f"🔗 https://www.tradingview.com/chart/?symbol=GATEIO:{symbol}_USDT",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"💡 /coin {symbol} للتحليل الشامل",
        ]
        return "\n".join(lines)


# ==================== ✅ Scheduled Jobs مع منع الإرسال المزدوج ====================
async def job_volume_report(context: ContextTypes.DEFAULT_TYPE):
    # ✅ منع التشغيل المتزامن
    if job_locks["volume_report"].locked():
        logger.warning("⚠️ job_volume_report قيد التشغيل بالفعل - تخطي")
        return
    # ✅ منع التشغيل المتقارب
    last = last_job_run["volume_report"]
    if last and (datetime.now() - last).total_seconds() < MIN_JOB_GAP_SECONDS:
        logger.warning("⚠️ job_volume_report تم تشغيله للتو - تخطي")
        return
    async with job_locks["volume_report"]:
        last_job_run["volume_report"] = datetime.now()
        try:
            await send_volume_report(context.bot)
        except Exception as e:
            logger.error(f"خطأ في job_volume_report: {e}")

async def job_check_signals(context: ContextTypes.DEFAULT_TYPE):
    # هذه الدالة تركت للتوافق مع /scan فقط — السكان الفعلي الآن مستمر
    if job_locks["check_signals"].locked():
        logger.warning("⚠️ job_check_signals قيد التشغيل بالفعل - تخطي")
        return
    last = last_job_run["check_signals"]
    if last and (datetime.now() - last).total_seconds() < MIN_JOB_GAP_SECONDS:
        logger.warning("⚠️ job_check_signals تم تشغيله للتو - تخطي")
        return
    async with job_locks["check_signals"]:
        last_job_run["check_signals"] = datetime.now()
        try:
            await check_signals(context.bot)
        except Exception as e:
            logger.error(f"خطأ في job_check_signals: {e}")


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
        "/info SYMBOL — توكنوميكس\n"
        "/vol SYMBOL  — حجم تداول\n"
        "/status      — حالة البوت\n"
        "/chatid      — معرفة الـ Chat ID"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 جاري جلب أعلى 50 عملة زيادة سيولة...")
    await send_volume_report(context.bot, target_chat=update.effective_chat.id)

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🔍 جاري فحص الإشارات التقنية (score >= {MIN_SCORE})...")
    await check_signals(context.bot, target_chat=update.effective_chat.id)

async def cmd_vol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم: /vol اسم_العملة\nمثال: /vol ETH")
        return
    await update.message.reply_text(f"🔍 جاري جلب بيانات {context.args[0].upper()}...")
    result = await get_vol(context.args[0])
    await update.message.reply_text(result)

async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم: /info اسم_العملة\nمثال: /info ETH")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 جاري جلب توكنوميكس {symbol}...")
    result = await get_token_info(symbol)
    await update.message.reply_text(result, disable_web_page_preview=True)

async def cmd_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم: /coin اسم_العملة\nمثال: /coin ETH")
        return
    await update.message.reply_text(f"🔍 جاري التحليل الشامل لـ {context.args[0].upper()}...")
    result = await get_coin_analysis(context.args[0])
    await update.message.reply_text(result, disable_web_page_preview=True)


# ✅ v4.0 — أمر /check للتقييم السريع بـ 4 مقاييس
async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "استخدم: /check اسم_العملة\n"
            "مثال: /check ETH\n\n"
            "يعطيك:\n"
            "  💪 قوة العملة\n"
            "  📐 احترام التحليل (Trend Quality)\n"
            "  💧 وجود السيولة\n"
            "  ⚡ سرعة الحركة"
        )
        return
    await update.message.reply_text(f"📊 جاري تقييم {context.args[0].upper()}...")
    result = await get_coin_check(context.args[0])
    await update.message.reply_text(result, disable_web_page_preview=True)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not previous_signals:
        await update.message.reply_text("لا توجد إشارات بعد، استخدم /scan")
        return
    top5  = sorted(previous_signals.values(), key=lambda x: x.get("score",0), reverse=True)[:5]
    lines = ["🏆 أفضل 5 إشارات:\n"]
    for i, c in enumerate(top5, 1):
        lines.append(f"{i}. {c['symbol']}  نقاط: {c.get('score',0)}/100  ({c['price_change_24h']:+.1f}%)")
    await update.message.reply_text("\n".join(lines))

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
    app.add_handler(CommandHandler("vol",     cmd_vol))
    app.add_handler(CommandHandler("info",    cmd_info))
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
