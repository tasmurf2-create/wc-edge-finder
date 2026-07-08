#!/usr/bin/env python3
"""
Paddy Power odds pusher (Option B) — run this on a RESIDENTIAL IRISH machine.

Paddy Power's GAA feed is Cloudflare + Ireland-geo gated, so the hosted app
(Render, a foreign data-centre IP) can't fetch it. This script runs where PP
*is* reachable — your Irish laptop — pulls the GAA odds and POSTs them to the
hosted app's /api/gaa/push endpoint, which stores and serves the snapshot.

While this is running the hosted GAA tab shows live PP prices + edges. Close the
laptop and the site keeps showing the last snapshot (flagged stale); reopen and
it refreshes on the next push.

Setup (on your laptop):
    set PUSH_URL=https://wc-edge-finder.onrender.com   (your app URL)
    set GAA_PUSH_SECRET=<same secret you set in Render env>
    python pp_push.py                 # loops every 10 min
    python pp_push.py --once          # single push then exit
    python pp_push.py --interval 300  # custom seconds

Leave the terminal open (or add it to Task Scheduler / cron) while you want the
hosted odds kept fresh.
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error

import paddypower


def _load_env(path=None):
    # Resolve .env next to this script so it works under Task Scheduler/cron
    # regardless of the current working directory.
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def push_once(base_url, secret):
    odds = paddypower.get_gaa_odds()
    if not odds:
        print(f"[{time.strftime('%H:%M:%S')}] no PP odds fetched — is this an Irish IP? skipping push")
        return False
    body = json.dumps({"odds": odds}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/gaa/push", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Push-Secret": secret})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            r = json.loads(resp.read().decode())
        print(f"[{time.strftime('%H:%M:%S')}] pushed {r.get('events')} events "
              f"({', '.join(odds.keys())})")
        return True
    except urllib.error.HTTPError as e:
        print(f"[{time.strftime('%H:%M:%S')}] push rejected: HTTP {e.code} {e.read().decode()[:200]}")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] push failed: {e}")
    return False


def main():
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="push once and exit")
    ap.add_argument("--interval", type=int, default=600, help="seconds between pushes (default 600)")
    ap.add_argument("--url", default=os.environ.get("PUSH_URL", ""), help="hosted app base URL")
    args = ap.parse_args()

    base_url = args.url.strip()
    secret = (os.environ.get("GAA_PUSH_SECRET") or "").strip()
    if not base_url:
        sys.exit("Set PUSH_URL (env) or pass --url, e.g. https://wc-edge-finder.onrender.com")
    if not secret:
        sys.exit("Set GAA_PUSH_SECRET (env) to the same value configured in Render.")

    print(f"Pusher target: {base_url}  |  interval: "
          f"{'once' if args.once else str(args.interval) + 's'}")
    if args.once:
        push_once(base_url, secret)
        return
    while True:
        push_once(base_url, secret)
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()
