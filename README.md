# Trust-Miner 🍌

> **Automated micro-SaaS deal discovery + Telegram bot** — powered by TrustMRR

Trust-Miner is a lightweight Python pipeline that:

1. **Broad Scrapes** TrustMRR's public sitemaps to discover 1000+ active deal listings (Base Layer).
2. **Enriches** those listings via the `/api/ai` endpoint to pull pristine financial metrics (askingPrice, MRR, multiple) for 'for-sale' deals (Gold Layer).
3. **Stores** everything in a local SQLite database with full upsert support.
4. **Broadcasts** deals to subscribers through a Telegram bot with budget-filtered queries.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Trust-Miner Stack                 │
│                                                     │
│  ┌─────────────┐       ┌──────────────────────────┐ │
│  │ TrustMRR    │──────▶│  daily_ingest.py         │ │
│  │ Sitemaps    │       │  (Hybrid Engine v3)      │ │
│  │ & /api/ai   │       │  Step 1: Sitemap Scrape  │ │
│  └─────────────┘       │  Step 2: API Enrichment  │ │
│                        └────────────┬─────────────┘ │
│                                     │               │
│                        ┌────────────▼─────────────┐ │
│                        │  trustmrr_deals.db       │ │
│                        │  (SQLite — WAL mode)     │ │
│                        │  • deals                 │ │
│                        │  • subscribers           │ │
│                        │  • ingestion_log         │ │
│                        └────────────┬─────────────┘ │
│                                     │               │
│                        ┌────────────▼─────────────┐ │
│                        │  telegram_bot.py          │ │
│                        │  /start  /price  /stats  │ │
│                        └──────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## File Reference

| File | Purpose |
|---|---|
| `requirements.txt` | Python package dependencies |
| `.env.example` | Template for secrets — copy to `.env` |
| `.gitignore` | Excludes `.env`, `*.db`, caches, venv |
| `setup_db.py` | One-time DB initialiser |
| `daily_ingest.py` | Scrape → parse → upsert pipeline |
| `telegram_bot.py` | Telegram bot interface |

---

## Quick Start

### 1. Clone / Download

```bash
git clone <your-repo-url>
cd trust-miner
```

### 2. Create & Activate Virtual Environment

```bash
# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Secrets

```bash
# Copy the template
cp .env.example .env

# Edit .env and fill in your values:
#   BOT_TOKEN     — from @BotFather on Telegram
#   AFFILIATE_TAG — your TrustMRR referral ID (optional)
```

### 5. Initialise the Database

```bash
python setup_db.py
```

Expected output:
```
2026-07-19 08:00:00 [INFO] Connecting to database at: trustmrr_deals.db
2026-07-19 08:00:00 [INFO] Creating table: deals …
2026-07-19 08:00:00 [INFO] Creating table: subscribers …
2026-07-19 08:00:00 [INFO] Creating table: ingestion_log …
2026-07-19 08:00:00 [INFO] ✅ Database initialised successfully.
```

### 6. Run the Ingestion Engine

```bash
python daily_ingest.py
```

This will:
- **Step 1:** Asynchronously scrape TrustMRR's sitemap XML for all listing URLs and extract base metadata.
- **Step 2:** Fetch the `/api/ai` endpoint to enrich top deals with precise financial data.
- Upsert records into `trustmrr_deals.db`.
- Log results to the `ingestion_log` table.

**Schedule for daily runs:**

```bash
# Linux / macOS cron (runs at 7 AM daily)
0 7 * * * /path/to/venv/bin/python /path/to/daily_ingest.py

# Windows Task Scheduler (PowerShell)
# Create a scheduled task pointing to:
#   .\venv\Scripts\python.exe daily_ingest.py
```

### 7. Start the Telegram Bot

```bash
python telegram_bot.py
```

---

## Telegram Bot Commands

| Command | Description | Example |
|---|---|---|
| `/start` | Register & show welcome message | `/start` |
| `/price <amount>` | Find top 3 deals ≤ budget (USD) | `/price 5000` |
| `/stats` | Total deals & active categories | `/stats` |

### Sample `/price` Output

```
🎯 Top 3 deals under $5,000

#1 — My Awesome SaaS
💰 Price:    $4,500
📈 MRR:      $380/mo
✖️ Multiple: 0.99×
🏷 Category: SaaS
⚙️ Stack:    Ruby on Rails, PostgreSQL
🔗 View Listing

─────────────────────
#2 — Newsletter Tool
...
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ Yes | Telegram bot token from @BotFather |
| `AFFILIATE_TAG` | Optional | Your TrustMRR referral/affiliate ID |

---

## Security Notes

- ⚠️ **Never commit `.env`** — it is in `.gitignore` by default.
- The bot token grants full control of your Telegram bot. Treat it like a password.
- The SQLite database contains subscriber chat IDs — handle with care.

---

## Extending the System

- **Add a `/latest` command**: query the 5 most recently added deals by `last_updated`.
- **Push notifications**: store `chat_id`s and use `bot.send_message()` after each ingest run to alert subscribers to new deals.
- **Deploy to a server**: use `systemd` (Linux) or Task Scheduler (Windows) to run both scripts persistently.
- **PostgreSQL migration**: swap `sqlite3` for `psycopg2` and update `DB_PATH` to a connection string.

---

## License

MIT — do whatever you want, just don't sell it back as a SaaS without buying me a coffee. ☕

---

## Broadcaster Setup (Omnipresence)

Trust-Miner includes a standalone automated broadcaster engine (`auto_broadcaster.py`) that queries the database for the best deal of the day, generates a unique variant of the message using spintax, and distributes it across Telegram and Reddit.

### 1. Telegram Channel
1. Create a public Telegram channel.
2. Add your bot as an Administrator.
3. Get the channel ID (usually looks like `-100xxxxxxxxxx`).
4. Add it to your `.env` as `TELEGRAM_CHANNEL_ID`.

### 2. Reddit API Credentials
1. Go to [Reddit Apps](https://www.reddit.com/prefs/apps).
2. Click **Create another app** (select "script").
3. Name it, set redirect uri to `http://localhost:8080`, and create it.
4. Copy the client ID (under the name) and the secret into your `.env`.

### 3. Go Live
By default, `auto_broadcaster.py` runs in **DRY_RUN** mode to prevent accidental API bans while testing.
To activate the live broadcast:
1. Open `auto_broadcaster.py`.
2. Set `DRY_RUN = False`.
3. Run `python auto_broadcaster.py`.

