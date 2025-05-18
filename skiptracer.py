"""Simple skip tracer using Playwright to scrape public sites."""

import os
import random
import re
import json
from typing import List, Dict
from urllib.parse import quote_plus

try:
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright
except ImportError as exc:
    missing = str(exc).split("'")[1]
    print(f"Missing dependency: install with `pip install {missing}`")
    raise SystemExit(1)

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")


def _normalize_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number


def _parse_phones(text: str) -> List[str]:
    phones = set()
    for match in PHONE_RE.findall(text or ""):
        normalized = _normalize_phone(match)
        phones.add(normalized)
    return list(phones)


def _ensure_logs():
    os.makedirs("logs", exist_ok=True)


def _fetch_html(url: str, debug: bool = False, retries: int = 3) -> str:
    """Fetches the given URL using Playwright and returns HTML."""
    last_html = ""
    for attempt in range(retries):
        ua = random.choice(USER_AGENTS)
        if debug:
            print(f"Fetching {url} (attempt {attempt + 1})")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=ua, extra_http_headers=HEADERS)
            page = context.new_page()
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
                status = response.status if response else None
                last_html = page.content()
                if status == 403:
                    if debug:
                        print("Blocked — retrying with new headers")
                    browser.close()
                    continue
                return last_html
            except Exception as exc:
                if debug:
                    print(f"Error: {exc}")
            finally:
                browser.close()
    if debug and last_html:
        _ensure_logs()
        with open("logs/debug_last.html", "w", encoding="utf-8") as fh:
            fh.write(last_html)
    return last_html


def search_truepeoplesearch(address: str, debug: bool = False) -> List[Dict[str, object]]:
    """Searches TruePeopleSearch for the given address."""
    if debug:
        print("Trying TruePeopleSearch...")
    url = "https://www.truepeoplesearch.com/results?" + f"streetaddress={quote_plus(address)}"
    html = _fetch_html(url, debug=debug)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card") or soup.select("div.result")
    if debug:
        print(f"Found {len(cards)} cards...")
    results = []
    for card in cards:
        name_el = card.find("a", href=re.compile("/details"))
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        location_el = card.find("div", class_=re.compile("address"))
        location = location_el.get_text(strip=True) if location_el else ""
        phone_text = card.get_text(" ")
        phones = _parse_phones(phone_text)
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "TruePeopleSearch",
            })
    if debug:
        print("Parsing result...")
    if debug and not results:
        print("No matches found.")
    return results


def search_fastpeoplesearch(address: str, debug: bool = False) -> List[Dict[str, object]]:
    """Searches FastPeopleSearch for the given address."""
    if debug:
        print("Trying FastPeopleSearch...")
    slug = quote_plus(address.lower().replace(",", "").replace(" ", "-"))
    url = f"https://www.fastpeoplesearch.com/address/{slug}"
    html = _fetch_html(url, debug=debug)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card") or soup.select("div.result")
    if debug:
        print(f"Found {len(cards)} cards...")
    results = []
    for card in cards:
        name_el = card.find("a", href=re.compile("/person"))
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        location_el = card.find("div", class_=re.compile("address"))
        location = location_el.get_text(strip=True) if location_el else ""
        phone_text = card.get_text(" ")
        phones = _parse_phones(phone_text)
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "FastPeopleSearch",
            })
    if debug:
        print("Parsing result...")
    if debug and not results:
        print("No matches found.")
    return results


def skip_trace(address: str, debug: bool = False) -> List[Dict[str, object]]:
    """Returns matches for the given property address."""
    try:
        results = search_truepeoplesearch(address, debug=debug)
        if results:
            return results
    except Exception as exc:
        if debug:
            print(f"TruePeopleSearch error: {exc}")

    try:
        results = search_fastpeoplesearch(address, debug=debug)
        if results:
            return results
    except Exception as exc:
        if debug:
            print(f"FastPeopleSearch error: {exc}")

    return []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Simple skip tracer")
    parser.add_argument("address", nargs="+", help="Full property address")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    address_input = " ".join(args.address)
    matches = skip_trace(address_input, debug=args.debug)
    if not matches:
        print("No matches found for this address.")
    else:
        for match in matches:
            print(json.dumps(match, ensure_ascii=False))
