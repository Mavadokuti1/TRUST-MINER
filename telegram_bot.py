"""
telegram_bot.py — Trust-Miner Telegram Bot (Webhook edition)
=============================================================
Runs as a single Render **Free Web Service**:

  • Telegram commands are delivered via WEBHOOK (not long-polling), so the
    service can sleep when idle and Telegram wakes it with an HTTP POST.
  • An HTTP GET /trigger-ingest endpoint lets an external scheduler
    (e.g. cron-job.org) run the daily scrape + clean broadcast once a day.

Commands:
  /start           — Register the user and show a welcome message.
  /price <amount>  — Find top 3 deals priced at or below <amount> USD.
  /stats           — Show total deals count and active categories.

HTTP routes:
  GET  /                 — human-readable liveness string
  GET  /healthz          — JSON health check
  GET  /trigger-ingest   — run daily_ingest + broadcaster (optional ?key=)
  POST /webhook/<token>  — Telegram update delivery

Environment:
  BOT_TOKEN            (required in production)  — from @BotFather
  AFFILIATE_TAG        (optional)                — TrustMRR referral tag
  WEBHOOK_URL          (production)              — public base URL of the service
  DB_PATH              (optional)                — SQLite path
  INGEST_SECRET        (optional)                — guards /trigger-ingest
  TEST_MODE=1          (local verification only) — serve HTTP without live Telegram
  SKIP_INGEST_ON_TRIGGER=1 (local only)          — /trigger-ingest broadcasts only
"""

import asyncio
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from aiohttp import web
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from setup_db import init_db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TEST_MODE: bool = os.getenv("TEST_MODE") == "1"
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
AFFILIATE_TAG: str = os.getenv("AFFILIATE_TAG", "")
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "").rstrip("/")
DB_PATH: Path = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "trustmrr_deals.db")))
PORT: int = int(os.getenv("PORT", "10000"))

# NOTE: A missing/invalid BOT_TOKEN must NOT crash the process. On Render a crash
# at boot means the web server never binds, so the router returns "Not Found" (404)
# for every path — including /healthz. Instead we bind the HTTP server first and
# wire Telegram concurrently, swallowing any Telegram failure (see run()).

# Set once Telegram is wired; stays None in TEST_MODE / HTTP-only / on failure.
application: Application | None = None


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_connection() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def register_subscriber(chat_id: int) -> None:
    with get_connection() as con:
        con.execute(
            "INSERT OR IGNORE INTO subscribers (chat_id, joined_at) VALUES (?, ?)",
            (chat_id, datetime.now(timezone.utc).isoformat()),
        )


def query_deals_by_price(max_price: float) -> list[sqlite3.Row]:
    with get_connection() as con:
        return con.execute(
            """
            SELECT slug, name, price, mrr, revenue_30d, multiple,
                   category, payment_provider, profit_margin,
                   listing_tier, country
            FROM   deals
            WHERE  price IS NOT NULL AND price <= ? AND on_sale = 1
            ORDER  BY multiple ASC
            LIMIT  3
            """,
            (max_price,),
        ).fetchall()


def get_stats() -> dict:
    with get_connection() as con:
        total = con.execute("SELECT COUNT(*) AS c FROM deals").fetchone()["c"]
        for_sale = con.execute("SELECT COUNT(*) AS c FROM deals WHERE on_sale = 1").fetchone()["c"]
        with_price = con.execute("SELECT COUNT(*) AS c FROM deals WHERE price IS NOT NULL").fetchone()["c"]
        cats = con.execute(
            """
            SELECT category, COUNT(*) AS n FROM deals
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category ORDER BY n DESC LIMIT 8
            """
        ).fetchall()
        cheapest = con.execute(
            """
            SELECT name, price, multiple FROM deals
            WHERE price IS NOT NULL AND on_sale = 1
            ORDER BY price ASC LIMIT 1
            """
        ).fetchone()
    return {
        "total_deals": total,
        "for_sale": for_sale,
        "with_price": with_price,
        "categories": [(r["category"], r["n"]) for r in cats],
        "cheapest": cheapest,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def build_affiliate_url(slug: str) -> str:
    base = f"https://trustmrr.com/startup/{slug}"
    return f"{base}?ref={AFFILIATE_TAG}" if AFFILIATE_TAG else base


def format_deal(row: sqlite3.Row, rank: int) -> str:
    price = f"${row['price']:,.0f}" if row["price"] else "N/A"
    mrr = f"${row['mrr']:,.0f}/mo" if row["mrr"] else "N/A"
    multiple = f"{row['multiple']:.2f}x" if row["multiple"] else "N/A"
    category = row["category"] or "Uncategorised"
    tier = (row["listing_tier"] or "standard").title()
    url = build_affiliate_url(row["slug"])
    return (
        f"*#{rank} — {row['name']}* [{tier}]\n"
        f"💰 Price: {price}\n"
        f"📈 MRR: {mrr}\n"
        f"✖️ Multiple: {multiple}\n"
        f"🏷 Category: {category}\n"
        f"🔗 [View Listing]({url})\n"
    )


def build_welcome_message(first_name: str) -> str:
    """High-converting /start welcome: leads with value, adds gentle urgency, and
    ends with a clear share + notify call-to-action. No hype, no false promises."""
    return (
        f"👋 *Welcome aboard, {first_name}!*\n\n"
        "You just joined *TRUST-MINER* — your daily edge for spotting profitable "
        "micro-SaaS businesses *before everyone else does.*\n\n"
        "Every day I hand you:\n"
        "✅ Real acquisition deals with *verified MRR*\n"
        "✅ The *lowest valuation multiples* — best value first\n"
        "✅ Direct links to view financials and make an offer\n\n"
        "⚡️ *Fresh deals drop daily at 8:00 AM.* The strongest ones get claimed "
        "fast, so the early movers win.\n\n"
        "*Try it right now:*\n"
        "🔍 `/price 5000` — top deals under your budget\n"
        "📊 `/stats` — what's on the market today\n\n"
        "🔔 *Tap the bell to turn on notifications* so you never miss a drop.\n"
        "📲 *Know a founder hunting for a business?* Forward this channel — "
        "great deals are better shared.\n\n"
        "Happy hunting! 🚀"
    )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    try:
        register_subscriber(chat_id)
        log.info("New subscriber: chat_id=%s", chat_id)
    except sqlite3.Error as exc:
        log.error("Failed to register subscriber %s: %s", chat_id, exc)

    first_name = user.first_name if user else "there"
    welcome = build_welcome_message(first_name)
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ Provide a budget. Example: `/price 5000`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        max_price = float(context.args[0].replace(",", "").replace("$", ""))
        if max_price <= 0:
            raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_text("⚠️ Invalid amount. Example: `/price 10000`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        deals = query_deals_by_price(max_price)
    except sqlite3.Error as exc:
        log.error("DB error in /price: %s", exc)
        await update.message.reply_text("❌ Database error. Please try again later.")
        return
    if not deals:
        await update.message.reply_text(f"😔 No deals found under ${max_price:,.0f}.")
        return
    header = f"🎯 *Top {len(deals)} deals under ${max_price:,.0f}*\n\n"
    body = "\n─────────────────────\n".join(format_deal(r, i + 1) for i, r in enumerate(deals))
    await update.message.reply_text(header + body, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        stats = get_stats()
    except sqlite3.Error as exc:
        log.error("DB error in /stats: %s", exc)
        await update.message.reply_text("❌ Database error. Please try again later.")
        return
    cats = stats["categories"]
    cat_lines = "\n".join(f"  • {n} ({c})" for n, c in cats) if cats else "  _None yet_"
    cheapest = stats["cheapest"]
    cheapest_line = ""
    if cheapest:
        mult = f"{cheapest['multiple']:.2f}x" if cheapest["multiple"] else "N/A"
        cheapest_line = f"\n💡 *Cheapest:* {cheapest['name']} — ${cheapest['price']:,.0f} | {mult}\n"
    message = (
        f"📊 *Trust-Miner Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 Total in DB: *{stats['total_deals']}*\n"
        f"🔥 For Sale: *{stats['for_sale']}*\n"
        f"💰 With Price: *{stats['with_price']}*\n"
        f"{cheapest_line}\n"
        f"🗂 Top Categories:\n{cat_lines}"
    )
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Ingest + broadcast (runs in a worker thread; no blocking of the event loop)
# ---------------------------------------------------------------------------
# Second layer of duplicate protection: a non-blocking lock. /trigger-ingest runs
# in a thread-pool executor, so two overlapping cron hits on the same warm instance
# would spawn two threads. The first grabs the lock and runs; the second fails the
# non-blocking acquire and returns immediately without a wasteful second ingest.
# (The atomic per-day claim in broadcaster.broadcast() covers the sequential-retry
# case where the first run already finished and released this lock.)
_ingest_lock = threading.Lock()


def _do_ingest_and_broadcast() -> dict:
    if not _ingest_lock.acquire(blocking=False):
        log.warning(
            "An ingest+broadcast run is already in progress — ignoring this concurrent "
            "/trigger-ingest so the day's deals are not posted twice."
        )
        return {"status": "ignored", "reason": "run_already_in_progress"}
    try:
        summary: dict = {}
        if os.getenv("SKIP_INGEST_ON_TRIGGER") == "1":
            summary["ingest"] = "skipped"
        else:
            from daily_ingest import run_ingest

            try:
                run_ingest()
                summary["ingest"] = "done"
            except Exception as exc:
                # A transient ingest/network failure must never abort the day's broadcast or
                # crash the service — log it and broadcast whatever is already in the DB.
                log.exception("Ingest failed; broadcasting cached deals instead: %s", exc)
                summary["ingest"] = "failed"
        from broadcaster import broadcast

        summary["broadcast"] = broadcast()
        return summary
    finally:
        _ingest_lock.release()


# ---------------------------------------------------------------------------
# RSS feed (passive discoverability — latest deals as standard RSS 2.0)
# ---------------------------------------------------------------------------
def get_recent_deals_for_feed(limit: int = 10) -> list[sqlite3.Row]:
    with get_connection() as con:
        return con.execute(
            """
            SELECT slug, name, description, price, mrr, multiple, category, url, last_updated
            FROM   deals
            WHERE  on_sale = 1 AND price IS NOT NULL
            ORDER  BY last_updated DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()


def _feed_deal_url(row: sqlite3.Row) -> str:
    base = row["url"] or f"https://trustmrr.com/startup/{row['slug']}"
    if AFFILIATE_TAG:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}ref={AFFILIATE_TAG}"
    return base


def _rss_pubdate(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)
    return format_datetime(dt)


def build_rss(deals: list[sqlite3.Row], base_url: str) -> str:
    """Render the latest deals as a standards-compliant RSS 2.0 document."""
    now = format_datetime(datetime.now(timezone.utc))
    root = base_url.rstrip("/")
    items: list[str] = []
    for d in deals:
        price = f"${d['price']:,.0f}" if d["price"] else "N/A"
        mrr = f"${d['mrr']:,.0f}/mo" if d["mrr"] else "N/A"
        mult = f"{d['multiple']:.2f}x" if d["multiple"] is not None else "N/A"
        cat = d["category"] or "Software"
        title = f"{d['name']} — {mrr} MRR, asking {price} ({mult})"
        desc = (
            f"{d['name']} is a {cat} micro-SaaS currently for sale. "
            f"MRR: {mrr}. Asking price: {price}. Valuation multiple: {mult}. "
            f"View the full financials and make an offer."
        )
        items.append(
            "    <item>\n"
            f"      <title>{escape(title)}</title>\n"
            f"      <link>{escape(_feed_deal_url(d))}</link>\n"
            f"      <guid isPermaLink=\"false\">{escape(d['slug'])}</guid>\n"
            f"      <category>{escape(cat)}</category>\n"
            f"      <pubDate>{_rss_pubdate(d['last_updated'])}</pubDate>\n"
            f"      <description>{escape(desc)}</description>\n"
            "    </item>"
        )
    items_xml = "\n".join(items)
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<rss version=\"2.0\" xmlns:atom=\"http://www.w3.org/2005/Atom\">\n"
        "  <channel>\n"
        "    <title>TRUST-MINER — Daily Micro-SaaS Deals</title>\n"
        f"    <link>{escape(root)}</link>\n"
        f"    <atom:link href=\"{escape(root + '/feed.xml')}\" rel=\"self\" type=\"application/rss+xml\"/>\n"
        "    <description>Hand-picked micro-SaaS and startup acquisition deals from TrustMRR, refreshed daily.</description>\n"
        "    <language>en-us</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        "    <ttl>720</ttl>\n"
        f"{items_xml}\n"
        "  </channel>\n"
        "</rss>\n"
    )


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------
async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="TRUST-MINER bot is alive.")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response(
        {"status": "ok", "test_mode": TEST_MODE, "telegram": application is not None}
    )


async def handle_feed(request: web.Request) -> web.Response:
    try:
        deals = get_recent_deals_for_feed(10)
    except sqlite3.Error as exc:
        log.error("/feed.xml DB error: %s", exc)
        deals = []
    base = WEBHOOK_URL or f"{request.scheme}://{request.host}"
    xml = build_rss(deals, base)
    log.info("/feed.xml served %d items.", len(deals))
    return web.Response(text=xml, content_type="application/rss+xml", charset="utf-8")


async def handle_trigger(request: web.Request) -> web.Response:
    required = os.getenv("INGEST_SECRET")
    if required and request.query.get("key") != required:
        log.warning("Rejected /trigger-ingest with missing/invalid key from %s.", request.remote)
        return web.json_response({"error": "unauthorized"}, status=401)
    log.info("/trigger-ingest invoked — starting daily ingest + broadcast.")
    started = datetime.now(timezone.utc)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _do_ingest_and_broadcast)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info("/trigger-ingest completed in %.1fs — %s", elapsed, result)
        return web.json_response({"status": "ok", **result})
    except Exception as exc:
        log.exception("/trigger-ingest failed after %s: %s", datetime.now(timezone.utc) - started, exc)
        return web.json_response({"status": "error", "detail": str(exc)}, status=500)


async def handle_webhook(request: web.Request) -> web.Response:
    if not BOT_TOKEN or request.match_info.get("token") != BOT_TOKEN:
        log.warning("Rejected webhook POST with missing/invalid token from %s.", request.remote)
        return web.Response(status=403, text="forbidden")
    if TEST_MODE or application is None:
        log.warning(
            "Webhook update arrived but Telegram is not wired (test_mode=%s, telegram_ready=%s). "
            "Acknowledging so Telegram does not retry — check BOT_TOKEN / WEBHOOK_URL if this persists.",
            TEST_MODE, application is not None,
        )
        return web.json_response({"status": "ok", "test_mode": True})
    try:
        data = await request.json()
    except Exception as exc:
        log.error("Malformed webhook payload: %s", exc)
        return web.Response(status=400, text="bad request")
    try:
        await application.process_update(Update.de_json(data, application.bot))
    except Exception as exc:
        # Ack with 200 so Telegram doesn't hammer us with retries on a single bad update.
        log.exception("Failed to process Telegram update: %s", exc)
        return web.json_response({"status": "error"})
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
def build_web_app() -> web.Application:
    web_app = web.Application()
    web_app.router.add_get("/", handle_root)
    web_app.router.add_get("/healthz", handle_health)
    web_app.router.add_get("/feed.xml", handle_feed)
    web_app.router.add_get("/trigger-ingest", handle_trigger)
    web_app.router.add_post("/webhook/{token}", handle_webhook)
    return web_app


async def _setup_telegram() -> None:
    """Wire up live Telegram. Any failure here is logged and swallowed so the already-bound
    HTTP server keeps serving — a boot crash would make Render return 404 for all paths."""
    global application
    try:
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("price", cmd_price))
        app.add_handler(CommandHandler("stats", cmd_stats))
        await app.initialize()
        await app.start()
        if WEBHOOK_URL:
            full = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
            await app.bot.set_webhook(
                url=full, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
            )
            log.info("Webhook registered at %s/webhook/***", WEBHOOK_URL)
        else:
            log.warning("WEBHOOK_URL not set — Telegram will not deliver updates until it is.")
        application = app
    except Exception as exc:
        application = None
        log.exception(
            "Telegram initialisation failed (%s). Continuing in HTTP-only mode so the web "
            "service stays reachable; verify BOT_TOKEN / WEBHOOK_URL in the Render dashboard.",
            exc,
        )


async def run() -> None:
    init_db(DB_PATH)

    # Bind the HTTP server FIRST so /healthz answers immediately and the deploy passes
    # Render's health check even if Telegram's API is slow or unreachable. Binds to the
    # port Render provides via $PORT, on all interfaces (0.0.0.0).
    runner = web.AppRunner(build_web_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("HTTP server listening on 0.0.0.0:%d", PORT)

    if TEST_MODE:
        log.info("TEST_MODE enabled — serving HTTP routes without a live Telegram connection.")
    elif not BOT_TOKEN:
        log.error(
            "BOT_TOKEN is not set — running in HTTP-only mode. Telegram commands are DISABLED "
            "until BOT_TOKEN is configured in the Render dashboard. /healthz and /trigger-ingest "
            "remain available."
        )
    else:
        # Wire Telegram concurrently — never block the already-bound server on its handshake.
        asyncio.create_task(_setup_telegram())

    await asyncio.Event().wait()  # run forever


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
