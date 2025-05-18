import re
import sys
import json
from pathlib import Path
from typing import List, Dict
from urllib.parse import quote_plus

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    missing = str(e).split("'")[1]
    print(f"Missing dependency: install with 'pip install {missing}'")
    sys.exit(1)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/113.0 Safari/537.36"
    )
}

LOG_DIR = Path("logs")
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


def search_truepeoplesearch(address: str, debug: bool = False) -> List[Dict[str, object]]:
    """Searches TruePeopleSearch for the given address."""
    if debug:
        print("Trying TruePeopleSearch...")

    url = (
        "https://www.truepeoplesearch.com/results?" +
        f"streetaddress={quote_plus(address)}"
    )

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        if debug:
            print(f"Request failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.card, div.result, div.results > div")

    if debug:
        print(f"Found {len(cards)} cards...")
        if len(cards) == 0:
            LOG_DIR.mkdir(exist_ok=True)
            debug_file = LOG_DIR / "debug_last.html"
            debug_file.write_text(resp.text)
            print(f"No cards found. Saved response to {debug_file}")

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
        if debug:
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
    if debug:
        print("Trying FastPeopleSearch...")

    slug = quote_plus(address.lower().replace(",", "").replace(" ", "-"))
    url = f"https://www.fastpeoplesearch.com/address/{slug}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        if debug:
            print(f"Request failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.card, div.result, div.results > div")

    if debug:
        print(f"Found {len(cards)} cards...")
        if len(cards) == 0:
            LOG_DIR.mkdir(exist_ok=True)
            debug_file = LOG_DIR / "debug_last.html"
            debug_file.write_text(resp.text)
            print(f"No cards found. Saved response to {debug_file}")

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
        if debug:
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
    for func in (search_truepeoplesearch, search_fastpeoplesearch):
        try:
            results = func(address, debug=debug)
            if results:
                return results
        except Exception as e:
            if debug:
                print(f"{func.__name__} failed: {e}")
    return []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Free skip tracing for an address")
    parser.add_argument("address", nargs="+", help="Property address")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    address_input = " ".join(args.address)
    matches = skip_trace(address_input, debug=args.debug)
    if matches:
        for match in matches:
            print(json.dumps(match, ensure_ascii=False))
    else:
        print("No matches found for this address.")
