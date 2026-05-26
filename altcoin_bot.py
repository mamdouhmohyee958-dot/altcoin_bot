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
TELEGRAM_TOKEN = "8794878965:AAEZR3MdSG-3OiGBeR05q9MJzvvo1ODmNmc"
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
GATE_MIN_VOLUME_USD       = 500_000    # تجاهل عملات بفوليوم أقل (ميتة) لتوفير الوقت
GATE_MAX_CANDIDATES       = 1500       # سقف عدد العملات في الفحص الواحد
GATE_PARALLEL_LIMIT       = 25         # طلبات كلاينز متوازية (زدناها لـ 25)

# ==================== ✅ نظام النقاط المتطور (مجموع = 130 → mapped to 100) ====================
SCORE_RVOL              = 15
SCORE_VOL_SURGE         = 12
SCORE_VOL_TREND         = 5
SCORE_BB_SQUEEZE        = 12
SCORE_SIDEWAYS          = 5
SCORE_BREAKOUT          = 12
SCORE_ABSORPTION        = 8
SCORE_HIGHER_LOWS       = 6
SCORE_ABOVE_MA          = 5
# ✅ مؤشرات متطورة جديدة
SCORE_RSI_DIVERGENCE    = 12
SCORE_CVD_POSITIVE      = 10
SCORE_ORDER_FLOW        = 10
SCORE_WYCKOFF           = 10
SCORE_SMART_MONEY       = 10
SCORE_LIQUIDITY_GRAB    = 8
SCORE_EMA_CROSS         = 7
SCORE_VWAP_CROSS        = 5
SCORE_DEC_SELL          = 4
SCORE_CANDLE_GROWTH     = 4

# ✅ v4.0 — Confluence Engine
# المحركات الثلاثة + شرط 2/3 على الأقل لإرسال الإشارة
CONFLUENCE_MOMENTUM_REQ  = 3   # RSI Recovery + MACD + Stoch  (3/3 لاجتياز Momentum)
CONFLUENCE_SMART_REQ     = 3   # CVD + OF + Wyckoff + Smart   (3/4 لاجتياز Smart Money)
CONFLUENCE_BREAKOUT_REQ  = 3   # Squeeze + Surge + Above MA + HL (3/4 لاجتياز Breakout)
CONFLUENCE_ENGINES_REQ   = 2   # كم محرك لازم يعطي ✅ (2/3)
SCORE_CONFLUENCE_BONUS   = 8   # نقاط إضافية لكل محرك ناجح
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


async def build_all_gate_candidates(session, min_volume_usd=500_000):
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

    # ✅ جديد v3.1: استبعاد العملات ذات قوة السير الضعيف/الضعيف جداً
    # ✅ جديد v3.2: نشترط كمان هيمنة الشراء >= MIN_BUY_DOMINANCE
    # نُبقي فقط: قوي شرائياً (≥70%) + شراء غالب (≥55%)
    before_filter = len(top50)
    top50 = [
        c for c in top50
        if c.get("flow")
        and c["flow"].get("score", 0) >= MIN_FLOW_SCORE_FOR_REPORT
        and c["flow"].get("buy_dominance", 0) >= MIN_BUY_DOMINANCE
    ]
    # ✅ v4.0 — الترتيب: VIP أولاً، ثم قوة السير، ثم هيمنة الشراء
    top50.sort(
        key=lambda x: (
            x.get("is_vip", False),
            x["flow"]["score"],
            x["flow"]["buy_dominance"],
            x["volume_change"]
        ),
        reverse=True
    )
    vip_count = sum(1 for c in top50 if c.get("is_vip"))
    logger.info(f"فلتر الشراء: {before_filter} → {len(top50)} عملة | 💎 VIP: {vip_count}")

    if not top50:
        try:
            await bot.send_message(
                chat_id=chat_target,
                text=f"📊 لا توجد عملات بسير شرائي قوي حالياً\n"
                     f"   (المطلوب: قوة ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}% + شراء ≥ {MIN_BUY_DOMINANCE:.0f}%)\n"
                     f"⏰ {scan_time}",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"خطأ ارسال تقرير فارغ: {e}")
        logger.info("لا توجد عملات شراء قوي بعد الفلتر")
        return

    chunk_size = 10
    chunks = [top50[i:i+chunk_size] for i in range(0, len(top50), chunk_size)]

    for idx, chunk in enumerate(chunks, 1):
        lines = []
        if idx == 1:
            lines += [
                f"📊 أعلى Altcoin بسير شرائي قوي — 24 ساعة",
                f"⏰ {scan_time}",
                f"📡 المصدر: CMC + Gate.io | الفوليوم الشرائي فقط",
                f"🎯 الفلتر: قوة ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}% + شراء ≥ {MIN_BUY_DOMINANCE:.0f}%",
                f"✅ {len(top50)} عملة  |  💎 VIP: {vip_count}",
                f"💎 VIP = سيولة شراء مستمرة (3h+) + فوق VWAP",
                "━━━━━━━━━━━━━━━━━━━━", ""
            ]

        for i, c in enumerate(chunk, (idx-1)*chunk_size + 1):
            pc  = c["price_change_24h"]
            vc  = c["volume_change"]
            p1h = c["price_change_1h"]
            arrow = "🟢" if pc > 0 else "🔴"
            vip_badge = " 💎 VIP" if c.get("is_vip") else ""
            if vc >= 200:   vol_icon = "🔥🔥🔥"
            elif vc >= 100: vol_icon = "🔥🔥"
            elif vc >= 50:  vol_icon = "🔥"
            else:           vol_icon = "📈"

            lines.append(f"{i}. {arrow} {c['symbol']}{vip_badge} — {escape_md(c['name'])}")
            lines.append(f"   💵 {fmt_price(c['price'])}  ({pc:+.1f}%)  |  1h: {p1h:+.1f}%")
            lines.append(f"   💰 فوليم 24h: {fmt_vol(c['volume_24h'])}")
            lines.append(f"   {vol_icon} زيادة الفوليم: {vc:+.0f}%")
            # ===== قوة السير الشرائي + هيمنة الشراء =====
            flow = c.get("flow")
            if flow:
                label, _ = classify_flow_strength(flow["score"])
                lines.append(f"   📡 قوة سير الشراء: {flow['score']:.0f}%  {label}")
                lines.append(f"   🟢 هيمنة الشراء: {flow['buy_dominance']:.0f}% من إجمالي الفوليوم")
            else:
                lines.append(f"   📡 قوة سير الشراء: ❓ بيانات غير متاحة")
            lines.append(f"   🌐 {c['num_market_pairs']} منصة  |  CMC #{c['rank']}")
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


# ============================================================
# ✅ الوظيفة 2: فحص الإشارات — score >= 80 + شروط منظمة رأسياً
# ============================================================
async def check_signals(bot: Bot, target_chat: int = None):
    global previous_signals
    logger.info("فحص الإشارات التقنية المتطورة...")

    chat_target = target_chat if target_chat else int(ADMIN_CHAT_ID)

    async with aiohttp.ClientSession() as session:
        # ✅ v4.1 — جلب كل عملات Gate.io بدل CMC top 500
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
            if not cmc_raw: return
            candidates_raw = [parse_coin(c) for c in cmc_raw]

        # فلتر العملات المستبعدة (memes/stocks) + الفوليم الأدنى
        candidates = []
        for d in candidates_raw:
            symbol = d.get("symbol", "")
            name   = d.get("name", "")
            tags   = d.get("tags", [])
            if symbol in EXCLUDED_SYMBOLS: continue
            if is_meme_coin(symbol, name, tags): continue
            if d["volume_24h"] < MIN_VOL_FOR_SIGNAL: continue
            candidates.append(d)
        # سقف للأمان
        candidates = candidates[:GATE_MAX_CANDIDATES]
        logger.info(f"📋 سيتم فحص {len(candidates)} عملة")

        # ✅ v4.1 — semaphore لتحديد التوازي + تجنب rate limits
        sem = asyncio.Semaphore(GATE_PARALLEL_LIMIT)

        async def analyze(coin):
            async with sem:
                candles = await fetch_klines(session, coin["symbol"])
                if not candles or len(candles) < 25:
                    return None  # كلاينز غير كافية
                res     = score_coin(candles, coin)
                sc      = res["score"]
                details = res["details"]
                # ✅ لا يضيف إلا لو النقاط >= 80
                if sc < MIN_SCORE:
                    return None
                # ✅ v4.0 — لا يضيف إلا لو 2 من 3 محركات اجتازت
                if not details.get("confluence_passed", False):
                    return None
                rv = details.get("rvol", 1.0)
                if rv < MIN_RVOL: return None
                prev_pump = calc_prev_pump(candles)
                if prev_pump > MAX_PREV_PUMP:
                    logger.info(f"استبعاد {coin['symbol']} — pump سابق {prev_pump:.1f}%")
                    return None
                # ✅ v4.0 — احسب قوة السير + VIP status للإشارة
                flow = calc_volume_flow_strength(candles)
                is_vip, vip_checks = evaluate_vip_status(candles, flow)
                coin.update({"score": sc, "reasons": res["reasons"],
                             "details": details, "rvol": rv,
                             "flow": flow, "is_vip": is_vip, "vip_checks": vip_checks})
                return coin

        # ✅ v4.1 — تشغيل التحليل على كل العملات (مع semaphore داخلي)
        tasks   = [analyze(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    signals = [r for r in results if r and not isinstance(r, Exception)]

    fresh_signals = []
    for c in signals:
        sym = c["symbol"]
        if sym in seen_signals:
            elapsed = datetime.now() - seen_signals[sym]
            # ✅ v3.2: cooldown 6 ساعات بدل 24 (السكان أصبح مستمر)
            if elapsed.total_seconds() < SIGNAL_COOLDOWN_HOURS * 3600:
                logger.info(f"تخطي {sym} — إشارة مكررة (cooldown {SIGNAL_COOLDOWN_HOURS}h)")
                continue
        fresh_signals.append(c)

    signals = fresh_signals
    signals.sort(key=lambda x: x.get("score",0), reverse=True)

    if not signals:
        logger.info(f"لا توجد إشارات جديدة >= {MIN_SCORE} نقطة")
        return

    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # ✅ إشارة واحدة في كل رسالة (لأن الرسالة بقت طويلة بسبب الترتيب الرأسي)
    chunk_size = 1
    max_total = 10
    signals_to_send = signals[:max_total]

    # رسالة مقدمة
    intro = [
        f"🚨 تنبيه — {len(signals)} إشارة Pre-Pump (score >= {MIN_SCORE})",
        f"⏰ {scan_time}",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    try:
        await bot.send_message(chat_id=chat_target, text="\n".join(intro),
                               disable_web_page_preview=True)
        await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"خطأ ارسال intro: {e}")

    for c in signals_to_send:
        pc    = c["price_change_24h"]
        p1h   = c["price_change_1h"]
        vc    = c["volume_change"]
        sc    = c.get("score",0)
        rv    = c.get("rvol",1.0)
        dt    = c.get("details",{})
        conf  = dt.get("confluence", {})
        flow  = c.get("flow")
        is_vip = c.get("is_vip", False)
        arrow = "🟢" if pc > 0 else "🔴"
        vip_badge = " 💎 VIP" if is_vip else ""

        if sc >= 95:   strength = "🔥🔥🔥 ممتازة"
        elif sc >= 90: strength = "🔥🔥 قوية جداً"
        elif sc >= 85: strength = "🔥 قوية"
        else:          strength = "✨ جيدة (80+)"

        # ════════════ ✅ v4.0 — إشارة منظمة بالمحركات الثلاثة ════════════
        lines = []
        lines.append(f"{arrow} {c['symbol']}{vip_badge} — {escape_md(c['name'])}")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"💵 السعر: {fmt_price(c['price'])}  ({pc:+.1f}%)")
        lines.append(f"⏱ 1h: {p1h:+.2f}%  |  7d: {c['price_change_7d']:+.1f}%")
        lines.append(f"🎯 النقاط: {sc}/100  —  {strength}")
        engines = conf.get("engines_passed", 0)
        lines.append(f"⚙️  محركات الـ Confluence: {engines}/3 ✅")
        lines.append("")

        # ═══ المحركات الثلاثة (الجزء الأهم) ═══
        lines.append("🔥 محركات الإشارة:")
        # محرك 1 - Momentum
        mom = conf.get("momentum", {})
        mom_icon = "✅" if mom.get("pass") else "❌"
        lines.append(f"   {mom_icon} Momentum ({mom.get('score',0)}/3) — RSI+MACD+Stoch")
        if mom.get("rsi") is not None:
            lines.append(f"      └ RSI: {mom['rsi']}  |  Stoch K: {mom.get('stoch_k','—')}")
        # محرك 2 - Smart Money
        sm = conf.get("smart", {})
        sm_icon = "✅" if sm.get("pass") else "❌"
        lines.append(f"   {sm_icon} Smart Money ({sm.get('score',0)}/4) — CVD+OF+Wyckoff+SM")
        # محرك 3 - Breakout
        br = conf.get("breakout", {})
        br_icon = "✅" if br.get("pass") else "❌"
        lines.append(f"   {br_icon} Breakout ({br.get('score',0)}/4) — Squeeze+Surge+MA+HL")
        lines.append("")

        # ═══ السيولة الشرائية ═══
        lines.append("📊 السيولة الشرائية:")
        lines.append(f"   • RVOL: {rv:.2f}x")
        lines.append(f"   • فوليم 24h: {fmt_vol(c['volume_24h'])}")
        lines.append(f"   • زيادة الفوليم: {vc:+.0f}%")
        if flow:
            label, _ = classify_flow_strength(flow["score"])
            lines.append(f"   • قوة سير الشراء: {flow['score']:.0f}%  {label}")
            lines.append(f"   • هيمنة الشراء: {flow['buy_dominance']:.0f}%")
        if dt.get("vol_surge"):
            lines.append(f"   • قفزة فوليم: {dt.get('surge_ratio',0):.1f}x ⚡")
        lines.append("")

        # ═══ علامة VIP (لو متاحة) ═══
        if is_vip:
            lines.append("💎 معايير VIP المُحققة:")
            for name, ok in c.get("vip_checks", []):
                lines.append(f"   ✅ {name}")
            lines.append("")

        # ═══ معلومات السوق ═══
        lines.append("ℹ️ معلومات السوق:")
        lines.append(f"   • عدد المنصات: {c['num_market_pairs']}")
        lines.append(f"   • CMC Rank: #{c['rank']}")
        lines.append("")
        lines.append(f"🔗 https://www.tradingview.com/chart/?symbol=GATEIO:{c['symbol']}_USDT")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"💡 /coin {c['symbol']} للتحليل الشامل")
        lines.append(f"📊 /check {c['symbol']} لتقييم القوة")

        try:
            await bot.send_message(
                chat_id=chat_target,
                text="\n".join(lines),
                disable_web_page_preview=True
            )
            await asyncio.sleep(0.7)
        except Exception as e:
            logger.error(f"خطأ ارسال إشارة: {e}")

    # رسالة الختام
    try:
        await bot.send_message(
            chat_id=chat_target,
            text="📡 CMC + Gate.io | بوت Pre-Pump v3",
            disable_web_page_preview=True
        )
    except: pass

    for c in signals:
        seen_signals[c["symbol"]] = datetime.now()
    previous_signals = {c["symbol"]: c for c in signals}
    logger.info(f"تم إرسال {len(signals_to_send)} إشارة")


# ============================================================
# نظام seen coins
# ============================================================
SEEN_FILE  = "seen_coins.json"

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
    src = "كل عملات Gate.io" if USE_FULL_GATE_SCAN else f"أعلى {CMC_LIMIT} في CMC"
    await update.message.reply_text(
        "🚀 Altcoin Smart Scanner Bot v4.1\n"
        "    — Full Gate.io + Confluence —\n\n"
        "✨ الجديد في v4.1:\n"
        f"• 🌐 الفحص يشمل {src}\n"
        f"• ~1500-2500 عملة بدل 500\n"
        f"• فلتر أولي: فوليوم ≥ ${GATE_MIN_VOLUME_USD/1000:.0f}K\n"
        f"• {GATE_PARALLEL_LIMIT} طلبات متوازية\n\n"
        "⚙️ 3 محركات Confluence (≥ 2/3):\n"
        "   • Momentum (RSI+MACD+Stoch)\n"
        "   • Smart Money (CVD+OF+Wyckoff+SM)\n"
        "   • Breakout (Squeeze+Surge+MA+HL)\n\n"
        "🔄 سكان البامب: مستمر بلا توقف\n"
        f"   فاصل {SIGNAL_LOOP_GAP_SECONDS}ث | حد ≥ {MIN_SCORE}\n\n"
        "📊 تقرير الفوليوم:\n"
        f"   كل {SCAN_INTERVAL_MINUTES//60} ساعات\n"
        f"   شراء فقط + قوة ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}% + شراء ≥ {MIN_BUY_DOMINANCE:.0f}%\n"
        "   💎 VIP يُرتّب أولاً\n\n"
        "الأوامر:\n"
        "/report  — تقرير فوري للسير الشرائي\n"
        "/scan    — فحص الإشارات الآن\n"
        "/coin SYMBOL  — تحليل شامل احترافي\n"
        "/check SYMBOL — تقييم سريع (قوة/تحليل/سيولة/سرعة)\n"
        "/info SYMBOL  — توكنوميكس\n"
        "/vol SYMBOL   — حجم تداول\n"
        "/top     — أفضل 5 إشارات\n"
        "/status  — حالة البوت\n"
        "/chatid  — معرفة الـ Chat ID"
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
        f"✅ Altcoin Bot — v4.1 Full Gate.io\n\n"
        f"🌐 مصدر العملات:\n"
        f"   {'كل Gate.io USDT (~1500-2500)' if USE_FULL_GATE_SCAN else f'CMC top {CMC_LIMIT}'}\n"
        f"   فلتر أولي: فوليم ≥ ${GATE_MIN_VOLUME_USD/1000:.0f}K\n"
        f"   توازي: {GATE_PARALLEL_LIMIT} طلب\n\n"
        f"📊 تقرير الفوليوم:\n"
        f"   كل {SCAN_INTERVAL_MINUTES//60} ساعات\n"
        f"   شراء ≥ {MIN_BUY_DOMINANCE:.0f}% + قوة ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}%\n"
        f"   💎 VIP يُرتّب أولاً\n\n"
        f"🔍 سكان البامب: {scanner_status}\n"
        f"   فاصل: {SIGNAL_LOOP_GAP_SECONDS}ث\n"
        f"   آخر دورة: {last_str}\n"
        f"   حد الإشارة: ≥ {MIN_SCORE}\n"
        f"   محركات Confluence: ≥ {CONFLUENCE_ENGINES_REQ}/3\n"
        f"   Cooldown: {SIGNAL_COOLDOWN_HOURS}h\n\n"
        f"⚙️ 3 محركات Confluence:\n"
        f"   • Momentum: RSI+MACD+Stoch (3/3)\n"
        f"   • Smart Money: CVD+OF+Wyckoff+SM (3/4)\n"
        f"   • Breakout: Squeeze+Surge+MA+HL (3/4)\n\n"
        f"📡 Gate.io + CMC (1h + 4h)\n"
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
                "🟢 *البوت بدأ التشغيل*\n"
                f"🔄 السكان المستمر: شغال (فاصل {SIGNAL_LOOP_GAP_SECONDS}ث)\n"
                f"📊 تقرير الفوليوم: كل {SCAN_INTERVAL_MINUTES//60} ساعات\n"
                f"🎯 الفلتر: شراء ≥ {MIN_BUY_DOMINANCE:.0f}% + قوة ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}%"
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
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("scan",    cmd_scan))
    app.add_handler(CommandHandler("vol",     cmd_vol))
    app.add_handler(CommandHandler("info",    cmd_info))
    app.add_handler(CommandHandler("coin",    cmd_coin))
    app.add_handler(CommandHandler("check",   cmd_check))   # ✅ v4.0
    app.add_handler(CommandHandler("top",     cmd_top))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("chatid",  cmd_chatid))

    load_seen_coins()

    # ✅ التأكد من إضافة الـ jobs مرة واحدة فقط
    jq = app.job_queue
    # إزالة أي jobs قديمة بنفس الاسم (احتياط)
    for j in list(jq.jobs()):
        try: j.schedule_removal()
        except: pass

    # ✅ تقرير الفوليوم فقط يبقى مجدولاً — السكان أصبح مستمراً عبر post_init
    jq.run_repeating(
        job_volume_report,
        interval=SCAN_INTERVAL_MINUTES*60,
        first=30,
        name="volume_report_job"
    )

    print("="*60)
    print("🚀 Altcoin Smart Scanner Bot v4.1 - Full Gate.io")
    src = "كل Gate.io USDT" if USE_FULL_GATE_SCAN else f"CMC top {CMC_LIMIT}"
    print(f"🌐 المصدر: {src}")
    print(f"   فلتر أولي: فوليم ≥ ${GATE_MIN_VOLUME_USD/1000:.0f}K")
    print(f"   توازي: {GATE_PARALLEL_LIMIT} طلب")
    print(f"📊 تقرير الفوليوم كل {SCAN_INTERVAL_MINUTES//60} ساعات (شرائي فقط)")
    print(f"   الفلتر: قوة ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}% + شراء ≥ {MIN_BUY_DOMINANCE:.0f}%")
    print(f"   💎 VIP يُرتّب أولاً")
    print(f"🔄 سكان البامب: مستمر (فاصل {SIGNAL_LOOP_GAP_SECONDS}ث)")
    print(f"   حد الإشارة: score >= {MIN_SCORE}")
    print(f"   محركات Confluence: >= {CONFLUENCE_ENGINES_REQ}/3")
    print(f"⚙️  3 محركات: Momentum + Smart Money + Breakout")
    print(f"📋 /coin = تحليل شامل  |  /check = تقييم سريع")
    print(f"🔒 Lock نشط ضد الإرسال المزدوج")
    print("="*60)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
