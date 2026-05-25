"""
🚀 Altcoin Smart Scanner Bot - Ultimate Edition v2
التغييرات:
1. التقرير: أعلى 50 عملة زادت سيولتها في 24 ساعة (volume_change %) مش مجرد أعلى فوليم
2. إلغاء الإرسال المزدوج — البوت يبعت للأدمن فقط
3. فلتر البامب: شروط إضافية + لا يبعت إلا لو النقاط >= 75
"""

import asyncio
import aiohttp
import logging
import sys
import math
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==================== الاعدادات ====================
TELEGRAM_TOKEN = "8794878965:AAEZR3MdSG-3OiGBeR05q9MJzvvo1ODmNmc"
ADMIN_CHAT_ID  = "6914157653"
CMC_API_KEY    = "7eeaf1fd132e416ab49279ee21cc6ce0"

# ==================== اعدادات التقرير الدوري ====================
SCAN_INTERVAL_MINUTES = 240   # كل 4 ساعات
TOP_DISPLAY           = 50    # اعلى 50 عملة
CMC_LIMIT             = 500   # نجيب اول 500 من CMC

# ==================== اعدادات الاشارات ====================
MIN_SCORE          = 75       # الحد الادنى للاشارة — لا يبعت إلا فوق 75
MIN_RVOL           = 2.5      # RVOL > 2.5
MAX_PREV_PUMP      = 12.0     # استبعاد pump سابق > 12%
MIN_VOL_FOR_SIGNAL = 2_000_000

# ==================== اعدادات الفلترة ====================
MAX_MARKET_CAP     = 2_000_000_000
MIN_VOLUME_REPORT  = 5_000_000
# الحد الأدنى لتغيير الفوليم في 24 ساعة للتقرير
MIN_VOL_CHANGE_FOR_REPORT = 20.0   # زيادة الفوليم 20% على الأقل في 24h

# ==================== نظام النقاط الموسع ====================
SCORE_RVOL         = 20
SCORE_SQUEEZE      = 20
SCORE_BREAKOUT     = 15
SCORE_ABSORPTION   = 10
SCORE_MOMENTUM     = 10
SCORE_VOL_SURGE    = 15   # قفزة فوليم مفاجئة
SCORE_MULTI_FRAME  = 10   # تأكيد على أكثر من فريم

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
trending_cache:   dict = {}

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
MIN_VOLUME_RATIO     = 0.1

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


# ==================== ادوات ====================
def is_coin_cooldown(symbol: str) -> bool:
    if symbol not in seen_coins:
        return False
    elapsed = (datetime.now() - seen_coins[symbol]).total_seconds()
    return elapsed < 86400

def mark_coin_seen(symbol: str):
    seen_coins[symbol] = datetime.now()


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


# ==================== حسابات تقنية ====================
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

def calc_momentum(c):
    if len(c) < 5: return {"green": 0, "fast": False}
    g  = sum(1 for x in c[-3:] if x["close"] > x["open"])
    r  = [abs(x["close"]-x["open"])/x["open"]*100 for x in c[-3:] if x["open"]>0]
    n  = [abs(x["close"]-x["open"])/x["open"]*100 for x in c[:-3]  if x["open"]>0]
    ar = sum(r)/len(r) if r else 0
    an = sum(n)/len(n) if n else 1
    return {"green": g, "fast": ar > an*2}

def calc_vol_trend(c):
    if len(c) < 5: return False
    v = [x["volume"] for x in c[-5:]]
    return sum(1 for i in range(1,len(v)) if v[i]>v[i-1]) >= 3

def calc_prev_pump(c):
    if len(c) < 3: return 0.0
    return max((c[i]["close"]-c[i-1]["close"])/c[i-1]["close"]*100
               for i in range(1,min(20,len(c))))

def calc_vol_surge(c):
    """هل في قفزة فوليم مفاجئة في الكاندل الأخير مقارنة بمتوسط الـ 10 الأخيرة؟"""
    if len(c) < 10: return False, 0.0
    avg_vol = sum(x["volume"] for x in c[-11:-1]) / 10
    last_vol = c[-1]["volume"]
    ratio = last_vol / avg_vol if avg_vol > 0 else 0
    return ratio >= 3.0, ratio  # قفزة أكبر من 3x المتوسط

def calc_higher_lows(c, periods=6):
    """تحقق من Higher Lows (أدنى نقاط صاعدة) — مؤشر على الاتجاه الصاعد"""
    if len(c) < periods: return False
    lows = [x["low"] for x in c[-periods:]]
    return all(lows[i] >= lows[i-1] for i in range(1, len(lows)))

def calc_price_above_ma(c, period=20):
    """السعر فوق المتوسط المتحرك — مؤشر قوي على الزخم"""
    if len(c) < period: return False
    ma = sum(x["close"] for x in c[-period:]) / period
    return c[-1]["close"] > ma

def calc_decreasing_sell_pressure(c):
    """ضغط البيع ينخفض — الشموع الحمراء بتقل"""
    if len(c) < 8: return False
    first_half_red  = sum(1 for x in c[-8:-4] if x["close"] < x["open"])
    second_half_red = sum(1 for x in c[-4:]   if x["close"] < x["open"])
    return second_half_red < first_half_red

def calc_candle_size_increase(c):
    """حجم الشموع الخضرا بيكبر — الزخم الشرائي بيقوى"""
    if len(c) < 6: return False
    green = [abs(x["close"]-x["open"]) for x in c[-6:] if x["close"] > x["open"]]
    if len(green) < 3: return False
    return green[-1] > green[0] * 1.2

def calc_vwap_cross(c):
    """السعر اخترق فوق VWAP — إشارة قوة"""
    if len(c) < 10: return False
    total_vol = sum(x["volume"] for x in c[-10:])
    if total_vol == 0: return False
    vwap = sum(((x["high"]+x["low"]+x["close"])/3) * x["volume"]
               for x in c[-10:]) / total_vol
    prev_below = c[-2]["close"] < vwap
    curr_above = c[-1]["close"] > vwap
    return prev_below and curr_above


# ==================== نظام النقاط الموسع ====================
def score_coin(candles, cmc):
    sc, rs, dt = 0, [], {}
    vc  = cmc.get("volume_change", 0)
    pc  = cmc.get("price_change_24h", 0)
    pc1h = cmc.get("price_change_1h", 0)

    # ─── 1. RVOL (20 نقطة) ───────────────────────────────
    rv = calc_rvol(candles) if candles and len(candles) >= 5 else max(1.0, 1+vc/100)
    if rv >= 3.0:
        sc += 20; rs.append(f"RVOL قوي جدا {rv:.1f}x")
    elif rv >= MIN_RVOL:
        sc += 15; rs.append(f"RVOL {rv:.1f}x")
    elif rv >= 1.5:
        sc += 8;  rs.append(f"RVOL متوسط {rv:.1f}x")
    elif vc >= 100:
        sc += 15; rs.append(f"فوليم +{vc:.0f}%")
    elif vc >= 50:
        sc += 8;  rs.append(f"فوليم +{vc:.0f}%")

    # ─── 2. قفزة فوليم مفاجئة (15 نقطة) ─────────────────
    surge, surge_ratio = calc_vol_surge(candles) if candles and len(candles) >= 10 else (False, 0)
    if surge:
        sc += 15; rs.append(f"قفزة فوليم {surge_ratio:.1f}x")
    elif surge_ratio >= 2.0:
        sc += 8;  rs.append(f"زيادة فوليم {surge_ratio:.1f}x")

    # ─── 3. Squeeze + Sideways (20 نقطة) ─────────────────
    if candles and len(candles) >= 20:
        bb   = calc_bb(candles)
        side = calc_sideways(candles)
        if bb["squeeze"]:
            sc += 20; rs.append(f"Squeeze قوي BB {bb['width']:.1f}%")
        elif bb["width"] < 8:
            sc += 14; rs.append(f"BB ضيق {bb['width']:.1f}%")
        elif bb["width"] < 12 and side:
            sc += 10; rs.append(f"Sideways + BB {bb['width']:.1f}%")
        elif side:
            sc += 6;  rs.append("نطاق Sideways")
        elif bb["width"] < 15:
            sc += 4;  rs.append(f"BB نسبي {bb['width']:.1f}%")
    else:
        if abs(pc) < 3:
            sc += 10; rs.append("حركة سعر هادئة")
        elif abs(pc) < 6:
            sc += 4;  rs.append("حركة معتدلة")

    # ─── 4. Breakout (15 نقطة) ────────────────────────────
    brk = calc_breakout(candles) if candles and len(candles) >= 21 else False
    if brk:
        sc += 15; rs.append("اختراق للأعلى Breakout")

    # ─── 5. امتصاص البيع (10 نقطة) ───────────────────────
    abso = calc_absorption(candles) if candles and len(candles) >= 5 else False
    if abso:
        sc += 10; rs.append("امتصاص بيع قوي")

    # ─── 6. Higher Lows (8 نقطة) ─────────────────────────
    hl = calc_higher_lows(candles) if candles and len(candles) >= 6 else False
    if hl:
        sc += 8; rs.append("Higher Lows صاعد")

    # ─── 7. السعر فوق MA20 (7 نقطة) ──────────────────────
    above_ma = calc_price_above_ma(candles) if candles and len(candles) >= 20 else False
    if above_ma:
        sc += 7; rs.append("سعر فوق MA20")

    # ─── 8. ضغط البيع ينخفض (5 نقطة) ─────────────────────
    dec_sell = calc_decreasing_sell_pressure(candles) if candles and len(candles) >= 8 else False
    if dec_sell:
        sc += 5; rs.append("ضغط بيع ينخفض")

    # ─── 9. شموع خضرا بتكبر (5 نقطة) ────────────────────
    growing_candles = calc_candle_size_increase(candles) if candles and len(candles) >= 6 else False
    if growing_candles:
        sc += 5; rs.append("شموع شراء تتضخم")

    # ─── 10. اختراق VWAP (5 نقطة) ────────────────────────
    vwap = calc_vwap_cross(candles) if candles and len(candles) >= 10 else False
    if vwap:
        sc += 5; rs.append("اختراق VWAP")

    # ─── تجميع التفاصيل ───────────────────────────────────
    dt = {
        "rvol":        rv,
        "squeeze":     (sc >= MIN_SCORE),
        "vol_trend":   vc > 50,
        "vol_surge":   surge,
        "surge_ratio": surge_ratio,
        "breakout":    brk,
        "absorption":  abso,
        "higher_lows": hl,
        "above_ma":    above_ma,
        "dec_sell":    dec_sell,
        "vwap_cross":  vwap,
        "bb_width":    calc_bb(candles)["width"] if candles and len(candles)>=20 else 999,
    }
    return {"score": min(sc, 100), "reasons": rs, "details": dt}


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
# ★ الوظيفة 1: التقرير الدوري — أعلى 50 عملة زادت سيولتها
# ============================================================
async def send_volume_report(bot: Bot, target_chat: int = None):
    """
    التغيير الرئيسي:
    - بدل ترتيب بأعلى فوليم مطلق
    - الترتيب بأعلى volume_change_24h% (أكثر عملة زادت سيولتها)
    - الحد الأدنى: volume_change >= MIN_VOL_CHANGE_FOR_REPORT
    """
    global previous_report
    logger.info("التقرير الدوري: جلب أكثر العملات زيادة في السيولة خلال 24 ساعة...")
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # المبعت الوحيد هو الأدمن — إلغاء broadcast
    chat_target = int(ADMIN_CHAT_ID)

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
        # ★ شرط الفوليم الأدنى والتغيير
        if d["volume_24h"]    < MIN_VOLUME_REPORT:          continue
        if d["volume_change"] < MIN_VOL_CHANGE_FOR_REPORT:  continue
        if is_dead_coin(d): continue
        coins.append(d)

    # ★ ترتيب بأعلى volume_change% مش أعلى فوليم مطلق
    coins.sort(key=lambda x: x["volume_change"], reverse=True)

    # فصل: جديدة / قديمة (cooldown 24h)
    fresh = [c for c in coins if not is_coin_cooldown(c["symbol"])]
    old_c = [c for c in coins if is_coin_cooldown(c["symbol"])]
    logger.info(f"فوليم زيادة: {len(fresh)} جديدة، {len(old_c)} في cooldown")

    if len(fresh) >= TOP_DISPLAY:
        top50 = fresh[:TOP_DISPLAY]
    else:
        needed = TOP_DISPLAY - len(fresh)
        top50  = fresh + old_c[:needed]
        logger.info(f"أضفنا {needed} من القديمة لإكمال الـ 50")

    for c in top50:
        if not is_coin_cooldown(c["symbol"]):
            seen_coins[c["symbol"]] = datetime.now()
    save_seen_coins()
    previous_report = top50

    # بناء الرسائل (10 في كل رسالة) — للأدمن فقط
    chunk_size = 10
    chunks = [top50[i:i+chunk_size] for i in range(0, len(top50), chunk_size)]

    for idx, chunk in enumerate(chunks, 1):
        lines = []
        if idx == 1:
            lines += [
                "📊 أعلى 50 Altcoin ارتفاعاً في السيولة — 24 ساعة",
                f"⏰ {scan_time}",
                f"📡 المصدر: CoinMarketCap | مرتب بأعلى % زيادة فوليم",
                "━━━━━━━━━━━━━━━━━━━━", ""
            ]

        for i, c in enumerate(chunk, (idx-1)*chunk_size + 1):
            pc  = c["price_change_24h"]
            vc  = c["volume_change"]
            p1h = c["price_change_1h"]
            arrow = "🟢" if pc > 0 else "🔴"
            # أيقونة نسبة الزيادة
            if vc >= 200:   vol_icon = "🔥🔥🔥"
            elif vc >= 100: vol_icon = "🔥🔥"
            elif vc >= 50:  vol_icon = "🔥"
            else:           vol_icon = "📈"

            lines.append(f"{i}. {arrow} {c['symbol']} — {escape_md(c['name'])}")
            lines.append(f"   💵 {fmt_price(c['price'])}  ({pc:+.1f}%)  |  1h: {p1h:+.1f}%")
            lines.append(f"   💰 فوليم 24h: {fmt_vol(c['volume_24h'])}")
            lines.append(f"   {vol_icon} زيادة الفوليم: {vc:+.0f}%")
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

    logger.info(f"تم إرسال التقرير للأدمن: {len(top50)} عملة")


# ============================================================
# ★ الوظيفة 2: فحص الإشارات — الإرسال فقط لو النقاط >= 75
# ============================================================
async def check_signals(bot: Bot, target_chat: int = None):
    """
    التغيير: يبعت للأدمن فقط، لا يبعت إلا لو score >= MIN_SCORE (75)
    """
    global previous_signals
    logger.info("فحص الإشارات التقنية...")

    # المبعت الوحيد هو الأدمن
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
            # ★ لا يضيف للقائمة إلا لو النقاط >= 75
            if sc < MIN_SCORE: return None
            rv = res["details"].get("rvol", 1.0)
            if len(candles) <= 5:
                vc = coin.get("volume_change", 0)
                if vc < 50: return None
            else:
                if rv < MIN_RVOL: return None
            # ★ فلتر البامب السابق
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

    # cooldown 24 ساعة
    from datetime import timedelta
    fresh_signals = []
    for c in signals:
        sym = c["symbol"]
        if sym in seen_signals:
            elapsed = datetime.now() - seen_signals[sym]
            if elapsed.total_seconds() < 86400:
                logger.info(f"تخطي {sym} — إشارة مكررة ({elapsed.seconds//3600}h مضت)")
                continue
        fresh_signals.append(c)

    signals = fresh_signals
    signals.sort(key=lambda x: x.get("score",0), reverse=True)

    if not signals:
        logger.info("لا توجد إشارات جديدة >= 75 نقطة")
        return

    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chunk_size = 5
    chunks = [signals[i:i+chunk_size] for i in range(0, min(len(signals),20), chunk_size)]

    for idx, chunk in enumerate(chunks, 1):
        lines = []
        if idx == 1:
            lines += [
                f"🚨 تنبيه — {len(signals)} إشارة Pre-Pump (score >= {MIN_SCORE})",
                f"⏰ {scan_time}",
                "━━━━━━━━━━━━━━━━━━━━", ""
            ]

        for c in chunk:
            pc    = c["price_change_24h"]
            p1h   = c["price_change_1h"]
            vc    = c["volume_change"]
            sc    = c.get("score",0)
            rv    = c.get("rvol",1.0)
            rs    = c.get("reasons",[])
            dt    = c.get("details",{})
            arrow = "🟢" if pc > 0 else "🔴"

            if sc >= 90:   strength = "🔥🔥🔥 قوية جداً"
            elif sc >= 80: strength = "🔥🔥 قوية"
            else:          strength = "🔥 جيدة (75+)"

            extras = []
            if dt.get("vol_surge"):                    extras.append(f"قفزة فوليم {dt.get('surge_ratio',0):.1f}x")
            if dt.get("breakout"):                     extras.append("Breakout")
            if dt.get("absorption"):                   extras.append("امتصاص بيع")
            if dt.get("higher_lows"):                  extras.append("Higher Lows")
            if dt.get("above_ma"):                     extras.append("فوق MA20")
            if dt.get("dec_sell"):                     extras.append("بيع ينخفض")
            if dt.get("vwap_cross"):                   extras.append("اختراق VWAP")
            if dt.get("vol_trend"):                    extras.append("فوليم متصاعد")

            lines.append(f"{arrow} {c['symbol']} — {escape_md(c['name'])}")
            lines.append(f"   💵 {fmt_price(c['price'])}  ({pc:+.1f}%)  |  1h: {p1h:+.1f}%")
            lines.append(f"   🎯 {sc}/100  —  {strength}")
            lines.append(f"   📊 RVOL: {rv:.1f}x  |  فوليم: {fmt_vol(c['volume_24h'])} ({vc:+.0f}%)")
            lines.append(f"   🌐 {c['num_market_pairs']} منصة  |  7d: {c['price_change_7d']:+.1f}%")
            if rs:      lines.append(f"   ✅ {' | '.join(rs[:4])}")
            if extras:  lines.append(f"   📌 {' · '.join(extras[:5])}")
            lines.append(f"   🔗 https://www.tradingview.com/chart/?symbol=GATEIO:{c['symbol']}_USDT")
            lines.append("")

        if idx == len(chunks):
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("📡 CMC + Gate.io")

        try:
            await bot.send_message(
                chat_id=chat_target,
                text="\n".join(lines),
                disable_web_page_preview=True
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"خطأ ارسال إشارة: {e}")

    for c in signals:
        seen_signals[c["symbol"]] = datetime.now()
    previous_signals = {c["symbol"]: c for c in signals}
    logger.info(f"تم إرسال {len(signals)} إشارة للأدمن")


# ============================================================
# نظام المشتركين (مبسط — الأدمن فقط)
# ============================================================
import json, os

SUBS_FILE  = "subscribers.json"
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
# ميزة /info — التوكنوميكس
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
            results["tags"]          = cmc_coin.get("tags",[])
            results["cmc_id"]        = cmc_coin.get("id","")

        try:
            cg_url = f"https://api.coingecko.com/api/v3/search?query={symbol}"
            async with session.get(cg_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                cg_data = await r.json()
            coins_list = cg_data.get("coins",[])
            cg_id = next((c["id"] for c in coins_list
                          if c.get("symbol","").upper() == symbol), None)
            if cg_id:
                results["cg_id"] = cg_id
                detail_url = f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false&market_data=true&community_data=true&developer_data=false"
                async with session.get(detail_url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                    detail = await r.json()
                community = detail.get("community_data",{})
                results["twitter_followers"]  = community.get("twitter_followers",0) or 0
                results["reddit_subscribers"] = community.get("reddit_subscribers",0) or 0
                md = detail.get("market_data",{})
                if not results.get("circulating"):
                    results["circulating"]  = float(md.get("circulating_supply",0) or 0)
                if not results.get("total_supply"):
                    results["total_supply"] = float(md.get("total_supply",0) or 0)
                if not results.get("max_supply"):
                    results["max_supply"]   = md.get("max_supply")
                if results.get("total_supply",0) > 0 and results.get("circulating",0) > 0:
                    results["circ_pct"] = results["circulating"] / results["total_supply"] * 100
                else:
                    results["circ_pct"] = None
                links = detail.get("links",{})
                results["website"]  = (links.get("homepage",[None])[0] or "").strip("/")
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
    if results.get("date_added"):
        lines.append(f"")
        lines.append(f"📅 تاريخ الإضافة على CMC: {results['date_added']}")
    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"📡 CMC + CoinGecko",
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
            f"💰 حجم التداول 24h الكلي (كل المنصات):\n"
            f"   {fmt_vol(vol)}\n"
            f"   زيادة الفوليم: {vc:+.1f}%\n\n"
            f"🌐 عدد المنصات: {pairs}\n"
            f"💎 Market Cap: {fmt_vol(mc)}\n"
            f"📊 رانك CMC: #{rank}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"📡 CoinMarketCap (كل المنصات)"
        )


# ============================================================
# /coin — تحليل شامل
# ============================================================
async def get_coin_analysis(symbol: str) -> str:
    symbol = symbol.upper().strip()
    async with aiohttp.ClientSession() as session:
        coin = await fetch_cmc_single(session, symbol)
        if not coin:
            return f"العملة {symbol} مش موجودة في CMC"
        d       = parse_coin(coin)
        candles = await fetch_klines(session, symbol, limit=48)
        rv      = calc_rvol(candles) if candles else 1.0
        _, atrd = calc_atr(candles)  if candles else (0,"unknown")
        bb      = calc_bb(candles)   if candles else {"width":0,"squeeze":False}
        brk     = calc_breakout(candles) if candles else False
        side    = calc_sideways(candles) if candles else False
        abso    = calc_absorption(candles) if candles else False
        vt      = calc_vol_trend(candles) if candles else False
        hl      = calc_higher_lows(candles) if candles else False
        above_ma= calc_price_above_ma(candles) if candles else False
        surge, surge_ratio = calc_vol_surge(candles) if candles else (False, 0)

        arrow = "🟢" if d["price_change_24h"] > 0 else "🔴"
        lines = [
            f"🔍 تحليل {symbol} — {escape_md(d['name'])}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"{arrow} السعر: {fmt_price(d['price'])}  ({d['price_change_24h']:+.2f}%)",
            f"⏱ 1h: {d['price_change_1h']:+.2f}%  |  7d: {d['price_change_7d']:+.2f}%",
            f"",
            f"💰 حجم التداول 24h: {fmt_vol(d['volume_24h'])}  ({d['volume_change']:+.0f}%)",
            f"🌐 المنصات: {d['num_market_pairs']}  |  Market Cap: {fmt_vol(d['market_cap'])}",
            f"📊 رانك CMC: #{d['rank']}",
            f"",
            f"📈 التحليل التقني:",
            f"   RVOL: {rv:.2f}x  {'✅' if rv>=MIN_RVOL else '⚠️'}",
            f"   قفزة فوليم: {'✅ ' + str(round(surge_ratio,1)) + 'x' if surge else '❌'}",
            f"   ATR: {'↗️ ارتفاع' if atrd=='rising' else '↘️ هبوط' if atrd=='falling' else '➡️ ثابت'}",
            f"   Bollinger: {bb['width']:.1f}%  {'🔴 Squeeze!' if bb['squeeze'] else ''}",
            f"   Breakout: {'✅' if brk else '❌'}  |  Sideways: {'✅' if side else '❌'}",
            f"   Higher Lows: {'✅' if hl else '❌'}  |  فوق MA20: {'✅' if above_ma else '❌'}",
            f"   امتصاص بيع: {'✅' if abso else '❌'}  |  فوليم متصاعد: {'✅' if vt else '❌'}",
        ]
        if candles and len(candles) >= 10:
            res = score_coin(candles, d)
            sc  = res["score"]
            rs  = res["reasons"]
            lines += [
                f"",
                f"🎯 نقاط الإشارة: {sc}/100",
                f"   {'🚀 إشارة قوية! (>= 75)' if sc>=MIN_SCORE else '😴 لا إشارة بعد (< 75)'}",
            ]
            if rs: lines.append(f"   {' | '.join(rs[:5])}")
        lines += [
            f"",
            f"🔗 https://www.tradingview.com/chart/?symbol=GATEIO:{symbol}_USDT",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        return "\n".join(lines)


# ==================== Scheduled Jobs ====================
async def job_volume_report(context: ContextTypes.DEFAULT_TYPE):
    try:
        await send_volume_report(context.bot)
    except Exception as e:
        logger.error(f"خطأ في job_volume_report: {e}")

async def job_check_signals(context: ContextTypes.DEFAULT_TYPE):
    try:
        await check_signals(context.bot)
    except Exception as e:
        logger.error(f"خطأ في job_check_signals: {e}")


# ==================== أوامر البوت ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Altcoin Smart Scanner Bot\n\n"
        "التقارير التلقائية:\n"
        "📊 كل 4 ساعات: أعلى 50 عملة زادت سيولتها (مرتب بأعلى % زيادة)\n"
        "🚨 فوري: تنبيه عند توفر إشارة قوية >= 75 نقطة\n\n"
        "الأوامر:\n"
        "/report  — تقرير فوري لأعلى 50 زيادة سيولة\n"
        "/scan    — فحص الإشارات التقنية الآن\n"
        "/info ETH — توكنوميكس + holders\n"
        "/vol ETH — حجم تداول أي عملة\n"
        "/coin ETH — تحليل كامل لعملة\n"
        "/top     — أفضل 5 إشارات\n"
        "/status  — حالة البوت\n"
        "/chatid  — معرفة الـ Chat ID"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 جاري جلب أعلى 50 عملة زيادة سيولة...")
    await send_volume_report(context.bot, target_chat=update.effective_chat.id)

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص الإشارات التقنية (score >= 75)...")
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
    await update.message.reply_text(
        f"✅ البوت شغال\n"
        f"📊 تقرير كل {SCAN_INTERVAL_MINUTES} دقيقة (أعلى % زيادة سيولة)\n"
        f"🔍 فحص إشارات كل 30 دقيقة (score >= {MIN_SCORE})\n"
        f"📡 CMC + Gate.io\n"
        f"🔔 الإرسال: الأدمن فقط"
    )

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID:\n{update.effective_chat.id}")


# ==================== تشغيل البوت ====================
def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = Application.builder().token(TELEGRAM_TOKEN).build()
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

    # التقرير كل 4 ساعات — أول تقرير بعد 30 ثانية
    app.job_queue.run_repeating(job_volume_report,
                                interval=SCAN_INTERVAL_MINUTES*60, first=30)
    # فحص الإشارات كل 30 دقيقة — أول فحص بعد دقيقتين
    app.job_queue.run_repeating(job_check_signals,
                                interval=1800, first=120)

    print("="*55)
    print("🚀 Altcoin Smart Scanner Bot v2")
    print(f"📊 تقرير أعلى % زيادة سيولة كل {SCAN_INTERVAL_MINUTES} دقيقة")
    print(f"🚨 إشارات كل 30 دقيقة (score >= {MIN_SCORE} فقط)")
    print("🔔 الإرسال: الأدمن فقط — لا broadcast")
    print("📡 CMC + Gate.io")
    print("="*55)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
