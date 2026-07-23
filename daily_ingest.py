"""
daily_ingest.py — Trust-Miner Ingestion Engine (v3 Hybrid)
===========================================================
ARCHITECTURE: Option C (Hybrid Ingestion)
  Step 1: Broad Scrape (Base Layer)
    - Fetch sitemap(s) to discover all /startup/*.md URLs.
    - Asynchronously fetch all .md files and extract basic metadata (name, slug, category, tech_stack) via regex.
    - Upsert to DB with price=NULL, onSale=0.
  Step 2: API Enrichment (Gold Layer)
    - Fetch /api/ai JSON (recentlyListedStartups + bestDeals).
    - Upsert records, enriching them with full financial data (askingPrice, mrr, multiple) and setting onSale=1.

Schedule daily via cron / Task Scheduler:
    python daily_ingest.py
"""

import asyncio
import aiohttp
import logging
import sqlite3
import os
import time
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "trustmrr_deals.db")))

API_URL = "https://trustmrr.com/api/ai"
SITEMAP_URLS = [
    "https://trustmrr.com/sitemap-3.xml",
    # Can add more sitemaps here if full history is needed
]

REQUEST_TIMEOUT = 20  # seconds

HEADERS = {
    "User-Agent": (
        "TrustMinerBot/3.0 (+https://github.com/trust-miner; "
        "hybrid crawler)"
    ),
}

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

# ---------------------------------------------------------------------------
# Database Upsert
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO deals (
    slug, name, description, price, mrr, revenue_30d, multiple,
    category, payment_provider, target_audience, country,
    on_sale, listing_tier, profit_margin, active_subs,
    founded_date, url, tech_stack, last_updated
) VALUES (
    :slug, :name, :description, :price, :mrr, :revenue_30d, :multiple,
    :category, :payment_provider, :target_audience, :country,
    :on_sale, :listing_tier, :profit_margin, :active_subs,
    :founded_date, :url, :tech_stack, :last_updated
)
ON CONFLICT(slug) DO UPDATE SET
    name             = COALESCE(excluded.name, deals.name),
    description      = COALESCE(excluded.description, deals.description),
    price            = COALESCE(excluded.price, deals.price),
    mrr              = COALESCE(excluded.mrr, deals.mrr),
    revenue_30d      = COALESCE(excluded.revenue_30d, deals.revenue_30d),
    multiple         = COALESCE(excluded.multiple, deals.multiple),
    category         = COALESCE(excluded.category, deals.category),
    payment_provider = COALESCE(excluded.payment_provider, deals.payment_provider),
    target_audience  = COALESCE(excluded.target_audience, deals.target_audience),
    country          = COALESCE(excluded.country, deals.country),
    on_sale          = COALESCE(excluded.on_sale, deals.on_sale),
    listing_tier     = COALESCE(excluded.listing_tier, deals.listing_tier),
    profit_margin    = COALESCE(excluded.profit_margin, deals.profit_margin),
    active_subs      = COALESCE(excluded.active_subs, deals.active_subs),
    founded_date     = COALESCE(excluded.founded_date, deals.founded_date),
    url              = COALESCE(excluded.url, deals.url),
    tech_stack       = COALESCE(excluded.tech_stack, deals.tech_stack),
    last_updated     = excluded.last_updated
"""

LOG_SQL = """
INSERT INTO ingestion_log (timestamp, source, deals_added, deals_updated, deals_skipped)
VALUES (?, ?, ?, ?, ?)
"""

def upsert_deal(cur: sqlite3.Cursor, record: dict) -> str:
    existing = cur.execute(
        "SELECT slug FROM deals WHERE slug = ?", (record["slug"],)
    ).fetchone()
    cur.execute(UPSERT_SQL, record)
    return "added" if existing is None else "updated"

# ---------------------------------------------------------------------------
# Step 1: Broad Scrape (Base Layer)
# ---------------------------------------------------------------------------

def fetch_sitemap_urls() -> list[str]:
    urls = set()
    for sitemap_url in SITEMAP_URLS:
        log.info("Fetching sitemap: %s", sitemap_url)
        try:
            r = requests.get(sitemap_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            matches = re.findall(r"<loc>\s*(https://trustmrr\.com/startup/[^<]+\.md)\s*</loc>", r.text)
            urls.update(matches)
            log.info("Found %d URLs in %s", len(matches), sitemap_url)
        except Exception as e:
            log.warning("Sitemap fetch failed for %s: %s", sitemap_url, e)
    return list(urls)

async def fetch_md(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        try:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    text = await response.text()
                    
                    name_match = re.search(r'- Name:\s*(.*)', text)
                    slug_match = re.search(r'- Slug:\s*`?(.*?)`?\n', text)
                    cat_match = re.search(r'- Category:\s*(.*)', text)
                    tech_match = re.search(r'- Tech(?:nologies| stack):\s*(.*)', text, re.I)
                    
                    slug = slug_match.group(1).strip() if slug_match else url.split('/')[-1].replace('.md', '')
                        
                    return {
                        "slug": slug,
                        "name": name_match.group(1).strip() if name_match else slug.replace('-', ' ').title(),
                        "category": cat_match.group(1).strip() if cat_match else None,
                        "tech_stack": tech_match.group(1).strip() if tech_match else None,
                        "description": None,
                        "price": None,
                        "mrr": None,
                        "revenue_30d": None,
                        "multiple": None,
                        "payment_provider": None,
                        "target_audience": None,
                        "country": None,
                        "on_sale": 0,
                        "listing_tier": None,
                        "profit_margin": None,
                        "active_subs": None,
                        "founded_date": None,
                        "url": url.replace('.md', ''),
                        "last_updated": now_iso()
                    }
        except Exception:
            pass
            
    # Fallback to URL parsing immediately to ensure 100% ingest rate
    slug = url.split('/')[-1].replace('.md', '')
    return {
        "slug": slug,
        "name": slug.replace('-', ' ').title(),
        "category": None,
        "tech_stack": None,
        "description": None,
        "price": None,
        "mrr": None,
        "revenue_30d": None,
        "multiple": None,
        "payment_provider": None,
        "target_audience": None,
        "country": None,
        "on_sale": 0,
        "listing_tier": None,
        "profit_margin": None,
        "active_subs": None,
        "founded_date": None,
        "url": url.replace('.md', ''),
        "last_updated": now_iso()
    }

async def run_broad_scrape_async(urls: list[str]) -> list[dict]:
    log.info("Starting async fetch for %d .md URLs...", len(urls))
    sem = asyncio.Semaphore(100) # Max concurrency, fallback handles failures
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [fetch_md(session, url, sem) for url in urls]
        return await asyncio.gather(*tasks)

def step1_broad_scrape(cur: sqlite3.Cursor):
    urls = fetch_sitemap_urls()
    if not urls:
        log.warning("No URLs found in sitemaps.")
        return 0, 0
    
    records = asyncio.run(run_broad_scrape_async(urls))
    log.info("Successfully fetched and parsed %d .md profiles", len(records))
    
    added = 0
    updated = 0
    for record in records:
        action = upsert_deal(cur, record)
        if action == "added":
            added += 1
        else:
            updated += 1
            
    log.info("Broad scrape upserted %d new base records (and updated %d)", added, updated)
    return added, updated

# ---------------------------------------------------------------------------
# Step 2: API Enrichment (Gold Layer)
# ---------------------------------------------------------------------------

def fetch_api_data() -> dict:
    log.info("Fetching: %s", API_URL)
    resp = requests.get(API_URL, headers={"User-Agent": HEADERS["User-Agent"], "Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    log.info("API response received — recentlyListed: %d, bestDeals: %d",
             len(data.get("recentlyListedStartups", [])),
             len(data.get("bestDeals", [])))
    return data

def merge_listings(data: dict) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for record in (data.get("recentlyListedStartups", []) + data.get("bestDeals", [])):
        slug = record.get("slug", "")
        if slug and slug not in seen:
            seen.add(slug)
            merged.append(record)
    return merged

def normalise_record(raw: dict) -> dict:
    revenue = raw.get("revenue") or {}
    asking_price = safe_float(raw.get("askingPrice"))
    mrr          = safe_float(revenue.get("mrr"))
    multiple     = safe_float(raw.get("multiple"))
    
    if multiple is None and asking_price and mrr and mrr > 0:
        multiple = round(asking_price / (mrr * 12), 4)

    return {
        "slug":             raw.get("slug", ""),
        "name":             raw.get("name") or raw.get("slug", ""),
        "description":      raw.get("description"),
        "price":            asking_price,
        "mrr":              mrr,
        "revenue_30d":      safe_float(revenue.get("last30Days")),
        "multiple":         multiple,
        "category":         raw.get("category"),
        "payment_provider": raw.get("paymentProvider"),
        "target_audience":  raw.get("targetAudience"),
        "country":          raw.get("country"),
        "on_sale":          1 if raw.get("onSale") else 0,
        "listing_tier":     raw.get("listingTier"),
        "profit_margin":    safe_float(raw.get("profitMarginLast30Days")),
        "active_subs":      safe_int(raw.get("activeSubscriptions")),
        "founded_date":     (raw.get("foundedDate") or "")[:10] or None,
        "url":              raw.get("url"),
        "tech_stack":       None, # We don't overwrite this from API as it isn't provided
        "last_updated":     now_iso(),
    }

def step2_api_enrichment(cur: sqlite3.Cursor):
    try:
        api_data = fetch_api_data()
    except Exception as exc:
        log.error(
            "TrustMRR API unreachable or errored (%s). Skipping enrichment for this run; "
            "today's broadcast will fall back to the existing cached deals. The service "
            "stays up and will retry on the next scheduled run.",
            exc,
        )
        return 0, 0

    listings = merge_listings(api_data)
    added = 0
    updated = 0
    
    for raw in listings:
        slug = raw.get("slug", "")
        if not slug: continue
        record = normalise_record(raw)
        action = upsert_deal(cur, record)
        if action == "added":
            added += 1
        else:
            updated += 1
            
    log.info("API enrichment upserted %d new and enriched %d existing records", added, updated)
    return added, updated

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def run_ingest(db_path: Path = DB_PATH) -> None:
    log.info("=" * 60)
    log.info("Trust-Miner Ingestion Engine v3 (HYBRID) — %s", now_iso())
    log.info("=" * 60)

    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()

        # STEP 1
        log.info("--- STEP 1: Broad Scrape (Base Layer) ---")
        try:
            added1, updated1 = step1_broad_scrape(cur)
            con.commit()
        except Exception as exc:
            log.exception("Step 1 (broad scrape) failed — continuing with cached data: %s", exc)
            added1, updated1 = 0, 0

        # STEP 2
        log.info("--- STEP 2: API Enrichment (Gold Layer) ---")
        try:
            added2, updated2 = step2_api_enrichment(cur)
            con.commit()
        except Exception as exc:
            log.exception("Step 2 (API enrichment) failed — continuing with cached data: %s", exc)
            added2, updated2 = 0, 0

        # Log
        cur.execute(LOG_SQL, (now_iso(), "hybrid_v3", added1+added2, updated1+updated2, 0))
        con.commit()

    except Exception as exc:
        # Broad catch: an ingest hiccup must never crash the Render service — it stays
        # up, logs the cause clearly, and is ready for the next scheduled run.
        log.exception("Ingest run aborted early (service stays up): %s", exc)
    finally:
        con.close()

    _print_db_summary(db_path)

def _print_db_summary(db_path: Path) -> None:
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        total      = cur.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
        for_sale   = cur.execute("SELECT COUNT(*) FROM deals WHERE on_sale=1").fetchone()[0]
        with_price = cur.execute("SELECT COUNT(*) FROM deals WHERE price IS NOT NULL").fetchone()[0]
        cats       = cur.execute(
            "SELECT category, COUNT(*) as n FROM deals WHERE category IS NOT NULL "
            "GROUP BY category ORDER BY n DESC LIMIT 5"
        ).fetchall()

        log.info("=" * 60)
        log.info("DB SUMMARY")
        log.info("  Total deals    : %d", total)
        log.info("  For sale       : %d", for_sale)
        log.info("  With price     : %d", with_price)
        log.info("  Top categories :")
        for row in cats:
            log.info("    %-25s %d", row["category"], row["n"])
        log.info("=" * 60)
        con.close()
    except sqlite3.Error as exc:
        log.warning("Could not print DB summary: %s", exc)

if __name__ == "__main__":
    run_ingest()
