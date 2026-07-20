"""
setup_db.py — Trust-Miner Database Initialiser (v2)
=====================================================
Creates the SQLite database `trustmrr_deals.db` with three tables:
  • deals         — scraped listing metadata from TrustMRR /api/ai
  • subscribers   — Telegram chat IDs of bot users
  • ingestion_log — audit trail of every ingest run

All financial fields (price, mrr, multiple) are explicitly NULLABLE
because not every startup profile has asking price data.

Run once before starting the bot or ingestion engine:
    python setup_db.py
"""

import sqlite3
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
import os
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "trustmrr_deals.db")))

# ---------------------------------------------------------------------------
# SQL Definitions
# ---------------------------------------------------------------------------

CREATE_DEALS_TABLE = """
CREATE TABLE IF NOT EXISTS deals (
    slug                TEXT PRIMARY KEY,      -- unique URL slug
    name                TEXT NOT NULL,         -- display name
    description         TEXT,                  -- short description from API
    price               REAL,                  -- askingPrice (USD) — NULLABLE
    mrr                 REAL,                  -- MRR from revenue.mrr — NULLABLE
    revenue_30d         REAL,                  -- last-30-day revenue — NULLABLE
    multiple            REAL,                  -- price / (mrr*12) — NULLABLE
    category            TEXT,                  -- e.g. "SaaS", "Health & Fitness"
    payment_provider    TEXT,                  -- stripe, revenuecat, whop, etc.
    target_audience     TEXT,                  -- B2C / B2B / null
    country             TEXT,                  -- ISO country code
    on_sale             INTEGER NOT NULL DEFAULT 0,  -- 1 = actively for sale
    listing_tier        TEXT,                  -- starter / premium / null
    profit_margin       REAL,                  -- profitMarginLast30Days — NULLABLE
    active_subs         INTEGER,               -- activeSubscriptions — NULLABLE
    founded_date        TEXT,                  -- ISO date string
    url                 TEXT,                  -- full TrustMRR listing URL
    tech_stack          TEXT,                  -- comma-separated tech stack
    last_updated        TEXT NOT NULL          -- ISO-8601 timestamp of last upsert
);
"""

CREATE_SUBSCRIBERS_TABLE = """
CREATE TABLE IF NOT EXISTS subscribers (
    chat_id   INTEGER PRIMARY KEY,             -- Telegram chat ID
    joined_at TEXT NOT NULL                    -- ISO-8601 timestamp of /start
);
"""

CREATE_INGESTION_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS ingestion_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'api/ai',  -- which endpoint was used
    deals_added    INTEGER NOT NULL DEFAULT 0,
    deals_updated  INTEGER NOT NULL DEFAULT 0,
    deals_skipped  INTEGER NOT NULL DEFAULT 0
);
"""


def init_db(db_path: Path = DB_PATH) -> None:
    """
    Initialise the SQLite database at *db_path*, creating all required tables
    if they do not already exist.  Safe to re-run; existing data is preserved.

    Args:
        db_path: Filesystem path to the SQLite file.
    """
    log.info("Connecting to database at: %s", db_path)
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()

        # WAL mode for concurrent bot + ingest access
        cur.execute("PRAGMA journal_mode=WAL;")

        log.info("Creating table: deals …")
        cur.execute(CREATE_DEALS_TABLE)

        log.info("Creating table: subscribers …")
        cur.execute(CREATE_SUBSCRIBERS_TABLE)

        log.info("Creating table: ingestion_log …")
        cur.execute(CREATE_INGESTION_LOG_TABLE)

        con.commit()
        log.info("✅ Database initialised successfully.")
    except sqlite3.Error as exc:
        log.exception("❌ Failed to initialise database: %s", exc)
        raise
    finally:
        con.close()


if __name__ == "__main__":
    init_db()
