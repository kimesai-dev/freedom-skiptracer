import re
from typing import List, Dict
import sys

try:
    import requests
    from bs4 import BeautifulSoup
except ModuleNotFoundError as exc:
    missing = exc.name
    print(f"Missing dependency: install with 'pip install {missing}'")
    sys.exit(1)
from urllib.parse import quote_plus
import random
import time
import os

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0",
]

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def _make_headers() -> dict:
    headers = DEFAULT_HEADERS.copy()
    headers["User-Agent"] = random.choice(USER_AGENTS)
    return headers

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


def _fetch(url: str, debug: bool = False, retries: int = 3) -> requests.Response:
    """Fetch a URL with basic 403 retry handling and rotating user-agent."""
    for attempt in range(1, retries + 1):
        headers = _make_headers()
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 403:
            break
        if attempt < retries:
            print("Blocked \u2014 retrying with new headers")
            time.sleep(random.uniform(0.5, 1.5))
    if debug:
        os.makedirs("logs", exist_ok=True)
        with open("logs/debug_last.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
    resp.raise_for_status()
    return resp


def search_truepeoplesearch(address: str, debug: bool = False) -> List[Dict[str, object]]:
    """Searches TruePeopleSearch for the given address."""
    print("Trying TruePeopleSearch...")
    url = (
        "https://www.truepeoplesearch.com/results?" +
        f"streetaddress={quote_plus(address)}"
    )
    resp = _fetch(url, debug)
    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.card")
    if not cards:
        cards = soup.select("li.card")
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
        print("Parsing result...")
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "TruePeopleSearch",
            })
    return results


def search_fastpeoplesearch(address: str, debug: bool = False) -> List[Dict[str, object]]:
    """Searches FastPeopleSearch for the given address."""
    print("Trying FastPeopleSearch...")
    slug = quote_plus(address.lower().replace(",", "").replace(" ", "-"))
    url = f"https://www.fastpeoplesearch.com/address/{slug}"
    resp = _fetch(url, debug)
    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.card")
    if not cards:
        cards = soup.select("li.card")
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
        print("Parsing result...")
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "FastPeopleSearch",
            })
    return results


def skip_trace(address: str, debug: bool = False) -> List[Dict[str, object]]:
    """Returns matches for the given property address."""
    try:
        results = search_truepeoplesearch(address, debug)
        if results:
            return results
    except Exception:
        if debug:
            print("TruePeopleSearch lookup failed")

    try:
        results = search_fastpeoplesearch(address, debug)
        if results:
            return results
    except Exception:
        if debug:
            print("FastPeopleSearch lookup failed")

    return []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Simple skip tracer")
    parser.add_argument("address", nargs="+", help="Full property address")
    parser.add_argument("--debug", action="store_true", help="Save and print debug output")
    args = parser.parse_args()

    address_input = " ".join(args.address)
    matches = skip_trace(address_input, args.debug)
    if not matches:
        print("No matches found for this address.")
    else:
        for match in matches:
            print(match)
