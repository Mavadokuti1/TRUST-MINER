"""
test_connections.py — TRUST-MINER Platform Connection Verifier
==============================================================
Performs authentication-only checks for all 4 platforms.
Does NOT post any content to public channels.
Reports pass/fail for each without printing secret values.
"""
import os
import sys
import io
import requests
from pathlib import Path
from dotenv import load_dotenv

# Force UTF-8 output on Windows to avoid cp1252 encoding errors
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv(Path(__file__).parent / ".env")

PASS = "[PASS]"
FAIL = "[FAIL]"
results = {}


# ─── 1. TELEGRAM ─────────────────────────────────────────────────────────────
def test_telegram():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print(f"  [Telegram] {FAIL} — BOT_TOKEN not set")
        return False
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        data = r.json()
        if data.get("ok"):
            username = data["result"].get("username", "unknown")
            print(f"  [Telegram] {PASS} — Bot authenticated as @{username}")
            return True
        else:
            print(f"  [Telegram] {FAIL} — {data.get('description', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"  [Telegram] {FAIL} — Exception: {e}")
        return False


# ─── 2. TWITTER / X ──────────────────────────────────────────────────────────
def test_twitter():
    api_key        = os.getenv("TWITTER_API_KEY")
    api_secret     = os.getenv("TWITTER_API_SECRET")
    access_token   = os.getenv("TWITTER_ACCESS_TOKEN")
    access_secret  = os.getenv("TWITTER_ACCESS_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        print(f"  [Twitter]  {FAIL} — One or more Twitter credentials not set")
        return False
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
            print(f"  [Twitter]  {PASS} — Authenticated as @{me.data.username}")
            return True
        else:
            print(f"  [Twitter]  {FAIL} — get_me() returned no data")
            return False
    except Exception as e:
        err = str(e)
        if "403" in err or "forbidden" in err.lower():
            print(f"  [Twitter]  {FAIL} — 403 Forbidden (app permissions need Read+Write)")
        elif "401" in err:
            print(f"  [Twitter]  {FAIL} — 401 Unauthorized (invalid credentials)")
        elif "402" in err or "depleted" in err:
            # 402 means auth worked but quota depleted — credentials are valid
            print(f"  [Twitter]  {PASS} (quota limited) — Credentials valid but API credits depleted")
            return True
        else:
            print(f"  [Twitter]  {FAIL} — {err}")
        return False


# ─── 3. LINKEDIN ─────────────────────────────────────────────────────────────
def test_linkedin():
    li_at      = os.getenv("LINKEDIN_LI_AT")
    jsessionid = os.getenv("LINKEDIN_JSESSIONID")

    if not li_at or not jsessionid:
        print(f"  [LinkedIn] {FAIL} — LINKEDIN_LI_AT or LINKEDIN_JSESSIONID not set")
        return False
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
            try:
                name = r.json().get("miniProfile", {}).get("firstName", "")
                print(f"  [LinkedIn] {PASS} — Session active (name: {name if name else 'found'})")
            except Exception:
                print(f"  [LinkedIn] {PASS} — Session active (HTTP 200 received)")
            return True
        elif r.status_code == 401 or r.status_code == 403:
            print(f"  [LinkedIn] {FAIL} — Session expired or invalid cookies (HTTP {r.status_code})")
            return False
        else:
            print(f"  [LinkedIn] {FAIL} — Unexpected HTTP {r.status_code}")
            return False
    except Exception as e:
        print(f"  [LinkedIn] {FAIL} — Exception: {e}")
        return False


# ─── 4. MEDIUM ───────────────────────────────────────────────────────────────
def test_medium():
    medium_sid = os.getenv("MEDIUM_SID")
    if not medium_sid:
        print(f"  [Medium]   {FAIL} — MEDIUM_SID not set")
        return False
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
        # 200 = session valid and logged in; 301/302 = redirected to login = expired
        if r.status_code == 200:
            print(f"  [Medium]   {PASS} — Session active (HTTP 200)")
            return True
        elif r.status_code in (301, 302):
            loc = r.headers.get("Location", "")
            if "login" in loc or "sign" in loc:
                print(f"  [Medium]   {FAIL} — Session expired (redirected to login)")
                return False
            # Unexpected redirect but could still be valid
            print(f"  [Medium]   ⚠️ WARN — Redirect to {loc}, session may still be active")
            return True
        else:
            print(f"  [Medium]   {FAIL} — HTTP {r.status_code}")
            return False
    except Exception as e:
        print(f"  [Medium]   {FAIL} — Exception: {e}")
        return False


# ─── RUN ALL TESTS ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("TRUST-MINER — Platform Connection Verification")
    print("=" * 55)

    results["telegram"] = test_telegram()
    results["twitter"]  = test_twitter()
    results["linkedin"] = test_linkedin()
    results["medium"]   = test_medium()

    print("-" * 55)
    passed = sum(results.values())
    total  = len(results)
    print(f"Result: {passed}/{total} platforms verified successfully.")

    if passed < total:
        failed = [k for k, v in results.items() if not v]
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("All platform connections verified. Ready for deployment.")
        sys.exit(0)
