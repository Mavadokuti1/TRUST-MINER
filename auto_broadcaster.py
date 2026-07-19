import os
import requests
import logging
import sqlite3
import random
import time
from pathlib import Path
from dotenv import load_dotenv

import praw
import spintax

DRY_RUN = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "trustmrr_deals.db"

def get_best_deal():
    """Query the database for the absolute best deal (lowest multiple)."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        row = cur.execute("""
            SELECT * FROM deals 
            WHERE on_sale=1 AND price IS NOT NULL 
            ORDER BY multiple ASC LIMIT 1
        """).fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        log.error("Database query failed: %s", e)
        return None
    finally:
        con.close()

def build_message(deal, wiseurl_base):
    """Use spintax to generate a unique post."""
    slug = deal.get("slug", "")
    name = deal.get("name", "Unknown")
    category = deal.get("category") or "Software"
    mrr = f"{deal.get('mrr', 0):,.0f}" if deal.get("mrr") is not None else "0"
    price = f"{deal.get('price', 0):,.0f}" if deal.get("price") is not None else "0"
    multiple = f"{deal.get('multiple', 0):.2f}" if deal.get("multiple") is not None else "N/A"
    
    wise_url = f"{wiseurl_base}{slug}"
    
    spin_template = (
        "{🚨|🔥|💎} {Micro-SaaS Deal|SaaS Acquisition|Profitable Startup} of the Day!\n"
        f"Name: {name} ({category})\n"
        f"MRR: ${mrr}/mo\n"
        f"Asking: ${price}\n"
        f"{{This is a highly profitable|Great}} {multiple}x multiple.\n\n"
        f"{{View the metrics here|Check the verified numbers}}: {wise_url}"
    )
    
    return spintax.spin(spin_template)

def broadcast_telegram(message, bot_token, chat_id):
    """Send message to a Telegram Channel."""
    if DRY_RUN:
        log.info("[DRY RUN] Telegram Payload:\n%s", message)
        return
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": message})
        r.raise_for_status()
        log.info("Successfully broadcasted to Telegram.")
    except Exception as e:
        log.error("Telegram broadcast failed: %s", e)

def post_to_reddit(message, client_id, client_secret, username, password):
    """Post message to Reddit."""
    if DRY_RUN:
        log.info("[DRY RUN] Reddit Payload:\n%s", message)
        return
        
    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent="TrustMinerBot/1.0",
            username=username,
            password=password
        )
        
        # Extract title from the first line of the spun message
        title_split = message.split('\n', 1)
        title = title_split[0] if len(title_split) > 0 else "Profitable Micro-SaaS for Sale!"
        
        reddit.subreddit("SaaS").submit(title=title, selftext=message)
        log.info("Successfully posted to Reddit.")
    except Exception as e:
        log.error("Reddit post failed: %s", e)

def main():
    load_dotenv()
    
    if DRY_RUN:
        log.info("DRY_RUN is ENABLED. No API calls will be made.")
        
    deal = get_best_deal()
    if not deal:
        log.warning("No suitable deals found in database.")
        return
        
    bot_token = os.getenv("BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
    wiseurl_base = os.getenv("WISEURL_BASE", "https://yourdomain.com/go/")
    
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    username = os.getenv("REDDIT_USERNAME")
    password = os.getenv("REDDIT_PASSWORD")
    
    message = build_message(deal, wiseurl_base)
    
    log.info("=== Spun Message ===")
    log.info("\n%s\n", message)
    log.info("====================")
    
    # TELEGRAM NUCLEUS
    if bot_token and channel_id:
        broadcast_telegram(message, bot_token, channel_id)
    else:
        log.warning("Missing Telegram credentials. Skipping Telegram broadcast.")
        
    # REDDIT DEAD THREAD REVIVAL
    if client_id and client_secret and username and password:
        if not DRY_RUN:
            sleep_time = random.uniform(30, 90)
            log.info("Sleeping for %.1f seconds before Reddit post...", sleep_time)
            time.sleep(sleep_time)
        post_to_reddit(message, client_id, client_secret, username, password)
    else:
        log.warning("Missing Reddit credentials. Skipping Reddit post.")

if __name__ == "__main__":
    main()
