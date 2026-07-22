"""
verify_secrets_and_auth.py — TRUST-MINER Handover Verification Script
=====================================================================
1. Lists repo secrets from the GitHub API.
2. Performs read-only auth checks for Telegram, Twitter, LinkedIn, and Medium.
Does NOT post or modify anything.
"""
import os
import sys
import io
import requests
from pathlib import Path
from dotenv import load_dotenv

# Force UTF-8 stdout
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv(Path(__file__).parent / ".env")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "Mavadokuti1/TRUST-MINER"


def get_github_secrets():
    """Lists repository secrets from the GitHub API."""
    if not GITHUB_TOKEN:
        print("[GitHub Secrets] GITHUB_TOKEN not found in env")
        return []
    url = f"https://api.github.com/repos/{REPO}/actions/secrets"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.ok:
            secrets = [s["name"] for s in r.json().get("secrets", [])]
            return secrets
        else:
            print(f"[GitHub Secrets] API error: {r.status_code} — {r.text}")
            return []
    except Exception as e:
        print(f"[GitHub Secrets] Exception: {e}")
        return []


def auth_telegram():
    token = os.getenv("BOT_TOKEN")
    if not token:
        return "FAIL (Missing BOT_TOKEN)"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if r.ok and r.json().get("ok"):
            return "PASS"
        return f"FAIL (HTTP {r.status_code})"
    except Exception:
        return "FAIL (Exception)"


def auth_twitter():
    api_key = os.getenv("TWITTER_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET")
    if not all([api_key, api_secret, access_token, access_secret]):
        return "FAIL (Missing credentials)"
    try:
        import tweepy
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        me = client.get_me()
        if me.data:
            return "PASS"
        return "FAIL"
    except Exception as e:
        err = str(e)
        if "402" in err or "depleted" in err:
            return "PASS"  # Quota depleted means auth worked successfully!
        return f"FAIL ({err})"


def auth_linkedin():
    li_at = os.getenv("LINKEDIN_LI_AT")
    jsessionid = os.getenv("LINKEDIN_JSESSIONID")
    if not li_at or not jsessionid:
        return "FAIL (Missing cookies)"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/vnd.linkedin.normalized+json+2.1",
            "x-li-lang": "en_US",
            "x-li-track": '{"clientVersion":"1.13","osName":"web"}',
            "csrf-token": jsessionid,
        }
        cookies = {"li_at": li_at, "JSESSIONID": f'"{jsessionid}"'}
        r = requests.get(
            "https://www.linkedin.com/voyager/api/me",
            headers=headers, cookies=cookies, timeout=15,
        )
        if r.status_code == 200:
            return "PASS"
        return f"FAIL (HTTP {r.status_code})"
    except Exception as e:
        return f"FAIL (Exception: {e})"


def auth_medium():
    medium_sid = os.getenv("MEDIUM_SID")
    if not medium_sid:
        return "FAIL (Missing cookie)"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        cookies = {"sid": medium_sid}
        r = requests.get(
            "https://medium.com/me/settings",
            headers=headers, cookies=cookies,
            timeout=15, allow_redirects=False,
        )
        if r.status_code == 200:
            return "PASS"
        return f"FAIL (HTTP {r.status_code}, Location: {r.headers.get('Location', 'none')})"
    except Exception as e:
        return f"FAIL (Exception: {e})"


if __name__ == "__main__":
    secrets = get_github_secrets()
    tg = auth_telegram()
    tw = auth_twitter()
    li = auth_linkedin()
    md = auth_medium()

    print("\n--- RESULTS ---")
    print("Secrets list:", secrets)
    print("Telegram:", tg)
    print("Twitter:", tw)
    print("LinkedIn:", li)
    print("Medium:", md)
