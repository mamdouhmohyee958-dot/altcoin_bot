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
SIGNAL_LOOP_GAP_SECONDS = 90      # فاصل بين دورات السكان المستمر
SIGNAL_LOOP_ERR_GAP     = 30      # فاصل بعد خطأ
# ✅ جديد v3.1: فلتر تقرير الفوليوم
MIN_FLOW_SCORE_FOR_REPORT = 70.0  # يبعث القوي والقوي جداً فقط (>=70%)

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
    final_score = min(int(sc * 100 / 130), 100)
    return {"score": final_score, "raw_score": sc, "reasons": rs, "details": dt}


# ==================== قوة سير الفوليوم (Volume Flow Strength) ====================
# معيار مرجّح: لحظي (40%) + اتجاه (35%) + تسارع (25%)
def calc_volume_flow_strength(candles):
    """
    حساب قوة سير الفوليوم كنسبة مئوية 0-100+ من 3 مكونات:
    - لحظي: RVOL آخر ساعة vs متوسط 24 ساعة
    - اتجاه: ميل خط انحدار الفوليوم على آخر 12 ساعة
    - تسارع: مقارنة آخر 4 ساعات بالـ 20 ساعة قبلها
    """
    if not candles or len(candles) < 24:
        return None  # بيانات غير كافية

    vols = [c["volume"] for c in candles]
    n    = len(vols)

    # --- 1) لحظي: RVOL آخر ساعة (40%) ---
    last_hour = vols[-1]
    avg_24h   = sum(vols[-24:-1]) / 23 if n >= 24 else (sum(vols[:-1]) / max(1, n-1))
    inst_ratio = (last_hour / avg_24h) if avg_24h > 0 else 1.0
    # تحويل لنسبة 0-100: 1x=50%, 2x=100%, 3x+=150% (مع سقف)
    inst_score = min(150.0, max(0.0, (inst_ratio - 0.2) * 62.5))  # 0.2x=0, 1.0x=50, 2.0x=112.5

    # --- 2) اتجاه: ميل الانحدار على آخر 12 ساعة (35%) ---
    window = vols[-12:] if n >= 12 else vols
    m      = len(window)
    if m >= 3 and sum(window) > 0:
        avg_w  = sum(window) / m
        # ميل بسيط: (sum(i*v) - sum(i)*avg) / (sum(i²) - n*mean(i)²)
        mean_i = (m - 1) / 2
        num    = sum((i - mean_i) * (v - avg_w) for i, v in enumerate(window))
        den    = sum((i - mean_i) ** 2 for i in range(m))
        slope  = num / den if den > 0 else 0
        # تطبيع: الميل كنسبة من المتوسط × 100
        slope_pct = (slope / avg_w * 100) if avg_w > 0 else 0
        # ميل +10% لكل ساعة = اتجاه قوي جداً = 100
        trend_score = min(150.0, max(0.0, 50 + slope_pct * 5))
    else:
        trend_score = 50.0

    # --- 3) تسارع: آخر 4 ساعات vs الـ 20 ساعة قبلها (25%) ---
    if n >= 24:
        recent_4  = sum(vols[-4:]) / 4
        older_20  = sum(vols[-24:-4]) / 20
        accel_ratio = (recent_4 / older_20) if older_20 > 0 else 1.0
    elif n >= 8:
        half       = n // 2
        recent_h   = sum(vols[-half:]) / half
        older_h    = sum(vols[:-half]) / max(1, n - half)
        accel_ratio = (recent_h / older_h) if older_h > 0 else 1.0
    else:
        accel_ratio = 1.0
    # 1x=50, 2x=100, 3x+=150
    accel_score = min(150.0, max(0.0, (accel_ratio - 0.2) * 62.5))

    # --- المجموع المرجّح ---
    final = (inst_score * 0.40) + (trend_score * 0.35) + (accel_score * 0.25)

    return {
        "score":       round(final, 1),
        "instant":     round(inst_score, 1),
        "trend":       round(trend_score, 1),
        "accel":       round(accel_score, 1),
        "inst_ratio":  round(inst_ratio, 2),
        "accel_ratio": round(accel_ratio, 2),
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
        raw = await fetch_cmc(session, limit=CMC_LIMIT)

    if not raw:
        await bot.send_message(chat_id=chat_target, text="فشل جلب البيانات من CMC")
        return

    coins = []
    for c in raw:
        symbol = c.get("symbol","")
        name   = c.get("name","")
        tags   = [t.lower() for t in c.get("tags",[])]
        if symbol in EXCLUDED_SYMBOLS: continue
        if is_meme_coin(symbol, name, tags): continue
        if is_stock_token(symbol, name, tags): continue
        d = parse_coin(c)
        if d["volume_24h"]    < MIN_VOLUME_REPORT:          continue
        if d["volume_change"] < MIN_VOL_CHANGE_FOR_REPORT:  continue
        if is_dead_coin(d): continue
        coins.append(d)

    coins.sort(key=lambda x: x["volume_change"], reverse=True)

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
                coin["flow"] = calc_volume_flow_strength(kl)
            except Exception:
                coin["flow"] = None
            return coin
        # توازي بسقف معقول
        sem = asyncio.Semaphore(10)
        async def _with_sem(c):
            async with sem:
                return await _fetch_flow(c)
        await asyncio.gather(*[_with_sem(c) for c in top50], return_exceptions=True)

    # ✅ جديد v3.1: استبعاد العملات ذات قوة السير الضعيف/الضعيف جداً
    # نُبقي فقط: قوي (≥70) و قوي جداً (≥90)، ونستبعد ما دون 70 وما هو غير متاح
    before_filter = len(top50)
    top50 = [c for c in top50 if c.get("flow") and c["flow"].get("score", 0) >= MIN_FLOW_SCORE_FOR_REPORT]
    # إعادة ترتيب: حسب قوة السير أولاً، ثم زيادة الفوليوم
    top50.sort(key=lambda x: (x["flow"]["score"], x["volume_change"]), reverse=True)
    logger.info(f"فلتر قوة السير: {before_filter} → {len(top50)} عملة (≥{MIN_FLOW_SCORE_FOR_REPORT}%)")

    if not top50:
        try:
            await bot.send_message(
                chat_id=chat_target,
                text=f"📊 لا توجد عملات بقوة سير ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}% حالياً\n⏰ {scan_time}",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"خطأ ارسال تقرير فارغ: {e}")
        logger.info("لا توجد عملات قوية بعد الفلتر")
        return

    chunk_size = 10
    chunks = [top50[i:i+chunk_size] for i in range(0, len(top50), chunk_size)]

    for idx, chunk in enumerate(chunks, 1):
        lines = []
        if idx == 1:
            lines += [
                f"📊 أعلى Altcoin بقوة سير ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}% — 24 ساعة",
                f"⏰ {scan_time}",
                f"📡 المصدر: CMC + Gate.io | مرتب بقوة السير ثم زيادة الفوليم",
                f"✅ {len(top50)} عملة قوية / قوية جداً",
                "━━━━━━━━━━━━━━━━━━━━", ""
            ]

        for i, c in enumerate(chunk, (idx-1)*chunk_size + 1):
            pc  = c["price_change_24h"]
            vc  = c["volume_change"]
            p1h = c["price_change_1h"]
            arrow = "🟢" if pc > 0 else "🔴"
            if vc >= 200:   vol_icon = "🔥🔥🔥"
            elif vc >= 100: vol_icon = "🔥🔥"
            elif vc >= 50:  vol_icon = "🔥"
            else:           vol_icon = "📈"

            lines.append(f"{i}. {arrow} {c['symbol']} — {escape_md(c['name'])}")
            lines.append(f"   💵 {fmt_price(c['price'])}  ({pc:+.1f}%)  |  1h: {p1h:+.1f}%")
            lines.append(f"   💰 فوليم 24h: {fmt_vol(c['volume_24h'])}")
            lines.append(f"   {vol_icon} زيادة الفوليم: {vc:+.0f}%")
            # ===== قوة سير الفوليوم (مرجّح: لحظي + اتجاه + تسارع) =====
            flow = c.get("flow")
            if flow:
                label, _ = classify_flow_strength(flow["score"])
                lines.append(f"   📡 قوة السير: {flow['score']:.0f}%  {label}")
            else:
                lines.append(f"   📡 قوة السير: ❓ بيانات غير متاحة")
            lines.append(f"   🌐 {c['num_market_pairs']} منصة  |  CMC #{c['rank']}")
            lines.append("")

        if idx == len(chunks):
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("💡 /coin SYMBOL — تحليل كامل")
            lines.append("💡 /vol SYMBOL  — حجم عملة")

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
        raw = await fetch_cmc(session, limit=CMC_LIMIT)
        if not raw: return

        candidates = []
        for c in raw:
            symbol = c.get("symbol","")
            name   = c.get("name","")
            tags   = [t.lower() for t in c.get("tags",[])]
            if symbol in EXCLUDED_SYMBOLS: continue
            if is_meme_coin(symbol, name, tags): continue
            d = parse_coin(c)
            if d["volume_24h"] < MIN_VOL_FOR_SIGNAL: continue
            candidates.append(d)

        async def analyze(coin):
            candles = await fetch_klines(session, coin["symbol"])
            res     = score_coin(candles, coin)
            sc      = res["score"]
            # ✅ لا يضيف إلا لو النقاط >= 80
            if sc < MIN_SCORE: return None
            rv = res["details"].get("rvol", 1.0)
            if len(candles) <= 5:
                vc = coin.get("volume_change", 0)
                if vc < 50: return None
            else:
                if rv < MIN_RVOL: return None
            if candles and len(candles) >= 3:
                prev_pump = calc_prev_pump(candles)
                if prev_pump > MAX_PREV_PUMP:
                    logger.info(f"استبعاد {coin['symbol']} — pump سابق {prev_pump:.1f}%")
                    return None
            coin.update({"score": sc, "reasons": res["reasons"],
                         "details": res["details"], "rvol": rv})
            return coin

        tasks   = [analyze(c) for c in candidates[:80]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    signals = [r for r in results if r and not isinstance(r, Exception)]

    fresh_signals = []
    for c in signals:
        sym = c["symbol"]
        if sym in seen_signals:
            elapsed = datetime.now() - seen_signals[sym]
            if elapsed.total_seconds() < 86400:
                logger.info(f"تخطي {sym} — إشارة مكررة")
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
        arrow = "🟢" if pc > 0 else "🔴"

        if sc >= 95:   strength = "🔥🔥🔥 ممتازة"
        elif sc >= 90: strength = "🔥🔥 قوية جداً"
        elif sc >= 85: strength = "🔥 قوية"
        else:          strength = "✨ جيدة (80+)"

        # ════════════ ✅ ترتيب الشروط رأسياً تحت بعض ════════════
        lines = []
        lines.append(f"{arrow} {c['symbol']} — {escape_md(c['name'])}")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"💵 السعر: {fmt_price(c['price'])}  ({pc:+.1f}%)")
        lines.append(f"⏱ 1h: {p1h:+.2f}%  |  7d: {c['price_change_7d']:+.1f}%")
        lines.append(f"🎯 النقاط: {sc}/100  —  {strength}")
        lines.append("")
        lines.append("📊 بيانات السيولة:")
        lines.append(f"   • RVOL: {rv:.2f}x")
        lines.append(f"   • فوليم 24h: {fmt_vol(c['volume_24h'])}")
        lines.append(f"   • زيادة الفوليم: {vc:+.0f}%")
        if dt.get("vol_surge"):
            lines.append(f"   • قفزة فوليم: {dt.get('surge_ratio',0):.1f}x ⚡")
        lines.append("")

        # ✅ المؤشرات المتطورة - كل واحدة في سطر منفصل
        lines.append("🔬 المؤشرات المتطورة:")
        advanced_count = 0
        if dt.get("rsi_div"):
            lines.append("   ✅ تباعد RSI إيجابي (Bullish Divergence)")
            advanced_count += 1
        if dt.get("cvd_pos"):
            lines.append("   ✅ CVD صاعد - تجميع شراء")
            advanced_count += 1
        if dt.get("order_flow"):
            bp = dt.get("buy_pressure", 0) * 100
            lines.append(f"   ✅ ضغط شراء {bp:.0f}% (Order Flow)")
            advanced_count += 1
        if dt.get("wyckoff"):
            lines.append("   ✅ نمط Wyckoff Accumulation 🏗️")
            advanced_count += 1
        if dt.get("smart_money"):
            lines.append("   ✅ بصمة Smart Money 💎")
            advanced_count += 1
        if dt.get("liq_grab"):
            lines.append("   ✅ Liquidity Grab + ارتداد")
            advanced_count += 1
        if dt.get("ema_cross"):
            lines.append("   ✅ EMA 9/21 Bullish Cross")
            advanced_count += 1

        if advanced_count == 0:
            lines.append("   لا توجد مؤشرات متطورة مفعّلة")
        lines.append("")

        # ✅ Price Action - كل واحدة في سطر منفصل
        lines.append("📈 Price Action:")
        pa_count = 0
        if dt.get("squeeze"):
            lines.append(f"   • Bollinger Squeeze ({dt.get('bb_width', 0):.1f}%) 🎯")
            pa_count += 1
        elif dt.get("bb_width", 999) < 8:
            lines.append(f"   • Bollinger ضيق ({dt.get('bb_width', 0):.1f}%)")
            pa_count += 1
        if dt.get("breakout"):
            lines.append("   • اختراق مقاومة (Breakout)")
            pa_count += 1
        if dt.get("absorption"):
            lines.append("   • امتصاص بيع")
            pa_count += 1
        if dt.get("higher_lows"):
            lines.append("   • Higher Lows صاعد")
            pa_count += 1
        if dt.get("above_ma"):
            lines.append("   • سعر فوق MA20")
            pa_count += 1
        if dt.get("vwap_cross"):
            lines.append("   • اختراق VWAP")
            pa_count += 1
        if dt.get("dec_sell"):
            lines.append("   • ضغط بيع ينخفض")
            pa_count += 1
        if dt.get("candle_grow"):
            lines.append("   • شموع شراء تتضخم")
            pa_count += 1
        if dt.get("sideways"):
            lines.append("   • نطاق Sideways")
            pa_count += 1

        if pa_count == 0:
            lines.append("   لا توجد إشارات Price Action")
        lines.append("")

        lines.append("ℹ️ معلومات السوق:")
        lines.append(f"   • عدد المنصات: {c['num_market_pairs']}")
        lines.append(f"   • CMC Rank: #{c['rank']}")
        lines.append("")
        lines.append(f"🔗 https://www.tradingview.com/chart/?symbol=GATEIO:{c['symbol']}_USDT")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

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
    symbol = symbol.upper().strip()
    async with aiohttp.ClientSession() as session:
        coin = await fetch_cmc_single(session, symbol)
        if not coin:
            return f"العملة {symbol} مش موجودة في CMC"
        d       = parse_coin(coin)
        candles = await fetch_klines(session, symbol, limit=48)

        arrow = "🟢" if d["price_change_24h"] > 0 else "🔴"
        lines = [
            f"🔍 تحليل {symbol} — {escape_md(d['name'])}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"{arrow} السعر: {fmt_price(d['price'])}  ({d['price_change_24h']:+.2f}%)",
            f"⏱ 1h: {d['price_change_1h']:+.2f}%  |  7d: {d['price_change_7d']:+.1f}%",
            f"",
            f"💰 حجم التداول 24h: {fmt_vol(d['volume_24h'])}  ({d['volume_change']:+.0f}%)",
            f"🌐 المنصات: {d['num_market_pairs']}  |  Market Cap: {fmt_vol(d['market_cap'])}",
            f"📊 رانك CMC: #{d['rank']}",
            f"",
        ]
        if candles and len(candles) >= 10:
            res = score_coin(candles, d)
            sc  = res["score"]
            rs  = res["reasons"]
            dt  = res["details"]

            lines.append(f"🎯 نقاط الإشارة: {sc}/100")
            if sc >= MIN_SCORE:
                lines.append(f"   🚀 إشارة قوية! (>= {MIN_SCORE})")
            else:
                lines.append(f"   😴 لا إشارة بعد (< {MIN_SCORE})")
            lines.append("")

            lines.append("📈 المؤشرات الأساسية:")
            lines.append(f"   • RVOL: {dt['rvol']:.2f}x  {'✅' if dt['rvol']>=MIN_RVOL else '⚠️'}")
            lines.append(f"   • قفزة فوليم: {'✅ ' + str(round(dt['surge_ratio'],1)) + 'x' if dt['vol_surge'] else '❌'}")
            lines.append(f"   • Bollinger: {dt['bb_width']:.1f}%  {'🔴 Squeeze!' if dt['squeeze'] else ''}")
            lines.append(f"   • Breakout: {'✅' if dt['breakout'] else '❌'}")
            lines.append(f"   • Higher Lows: {'✅' if dt['higher_lows'] else '❌'}")
            lines.append(f"   • فوق MA20: {'✅' if dt['above_ma'] else '❌'}")
            lines.append("")

            lines.append("🔬 المؤشرات المتطورة:")
            lines.append(f"   • RSI Divergence: {'✅ إيجابي' if dt['rsi_div'] else '❌'}")
            lines.append(f"   • CVD (ضغط الشراء): {'✅ صاعد' if dt['cvd_pos'] else '❌'}")
            lines.append(f"   • Order Flow: {'✅ ' + str(int(dt['buy_pressure']*100)) + '%' if dt['order_flow'] else '❌'}")
            lines.append(f"   • Wyckoff Accumulation: {'✅' if dt['wyckoff'] else '❌'}")
            lines.append(f"   • Smart Money: {'✅' if dt['smart_money'] else '❌'}")
            lines.append(f"   • Liquidity Grab: {'✅' if dt['liq_grab'] else '❌'}")
            lines.append(f"   • EMA 9/21 Cross: {'✅' if dt['ema_cross'] else '❌'}")
            lines.append(f"   • VWAP Cross: {'✅' if dt['vwap_cross'] else '❌'}")
            lines.append("")

            if rs:
                lines.append("✨ الإيجابيات المكتشفة:")
                for r in rs[:10]:
                    lines.append(f"   • {r}")

        lines += [
            f"",
            f"🔗 https://www.tradingview.com/chart/?symbol=GATEIO:{symbol}_USDT",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
    logger.info(f"🔄 بدء السكان المستمر — فاصل {SIGNAL_LOOP_GAP_SECONDS}ث بين الدورات")
    # ننتظر قليلاً عند البدء حتى يجهز البوت
    await asyncio.sleep(60)

    while True:
        try:
            # نتجنب التشغيل المتزامن لو حد عمل /scan في نفس اللحظة
            if job_locks["check_signals"].locked():
                logger.info("⏸  السكان المستمر — منتظر انتهاء فحص يدوي")
                await asyncio.sleep(SIGNAL_LOOP_GAP_SECONDS)
                continue

            async with job_locks["check_signals"]:
                last_job_run["check_signals"] = datetime.now()
                logger.info("🔍 دورة سكان مستمرة...")
                await check_signals(bot)

            await asyncio.sleep(SIGNAL_LOOP_GAP_SECONDS)

        except asyncio.CancelledError:
            logger.info("🛑 السكان المستمر — تم الإيقاف")
            raise
        except Exception as e:
            logger.error(f"❌ خطأ في السكان المستمر: {e}")
            await asyncio.sleep(SIGNAL_LOOP_ERR_GAP)


# ==================== أوامر البوت ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Altcoin Smart Scanner Bot v3.1\n\n"
        "✨ الجديد في v3.1:\n"
        "• 🔄 سكان البامب مستمر بلا توقف\n"
        "• 📡 تقرير الفوليوم: قوي وقوي جداً فقط (≥70%)\n"
        "• مؤشرات متطورة (RSI Div, CVD, Wyckoff, Smart Money)\n"
        "• الحد الأدنى للإشارة: 80/100\n\n"
        "التشغيل التلقائي:\n"
        f"📊 تقرير الفوليوم كل {SCAN_INTERVAL_MINUTES//60} ساعات\n"
        f"🔄 سكان Pre-Pump مستمر (فاصل {SIGNAL_LOOP_GAP_SECONDS}ث)\n\n"
        "الأوامر:\n"
        "/report  — تقرير فوري لقوة السير\n"
        "/scan    — فحص الإشارات الآن\n"
        "/info ETH — توكنوميكس\n"
        "/vol ETH — حجم تداول\n"
        "/coin ETH — تحليل كامل بكل المؤشرات\n"
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
    await update.message.reply_text(f"🔍 جاري تحليل {context.args[0].upper()}...")
    result = await get_coin_analysis(context.args[0])
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
    scanner_status = "🔄 شغال مستمر" if (scanner and not scanner.done()) else "⛔ متوقف"
    last = last_job_run.get("check_signals")
    last_str = last.strftime("%H:%M:%S") if last else "لم يبدأ بعد"
    await update.message.reply_text(
        f"✅ البوت شغال — v3.1\n"
        f"📊 تقرير الفوليوم كل {SCAN_INTERVAL_MINUTES//60} ساعات\n"
        f"   فلتر قوة السير: ≥ {MIN_FLOW_SCORE_FOR_REPORT:.0f}%\n"
        f"🔍 سكان البامب: {scanner_status}\n"
        f"   فاصل بين الدورات: {SIGNAL_LOOP_GAP_SECONDS}ث\n"
        f"   آخر دورة: {last_str}\n"
        f"   حد الإشارة: score ≥ {MIN_SCORE}\n"
        f"🔬 17 مؤشر متطور\n"
        f"📡 CMC + Gate.io\n"
        f"🔔 الإرسال: الأدمن فقط (مع lock ضد الإرسال المزدوج)"
    )

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID:\n{update.effective_chat.id}")


# ✅ post_init hook لبدء السكان المستمر في الخلفية بعد جاهزية البوت
async def _post_init(app: Application):
    # نشغل السكان المستمر كـ background task
    app.bot_data["scanner_task"] = asyncio.create_task(
        continuous_signal_scanner(app.bot)
    )
    logger.info("✅ تم تشغيل السكان المستمر في الخلفية")


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
    print("🚀 Altcoin Smart Scanner Bot v3.1 - Continuous Edition")
    print(f"📊 تقرير زيادة السيولة كل {SCAN_INTERVAL_MINUTES} دقيقة")
    print(f"   فلتر قوة السير: >= {MIN_FLOW_SCORE_FOR_REPORT:.0f}% (قوي/قوي جداً فقط)")
    print(f"🔄 سكان البامب: مستمر بلا توقف (فاصل {SIGNAL_LOOP_GAP_SECONDS}ث)")
    print(f"   حد الإشارة: score >= {MIN_SCORE}")
    print(f"🔬 17 مؤشر تقني متطور")
    print(f"🔒 Lock نشط ضد الإرسال المزدوج")
    print(f"🔔 الإرسال: الأدمن فقط")
    print("="*60)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
