import os
import requests
import logging
import sqlite3
import random
import time
import asyncio
import subprocess
from pathlib import Path
from dotenv import load_dotenv

import praw
import spintax
import tweepy
from linkitin import LinkitinClient

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
    """Use spintax to generate a unique post. Returns (message_with_link, message_no_link, wise_url)."""
    slug = deal.get("slug", "")
    name = deal.get("name", "Unknown")
    category = deal.get("category") or "Software"
    mrr = f"{deal.get('mrr', 0):,.0f}" if deal.get("mrr") is not None else "0"
    price = f"{deal.get('price', 0):,.0f}" if deal.get("price") is not None else "0"
    multiple = f"{deal.get('multiple', 0):.2f}" if deal.get("multiple") is not None else "N/A"
    
    wise_url = f"{wiseurl_base}{slug}"
    
    # No-link version for Twitter tweet_1 (avoids X algorithm link suppression)
    spin_no_link = (
        "{🚨|🔥|💎} {Micro-SaaS Deal|SaaS Acquisition|Profitable Startup} of the Day!\n"
        f"Name: {name} ({category})\n"
        f"MRR: ${mrr}/mo\n"
        f"Asking: ${price}\n"
        f"{{This is a highly profitable|Great}} {multiple}x multiple."
    )

    # Full version with link for all other platforms
    spin_template = spin_no_link + f"\n\n{{View the metrics here|Check the verified numbers}}: {wise_url}"
    
    return spintax.spin(spin_template), spintax.spin(spin_no_link), wise_url

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

async def post_to_linkedin(message, li_at, jsessionid):
    """Post message to LinkedIn."""
    if DRY_RUN:
        log.info("[DRY RUN] LinkedIn Payload:\n%s", message)
        return
        
    try:
        li = LinkitinClient()
        await li.login_with_cookies(li_at, jsessionid)
        # linkitin supports document (PDF carousel) uploads which get 3-5x reach. Text posting implemented here as baseline.
        await li.create_post(message)
        log.info("Successfully posted to LinkedIn.")
    except Exception as e:
        log.error("LinkedIn post failed: %s", e)

def post_to_medium(message, medium_sid):
    """Post message to Medium via medium-ops CLI."""
    if DRY_RUN:
        log.info("[DRY RUN] Medium Payload:\n%s", message)
        return
        
    try:
        temp_dir = os.environ.get("TEMP", "/tmp")
        draft_path = Path(temp_dir) / "medium_draft.md"
        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(message)
            
        env = os.environ.copy()
        env["MEDIUM_SID"] = medium_sid
        
        subprocess.run(["medium-ops", "publish", str(draft_path)], env=env, check=True, capture_output=True)
        log.info("Successfully posted to Medium.")
    except Exception as e:
        log.error("Medium post failed: %s", e)

def post_to_twitter(message_no_link, wise_url, api_key, api_secret, access_token, access_secret):
    """
    Post a two-part thread to Twitter/X via tweepy (API v2).

    Anti-algorithm strategy:
    - tweet_1: metrics-only text with NO link (avoids X's link-suppression penalty on reach).
    - tweet_2: reply to tweet_1 containing only the bridge URL, maximising first-tweet distribution.
    """
    if DRY_RUN:
        log.info("[DRY RUN] Twitter tweet_1 Payload:\n%s", message_no_link)
        log.info("[DRY RUN] Twitter tweet_2 Payload:\nCheck out the full deal details here: %s", wise_url)
        return

    try:
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        # Step 1: Post the metrics tweet (no link = no reach penalty)
        response = client.create_tweet(text=message_no_link)
        tweet_1_id = response.data["id"]
        log.info("Twitter tweet_1 posted (id=%s).", tweet_1_id)

        # Step 2: Reply with the bridge link as a threaded reply
        client.create_tweet(
            text=f"Check out the full deal details here: {wise_url}",
            in_reply_to_tweet_id=tweet_1_id,
        )
        log.info("Twitter tweet_2 (link reply) posted successfully.")
    except Exception as e:
        log.error("Twitter post failed: %s", e)

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
    
    medium_sid = os.getenv("MEDIUM_SID")
    
    twitter_api_key = os.getenv("TWITTER_API_KEY")
    twitter_api_secret = os.getenv("TWITTER_API_SECRET")
    twitter_access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    twitter_access_secret = os.getenv("TWITTER_ACCESS_SECRET")

    message, message_no_link, wise_url = build_message(deal, wiseurl_base)
    
    log.info("=== Spun Message ===")
    log.info("\n%s\n", message)
    log.info("====================")
    
    # 1. TELEGRAM NUCLEUS
    if bot_token and channel_id:
        broadcast_telegram(message, bot_token, channel_id)
    else:
        log.warning("Missing Telegram credentials. Skipping Telegram broadcast.")
        
    # 2. REDDIT DEAD THREAD REVIVAL
    if client_id and client_secret and username and password:
        if not DRY_RUN:
            sleep_time = random.uniform(30, 90)
            log.info("Sleeping for %.1f seconds before Reddit post...", sleep_time)
            time.sleep(sleep_time)
        post_to_reddit(message, client_id, client_secret, username, password)
    else:
        log.warning("Missing Reddit credentials. Skipping Reddit post.")

    # 3. LINKEDIN CONNECTOR
    li_at = os.getenv("LINKEDIN_LI_AT")
    jsessionid = os.getenv("LINKEDIN_JSESSIONID")
    if not li_at or not jsessionid:
        log.warning("Missing LinkedIn credentials. Skipping LinkedIn post.")
    else:
        if not DRY_RUN:
            sleep_time = random.uniform(30, 90)
            log.info("Sleeping for %.1f seconds before LinkedIn post...", sleep_time)
            time.sleep(sleep_time)
        asyncio.run(post_to_linkedin(message, li_at, jsessionid))

    # 4. MEDIUM CONNECTOR
    if medium_sid:
        if not DRY_RUN:
            sleep_time = random.uniform(30, 90)
            log.info("Sleeping for %.1f seconds before Medium post...", sleep_time)
            time.sleep(sleep_time)
        post_to_medium(message, medium_sid)
    else:
        log.warning("Missing Medium credentials. Skipping Medium post.")

    # 5. TWITTER/X THREAD CONNECTOR
    if twitter_api_key and twitter_api_secret and twitter_access_token and twitter_access_secret:
        if not DRY_RUN:
            sleep_time = random.uniform(30, 90)
            log.info("Sleeping for %.1f seconds before Twitter post...", sleep_time)
            time.sleep(sleep_time)
        post_to_twitter(message_no_link, wise_url, twitter_api_key, twitter_api_secret,
                        twitter_access_token, twitter_access_secret)
    else:
        log.warning("Missing Twitter credentials. Skipping Twitter post.")

if __name__ == "__main__":
    main()
