#!/usr/bin/env python3
"""Batch skip tracer using Decodo's Web Scraper API."""

import os
import time
import re
from typing import Dict
import argparse
from urllib.parse import quote_plus
import logging

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
API_URL = "https://scraper-api.decodo.com/v2/scrape"
DELAY_SECONDS = 3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")


def _normalize_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number


def _parse_phones(text: str):
    return list({_normalize_phone(m) for m in PHONE_RE.findall(text or "")})


class Scraper:
    """Simple helper for fetching pages from Decodo's API."""

    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout

    def fetch(self, url: str) -> str:
        """Fetch HTML content using Decodo's API."""
        auth = (DECODO_USERNAME, DECODO_PASSWORD)
        payload = {
            "url": url,
            "headless": "html",
            "geo": "us",
            "locale": "en-US",
            "device_type": "desktop",
            "session_id": "skiptracer",
            "headers": {"User-Agent": "Mozilla/5.0"},
            "successful_status_codes": [200],
            "force_headers": True,
        }
        logger.info("Sending payload: %s", payload)
        resp = requests.post(
            API_URL,
            auth=auth,
            json=payload,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        logger.info("Response status: %s", resp.status_code)
        resp.raise_for_status()
        html = ""
        if "application/json" in resp.headers.get("Content-Type", ""):
            data = resp.json()
            html = data.get("content") or data.get("html") or data.get("result") or ""
        else:
            html = resp.text
        time.sleep(DELAY_SECONDS)
        return html


def extract_data(html: str) -> Dict[str, str]:
    """Extract the first result's details from TruePeopleSearch HTML."""
    soup = BeautifulSoup(html, "html.parser")
    card = soup.select_one("div.card")
    if not card:
        return {
            "Result Name": "",
            "Result Address": "",
            "Phone Number": "",
            "Status": "No Results",
        }
    name_el = card.select_one("a[href*='/details']")
    name = name_el.get_text(strip=True) if name_el else ""
    loc_el = card.find(string=re.compile("Current Address", re.I))
    address = loc_el.find_parent("div").get_text(strip=True) if loc_el else ""
    phones = _parse_phones(card.get_text(" "))
    phone = phones[0] if phones else ""
    status = "Success" if any([name, address, phone]) else "No Results"
    return {
        "Result Name": name,
        "Result Address": address,
        "Phone Number": phone,
        "Status": status,
    }


def scrape_address(address: str, scraper: Scraper) -> Dict[str, str]:
    """Scrape a single address from TruePeopleSearch."""
    try:
        url_address = quote_plus(address)
        url = f"https://www.truepeoplesearch.com/results?name=&citystatezip={url_address}"
        html = scraper.fetch(url)
        data = extract_data(html)
    except Exception as exc:
        return {
            "Input Address": address,
            "Result Name": "",
            "Result Address": "",
            "Phone Number": "",
            "Status": f"Error: {exc}",
        }
    data["Input Address"] = address
    return data



def main() -> None:
    parser = argparse.ArgumentParser(description="Batch skip tracer using Decodo's Web Scraper API")
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=60,
        help="Timeout in seconds for HTTP requests",
    )
    args = parser.parse_args()

    scraper = Scraper(timeout=args.request_timeout)
    df = pd.read_csv("input.csv")
    results = [
        scrape_address(addr, scraper)

        for addr in df.get("Address", [])
        if isinstance(addr, str)
    ]
    pd.DataFrame(results).to_csv("output.csv", index=False)


if __name__ == "__main__":
    main()
