"""
github_secrets_upload.py — Securely pushes all .env variables to GitHub Repository Secrets.
Uses the GitHub API with libsodium (PyNaCl) sealed-box encryption as required by GitHub.
SECURITY: No secret values are ever printed or logged.
"""
import os
import sys
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

try:
    from nacl import encoding, public
except ImportError:
    print("[ERROR] PyNaCl not installed. Run: pip install PyNaCl")
    sys.exit(1)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO         = "Mavadokuti1/TRUST-MINER"
API_BASE     = f"https://api.github.com/repos/{REPO}"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Secrets to upload (key name in GitHub Secrets → env var name in .env)
SECRETS_TO_UPLOAD = {
    "DB_PATH":               "/var/data/trustmirr_deals.db",  # Hard-coded override for Render
    "BOT_TOKEN":             os.getenv("BOT_TOKEN"),
    "TELEGRAM_CHANNEL_ID":   os.getenv("TELEGRAM_CHANNEL_ID"),
    "WISEURL_BASE":          os.getenv("WISEURL_BASE"),
    "AFFILIATE_TAG":         os.getenv("AFFILIATE_TAG"),
    "TWITTER_API_KEY":       os.getenv("TWITTER_API_KEY"),
    "TWITTER_API_SECRET":    os.getenv("TWITTER_API_SECRET"),
    "TWITTER_ACCESS_TOKEN":  os.getenv("TWITTER_ACCESS_TOKEN"),
    "TWITTER_ACCESS_SECRET": os.getenv("TWITTER_ACCESS_SECRET"),
    "LINKEDIN_LI_AT":        os.getenv("LINKEDIN_LI_AT"),
    "LINKEDIN_JSESSIONID":   os.getenv("LINKEDIN_JSESSIONID"),
    "MEDIUM_SID":            os.getenv("MEDIUM_SID"),
}


def get_public_key() -> tuple[str, str]:
    """Fetch the repo's public key for secret encryption."""
    r = requests.get(f"{API_BASE}/actions/secrets/public-key", headers=HEADERS, timeout=15)
    if not r.ok:
        print(f"[ERROR] Could not fetch public key: HTTP {r.status_code} — {r.text}")
        sys.exit(1)
    data = r.json()
    return data["key_id"], data["key"]


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Encrypt secret_value using libsodium sealed box with the repo's public key."""
    public_key_bytes = base64.b64decode(public_key_b64)
    pk = public.PublicKey(public_key_bytes)
    sealed_box = public.SealedBox(pk)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def upload_secret(secret_name: str, secret_value: str, key_id: str, public_key_b64: str) -> bool:
    """PUT an encrypted secret to the GitHub repo."""
    encrypted_value = encrypt_secret(public_key_b64, secret_value)
    payload = {"encrypted_value": encrypted_value, "key_id": key_id}
    r = requests.put(
        f"{API_BASE}/actions/secrets/{secret_name}",
        headers=HEADERS, json=payload, timeout=15,
    )
    if r.status_code in (201, 204):
        print(f"  [OK]  {secret_name}")
        return True
    else:
        print(f"  [ERR] {secret_name} — HTTP {r.status_code}: {r.text}")
        return False


def main():
    if not GITHUB_TOKEN:
        print("[ERROR] GITHUB_TOKEN not found in .env")
        sys.exit(1)

    print("=" * 55)
    print("TRUST-MINER — GitHub Secrets Upload")
    print("=" * 55)

    key_id, public_key_b64 = get_public_key()
    print(f"[INFO] Repo public key fetched (key_id: {key_id})")
    print(f"[INFO] Uploading {len(SECRETS_TO_UPLOAD)} secrets...")

    passed, failed = 0, 0
    for name, value in SECRETS_TO_UPLOAD.items():
        if not value:
            print(f"  [SKIP] {name} — value is empty/None")
            continue
        if upload_secret(name, value, key_id, public_key_b64):
            passed += 1
        else:
            failed += 1

    print("-" * 55)
    print(f"Result: {passed} secrets uploaded, {failed} failed.")
    if failed == 0:
        print("All secrets securely stored in GitHub Repository Secrets.")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
