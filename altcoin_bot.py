"""
🚀 Altcoin Volume Alert Bot - CoinMarketCap Edition
"""

import asyncio
import aiohttp
import logging
import sys
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==================== الإعدادات ====================
TELEGRAM_TOKEN = "8794878965:AAEZR3MdSG-3OiGBeR05q9MJzvvo1ODmNmc"
CHAT_ID        = "6914157653"
CMC_API_KEY    = "7eeaf1fd132e416ab49279ee21cc6ce0"

# ==================== معايير الفلترة ====================
MIN_VOLUME_USD        = 5_000_000    # حجم تداول minimum 5 مليون دولار
MIN_PRICE_CHANGE_PCT  = 2.0          # تغيير سعر minimum 2%
MAX_MARKET_CAP_USD    = 2_000_000_000 # استبعاد العملات فوق 2 مليار market cap
SCAN_INTERVAL_MINUTES = 240          # كل 4 ساعات
TOP_COINS_LIMIT       = 500          # بنجيب أول 500 عملة من CMC
TOP_RESULTS_DISPLAY   = 30           # عدد العملات في الرسالة

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
previous_data: dict = {}

# ==================== قوائم الاستبعاد ====================
EXCLUDED_SYMBOLS = {
    "BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","AVAX","SHIB",
    "DOT","LINK","MATIC","LTC","BCH","XLM","ETC","UNI","ATOM","NEAR",
    "FIL","ICP","HBAR","VET","ALGO","EGLD","TON","SUI","APT","OP",
    "ARB","INJ","SEI","TIA","PYTH","JUP","WLD",
    # Stablecoins
    "USDT","USDC","BUSD","DAI","TUSD","USDP","USDD","FDUSD",
    "USDE","PYUSD","GUSD","LUSD","FRAX","SUSD","EURC","USDS",
    # Wrapped
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
def is_meme_coin(symbol: str, name: str, tags: list) -> bool:
    if symbol in MEME_SYMBOLS:
        return True
    if tags and any(t in MEME_TAGS for t in tags):
        return True
    sym_lower  = symbol.lower()
    name_lower = name.lower()
    for kw in MEME_KEYWORDS:
        if kw in sym_lower or kw in name_lower:
            return True
    return False


# ==================== جلب البيانات ====================
async def fetch_cmc_listings(session: aiohttp.ClientSession) -> list:
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}
    params  = {
        "limit": TOP_COINS_LIMIT,
        "convert": "USD",
        "sort": "volume_24h",
        "sort_dir": "desc",
    }
    try:
        async with session.get(url, headers=headers, params=params,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status == 401:
                logger.error("❌ CMC API Key غلط!")
                return []
            if r.status == 429:
                logger.error("❌ تجاوزت حد الـ API calls!")
                return []
            data = await r.json()
        coins = data.get("data", [])
        logger.info(f"✅ CMC: جلب {len(coins)} عملة")
        return coins
    except Exception as e:
        logger.error(f"❌ CMC error: {e}")
        return []


# ==================== تحليل البيانات ====================
def parse_coins(raw_coins: list) -> list:
    result = []
    for coin in raw_coins:
        symbol = coin.get("symbol", "")
        name   = coin.get("name", "")
        tags   = [t.lower() for t in coin.get("tags", [])]

        if symbol in EXCLUDED_SYMBOLS:
            continue
        if is_meme_coin(symbol, name, tags):
            continue

        quote        = coin.get("quote", {}).get("USD", {})
        volume_24h   = float(quote.get("volume_24h", 0) or 0)
        market_cap   = float(quote.get("market_cap", 0) or 0)
        price_change = float(quote.get("percent_change_24h", 0) or 0)
        vol_change   = float(quote.get("volume_change_24h", 0) or 0)
        price        = float(quote.get("price", 0) or 0)
        change_7d    = float(quote.get("percent_change_7d", 0) or 0)
        change_1h    = float(quote.get("percent_change_1h", 0) or 0)

        # فلترة الحجم
        if volume_24h < MIN_VOLUME_USD:
            continue

        # فلترة market cap (لو موجود بس كبير أوي نستبعده)
        if market_cap > MAX_MARKET_CAP_USD:
            continue

        # فلترة تغيير السعر
        if abs(price_change) < MIN_PRICE_CHANGE_PCT:
            continue

        result.append({
            "id":               coin.get("id"),
            "name":             name,
            "symbol":           symbol,
            "price":            price,
            "market_cap":       market_cap,
            "volume_24h":       volume_24h,
            "volume_change":    vol_change,
            "price_change_1h":  change_1h,
            "price_change_24h": price_change,
            "price_change_7d":  change_7d,
            "rank":             coin.get("cmc_rank", 999),
            "num_market_pairs": coin.get("num_market_pairs", 0),
        })

    result.sort(key=lambda x: x["volume_24h"], reverse=True)
    return result


# ==================== بناء الرسالة ====================
def fmt_vol(v: float) -> str:
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.2f}B$"
    elif v >= 1_000_000:
        return f"{v/1_000_000:.2f}M$"
    return f"{v/1_000:.1f}K$"


def fmt_price(p: float) -> str:
    if p >= 1:      return f"${p:.4f}"
    if p >= 0.001:  return f"${p:.6f}"
    return f"${p:.8f}"


def escape_md(text: str) -> str:
    """تنظيف أي حرف ممكن يكسر الـ Markdown"""
    for ch in ['_', '*', '[', ']', '`']:
        text = text.replace(ch, '')
    return text


def build_message(coins: list, scan_time: str, part: int = 1, total_parts: int = 1) -> str:
    lines = []
    if part == 1:
        lines += [
            "🔥 Altcoins الساخنة - فوليم كلي من كل المنصات",
            f"⏰ {scan_time}",
            f"📊 المصدر: CoinMarketCap | إجمالي: {len(coins)} عملة",
            "━━━━━━━━━━━━━━━━━━━━", ""
        ]

    for c in coins:
        pc  = c["price_change_24h"]
        vc  = c["volume_change"]
        p1h = c["price_change_1h"]
        arrow = "🟢" if pc > 0 else "🔴"
        pc_str = f"+{pc:.1f}%" if pc > 0 else f"{pc:.1f}%"
        vc_str = f"+{vc:.0f}%" if vc > 0 else f"{vc:.0f}%"
        p1h_str = f"+{p1h:.1f}%" if p1h > 0 else f"{p1h:.1f}%"

        name_clean = escape_md(c['name'])

        lines.append(f"{arrow} {c['symbol']} — {name_clean}  |  رانك #{c['rank']}")
        lines.append(f"   💵 {fmt_price(c['price'])}  ({pc_str})  |  1h: {p1h_str}")
        lines.append(f"   💰 فوليم: {fmt_vol(c['volume_24h'])}  (حجم: {vc_str})")
        lines.append(f"   🌐 {c['num_market_pairs']} منصة  |  7d: {c['price_change_7d']:+.1f}%")
        lines.append("")

    if part == total_parts:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📡 CoinMarketCap — فوليم مجمّع من كل المنصات")

    return "\n".join(lines)


# ==================== المسح الرئيسي ====================
async def scan_markets(bot: Bot):
    global previous_data
    logger.info("🔍 بدء مسح السوق...")
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async with aiohttp.ClientSession() as session:
        raw_coins = await fetch_cmc_listings(session)

    if not raw_coins:
        logger.warning("⚠️ لم يتم جلب بيانات من CMC")
        try:
            await bot.send_message(chat_id=CHAT_ID, text="⚠️ فشل جلب البيانات من CMC، هحاول مرة ثانية في الساعة الجاية.")
        except Exception as e:
            logger.error(f"خطأ في إرسال تنبيه الفشل: {e}")
        return

    hot_coins = parse_coins(raw_coins)
    logger.info(f"🔥 عملات ساخنة بعد الفلترة: {len(hot_coins)}")
    previous_data = {c["symbol"]: c for c in hot_coins}

    if not hot_coins:
        logger.info("😴 لا توجد عملات تستوفي المعايير الآن")
        try:
            await bot.send_message(chat_id=CHAT_ID, text=f"😴 لا توجد altcoins ساخنة الآن\n⏰ {scan_time}")
        except Exception as e:
            logger.error(f"خطأ: {e}")
        return

    # تقسيم الرسائل (كل رسالة 10 عملات عشان ما تتجاوزش حد تليجرام)
    chunk_size = 15
    chunks = [hot_coins[i:i+chunk_size] for i in range(0, min(len(hot_coins), TOP_RESULTS_DISPLAY), chunk_size)]
    total  = len(chunks)

    for idx, chunk in enumerate(chunks, 1):
        msg = build_message(chunk, scan_time, part=idx, total_parts=total)
        try:
            await bot.send_message(chat_id=CHAT_ID, text=msg)
            logger.info(f"✅ إرسال رسالة {idx}/{total}")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"❌ خطأ في الإرسال {idx}: {e}")


async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    await scan_markets(context.bot)


# ==================== أوامر البوت ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Altcoin Volume Alert Bot\n"
        "فوليم مجمّع من كل المنصات عبر CoinMarketCap\n\n"
        "الأوامر:\n"
        "/scan — مسح فوري الآن\n"
        "/top — أفضل 5 عملات\n"
        "/status — حالة البوت\n"
        "/chatid — معرفة الـ Chat ID"
    )

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري مسح السوق...")
    await scan_markets(context.bot)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not previous_data:
        await update.message.reply_text("⏳ لم يتم المسح بعد، استخدم /scan")
        return
    top5 = sorted(previous_data.values(), key=lambda x: x["volume_24h"], reverse=True)[:5]
    lines = ["🏆 أفضل 5 عملات حالياً:\n"]
    for i, c in enumerate(top5, 1):
        pc = c["price_change_24h"]
        lines.append(f"{i}. {c['symbol']} — {fmt_vol(c['volume_24h'])}  ({pc:+.1f}%)")
    await update.message.reply_text("\n".join(lines))

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"✅ البوت شغال\n"
        f"📊 عملات مرصودة: {len(previous_data)}\n"
        f"⏱ مسح كل {SCAN_INTERVAL_MINUTES} دقيقة\n"
        f"📡 المصدر: CoinMarketCap API"
    )

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID:\n{update.effective_chat.id}")


# ==================== تشغيل البوت ====================
def main():
    if "ضع_" in TELEGRAM_TOKEN:
        print("❌ حط التوكن الصح في TELEGRAM_TOKEN")
        return
    if "ضع_" in CMC_API_KEY:
        print("❌ حط CMC API Key في CMC_API_KEY")
        print("احصل على مفتاح مجاني من: https://pro.coinmarketcap.com/signup")
        return

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("chatid", cmd_chatid))

    app.job_queue.run_repeating(
        scheduled_scan,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=10
    )

    print("=" * 55)
    print("🚀 Altcoin Volume Alert Bot شغال!")
    print(f"⏱  مسح كل {SCAN_INTERVAL_MINUTES} دقيقة")
    print("📡 CoinMarketCap — كل المنصات")
    print("=" * 55)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
