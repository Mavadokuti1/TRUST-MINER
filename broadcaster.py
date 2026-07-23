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
from datetime import datetime, timezone
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
    """Format a clean, high-CTR daily digest for the Telegram channel.

    No spintax, no evasion — just scannable metrics, clear visual hierarchy, one
    strong call-to-action per deal, and a share/notify nudge at the end.
    """
    lines = [
        "🔥 *TODAY'S TOP MICRO-SAAS DEALS*",
        "_Vetted acquisitions, best value first_",
        "",
    ]
    for i, d in enumerate(deals, 1):
        price = f"${d['price']:,.0f}" if d.get("price") else "N/A"
        mrr = f"${d['mrr']:,.0f}/mo" if d.get("mrr") else "N/A"
        mult = f"{d['multiple']:.2f}x" if d.get("multiple") is not None else "N/A"
        cat = d.get("category") or "Software"
        lines.append(f"*{i}. {d.get('name', 'Unknown')}*  ·  {cat}")
        lines.append(f"    💸 MRR: *{mrr}*")
        lines.append(f"    🏷 Asking: *{price}*")
        lines.append(f"    📊 Multiple: *{mult}*")
        lines.append(f"    👉 [View Deal & Financials]({deal_url(d)})")
        lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔔 *Turn on notifications* so you never miss a drop.")
    lines.append("📲 *Forward this to a founder* hunting for their next business.")
    tags = hashtag_line(category=deals[0].get("category", ""), name=deals[0].get("name", ""))
    if tags:
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
# Once-per-day safeguard (atomic SQLite "claim")
# ---------------------------------------------------------------------------
# The daily broadcast must fire exactly ONCE per day even if /trigger-ingest is
# hit twice (e.g. cron-job.org retries after a Render cold-start timeout). We use
# a one-row-per-day table with the date as PRIMARY KEY: the first run to
# `INSERT OR IGNORE` today's row wins the claim and posts; any duplicate finds the
# row already there and skips. SQLite serialises writes, so the claim is atomic
# even for two simultaneous requests. Lightweight, $0, no external DB.
_BROADCAST_LOG_DDL = """
CREATE TABLE IF NOT EXISTS broadcast_log (
    broadcast_date TEXT PRIMARY KEY,
    top_signature  TEXT,
    posted_at      TEXT NOT NULL
)
"""


def _today_key() -> str:
    """UTC calendar date used as the daily claim key (duplicates fire seconds apart,
    so the exact tz is irrelevant — UTC keeps it dependency-free and deterministic)."""
    return datetime.now(timezone.utc).date().isoformat()


def _claim_broadcast_slot(day: str, signature: str) -> bool:
    """Atomically claim today's broadcast slot. Returns True if THIS call won the
    claim (caller should post), False if the day was already claimed (skip)."""
    if not DB_PATH.exists():
        # No DB yet means nothing to broadcast anyway; treat as claimed-to-skip is wrong —
        # let the caller's empty-deals check handle it. Here we simply cannot claim.
        return True
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        con.execute(_BROADCAST_LOG_DDL)
        cur = con.execute(
            "INSERT OR IGNORE INTO broadcast_log (broadcast_date, top_signature, posted_at) "
            "VALUES (?, ?, ?)",
            (day, signature, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        won = cur.rowcount == 1  # rowcount == 0 means the row already existed
        return won
    except sqlite3.Error as exc:
        # If the claim mechanism itself errors, fail OPEN (allow the post) rather than
        # silently skipping the day's only broadcast — a rare duplicate beats total silence.
        log.error("Broadcast claim check failed (%s) — proceeding without dedup this run.", exc)
        return True
    finally:
        con.close()


def _release_broadcast_slot(day: str) -> None:
    """Release today's claim so a legitimate retry can re-attempt (used only when the
    send actually failed after we had claimed the slot)."""
    if not DB_PATH.exists():
        return
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        con.execute("DELETE FROM broadcast_log WHERE broadcast_date = ?", (day,))
        con.commit()
    except sqlite3.Error as exc:
        log.error("Failed to release broadcast claim for %s: %s", day, exc)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def broadcast(force: bool | None = None) -> dict:
    """Fetch top deals and broadcast them to Telegram + Twitter, exactly once per day.

    A duplicate same-day call (e.g. a cron retry) is detected via an atomic SQLite
    claim and skipped without re-posting. Set BROADCAST_FORCE=1 (or pass force=True)
    to bypass the guard for a deliberate manual re-post.
    """
    deals = get_top_deals(TELEGRAM_DIGEST_SIZE)
    if not deals:
        log.warning("No eligible deals to broadcast.")
        return {"deals": 0, "telegram": False, "tweets": 0, "dry_run": DRY_RUN}

    if force is None:
        force = os.getenv("BROADCAST_FORCE", "0") == "1"

    day = _today_key()
    signature = "|".join(d.get("slug", "") for d in deals)

    if not force and not _claim_broadcast_slot(day, signature):
        log.warning(
            "Broadcast for %s already sent — skipping duplicate (deals: %s). "
            "This is the once-per-day safeguard doing its job.",
            day, signature,
        )
        return {
            "deals": len(deals),
            "telegram": False,
            "tweets": 0,
            "skipped": "already_posted_today",
            "date": day,
            "dry_run": DRY_RUN,
        }

    digest = format_telegram_digest(deals)
    tg_ok = send_telegram(digest)

    # If the primary Telegram send failed (and we're not dry-running), release the
    # claim so a genuine retry today can post — the guard only blocks true duplicates,
    # never a first successful post.
    if not tg_ok and not DRY_RUN and not force:
        log.warning("Telegram send failed after claiming %s — releasing slot for retry.", day)
        _release_broadcast_slot(day)

    tweets = send_tweets(deals)

    summary = {
        "deals": len(deals),
        "telegram": tg_ok,
        "tweets": tweets,
        "date": day,
        "forced": force,
        "dry_run": DRY_RUN,
    }
    log.info("Broadcast summary: %s", summary)
    return summary


if __name__ == "__main__":
    broadcast()
