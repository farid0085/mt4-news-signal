#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Creates news_signal.csv for MT4 EA v18.
Source: Trading Economics Calendar API or fallback manual events.

Required GitHub Secrets:
  TE_CLIENT
  TE_SECRET

Output:
  news_signal.csv

CSV format:
  YYYY.MM.DD HH:MI,USD,HIGH,PAUSE|BUY|SELL|BLOCK,valid_minutes,comment
"""

import csv
import datetime as dt
import os
import sys
from urllib.parse import urlencode
from urllib.request import urlopen, Request
import json

OUTPUT_FILE = "news_signal.csv"

# For NAS100 and XAUUSD, USD news is the main driver.
COUNTRIES = ["United States"]
CURRENCIES = ["USD"]

# Events that usually move NAS100/XAUUSD strongly.
HIGH_IMPACT_KEYWORDS = [
    "Non Farm Payrolls", "Nonfarm Payrolls", "NFP",
    "Unemployment Rate",
    "CPI", "Core CPI", "Inflation Rate",
    "PCE", "Core PCE",
    "Federal Funds Rate", "Fed Interest Rate Decision",
    "FOMC", "Powell",
    "GDP Growth Rate",
    "Retail Sales",
    "ISM Manufacturing", "ISM Services",
    "JOLTs",
    "Initial Jobless Claims",
]

# Default behavior:
# Before high-impact event -> PAUSE.
# After event -> direction is not guessed blindly.
# We use PAUSE rows by default. BUY/SELL rows should only be generated if actual/forecast logic is implemented.
DEFAULT_VALID_MINUTES = 60
PRE_NEWS_PAUSE_MINUTES = 30

def normalize_time_for_mt4(iso_time: str) -> str:
    """
    Converts Trading Economics date to 'YYYY.MM.DD HH:MM'.
    Keeps UTC/server time assumption. Adjust in code if your MT4 server timezone differs.
    """
    s = iso_time.replace("T", " ").replace("Z", "")
    # Try several formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = dt.datetime.strptime(s[:19], fmt)
            return d.strftime("%Y.%m.%d %H:%M")
        except Exception:
            pass
    return ""

def event_is_high_impact(event: dict) -> bool:
    importance = str(event.get("Importance") or event.get("importance") or "").lower()
    name = str(event.get("Event") or event.get("event") or event.get("Category") or "")
    if "high" in importance or importance == "3":
        return True
    for kw in HIGH_IMPACT_KEYWORDS:
        if kw.lower() in name.lower():
            return True
    return False

def classify_event_action(event: dict) -> str:
    """
    Conservative default:
    - PAUSE for high-impact USD events.
    You can later add actual-vs-forecast logic after the release:
      stronger USD -> for NAS100 often SELL, for XAUUSD often SELL
      weaker USD -> for NAS100 often BUY, for XAUUSD often BUY
    """
    return "PAUSE"

def fetch_trading_economics_calendar():
    client = os.getenv("TE_CLIENT", "").strip()
    secret = os.getenv("TE_SECRET", "").strip()

    if not client or not secret:
        raise RuntimeError("Missing TE_CLIENT or TE_SECRET GitHub secrets.")

    today = dt.date.today()
    end = today + dt.timedelta(days=7)

    # Trading Economics supports calendar API and JSON/CSV output.
    # Endpoint shape may depend on account plan; adjust if your TE plan provides another URL.
    base_url = "https://api.tradingeconomics.com/calendar/country/united%20states"
    params = {
        "c": f"{client}:{secret}",
        "format": "json",
        "d1": today.isoformat(),
        "d2": end.isoformat(),
    }
    url = base_url + "?" + urlencode(params)

    req = Request(url, headers={"User-Agent": "MT4-news-signal-generator"})
    with urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", errors="replace")

    data = json.loads(raw)
    if isinstance(data, dict) and "Calendar" in data:
        data = data["Calendar"]
    if not isinstance(data, list):
        raise RuntimeError("Unexpected API response format.")

    return data

def create_rows(events):
    rows = []
    seen = set()

    for ev in events:
        country = str(ev.get("Country") or ev.get("country") or "")
        if country and "united" not in country.lower():
            continue

        if not event_is_high_impact(ev):
            continue

        event_name = str(ev.get("Event") or ev.get("event") or ev.get("Category") or "USD event")
        date_raw = str(ev.get("Date") or ev.get("date") or ev.get("LastUpdate") or "")
        mt4_time = normalize_time_for_mt4(date_raw)
        if not mt4_time:
            continue

        action = classify_event_action(ev)
        key = (mt4_time, "USD", action, event_name)
        if key in seen:
            continue
        seen.add(key)

        rows.append([
            mt4_time,
            "USD",
            "HIGH",
            action,
            str(DEFAULT_VALID_MINUTES),
            event_name.replace(",", " ")
        ])

    rows.sort(key=lambda x: x[0])
    return rows

def write_csv(rows):
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)

def write_fallback():
    # Keeps file valid if API fails. Bot will still run, but without news bias.
    now = dt.datetime.utcnow().replace(second=0, microsecond=0)
    fallback_time = (now + dt.timedelta(days=1)).strftime("%Y.%m.%d %H:%M")
    rows = [[fallback_time, "USD", "HIGH", "PAUSE", "30", "fallback placeholder - replace API/secrets"]]
    write_csv(rows)

def main():
    try:
        events = fetch_trading_economics_calendar()
        rows = create_rows(events)
        if not rows:
            write_fallback()
            print("No high-impact events found; fallback file written.")
        else:
            write_csv(rows)
            print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        write_fallback()
        print("Fallback news_signal.csv written.")
        # Do not fail workflow hard; MT4 can still download fallback file.

if __name__ == "__main__":
    main()
