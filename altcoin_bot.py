"""
🚀 Altcoin Smart Scanner Bot - Ultimate Edition
3 وظائف:
1. كل 4 ساعات: اعلى 30 عملة فوليم من كل المنصات
2. تنبيه فوري: لما تتوفر اشارة قوية (نظام النقاط)
3. /vol SYMBOL: حجم تداول اي عملة بدون قيود
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
CHAT_ID        = "6914157653"
CMC_API_KEY    = "7eeaf1fd132e416ab49279ee21cc6ce0"

# ==================== اعدادات التقرير الدوري ====================
SCAN_INTERVAL_MINUTES = 240   # كل 4 ساعات
TOP_DISPLAY           = 30    # اعلى 30 عملة فوليم
CMC_LIMIT             = 500   # نجيب اول 500 من CMC

# ==================== اعدادات الاشارات ====================
MIN_SCORE          = 60       # الحد الادنى للاشارة
MIN_RVOL           = 2.5      # RVOL > 2.5
MAX_PREV_PUMP      = 12.0     # استبعاد pump سابق > 12%
MIN_VOL_FOR_SIGNAL = 2_000_000

# ==================== اعدادات الفلترة ====================
MAX_MARKET_CAP     = 2_000_000_000
MIN_VOLUME_REPORT  = 5_000_000   # للتقرير الدوري

# ==================== نظام النقاط ====================
SCORE_RVOL       = 25
SCORE_SQUEEZE    = 20
SCORE_BREAKOUT   = 25
SCORE_ABSORPTION = 15
SCORE_MOMENTUM   = 15

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

# ==================== قوائم الاستبعاد ====================
EXCLUDED_SYMBOLS = {
    # العملات الكبيرة
    "BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","AVAX","SHIB",
    "DOT","LINK","MATIC","LTC","BCH","XLM","ETC","UNI","ATOM","NEAR",
    "FIL","ICP","HBAR","VET","ALGO","EGLD","TON","SUI","APT","OP",
    "ARB","INJ","SEI","TIA","PYTH","JUP","WLD","RENDER","FET","TAO",
    "IMX","GRT","STX","MKR","AAVE","SNX","COMP","CRV","LDO","RPL",
    "SAND","MANA","AXS","ENJ","CHZ","FLOW","GALA","THETA","FTM",
    "ONE","ROSE","ZIL","ICX","QTUM","ZEC","XMR","DASH","DCR","XTZ",
    "EOS","TRB","BAT","ZRX","SUSHI","YFI","UMA","BAL","KNC","WAVES",
    "ONT","ZEN","SC","DGB","RVN","IOST","STORJ","ANKR","CKB","CELR",
    # Stablecoins
    "USDT","USDC","BUSD","DAI","TUSD","USDP","USDD","FDUSD",
    "USDE","PYUSD","GUSD","LUSD","FRAX","SUSD","EURC","USDS",
    "USD1","USDX","CUSD","MUSD","HUSD","USDJ","XUSD","ZUSD",
    "DUSD","NUSD","PUSD","CRVUSD","DOLA","PAX","PAXG","BEAN",
    # Wrapped tokens
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


# ==================== ادوات ====================
def is_meme_coin(symbol, name, tags):
    if symbol in MEME_SYMBOLS: return True
    if tags and any(t in MEME_TAGS for t in tags): return True
    for kw in MEME_KEYWORDS:
        if kw in symbol.lower() or kw in name.lower(): return True
    return False

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
    """جلب عملة محددة من CMC - يبحث في اول 2000"""
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
    url    = "https://api.binance.com/api/v3/klines"
    params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
    try:
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status != 200: return []
            data = await r.json()
        return [{"open": float(k[1]), "high": float(k[2]),
                 "low":  float(k[3]), "close": float(k[4]),
                 "volume": float(k[5])} for k in data]
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


# ==================== نظام النقاط ====================
def score_coin(candles, cmc):
    sc, rs, dt = 0, [], {}
    vc  = cmc.get("volume_change", 0)
    pc  = cmc.get("price_change_24h", 0)
    p1h = cmc.get("price_change_1h", 0)

    if not candles or len(candles) < 10:
        rv = max(1.0, 1+vc/100)
        if rv >= MIN_RVOL:  sc += SCORE_RVOL;    rs.append(f"RVOL {rv:.1f}x")
        if abs(pc) > 5:     sc += SCORE_BREAKOUT; rs.append(f"سعر {pc:+.1f}%")
        if p1h > 2:         sc += SCORE_MOMENTUM; rs.append(f"1h {p1h:+.1f}%")
        dt = {"rvol": rv, "atr_dir": "unknown", "squeeze": False, "breakout": abs(pc)>5}
        return {"score": sc, "reasons": rs, "details": dt}

    rv         = calc_rvol(candles)
    _, atr_dir = calc_atr(candles)
    bb         = calc_bb(candles)
    brk        = calc_breakout(candles)
    side       = calc_sideways(candles)
    abso       = calc_absorption(candles)
    mom        = calc_momentum(candles)
    vt         = calc_vol_trend(candles)
    pp         = calc_prev_pump(candles)

    if pp > MAX_PREV_PUMP:
        return {"score": 0, "reasons": [f"pump سابق {pp:.1f}%"], "details": {}}

    if rv >= MIN_RVOL:   sc += SCORE_RVOL;             rs.append(f"RVOL {rv:.1f}x")
    elif rv >= 1.5:      sc += int(SCORE_RVOL*0.5);    rs.append(f"RVOL {rv:.1f}x")
    if bb["squeeze"]:    sc += SCORE_SQUEEZE;           rs.append(f"Squeeze {bb['width']:.1f}%")
    elif bb["width"]<8:  sc += int(SCORE_SQUEEZE*0.5);  rs.append(f"BB ضيق {bb['width']:.1f}%")
    if brk and side:     sc += SCORE_BREAKOUT;          rs.append("Breakout+Sideways")
    elif brk:            sc += int(SCORE_BREAKOUT*0.7); rs.append("Breakout")
    if abso:             sc += SCORE_ABSORPTION;        rs.append("امتصاص بيع")
    m = 0
    if mom["green"] >= 3: m += SCORE_MOMENTUM;  rs.append("3 شموع خضر")
    elif mom["green"]==2: m += int(SCORE_MOMENTUM*0.5)
    if mom["fast"]:       m  = min(m+5, SCORE_MOMENTUM); rs.append("حركة سريعة")
    sc += m
    if atr_dir == "rising": sc += 5; rs.append("ATR ارتفاع")
    if vt:                  sc += 5; rs.append("فوليم متصاعد")

    dt = {"rvol":rv,"atr_dir":atr_dir,"bb_width":bb["width"],"squeeze":bb["squeeze"],
          "breakout":brk,"sideways":side,"absorption":abso,"green":mom["green"],
          "vol_trend":vt,"prev_pump":pp}
    return {"score": min(sc,100), "reasons": rs, "details": dt}


# ==================== تحويل بيانات CMC ====================
def parse_coin(coin):
    q   = coin.get("quote",{}).get("USD",{})
    return {
        "id":     coin.get("id"),
        "name":   coin.get("name",""),
        "symbol": coin.get("symbol",""),
        "price":  float(q.get("price",0) or 0),
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
# الوظيفة 1: التقرير الدوري — اعلى 30 عملة فوليم كل 4 ساعات
# ============================================================
async def send_volume_report(bot: Bot):
    global previous_report
    logger.info("التقرير الدوري: جلب اعلى عملات فوليم...")
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async with aiohttp.ClientSession() as session:
        raw = await fetch_cmc(session, limit=CMC_LIMIT)

    if not raw:
        await bot.send_message(chat_id=CHAT_ID, text="فشل جلب البيانات من CMC")
        return

    coins = []
    for c in raw:
        symbol = c.get("symbol","")
        name   = c.get("name","")
        tags   = [t.lower() for t in c.get("tags",[])]
        if symbol in EXCLUDED_SYMBOLS: continue
        if is_meme_coin(symbol, name, tags): continue
        d = parse_coin(c)
        if d["volume_24h"] < MIN_VOLUME_REPORT: continue
        coins.append(d)

    # ترتيب حسب الفوليم وناخد اعلى 30
    coins.sort(key=lambda x: x["volume_24h"], reverse=True)
    top30 = coins[:TOP_DISPLAY]
    previous_report = top30

    # بناء الرسائل (10 في كل رسالة)
    chunk_size = 10
    chunks = [top30[i:i+chunk_size] for i in range(0, len(top30), chunk_size)]

    for idx, chunk in enumerate(chunks, 1):
        lines = []
        if idx == 1:
            lines += [
                "📊 اعلى 30 Altcoin فوليم — كل المنصات",
                f"⏰ {scan_time}",
                f"📡 المصدر: CoinMarketCap",
                "━━━━━━━━━━━━━━━━━━━━", ""
            ]

        for i, c in enumerate(chunk, (idx-1)*chunk_size + 1):
            pc  = c["price_change_24h"]
            vc  = c["volume_change"]
            p1h = c["price_change_1h"]
            arrow = "🟢" if pc > 0 else "🔴"

            lines.append(f"{i}. {arrow} {c['symbol']} — {escape_md(c['name'])}")
            lines.append(f"   💵 {fmt_price(c['price'])}  ({pc:+.1f}%)  |  1h: {p1h:+.1f}%")
            lines.append(f"   💰 فوليم 24h: {fmt_vol(c['volume_24h'])}  ({vc:+.0f}%)")
            lines.append(f"   🌐 {c['num_market_pairs']} منصة  |  CMC #{c['rank']}")
            lines.append("")

        if idx == len(chunks):
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("💡 للتحليل الكامل: /coin SYMBOL")
            lines.append("💡 لحجم عملة: /vol SYMBOL")

        try:
            await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines),
                                   disable_web_page_preview=True)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"خطأ ارسال تقرير: {e}")

    logger.info(f"تم ارسال التقرير: {len(top30)} عملة")


# ============================================================
# الوظيفة 2: تنبيه الاشارات — يُرسل فقط عند توفر اشارة قوية
# ============================================================
async def check_signals(bot: Bot):
    global previous_signals
    logger.info("فحص الاشارات التقنية...")

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
            if d["market_cap"] > MAX_MARKET_CAP: continue
            if abs(d["price_change_24h"]) < 1.5 and d["volume_change"] < 50: continue
            candidates.append(d)

        # تحليل تقني
        async def analyze(coin):
            candles = await fetch_klines(session, coin["symbol"])
            res     = score_coin(candles, coin)
            sc      = res["score"]
            if sc < MIN_SCORE: return None
            rv = res["details"].get("rvol", 1.0)
            if rv < MIN_RVOL and len(candles) > 5: return None
            coin.update({"score": sc, "reasons": res["reasons"],
                         "details": res["details"], "rvol": rv})
            return coin

        tasks   = [analyze(c) for c in candidates[:80]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    signals = [r for r in results if r and not isinstance(r, Exception)]
    signals.sort(key=lambda x: x.get("score",0), reverse=True)

    if not signals:
        logger.info("لا توجد اشارات قوية الان")
        return

    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chunk_size = 5
    chunks = [signals[i:i+chunk_size] for i in range(0, min(len(signals),20), chunk_size)]

    for idx, chunk in enumerate(chunks, 1):
        lines = []
        if idx == 1:
            lines += [
                f"🚨 تنبيه — {len(signals)} اشارة Pre-Pump",
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

            if sc >= 90:   strength = "🔥🔥🔥 قوية جدا"
            elif sc >= 80: strength = "🔥🔥 قوية"
            else:          strength = "🔥 جيدة"

            extras = []
            if dt.get("squeeze"):              extras.append("Squeeze")
            if dt.get("breakout"):             extras.append("Breakout")
            if dt.get("absorption"):           extras.append("امتصاص بيع")
            if dt.get("vol_trend"):            extras.append("فوليم متصاعد")
            if dt.get("green",0) >= 3:         extras.append("3 شموع خضر")
            if dt.get("atr_dir") == "rising":  extras.append("ATR ارتفاع")

            lines.append(f"{arrow} {c['symbol']} — {escape_md(c['name'])}")
            lines.append(f"   💵 {fmt_price(c['price'])}  ({pc:+.1f}%)  |  1h: {p1h:+.1f}%")
            lines.append(f"   🎯 {sc}/100  —  {strength}")
            lines.append(f"   📊 RVOL: {rv:.1f}x  |  فوليم: {fmt_vol(c['volume_24h'])} ({vc:+.0f}%)")
            lines.append(f"   🌐 {c['num_market_pairs']} منصة  |  7d: {c['price_change_7d']:+.1f}%")
            if rs:      lines.append(f"   ✅ {' | '.join(rs[:3])}")
            if extras:  lines.append(f"   📌 {' · '.join(extras)}")
            lines.append(f"   🔗 https://www.tradingview.com/chart/?symbol=BINANCE:{c['symbol']}USDT")
            lines.append("")

        if idx == len(chunks):
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("📡 CMC + Binance Technical Analysis")

        try:
            await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines),
                                   disable_web_page_preview=True)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"خطأ ارسال اشارة: {e}")

    previous_signals = {c["symbol"]: c for c in signals}
    logger.info(f"تم ارسال {len(signals)} اشارة")


# ============================================================
# الوظيفة 3: /vol — حجم اي عملة بدون قيود
# ============================================================
async def get_vol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    async with aiohttp.ClientSession() as session:
        # ابحث اول في CMC بشكل مباشر
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
            f"⏱ 1h: {pc1h:+.2f}%  |  7d: {pc7d:+.2f}%\n"
            f"\n"
            f"💰 حجم التداول 24h الكلي (كل المنصات):\n"
            f"   {fmt_vol(vol)}\n"
            f"   تغيير الحجم: {vc:+.1f}%\n"
            f"\n"
            f"🌐 عدد المنصات: {pairs}\n"
            f"💎 Market Cap: {fmt_vol(mc)}\n"
            f"📊 رانك CMC: #{rank}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"📡 CoinMarketCap (كل المنصات)"
        )


# ============================================================
# الوظيفة الكاملة: /coin — تحليل شامل
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

        arrow = "🟢" if d["price_change_24h"] > 0 else "🔴"
        lines = [
            f"🔍 تحليل {symbol} — {escape_md(d['name'])}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"{arrow} السعر: {fmt_price(d['price'])}  ({d['price_change_24h']:+.2f}%)",
            f"⏱ 1h: {d['price_change_1h']:+.2f}%  |  7d: {d['price_change_7d']:+.2f}%",
            f"",
            f"💰 حجم التداول 24h الكلي (كل المنصات):",
            f"   {fmt_vol(d['volume_24h'])}  (تغيير: {d['volume_change']:+.0f}%)",
            f"🌐 عدد المنصات: {d['num_market_pairs']}  |  Market Cap: {fmt_vol(d['market_cap'])}",
            f"📊 رانك CMC: #{d['rank']}",
            f"",
            f"📈 التحليل التقني:",
            f"   RVOL: {rv:.2f}x  {'✅' if rv>=MIN_RVOL else '⚠️'}",
            f"   ATR: {'↗️ ارتفاع' if atrd=='rising' else '↘️ هبوط' if atrd=='falling' else '➡️ ثابت'}",
            f"   Bollinger: {bb['width']:.1f}%  {'🔴 Squeeze!' if bb['squeeze'] else ''}",
            f"   Breakout: {'✅' if brk else '❌'}  |  Sideways: {'✅' if side else '❌'}",
            f"   امتصاص بيع: {'✅' if abso else '❌'}  |  فوليم متصاعد: {'✅' if vt else '❌'}",
        ]

        if candles and len(candles) >= 10:
            res   = score_coin(candles, d)
            sc    = res["score"]
            rs    = res["reasons"]
            lines += [
                f"",
                f"🎯 نقاط الاشارة: {sc}/100",
                f"   {'🚀 اشارة قوية!' if sc>=MIN_SCORE else '😴 لا اشارة بعد'}",
            ]
            if rs: lines.append(f"   {' | '.join(rs[:4])}")

        lines += [
            f"",
            f"🔗 https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        return "\n".join(lines)


# ==================== Scheduled Jobs ====================
async def job_volume_report(context: ContextTypes.DEFAULT_TYPE):
    await send_volume_report(context.bot)

async def job_check_signals(context: ContextTypes.DEFAULT_TYPE):
    await check_signals(context.bot)


# ==================== اوامر البوت ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Altcoin Smart Scanner Bot\n\n"
        "التقارير التلقائية:\n"
        "📊 كل 4 ساعات: اعلى 30 عملة فوليم\n"
        "🚨 فوري: تنبيه عند توفر اشارة قوية\n\n"
        "الاوامر:\n"
        "/report  — تقرير فوري لاعلى 30 فوليم\n"
        "/scan    — فحص الاشارات التقنية الان\n"
        "/vol ETH — حجم تداول اي عملة\n"
        "/coin ETH — تحليل كامل لعملة\n"
        "/top     — افضل 5 اشارات\n"
        "/status  — حالة البوت\n"
        "/chatid  — معرفة الـ Chat ID"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 جاري جلب اعلى 30 عملة فوليم...")
    await send_volume_report(context.bot)

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص الاشارات التقنية...")
    await check_signals(context.bot)

async def cmd_vol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم: /vol اسم_العملة\nمثال: /vol ETH")
        return
    await update.message.reply_text(f"🔍 جاري جلب بيانات {context.args[0].upper()}...")
    result = await get_vol(context.args[0])
    await update.message.reply_text(result)

async def cmd_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم: /coin اسم_العملة\nمثال: /coin ETH")
        return
    await update.message.reply_text(f"🔍 جاري تحليل {context.args[0].upper()}...")
    result = await get_coin_analysis(context.args[0])
    await update.message.reply_text(result, disable_web_page_preview=True)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not previous_signals:
        await update.message.reply_text("لا توجد اشارات بعد، استخدم /scan")
        return
    top5  = sorted(previous_signals.values(), key=lambda x: x.get("score",0), reverse=True)[:5]
    lines = ["🏆 افضل 5 اشارات:\n"]
    for i, c in enumerate(top5, 1):
        lines.append(f"{i}. {c['symbol']}  نقاط: {c.get('score',0)}/100  ({c['price_change_24h']:+.1f}%)")
    await update.message.reply_text("\n".join(lines))

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"✅ البوت شغال\n"
        f"📊 اخر تقرير: {len(previous_report)} عملة\n"
        f"🚨 اشارات نشطة: {len(previous_signals)}\n"
        f"⏱ تقرير كل {SCAN_INTERVAL_MINUTES} دقيقة\n"
        f"🎯 حد الاشارة: {MIN_SCORE}/100\n"
        f"📡 CMC (كل المنصات) + Binance TA"
    )

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID:\n{update.effective_chat.id}")


# ==================== تشغيل البوت ====================
def main():
    if "ضع_" in TELEGRAM_TOKEN:
        print("❌ حط التوكن في TELEGRAM_TOKEN"); return
    if "ضع_" in CMC_API_KEY:
        print("❌ حط CMC API Key في CMC_API_KEY"); return

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("vol",    cmd_vol))
    app.add_handler(CommandHandler("coin",   cmd_coin))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("chatid", cmd_chatid))

    # التقرير الدوري كل 4 ساعات
    app.job_queue.run_repeating(job_volume_report,
                                interval=SCAN_INTERVAL_MINUTES*60, first=15)
    # فحص الاشارات كل ساعة
    app.job_queue.run_repeating(job_check_signals,
                                interval=3600, first=60)

    print("="*55)
    print("🚀 Altcoin Smart Scanner Bot")
    print(f"📊 تقرير فوليم كل {SCAN_INTERVAL_MINUTES} دقيقة")
    print("🚨 فحص اشارات كل ساعة")
    print("📡 CoinMarketCap + Binance")
    print("="*55)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
