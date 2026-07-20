"""
telegram_bot.py — Trust-Miner Telegram Bot Interface
======================================================
Commands:
  /start           — Register the user and show a welcome message.
  /price <amount>  — Find top 3 deals priced at or below <amount> USD.
  /stats           — Show total deals count and active categories.

Prerequisites:
  1. Copy .env.example → .env and fill in BOT_TOKEN & AFFILIATE_TAG.
  2. Run `python setup_db.py` to initialise the database.
  3. Run `python daily_ingest.py` (or schedule it) to populate deals.
  4. Run `python telegram_bot.py` to start the bot.

Uses python-telegram-bot v21 (async / Application pattern).
"""

import logging
import sqlite3
import sys
import threading
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import os

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()  # Load .env from current working directory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — sourced from .env
# ---------------------------------------------------------------------------
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
AFFILIATE_TAG: str = os.getenv("AFFILIATE_TAG", "")
DB_PATH: Path = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "trustmrr_deals.db")))

if not BOT_TOKEN:
    raise EnvironmentError(
        "BOT_TOKEN is not set. "
        "Copy .env.example → .env and add your Telegram Bot Token."
    )


# ---------------------------------------------------------------------------
# Database Helpers
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    """
    Open and return a new SQLite connection with row_factory set for
    dict-like access to rows.

    Returns:
        sqlite3.Connection with Row factory enabled.
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def register_subscriber(chat_id: int) -> None:
    """
    Insert the user's chat_id into the subscribers table (ignore if duplicate).

    Args:
        chat_id: Telegram chat ID of the user.
    """
    with get_connection() as con:
        con.execute(
            """
            INSERT OR IGNORE INTO subscribers (chat_id, joined_at)
            VALUES (?, ?)
            """,
            (chat_id, datetime.now(timezone.utc).isoformat()),
        )


def query_deals_by_price(max_price: float) -> list[sqlite3.Row]:
    """
    Fetch the top 3 for-sale deals priced at or below *max_price*,
    sorted by ascending multiple (best value ratio first).

    Args:
        max_price: Upper price bound in USD.

    Returns:
        List of sqlite3.Row objects (up to 3 rows).
    """
    with get_connection() as con:
        rows = con.execute(
            """
            SELECT slug, name, price, mrr, revenue_30d, multiple,
                   category, payment_provider, profit_margin,
                   listing_tier, country
            FROM   deals
            WHERE  price IS NOT NULL
              AND  price <= ?
              AND  on_sale = 1
            ORDER  BY multiple ASC NULLS LAST
            LIMIT  3
            """,
            (max_price,),
        ).fetchall()
    return rows


def get_stats() -> dict:
    """
    Return summary statistics about the deals database.

    Returns:
        Dict with keys: total_deals, for_sale, with_price,
        categories (list of (name, count) tuples), cheapest, most_recent.
    """
    with get_connection() as con:
        total = con.execute(
            "SELECT COUNT(*) AS cnt FROM deals"
        ).fetchone()["cnt"]

        for_sale = con.execute(
            "SELECT COUNT(*) AS cnt FROM deals WHERE on_sale = 1"
        ).fetchone()["cnt"]

        with_price = con.execute(
            "SELECT COUNT(*) AS cnt FROM deals WHERE price IS NOT NULL"
        ).fetchone()["cnt"]

        cats = con.execute(
            """
            SELECT category, COUNT(*) AS n
            FROM   deals
            WHERE  category IS NOT NULL AND category != ''
            GROUP  BY category
            ORDER  BY n DESC
            LIMIT  8
            """
        ).fetchall()

        cheapest = con.execute(
            """
            SELECT name, price, multiple
            FROM   deals
            WHERE  price IS NOT NULL AND on_sale = 1
            ORDER  BY price ASC
            LIMIT  1
            """
        ).fetchone()

    return {
        "total_deals": total,
        "for_sale":    for_sale,
        "with_price":  with_price,
        "categories":  [(row["category"], row["n"]) for row in cats],
        "cheapest":    cheapest,
    }


# ---------------------------------------------------------------------------
# Formatting Helpers
# ---------------------------------------------------------------------------

def build_affiliate_url(slug: str) -> str:
    """
    Construct a TrustMRR listing URL with an optional affiliate tag appended.

    Args:
        slug: The listing slug (e.g. "my-saas-tool").

    Returns:
        Full URL string, including ?ref=<AFFILIATE_TAG> if tag is set.
    """
    base = f"https://trustmrr.com/listings/{slug}"
    if AFFILIATE_TAG:
        return f"{base}?ref={AFFILIATE_TAG}"
    return base


def format_deal(row: sqlite3.Row, rank: int) -> str:
    """
    Render a single deal row as a nicely formatted Markdown message block.

    Args:
        row:  sqlite3.Row from the deals table (v2 schema).
        rank: 1-based position number.

    Returns:
        Markdown-formatted string for one deal.
    """
    price    = f"${row['price']:,.0f}"         if row['price']    else "N/A"
    mrr      = f"${row['mrr']:,.0f}/mo"        if row['mrr']      else "N/A"
    rev30    = f"${row['revenue_30d']:,.0f}"   if row['revenue_30d'] else "N/A"
    multiple = f"{row['multiple']:.2f}×"       if row['multiple'] else "N/A"
    margin   = f"{row['profit_margin']:.0f}%"  if row['profit_margin'] else "N/A"
    category = row['category']         or "Uncategorised"
    provider = row['payment_provider'] or "Unknown"
    tier     = (row['listing_tier']    or "standard").title()
    country  = row['country']          or "🌍"
    url      = build_affiliate_url(row['slug'])

    return (
        f"*#{rank} — {row['name']}* [{tier}]\n"
        f"💰 Price:       {price}\n"
        f"📈 MRR:         {mrr}\n"
        f"📊 Rev (30d):   {rev30}\n"
        f"✖️  Multiple:   {multiple}\n"
        f"💹 Margin:      {margin}\n"
        f"🏷 Category:    {category}\n"
        f"💳 Payments:    {provider}\n"
        f"🌐 Country:     {country}\n"
        f"🔗 [View Listing]({url})\n"
    )


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start — Register the user and send a welcome message.

    Args:
        update:  Incoming Telegram update.
        context: PTB context object.
    """
    chat_id = update.effective_chat.id
    user    = update.effective_user

    try:
        register_subscriber(chat_id)
        log.info("New subscriber registered: chat_id=%s", chat_id)
    except sqlite3.Error as exc:
        log.error("Failed to register subscriber %s: %s", chat_id, exc)

    first_name = user.first_name if user else "there"

    welcome = (
        f"👋 *Welcome, {first_name}\\!*\n\n"
        "I'm *Trust\\-Miner Bot* — your autonomous scout for micro\\-SaaS "
        "acquisition deals sourced from [TrustMRR](https://trustmrr.com)\\.\n\n"
        "*Available commands:*\n"
        "🔍 `/price <amount>` — Find top 3 deals under a budget\n"
        "    _Example: `/price 5000`_\n\n"
        "📊 `/stats` — Show database statistics\n\n"
        "Happy deal hunting\\! 🚀"
    )

    await update.message.reply_text(
        welcome,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /price <amount> — Query DB for top 3 deals priced at or below <amount>.

    Args:
        update:  Incoming Telegram update.
        context: PTB context (context.args holds the command arguments).
    """
    # Validate argument
    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide a budget amount.\n"
            "Example: `/price 5000`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        max_price = float(context.args[0].replace(",", "").replace("$", ""))
        if max_price <= 0:
            raise ValueError("Price must be positive.")
    except (ValueError, IndexError):
        await update.message.reply_text(
            "⚠️ Invalid amount. Please enter a positive number.\n"
            "Example: `/price 10000`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        deals = query_deals_by_price(max_price)
    except sqlite3.Error as exc:
        log.error("DB error in /price: %s", exc)
        await update.message.reply_text(
            "❌ Database error. Please try again later."
        )
        return

    if not deals:
        await update.message.reply_text(
            f"😔 No deals found under *${max_price:,.0f}*\\. "
            "Try a higher budget or run the ingest script to refresh deals\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    header = f"🎯 *Top {len(deals)} deals under ${max_price:,.0f}*\n\n"
    blocks = [format_deal(row, i + 1) for i, row in enumerate(deals)]
    body   = "\n─────────────────────\n".join(blocks)

    await update.message.reply_text(
        header + body,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /stats — Return total deals count, for-sale count, and category breakdown.

    Args:
        update:  Incoming Telegram update.
        context: PTB context object.
    """
    try:
        stats = get_stats()
    except sqlite3.Error as exc:
        log.error("DB error in /stats: %s", exc)
        await update.message.reply_text(
            "❌ Database error. Please try again later."
        )
        return

    total      = stats["total_deals"]
    for_sale   = stats["for_sale"]
    with_price = stats["with_price"]
    categories = stats["categories"]   # list of (name, count) tuples
    cheapest   = stats["cheapest"]

    cat_lines = (
        "\n".join(f"  • {name} ({n})" for name, n in categories)
        if categories
        else "  _None yet — run the ingest script_"
    )

    cheapest_line = ""
    if cheapest:
        cp   = f"${cheapest['price']:,.0f}"
        mult = f"{cheapest['multiple']:.2f}×" if cheapest['multiple'] else "N/A"
        cheapest_line = (
            f"\n💡 *Cheapest deal:* {cheapest['name']}\n"
            f"   Price: {cp} | Multiple: {mult}"
        )

    message = (
        f"📊 *Trust-Miner Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 Total in DB:    *{total}*\n"
        f"🔥 For Sale:       *{for_sale}*\n"
        f"💰 With Price:     *{with_price}*\n"
        f"{cheapest_line}\n\n"
        f"🗂 Top Categories:\n{cat_lines}"
    )

    await update.message.reply_text(
        message,
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Background Scheduler
# ---------------------------------------------------------------------------

def run_scheduler() -> None:
    """
    Background worker loop that runs daily_ingest.py and auto_broadcaster.py
    sequentially on startup and then on a 24-hour cycle.
    """
    log.info("Background scheduler thread started.")
    # Quick initial delay to let the bot startup and print logs
    time.sleep(5)
    
    while True:
        log.info("Starting scheduled database check/creation...")
        try:
            subprocess.run([sys.executable, "setup_db.py"], check=True)
            log.info("Database validation complete.")
        except Exception as e:
            log.error("Database setup validation failed: %s", e)

        log.info("Starting scheduled ingestion (daily_ingest.py)...")
        try:
            subprocess.run([sys.executable, "daily_ingest.py"], check=True)
            log.info("Scheduled ingestion complete.")
        except Exception as e:
            log.error("Scheduled ingestion failed: %s", e)

        log.info("Starting scheduled broadcasting (auto_broadcaster.py)...")
        try:
            subprocess.run([sys.executable, "auto_broadcaster.py"], check=True)
            log.info("Scheduled broadcasting complete.")
        except Exception as e:
            log.error("Scheduled broadcasting failed: %s", e)

        log.info("Scheduler cycle finished. Next run in 24 hours...")
        time.sleep(86400)


# ---------------------------------------------------------------------------
# Application Bootstrap
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Build the PTB Application, register command handlers, start background scheduler,
    and start polling. Blocks until interrupted with Ctrl-C.
    """
    log.info("Starting Trust-Miner Telegram Bot …")
    log.info("Database path: %s", DB_PATH)

    # Start the daemon background scheduler thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("stats", cmd_stats))

    log.info("Bot is live. Press Ctrl-C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,       # ignore messages sent while offline
    )


if __name__ == "__main__":
    main()
