"""
broadcaster.py — Clean, compliant daily broadcaster
====================================================
Publishes the day's top deal(s) to the owner's OWN channels using official
APIs only:
  • Telegram channel  — via the official Bot API (sendMessage).
  • Twitter / X        — via the official API v2 (tweepy), one clean tweet.

Compliance guarantees (contrast with the removed auto_broadcaster.py):
  • No spintax / spun message variants.
  • No random "human-like" sleeps to evade spam detection.
  • No link-splitting into reply tweets to dodge reach penalties.
  • No scraped session cookies (no LinkedIn / Medium / Reddit).
  • Posts genuine, honest deal metrics with a disclosed affiliate link.
  • At most `TWITTER_MAX_PER_RUN` (default 1) tweet per run.

Set BROADCAST_DRY_RUN=1 to format-and-log without sending anything.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

import requests
from dotenv import load_dotenv

from seo_helper import hashtag_line

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "trustmrr_deals.db")))
AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "")
DRY_RUN = os.getenv("BROADCAST_DRY_RUN", "0") == "1"

# How many deals to include in the Telegram digest, and max tweets per run.
TELEGRAM_DIGEST_SIZE = int(os.getenv("TELEGRAM_DIGEST_SIZE", "3"))
TWITTER_MAX_PER_RUN = min(int(os.getenv("TWITTER_MAX_PER_RUN", "1")), 3)


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def get_top_deals(limit: int) -> list[dict]:
    """Return the best `limit` for-sale deals (lowest multiple first)."""
    if not DB_PATH.exists():
        log.warning("DB not found at %s — nothing to broadcast.", DB_PATH)
        return []
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT slug, name, price, mrr, multiple, category, url
            FROM   deals
            WHERE  on_sale = 1 AND price IS NOT NULL AND multiple IS NOT NULL
            ORDER  BY multiple ASC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        log.error("DB query failed: %s", exc)
        return []
    finally:
        con.close()


def deal_url(deal: dict) -> str:
    """Build the listing URL with a disclosed affiliate ref (if configured)."""
    base = deal.get("url") or f"https://trustmrr.com/startup/{deal.get('slug', '')}"
    if AFFILIATE_TAG:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}ref={AFFILIATE_TAG}"
    return base


# ---------------------------------------------------------------------------
# Formatting (clean, standard Markdown — no evasion tricks)
# ---------------------------------------------------------------------------
def format_telegram_digest(deals: list[dict]) -> str:
    """Format a clean daily digest of the top deals for a Telegram channel."""
    lines = ["🚀 *Today's Top Micro-SaaS Deals*", ""]
    for i, d in enumerate(deals, 1):
        price = f"${d['price']:,.0f}" if d.get("price") else "N/A"
        mrr = f"${d['mrr']:,.0f}/mo" if d.get("mrr") else "N/A"
        mult = f"{d['multiple']:.2f}x" if d.get("multiple") is not None else "N/A"
        cat = d.get("category") or "Software"
        lines.append(f"*{i}. {d.get('name', 'Unknown')}* ({cat})")
        lines.append(f"   MRR: {mrr}  •  Asking: {price}  •  {mult}")
        lines.append(f"   [View listing]({deal_url(d)})")
        lines.append("")
    tags = hashtag_line(category=deals[0].get("category", ""), name=deals[0].get("name", ""))
    lines.append(tags)
    return "\n".join(lines).strip()


def format_tweet(deal: dict) -> str:
    """Format a single clean tweet (<= 280 chars) with an inline link."""
    price = f"${deal['price']:,.0f}" if deal.get("price") else "N/A"
    mrr = f"${deal['mrr']:,.0f}/mo" if deal.get("mrr") else "N/A"
    name = deal.get("name", "Unknown")
    url = deal_url(deal)
    tags = hashtag_line(category=deal.get("category", ""), name=name, limit=3)

    text = (
        f"🚀 New Micro-SaaS Deal: {name} | MRR: {mrr} | Asking: {price}. "
        f"Check it out: {url}\n\n{tags}"
    )
    if len(text) <= 280:
        return text
    # Trim the name if we somehow exceed the limit; never split the link out.
    overflow = len(text) - 280
    trimmed_name = (name[: max(3, len(name) - overflow - 1)] + "…") if len(name) > overflow + 1 else name
    return (
        f"🚀 New Micro-SaaS Deal: {trimmed_name} | MRR: {mrr} | Asking: {price}. "
        f"Check it out: {url}\n\n{tags}"
    )[:280]


# ---------------------------------------------------------------------------
# Senders (official APIs only)
# ---------------------------------------------------------------------------
def send_telegram(message: str) -> bool:
    """Post a message to the owner's Telegram channel via the official Bot API."""
    bot_token = os.getenv("BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
    if not bot_token or not channel_id:
        log.warning("Telegram channel broadcast skipped (BOT_TOKEN / TELEGRAM_CHANNEL_ID not set).")
        return False
    if DRY_RUN:
        log.info("[DRY RUN] Telegram channel message:\n%s", message)
        return True
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": channel_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        if r.ok and r.json().get("ok"):
            log.info("Telegram channel broadcast sent.")
            return True
        log.error("Telegram broadcast failed: HTTP %s — %s", r.status_code, r.text[:300])
        return False
    except Exception as exc:
        log.error("Telegram broadcast exception: %s", exc)
        return False


def send_tweets(deals: list[dict]) -> int:
    """Post up to TWITTER_MAX_PER_RUN clean tweets via the official API v2."""
    keys = {
        "consumer_key": os.getenv("TWITTER_API_KEY"),
        "consumer_secret": os.getenv("TWITTER_API_SECRET"),
        "access_token": os.getenv("TWITTER_ACCESS_TOKEN"),
        "access_token_secret": os.getenv("TWITTER_ACCESS_SECRET"),
    }
    if not all(keys.values()):
        log.warning("Twitter broadcast skipped (TWITTER_* credentials not set).")
        return 0

    posted = 0
    to_post = deals[:TWITTER_MAX_PER_RUN]
    if DRY_RUN:
        for d in to_post:
            text = format_tweet(d)
            log.info("[DRY RUN] Tweet (%d chars):\n%s", len(text), text)
        return len(to_post)

    try:
        import tweepy

        client = tweepy.Client(**keys)
        for d in to_post:
            text = format_tweet(d)
            try:
                client.create_tweet(text=text)
                posted += 1
                log.info("Tweet posted (%d chars).", len(text))
            except Exception as exc:
                err = str(exc)
                if "403" in err:
                    log.warning("Twitter: 403 — app likely needs Read+Write permission. Skipping.")
                elif "402" in err or "depleted" in err.lower():
                    log.warning("Twitter: monthly write quota reached. Skipping.")
                elif "429" in err:
                    log.warning("Twitter: rate limited. Skipping.")
                else:
                    log.error("Tweet failed: %s", err)
    except Exception as exc:
        log.error("Twitter client init failed: %s", exc)
    return posted


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def broadcast() -> dict:
    """Fetch top deals and broadcast them to Telegram + Twitter. Returns a summary."""
    deals = get_top_deals(TELEGRAM_DIGEST_SIZE)
    if not deals:
        log.warning("No eligible deals to broadcast.")
        return {"deals": 0, "telegram": False, "tweets": 0, "dry_run": DRY_RUN}

    digest = format_telegram_digest(deals)
    tg_ok = send_telegram(digest)
    tweets = send_tweets(deals)

    summary = {"deals": len(deals), "telegram": tg_ok, "tweets": tweets, "dry_run": DRY_RUN}
    log.info("Broadcast summary: %s", summary)
    return summary


if __name__ == "__main__":
    broadcast()
