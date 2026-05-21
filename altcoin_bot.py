"""
🚀 Altcoin Smart Scanner Bot - Ultimate Edition
دمج نظام حجم التداول الكلي + نظام النقاط التقني
"""

import asyncio
import aiohttp
import logging
import sys
import math
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==================== الإعدادات ====================
TELEGRAM_TOKEN = "8794878965:AAEZR3MdSG-3OiGBeR05q9MJzvvo1ODmNmc"
CHAT_ID        = "6914157653"
CMC_API_KEY    = "7eeaf1fd132e416ab49279ee21cc6ce0"

# ==================== معايير الفلترة ====================
MIN_VOLUME_24H        = 2_000_000      # حجم تداول كلي >= 2M$
MIN_RVOL              = 2.5            # RVOL > 2.5
MIN_SCORE             = 75             # نظام النقاط >= 75
MAX_MARKET_CAP_USD    = 2_000_000_000  # استبعاد فوق 2 مليار
MAX_PREV_PUMP_PCT     = 12.0           # استبعاد لو pump سابق > 12%
SCAN_INTERVAL_MINUTES = 240            # كل 4 ساعات
TOP_COINS_LIMIT       = 500
TOP_RESULTS_DISPLAY   = 30

# ==================== نظام النقاط ====================
SCORE_RVOL       = 25
SCORE_SQUEEZE    = 20
SCORE_BREAKOUT   = 25
SCORE_ABSORPTION = 15
SCORE_MOMENTUM   = 15

# ==================== Logging ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("altcoin_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
previous_data:   dict = {}
previous_volume: dict = {}

# ==================== قوائم الاستبعاد ====================
EXCLUDED_SYMBOLS = {
    "BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","AVAX","SHIB",
    "DOT","LINK","MATIC","LTC","BCH","XLM","ETC","UNI","ATOM","NEAR",
    "FIL","ICP","HBAR","VET","ALGO","EGLD","TON","SUI","APT","OP",
    "ARB","INJ","SEI","TIA","PYTH","JUP","WLD",
    "USDT","USDC","BUSD","DAI","TUSD","USDP","USDD","FDUSD",
    "USDE","PYUSD","GUSD","LUSD","FRAX","SUSD","EURC","USDS",
    "WBTC","WETH","STETH","CBETH","RETH","WBNB","WEETH",
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


# ==================== فحص الميم كوين ====================
def is_meme_coin(symbol, name, tags):
    if symbol in MEME_SYMBOLS: return True
    if tags and any(t in MEME_TAGS for t in tags): return True
    for kw in MEME_KEYWORDS:
        if kw in symbol.lower() or kw in name.lower(): return True
    return False


# ==================== أدوات التنسيق ====================
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
async def fetch_cmc_listings(session):
    url     = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}
    params  = {"limit": TOP_COINS_LIMIT, "convert": "USD",
                "sort": "volume_24h", "sort_dir": "desc"}
    try:
        async with session.get(url, headers=headers, params=params,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status == 401: logger.error("❌ CMC API Key غلط!"); return []
            if r.status == 429: logger.error("❌ تجاوزت حد الـ API!"); return []
            data = await r.json()
        coins = data.get("data", [])
        logger.info(f"✅ CMC: {len(coins)} عملة")
        return coins
    except Exception as e:
        logger.error(f"❌ CMC error: {e}"); return []


async def fetch_binance_klines(session, symbol, interval="1h", limit=48):
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
def calc_rvol(candles):
    if len(candles) < 5: return 1.0
    vols = [c["volume"] for c in candles]
    avg  = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else vols[-1]
    return vols[-1] / avg if avg > 0 else 1.0

def calc_atr(candles, period=14):
    if len(candles) < period + 1: return 0.0, "unknown"
    trs = [max(candles[i]["high"]-candles[i]["low"],
               abs(candles[i]["high"]-candles[i-1]["close"]),
               abs(candles[i]["low"] -candles[i-1]["close"]))
           for i in range(1, len(candles))]
    if len(trs) < period: return 0.0, "unknown"
    atr_now  = sum(trs[-period:]) / period
    atr_prev = sum(trs[-period*2:-period]) / period if len(trs) >= period*2 else atr_now
    direction = "rising" if atr_now > atr_prev*1.1 else ("falling" if atr_now < atr_prev*0.9 else "flat")
    return atr_now, direction

def calc_bollinger(candles, period=20):
    if len(candles) < period:
        return {"upper":0,"lower":0,"mid":0,"width":999,"squeeze":False}
    closes = [c["close"] for c in candles[-period:]]
    mid    = sum(closes)/period
    std    = math.sqrt(sum((x-mid)**2 for x in closes)/period)
    upper, lower = mid+2*std, mid-2*std
    width  = (upper-lower)/mid*100 if mid > 0 else 999
    return {"upper":upper,"lower":lower,"mid":mid,"width":width,"squeeze":width<5.0}

def calc_breakout(candles, lookback=20):
    if len(candles) < lookback+1: return {"breakout":False,"resistance":0}
    resistance    = max(c["high"] for c in candles[-(lookback+1):-1])
    current_close = candles[-1]["close"]
    return {"breakout": current_close > resistance*1.005, "resistance": resistance}

def calc_sideways(candles, lookback=20):
    if len(candles) < lookback: return False
    subset = candles[-lookback:-1]
    highs, lows = [c["high"] for c in subset], [c["low"] for c in subset]
    price_range = (max(highs)-min(lows))/min(lows)*100 if min(lows) > 0 else 999
    return price_range < 15.0

def calc_absorption(candles):
    if len(candles) < 5: return False
    count = sum(1 for c in candles[-5:]
                if abs(c["close"]-c["open"]) > 0 and
                   min(c["open"],c["close"])-c["low"] > abs(c["close"]-c["open"])*1.5)
    return count >= 2

def calc_momentum(candles):
    if len(candles) < 5: return {"green_streak":0,"fast_move":False}
    green_streak = sum(1 for c in candles[-3:] if c["close"] > c["open"])
    recent = [abs(c["close"]-c["open"])/c["open"]*100 for c in candles[-3:] if c["open"]>0]
    normal = [abs(c["close"]-c["open"])/c["open"]*100 for c in candles[:-3]  if c["open"]>0]
    avg_r  = sum(recent)/len(recent) if recent else 0
    avg_n  = sum(normal)/len(normal) if normal else 1
    return {"green_streak": green_streak, "fast_move": avg_r > avg_n*2}

def calc_vol_trend(candles):
    if len(candles) < 5: return False
    vols = [c["volume"] for c in candles[-5:]]
    return sum(1 for i in range(1,len(vols)) if vols[i]>vols[i-1]) >= 3

def calc_prev_pump(candles):
    if len(candles) < 3: return 0.0
    return max(
        (candles[i]["close"]-candles[i-1]["close"])/candles[i-1]["close"]*100
        for i in range(1, min(20,len(candles)))
    )


# ==================== نظام النقاط ====================
def calculate_score(candles, cmc_data):
    score, reasons, details = 0, [], {}

    if not candles or len(candles) < 10:
        vc, pc, p1h = cmc_data.get("volume_change",0), cmc_data.get("price_change_24h",0), cmc_data.get("price_change_1h",0)
        rvol_approx = max(1.0, 1 + vc/100)
        if rvol_approx >= MIN_RVOL:  score += SCORE_RVOL;     reasons.append(f"RVOL {rvol_approx:.1f}x")
        if abs(pc) > 5:              score += SCORE_BREAKOUT;  reasons.append(f"حركة سعر {pc:+.1f}%")
        if p1h > 2:                  score += SCORE_MOMENTUM;  reasons.append(f"زخم 1h {p1h:+.1f}%")
        details = {"rvol":rvol_approx,"atr_dir":"unknown","squeeze":False,"breakout":abs(pc)>5,"vol_trend":vc>50}
        return {"score":score,"reasons":reasons,"details":details}

    rvol         = calc_rvol(candles)
    atr, atr_dir = calc_atr(candles)
    bb           = calc_bollinger(candles)
    breakout     = calc_breakout(candles)
    sideways     = calc_sideways(candles)
    absorption   = calc_absorption(candles)
    momentum     = calc_momentum(candles)
    vol_trend    = calc_vol_trend(candles)
    prev_pump    = calc_prev_pump(candles)

    if prev_pump > MAX_PREV_PUMP_PCT:
        return {"score":0,"reasons":[f"pump سابق {prev_pump:.1f}%"],"details":{}}

    if rvol >= MIN_RVOL:    score += SCORE_RVOL;              reasons.append(f"RVOL {rvol:.1f}x")
    elif rvol >= 1.5:       score += int(SCORE_RVOL*0.5);     reasons.append(f"RVOL متوسط {rvol:.1f}x")

    if bb["squeeze"]:       score += SCORE_SQUEEZE;           reasons.append(f"Squeeze BB {bb['width']:.1f}%")
    elif bb["width"] < 8:   score += int(SCORE_SQUEEZE*0.5);  reasons.append(f"BB ضيق {bb['width']:.1f}%")

    if breakout["breakout"] and sideways:
                            score += SCORE_BREAKOUT;          reasons.append("Breakout بعد Sideways")
    elif breakout["breakout"]:
                            score += int(SCORE_BREAKOUT*0.7); reasons.append("Breakout")

    if absorption:          score += SCORE_ABSORPTION;        reasons.append("امتصاص بيع")

    mom = 0
    if momentum["green_streak"] >= 3: mom += SCORE_MOMENTUM;  reasons.append("3 شموع خضر")
    elif momentum["green_streak"]==2:  mom += int(SCORE_MOMENTUM*0.5)
    if momentum["fast_move"]:          mom = min(mom+5, SCORE_MOMENTUM); reasons.append("حركة سريعة")
    score += mom

    if atr_dir == "rising":  score += 5; reasons.append("ATR ارتفاع")
    if vol_trend:            score += 5; reasons.append("فوليم متصاعد")

    details = {
        "rvol": rvol, "atr": atr, "atr_dir": atr_dir,
        "bb_width": bb["width"], "squeeze": bb["squeeze"],
        "breakout": breakout["breakout"], "sideways": sideways,
        "absorption": absorption, "green_streak": momentum["green_streak"],
        "vol_trend": vol_trend, "prev_pump": prev_pump,
    }
    return {"score": min(score,100), "reasons": reasons, "details": details}


# ==================== فلترة أولية من CMC ====================
def parse_cmc_coins(raw_coins):
    result = []
    for coin in raw_coins:
        symbol = coin.get("symbol","")
        name   = coin.get("name","")
        tags   = [t.lower() for t in coin.get("tags",[])]

        if symbol in EXCLUDED_SYMBOLS: continue
        if is_meme_coin(symbol, name, tags): continue

        q      = coin.get("quote",{}).get("USD",{})
        vol    = float(q.get("volume_24h",0) or 0)
        mc     = float(q.get("market_cap",0) or 0)
        pc24   = float(q.get("percent_change_24h",0) or 0)
        vc     = float(q.get("volume_change_24h",0) or 0)
        price  = float(q.get("price",0) or 0)
        pc7d   = float(q.get("percent_change_7d",0) or 0)
        pc1h   = float(q.get("percent_change_1h",0) or 0)

        if vol < MIN_VOLUME_24H: continue
        if mc > MAX_MARKET_CAP_USD: continue
        if abs(pc24) < 1.5 and vc < 50: continue

        result.append({
            "id": coin.get("id"), "name": name, "symbol": symbol,
            "price": price, "market_cap": mc, "volume_24h": vol,
            "volume_change": vc, "price_change_1h": pc1h,
            "price_change_24h": pc24, "price_change_7d": pc7d,
            "rank": coin.get("cmc_rank",999),
            "num_market_pairs": coin.get("num_market_pairs",0),
        })
    return result


# ==================== تحليل عملة واحدة ====================
async def analyze_coin(session, coin_data):
    candles = await fetch_binance_klines(session, coin_data["symbol"])
    result  = calculate_score(candles, coin_data)
    score   = result["score"]
    if score < MIN_SCORE: return None
    rvol = result["details"].get("rvol", 1.0)
    if rvol < MIN_RVOL and len(candles) > 5: return None
    coin_data.update({
        "score":   score,
        "reasons": result["reasons"],
        "details": result["details"],
        "rvol":    rvol,
    })
    return coin_data


# ==================== بناء الرسالة الكاملة ====================
def build_message(coins, scan_time, part=1, total=1):
    lines = []
    if part == 1:
        lines += [
            "🚀 Altcoin Smart Scanner — Pre-Pump Signals",
            f"⏰ {scan_time}",
            f"🎯 إجمالي الإشارات: {len(coins)} عملة",
            "━━━━━━━━━━━━━━━━━━━━", ""
        ]

    for c in coins:
        pc    = c["price_change_24h"]
        p1h   = c["price_change_1h"]
        vc    = c["volume_change"]
        score = c.get("score", 0)
        rvol  = c.get("rvol", 1.0)
        reasons = c.get("reasons", [])
        details = c.get("details", {})
        pairs = c["num_market_pairs"]

        arrow = "🟢" if pc > 0 else "🔴"

        # قوة الإشارة
        if score >= 90:   strength = "🔥🔥🔥 قوية جداً"
        elif score >= 80: strength = "🔥🔥 قوية"
        else:             strength = "🔥 جيدة"

        # تفاصيل تقنية
        extras = []
        if details.get("squeeze"):               extras.append("Squeeze")
        if details.get("breakout"):              extras.append("Breakout")
        if details.get("absorption"):            extras.append("امتصاص بيع")
        if details.get("vol_trend"):             extras.append("فوليم متصاعد")
        if details.get("green_streak",0) >= 3:   extras.append("3 شموع خضر")
        if details.get("atr_dir") == "rising":   extras.append("ATR↗")
        if details.get("sideways"):              extras.append("Sideways→Breakout")

        lines.append(f"{arrow} {c['symbol']} — {escape_md(c['name'])}  |  CMC #{c['rank']}")
        lines.append(f"   💵 السعر: {fmt_price(c['price'])}  ({pc:+.1f}%)  |  1h: {p1h:+.1f}%  |  7d: {c['price_change_7d']:+.1f}%")
        lines.append(f"   🎯 النقاط: {score}/100  —  {strength}")
        lines.append(f"   📊 RVOL: {rvol:.1f}x  |  فوليم 24h الكلي: {fmt_vol(c['volume_24h'])}  ({vc:+.0f}%)")
        lines.append(f"   🌐 المنصات: {pairs}  |  Market Cap: {fmt_vol(c['market_cap'])}")
        if reasons:
            lines.append(f"   ✅ {' | '.join(reasons[:4])}")
        if extras:
            lines.append(f"   📌 {' · '.join(extras)}")
        lines.append(f"   🔗 https://www.tradingview.com/chart/?symbol=BINANCE:{c['symbol']}USDT")
        lines.append("")

    if part == total:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📡 CMC (كل المنصات) + Binance Technical Analysis")

    return "\n".join(lines)


# ==================== أمر تحليل عملة محددة ====================
async def get_coin_info(symbol):
    symbol = symbol.upper().strip()
    async with aiohttp.ClientSession() as session:
        url     = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
        headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}
        params  = {"limit": 500, "convert": "USD", "sort": "volume_24h"}
        try:
            async with session.get(url, headers=headers, params=params,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json()
        except:
            return f"❌ فشل جلب بيانات {symbol}"

        coin = next((c for c in data.get("data",[]) if c.get("symbol")==symbol), None)
        if not coin:
            return f"❌ العملة {symbol} مش موجودة أو حجمها صغير جداً"

        q    = coin.get("quote",{}).get("USD",{})
        vol  = float(q.get("volume_24h",0) or 0)
        price= float(q.get("price",0) or 0)
        pc24 = float(q.get("percent_change_24h",0) or 0)
        pc1h = float(q.get("percent_change_1h",0) or 0)
        pc7d = float(q.get("percent_change_7d",0) or 0)
        mc   = float(q.get("market_cap",0) or 0)
        vc   = float(q.get("volume_change_24h",0) or 0)
        pairs= coin.get("num_market_pairs",0)
        rank = coin.get("cmc_rank",999)

        candles      = await fetch_binance_klines(session, symbol, limit=48)
        rvol         = calc_rvol(candles) if candles else 1.0
        atr, atr_dir = calc_atr(candles)  if candles else (0,"unknown")
        bb           = calc_bollinger(candles) if candles else {"width":0,"squeeze":False}
        vol_trend    = calc_vol_trend(candles) if candles else False
        absorption   = calc_absorption(candles) if candles else False
        breakout     = calc_breakout(candles) if candles else {"breakout":False}
        sideways     = calc_sideways(candles) if candles else False

        arrow = "🟢" if pc24 > 0 else "🔴"
        lines = [
            f"🔍 تحليل {symbol} — {escape_md(coin.get('name',''))}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"{arrow} السعر: {fmt_price(price)}  ({pc24:+.2f}%)",
            f"⏱ آخر ساعة: {pc1h:+.2f}%  |  7 أيام: {pc7d:+.2f}%",
            f"",
            f"💰 حجم التداول 24h الكلي (كل المنصات):",
            f"   {fmt_vol(vol)}  (تغيير: {vc:+.0f}%)",
            f"🌐 عدد المنصات: {pairs}  |  Market Cap: {fmt_vol(mc)}",
            f"📊 رانك CMC: #{rank}",
            f"",
            f"📈 التحليل التقني:",
            f"   RVOL: {rvol:.2f}x  {'✅' if rvol>=MIN_RVOL else '⚠️'}",
            f"   ATR: {'↗️ ارتفاع' if atr_dir=='rising' else '↘️ هبوط' if atr_dir=='falling' else '➡️ ثابت'}",
            f"   Bollinger Width: {bb['width']:.1f}%  {'🔴 Squeeze!' if bb['squeeze'] else ''}",
            f"   Breakout: {'✅' if breakout['breakout'] else '❌'}  |  Sideways: {'✅' if sideways else '❌'}",
            f"   امتصاص بيع: {'✅' if absorption else '❌'}  |  فوليم متصاعد: {'✅' if vol_trend else '❌'}",
        ]

        if candles and len(candles) >= 10:
            coin_dict = {
                "symbol":symbol,"price":price,"volume_24h":vol,"volume_change":vc,
                "price_change_24h":pc24,"price_change_1h":pc1h,"price_change_7d":pc7d,
                "rank":rank,"num_market_pairs":pairs,"market_cap":mc,
                "name":coin.get("name",""),"id":coin.get("id")
            }
            res     = calculate_score(candles, coin_dict)
            score   = res["score"]
            reasons = res["reasons"]
            lines += [
                f"",
                f"🎯 نقاط الإشارة: {score}/100",
                f"   {'🚀 إشارة قوية!' if score>=MIN_SCORE else '😴 لا إشارة بعد'}",
            ]
            if reasons:
                lines.append(f"   الأسباب: {' | '.join(reasons[:4])}")

        lines += [
            f"",
            f"🔗 https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        return "\n".join(lines)


# ==================== المسح الرئيسي ====================
async def scan_markets(bot: Bot):
    global previous_data, previous_volume
    logger.info("🔍 بدء المسح الذكي...")
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async with aiohttp.ClientSession() as session:
        raw_coins = await fetch_cmc_listings(session)
        if not raw_coins:
            await bot.send_message(chat_id=CHAT_ID, text="⚠️ فشل جلب البيانات من CMC")
            return

        candidates = parse_cmc_coins(raw_coins)
        logger.info(f"📋 مرشحون: {len(candidates)}")

        tasks   = [analyze_coin(session, c) for c in candidates[:80]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    hot_coins = [r for r in results if r and not isinstance(r, Exception)]
    hot_coins.sort(key=lambda x: x.get("score",0), reverse=True)
    hot_coins = hot_coins[:TOP_RESULTS_DISPLAY]

    logger.info(f"🚀 إشارات: {len(hot_coins)}")
    previous_data   = {c["symbol"]: c for c in hot_coins}
    previous_volume = {c["symbol"]: c["volume_24h"] for c in hot_coins}

    if not hot_coins:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"😴 لا توجد إشارات قوية الآن (score < {MIN_SCORE})\n⏰ {scan_time}"
        )
        return

    chunk_size = 8
    chunks = [hot_coins[i:i+chunk_size] for i in range(0, len(hot_coins), chunk_size)]
    total  = len(chunks)

    for idx, chunk in enumerate(chunks, 1):
        msg = build_message(chunk, scan_time, part=idx, total=total)
        try:
            await bot.send_message(chat_id=CHAT_ID, text=msg, disable_web_page_preview=True)
            logger.info(f"✅ رسالة {idx}/{total}")
            await asyncio.sleep(0.8)
        except Exception as e:
            logger.error(f"❌ خطأ: {e}")


async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    await scan_markets(context.bot)


# ==================== أوامر البوت ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Altcoin Smart Scanner Bot\n"
        "دمج حجم التداول الكلي + التحليل التقني\n\n"
        "الأوامر:\n"
        "/scan     — مسح فوري الآن\n"
        "/coin ETH — تحليل كامل لعملة محددة
/vol ETH  — حجم التداول الكلي فقط\n"
        "/top      — أفضل 5 إشارات\n"
        "/status   — حالة البوت\n"
        "/chatid   — معرفة الـ Chat ID\n\n"
        "نظام النقاط:\n"
        f"RVOL={SCORE_RVOL} | Squeeze={SCORE_SQUEEZE} | Breakout={SCORE_BREAKOUT}\n"
        f"Absorption={SCORE_ABSORPTION} | Momentum={SCORE_MOMENTUM}\n"
        f"الحد الأدنى للإشارة: {MIN_SCORE}/100"
    )

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري المسح الذكي... (قد يأخذ دقيقة)")
    await scan_markets(context.bot)

async def cmd_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم: /coin اسم_العملة\nمثال: /coin ETH")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 جاري تحليل {symbol}...")
    result = await get_coin_info(symbol)
    await update.message.reply_text(result, disable_web_page_preview=True)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not previous_data:
        await update.message.reply_text("⏳ لم يتم المسح بعد، استخدم /scan")
        return
    top5  = sorted(previous_data.values(), key=lambda x: x.get("score",0), reverse=True)[:5]
    lines = ["🏆 أفضل 5 إشارات:\n"]
    for i, c in enumerate(top5, 1):
        lines.append(
            f"{i}. {c['symbol']}  نقاط: {c.get('score',0)}/100\n"
            f"   فوليم: {fmt_vol(c['volume_24h'])}  ({c['price_change_24h']:+.1f}%)"
        )
    await update.message.reply_text("\n".join(lines))

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"✅ البوت شغال\n"
        f"📊 إشارات نشطة: {len(previous_data)}\n"
        f"⏱ مسح كل {SCAN_INTERVAL_MINUTES} دقيقة\n"
        f"🎯 الحد الأدنى: {MIN_SCORE}/100\n"
        f"📡 CMC (كل المنصات) + Binance TA"
    )

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):

async def cmd_vol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم: /vol اسم_العملة\nمثال: /vol ETH")
        return
    symbol = context.args[0].upper().strip()
    await update.message.reply_text(f"🔍 جاري جلب حجم تداول {symbol}...")
    async with aiohttp.ClientSession() as session:
        url     = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
        headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}
        params  = {"limit": 500, "convert": "USD", "sort": "volume_24h"}
        try:
            async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json()
        except:
            await update.message.reply_text("❌ فشل الاتصال بـ CMC"); return
        coin = next((c for c in data.get("data", []) if c.get("symbol") == symbol), None)
        if not coin:
            await update.message.reply_text(f"❌ العملة {symbol} مش موجودة في أول 500 عملة"); return
        q     = coin.get("quote", {}).get("USD", {})
        vol   = float(q.get("volume_24h", 0) or 0)
        vc    = float(q.get("volume_change_24h", 0) or 0)
        price = float(q.get("price", 0) or 0)
        pc24  = float(q.get("percent_change_24h", 0) or 0)
        pc1h  = float(q.get("percent_change_1h", 0) or 0)
        mc    = float(q.get("market_cap", 0) or 0)
        pairs = coin.get("num_market_pairs", 0)
        rank  = coin.get("cmc_rank", 999)
        name  = coin.get("name", "")
        arrow = "🟢" if pc24 > 0 else "🔴"
        msg = (f"📊 حجم تداول {symbol} — {escape_md(name)}\n"
               f"━━━━━━━━━━━━━━━━━━━━\n"
               f"{arrow} السعر: {fmt_price(price)}  ({pc24:+.2f}%)\n"
               f"⏱ آخر ساعة: {pc1h:+.2f}%\n\n"
               f"💰 حجم التداول 24h الكلي (كل المنصات):\n"
               f"   {fmt_vol(vol)}\n"
               f"   تغيير الحجم: {vc:+.1f}%\n\n"
               f"🌐 عدد المنصات: {pairs}\n"
               f"💎 Market Cap: {fmt_vol(mc)}\n"
               f"📊 رانك CMC: #{rank}\n"
               f"━━━━━━━━━━━━━━━━━━━━\n"
               f"⏰ {datetime.now().strftime("%Y-%m-%d %H:%M")}\n"
               f"📡 CoinMarketCap (كل المنصات)")
        await update.message.reply_text(msg)
    await update.message.reply_text(f"Chat ID:\n{update.effective_chat.id}")


# ==================== تشغيل البوت ====================
def main():
    if "ضع_" in TELEGRAM_TOKEN:
        print("❌ حط التوكن الصح في TELEGRAM_TOKEN"); return
    if "ضع_" in CMC_API_KEY:
        print("❌ حط CMC API Key في CMC_API_KEY"); return

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("coin",   cmd_coin))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("vol",    cmd_vol))
    app.add_handler(CommandHandler("chatid", cmd_chatid))

    app.job_queue.run_repeating(scheduled_scan,
                                interval=SCAN_INTERVAL_MINUTES*60, first=15)

    print("="*55)
    print("🚀 Altcoin Smart Scanner Bot شغال!")
    print(f"⏱  مسح كل {SCAN_INTERVAL_MINUTES} دقيقة")
    print(f"🎯 الحد الأدنى: {MIN_SCORE}/100")
    print("📡 CoinMarketCap (كل المنصات) + Binance TA")
    print("="*55)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
