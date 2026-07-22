"""
render_deploy.py — Autonomous Render.com deployment script for TRUST-MINER.
Reads credentials from .env, creates a Background Worker + Persistent Disk via the Render API.
SECURITY: No secrets are printed; only status messages and non-sensitive metadata are logged.
"""
import os
import sys
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

# ── Load local .env so we can inject those vars into Render ──────────────────
load_dotenv(Path(__file__).parent / ".env")

RENDER_API_KEY = os.getenv("RENDER_API_KEY")
if not RENDER_API_KEY:
    print("[ERROR] RENDER_API_KEY not found. Pass it as an environment variable.")
    sys.exit(1)

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": f"Bearer {RENDER_API_KEY}",
}

BASE_URL = "https://api.render.com/v1"
GITHUB_REPO = "https://github.com/Mavadokuti1/TRUST-MINER"
SERVICE_NAME = "trust-miner-bot"

# ── Keys to read from .env and inject into Render ───────────────────────────
ENV_KEYS = [
    "DB_PATH",
    "BOT_TOKEN",
    "TELEGRAM_CHANNEL_ID",
    "WISEURL_BASE",
    "AFFILIATE_TAG",
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_SECRET",
    "LINKEDIN_LI_AT",
    "LINKEDIN_JSESSIONID",
    "MEDIUM_SID",
]

# DB_PATH override — must point to the persistent disk mount path on Render
ENV_OVERRIDES = {
    "DB_PATH": "/var/data/trustmrr_deals.db",
}


def get_owner_id() -> str:
    """Fetch the first workspace owner ID associated with the API key."""
    print("[INFO] Fetching Render workspace owner ID...")
    r = requests.get(f"{BASE_URL}/owners", headers=HEADERS, timeout=15)
    if not r.ok:
        print(f"[ERROR] Failed to fetch owners: HTTP {r.status_code} — {r.text}")
        sys.exit(1)
    owners = r.json()
    if not owners:
        print("[ERROR] No owners/workspaces found for this API key.")
        sys.exit(1)
    owner = owners[0]["owner"]
    print(f"[INFO] Workspace found: '{owner['name']}' (type: {owner['type']})")
    return owner["id"]


def build_env_vars() -> list:
    """Build the envVars list from local .env, applying any overrides."""
    env_vars = []
    present = []
    missing = []
    for key in ENV_KEYS:
        value = ENV_OVERRIDES.get(key) or os.getenv(key)
        if value:
            env_vars.append({"key": key, "value": value})
            present.append(key)
        else:
            missing.append(key)

    print(f"[INFO] Env vars to inject ({len(present)}): {', '.join(present)}")
    if missing:
        print(f"[WARNING] Missing env vars (will be skipped): {', '.join(missing)}")
    return env_vars


def create_service(owner_id: str, env_vars: list) -> dict:
    """Create the Background Worker service on Render via API."""
    print("[INFO] Creating Background Worker service on Render...")
    payload = {
        "type": "background_worker",
        "name": SERVICE_NAME,
        "ownerId": owner_id,
        "repo": GITHUB_REPO,
        "branch": "main",
        "autoDeploy": "yes",
        "envVars": env_vars,
        "serviceDetails": {
            "env": "python",
            "startCommand": "python telegram_bot.py",
            "plan": "starter",
            "envSpecificDetails": {
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": "python telegram_bot.py",
            },
            "disk": {
                "name": "trust-miner-db",
                "mountPath": "/var/data",
                "sizeGB": 1,
            },
        },
    }

    r = requests.post(f"{BASE_URL}/services", headers=HEADERS, json=payload, timeout=30)

    if r.status_code == 201:
        service = r.json()
        service_id = service.get("service", {}).get("id", "unknown")
        deploy_id = service.get("deployId", "unknown")
        dashboard_url = f"https://dashboard.render.com/worker/{service_id}"
        print(f"[SUCCESS] Service created successfully!")
        print(f"[INFO]    Service ID  : {service_id}")
        print(f"[INFO]    Deploy ID   : {deploy_id}")
        print(f"[INFO]    Dashboard   : {dashboard_url}")
        return service
    elif r.status_code == 400 and "already exists" in r.text:
        print(f"[WARNING] A service named '{SERVICE_NAME}' already exists in this workspace.")
        print("[INFO] No duplicate created. Check your Render dashboard.")
        sys.exit(0)
    elif r.status_code == 401:
        print("[ERROR] Authentication failed. Render API key is invalid or revoked.")
        sys.exit(1)
    elif r.status_code == 403:
        print("[ERROR] Access forbidden. The API key may not have permission to create services.")
        sys.exit(1)
    else:
        # Check for GitHub not connected error
        body = r.text
        if "github" in body.lower() or "repository" in body.lower() or "repo" in body.lower():
            print(f"[ERROR] GitHub not connected to Render.")
            print("[ACTION REQUIRED] Open this URL in your browser to authorize:")
            print("        https://dashboard.render.com/select-repo?type=github")
            print("        Then run this script again.")
        else:
            print(f"[ERROR] Service creation failed: HTTP {r.status_code}")
            print(f"[ERROR] Response: {body}")
        sys.exit(1)


def main():
    print("=" * 60)
    print("TRUST-MINER — Autonomous Render Deployment")
    print("=" * 60)

    owner_id = get_owner_id()
    env_vars = build_env_vars()
    create_service(owner_id, env_vars)

    print("=" * 60)
    print("[DONE] Deployment sequence complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
