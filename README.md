# Trust-Miner 🍌

> **Micro-SaaS deal discovery + a compliant Telegram/X publisher** — powered by TrustMRR

Trust-Miner is a lightweight Python service that:

1. **Scrapes** TrustMRR's public sitemaps to discover active deal listings.
2. **Enriches** them via the public `/api/ai` endpoint (asking price, MRR, multiple).
3. **Stores** everything in a local SQLite database.
4. **Serves** deals on demand via a Telegram bot (`/price`, `/stats`).
5. **Broadcasts** a clean daily digest to your own Telegram channel and X/Twitter — using official APIs only.

It runs as a single **Render Free Web Service** in webhook mode, with a daily
scrape/broadcast triggered by an external cron ping (e.g. cron-job.org).

---

## Compliance

This project uses **official platform APIs only**. It deliberately contains:

- ❌ No scraped session cookies (no LinkedIn / Medium / Reddit cookie automation).
- ❌ No spintax / spun message variants.
- ❌ No "human-like" random sleeps to evade spam filters.
- ❌ No link-splitting into reply tweets to dodge reach penalties.
- ❌ No programmatic doorway pages.

It posts genuine deal metrics to **your own** channels, with a disclosed
affiliate link, at a modest cadence (≤ 3 tweets/run, one Telegram digest).

---

## File Reference

| File | Purpose |
|---|---|
| `setup_db.py` | One-time SQLite initialiser (`deals`, `subscribers`, `ingestion_log`) |
| `daily_ingest.py` | Scrape → parse → enrich → upsert pipeline |
| `broadcaster.py` | Clean daily digest to Telegram channel + one X post (official APIs) |
| `seo_helper.py` | 3–5 relevant, natural hashtags per deal category |
| `telegram_bot.py` | Webhook bot + HTTP server (`/webhook`, `/trigger-ingest`, `/healthz`) |
| `render.yaml` | Render Free Web Service blueprint |
| `.env.example` | Environment variable template |

---

## HTTP Endpoints

| Method / Path | Purpose |
|---|---|
| `GET /` | Liveness string |
| `GET /healthz` | JSON health check (Render health check path) |
| `GET /trigger-ingest` | Run the daily scrape + broadcast (optional `?key=<INGEST_SECRET>`) |
| `POST /webhook/<token>` | Telegram update delivery |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `WEBHOOK_URL` | ✅ (prod) | Public base URL of the Render service |
| `AFFILIATE_TAG` | Optional | TrustMRR referral tag (disclosed on links) |
| `TELEGRAM_CHANNEL_ID` | Optional | Channel to broadcast the daily digest to |
| `TWITTER_API_KEY` / `_SECRET` / `ACCESS_TOKEN` / `ACCESS_SECRET` | Optional | Official X API v2 (Read+Write) |
| `INGEST_SECRET` | Optional | Shared secret guarding `/trigger-ingest` |
| `DB_PATH` | Optional | SQLite path (default `./trustmrr_deals.db`) |

Any optional integration left unset is simply skipped — the service still runs.

---

## $0 Deployment (Render Free Web Service + cron-job.org)

1. **Push this repo** to GitHub.
2. On Render, **New → Blueprint**, point it at the repo (it reads `render.yaml`).
3. Enter the `sync: false` env vars in the Render dashboard when prompted
   (`BOT_TOKEN`, `WEBHOOK_URL`, and any optional integrations). Secrets are
   entered directly into Render — never committed.
4. After the first deploy, set `WEBHOOK_URL` to the service's public URL
   (e.g. `https://trust-miner-bot.onrender.com`) and redeploy so the bot
   registers its Telegram webhook on startup.
5. On **cron-job.org**, create a daily job that does `GET`
   `https://<your-service>.onrender.com/trigger-ingest` (append
   `?key=<INGEST_SECRET>` if you set one). This refreshes the deals and posts
   the daily digest, and also wakes the free service.

> **Free-tier notes:** the service sleeps after ~15 min idle and cold-starts on
> the next request, so the first command after a nap can lag a few seconds
> (Telegram retries webhook delivery). The filesystem is ephemeral, so the
> SQLite DB is rebuilt by the daily `/trigger-ingest` run.

---

## Local Development

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in BOT_TOKEN etc.
python setup_db.py
python daily_ingest.py    # populate deals
python telegram_bot.py    # start webhook server (set WEBHOOK_URL for live Telegram)
```

---

## Telegram Commands

| Command | Description | Example |
|---|---|---|
| `/start` | Register & show welcome | `/start` |
| `/price <amount>` | Top 3 deals ≤ budget (USD) | `/price 5000` |
| `/stats` | Totals & top categories | `/stats` |

---

## Security Notes

- **Never commit `.env`** — it is git-ignored.
- The bot token and API keys grant control of your accounts; treat them like passwords and store them only in Render's environment settings.

---

## License

MIT.
