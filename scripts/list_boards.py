#!/usr/bin/env python3
"""
List all Pinterest boards on the connected account with their numeric IDs.

Reads the OAuth access token from the settings table (same one the app uses)
and calls the Pinterest v5 API. Use it to get a board's ID when adding a new
board to config.py PINTEREST_BOARDS.

Run: python3 scripts/list_boards.py
"""
import os
import sys
import json
import psycopg2
import requests

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.ehksqgyndmyihvyzumgj:7qFTfJCkQh1SJxxj@aws-1-us-east-1.pooler.supabase.com:5432/postgres",
)
API = "https://api.pinterest.com/v5"


def setting(cur, key):
    cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = cur.fetchone()
    return row[0] if row else None


def refresh_token(refresh, app_id, secret):
    import base64
    auth = base64.b64encode(f"{app_id}:{secret}".encode()).decode()
    r = requests.post(
        f"{API}/oauth/token",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": refresh},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("access_token")


def list_boards(token):
    boards, bookmark = [], None
    while True:
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark
        r = requests.get(f"{API}/boards", headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
        if r.status_code == 401:
            return None  # token expired
        r.raise_for_status()
        data = r.json()
        boards.extend(data.get("items", []))
        bookmark = data.get("bookmark")
        if not bookmark:
            break
    return boards


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    token = setting(cur, "pinterest_access_token")
    if not token:
        print("No pinterest_access_token in settings — connect Pinterest in Setup first.")
        return 1

    boards = list_boards(token)
    if boards is None:
        # try refresh
        refresh = setting(cur, "pinterest_refresh_token")
        app_id = os.environ.get("PINTEREST_APP_ID") or setting(cur, "pinterest_app_id")
        secret = os.environ.get("PINTEREST_APP_SECRET") or setting(cur, "pinterest_app_secret")
        if refresh and app_id and secret:
            print("Access token expired — refreshing...")
            token = refresh_token(refresh, app_id, secret)
            boards = list_boards(token)
        if boards is None:
            print("Token expired and refresh failed. Re-connect Pinterest in Setup.")
            return 1

    print(f"\n{len(boards)} boards on the connected account:\n")
    for b in sorted(boards, key=lambda x: x.get("name", "")):
        print(f'  {b.get("id"):<22}  {b.get("name")}')
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
