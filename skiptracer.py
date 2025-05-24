#!/usr/bin/env python3
"""Skip tracing using Decodo's scrape API."""

import os
import re
import time
import argparse
from typing import Dict, List
from urllib.parse import quote_plus

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

DECODO_USERNAME = os.getenv("DECODO_USERNAME")
DECODO_PASSWORD = os.getenv("DECODO_PASSWORD")

if not DECODO_USERNAME or not DECODO_PASSWORD:
    raise RuntimeError(
        "DECODO_USERNAME and DECODO_PASSWORD must be set in the environment"
    )

SCRAPE_URL = "https://scraper-api.decodo.com/v2/scrape"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
PHONE_RE = re.compile(r"\b(\d{3})[\s.-]?(\d{3})[\s.-]?(\d{4})\b")

auth = (DECODO_USERNAME, DECODO_PASSWORD)

def _normalize_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number

def _parse_phones(text: str) -> List[str]:
    return list({_normalize_phone(''.join(m)) for m in PHONE_RE.findall(text or "")})

def fetch_url(results_url: str, timeout: int = 120, *, visible: bool = False) -> str:
    payload = {
        "url": results_url,
        "headless": "html",
        "http_method": "GET",
        "geo": "US",
        "locale": "en-US",
        "session_id": "tsp-session-1",
    }
    print(f"📡 Payload: {payload}")
    for attempt in range(3):
        try:
            resp = requests.post(
                SCRAPE_URL,
                json=payload,
                auth=auth,
                headers=HEADERS,
                timeout=timeout,
            )
            print(f"🌐 fetch HTTP {resp.status_code}")
            if resp.status_code == 429 and attempt < 2:
                print("⏳ Received 429, retrying in 5s")
                time.sleep(5)
                continue
            resp.raise_for_status()
            data = resp.json() if "application/json" in resp.headers.get("Content-Type", "") else {}
            html = (
                data.get("content")
                or data.get("html")
                or data.get("result")
                or ""
            )
            if visible:
                print(html)
            else:
                print(html[:500])
            return html
        except Exception as exc:
            if attempt < 2:
                print(f"❌ {exc} - retrying in 5s")
                time.sleep(5)
                continue
            print(f"❌ {exc}")
            raise
    raise RuntimeError("Failed to fetch URL")

def parse_html(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    name_el = soup.find("h1") or soup.select_one("div.result-name")
    name = name_el.get_text(strip=True) if name_el else ""
    addr = ""
    for card in soup.select("div.card"):
        if "Current Address" in card.get_text():
            addr = card.get_text(strip=True)
            break
    phones = _parse_phones(soup.get_text(" "))
    phone_str = "; ".join(phones)
    status = "Success" if any([name, addr, phone_str]) else "No Results"
    return {
        "Owner Name": name,
        "Owner Address": addr,
        "Phone Numbers": phone_str,
        "Status": status,
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Skip tracer using Decodo's scrape API")
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=120,
        help="Timeout in seconds for HTTP requests",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Print the entire HTML response instead of just a snippet",
    )
    args = parser.parse_args()

    df = pd.read_csv("input.csv")
    results = []
    for _, row in df.iterrows():
        full_addr = f"{row['Address']}, {row['City']}, {row['StateZip']}"
        results_url = (
            "https://www.truepeoplesearch.com/results?name=&citystatezip="
            + quote_plus(full_addr)
        )
        try:
            html = fetch_url(
                results_url,
                timeout=args.request_timeout,
                visible=args.visible,
            )
            data = parse_html(html)
        except Exception as exc:
            data = {
                "Owner Name": "",
                "Owner Address": "",
                "Phone Numbers": "",
                "Status": f"Error: {exc}",
            }
        data["Input Address"] = full_addr
        print(f"📍 Input: {full_addr}")
        print(f"📄 Name: {data.get('Owner Name')}")
        print(f"🏠 Address: {data.get('Owner Address')}")
        print(f"📞 Phones: {data.get('Phone Numbers')}")
        print(f"📌 Status: {data.get('Status')}")
        results.append(data)

    pd.DataFrame(results).to_csv("output.csv", index=False)

if __name__ == "__main__":
    main()
