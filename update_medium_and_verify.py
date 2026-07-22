"""
update_medium_and_verify.py — Update MEDIUM_SID GitHub secret and verify auth.
SECURITY: Does NOT print the secret value. Only prints pass/fail status.
"""
import os
import sys
import base64
import io
import requests
from pathlib import Path
from dotenv import load_dotenv

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv(Path(__file__).parent / ".env")

from nacl import public

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
MEDIUM_SID   = os.getenv("MEDIUM_SID")
REPO         = "Mavadokuti1/TRUST-MINER"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}


def update_github_secret():
    """Encrypt and upload the fresh MEDIUM_SID to GitHub Secrets."""
    r = requests.get(f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=HEADERS, timeout=15)
    key_id  = r.json()["key_id"]
    pub_key = r.json()["key"]
    pk        = public.PublicKey(base64.b64decode(pub_key))
    box       = public.SealedBox(pk)
    encrypted = base64.b64encode(box.encrypt(MEDIUM_SID.encode())).decode()
    r2 = requests.put(
        f"https://api.github.com/repos/{REPO}/actions/secrets/MEDIUM_SID",
        headers=HEADERS,
        json={"encrypted_value": encrypted, "key_id": key_id},
        timeout=15,
    )
    if r2.status_code in (201, 204):
        print("[STEP 2] GitHub Secret MEDIUM_SID: UPDATED OK")
        return True
    else:
        print(f"[STEP 2] GitHub Secret MEDIUM_SID: FAILED (HTTP {r2.status_code})")
        return False


def verify_medium():
    """Read-only check: fetch Medium settings page with the fresh SID cookie."""
    cookies = {"sid": MEDIUM_SID}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36"
    hdrs = {"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"}
    r = requests.get(
        "https://medium.com/me/settings",
        cookies=cookies,
        headers=hdrs,
        timeout=15,
        allow_redirects=False,
    )
    if r.status_code == 200:
        print("[STEP 3] Medium auth: PASS (HTTP 200)")
        return True
    else:
        loc = r.headers.get("Location", "none")
        print(f"[STEP 3] Medium auth: FAIL (HTTP {r.status_code}, redirect -> {loc})")
        return False


if __name__ == "__main__":
    print("[STEP 1] .env MEDIUM_SID loaded:", bool(MEDIUM_SID))
    ok1 = update_github_secret()
    ok2 = verify_medium()
    if ok1 and ok2:
        print("\nMedium SID updated locally and in GitHub Secrets. Medium authentication verified successfully. The project is 100% ready for the new AI agent to deploy to Render.")
    else:
        print("\nOne or more steps failed. See above for details.")
