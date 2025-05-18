import re
from typing import List, Dict

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/113.0 Safari/537.36"
    )
}

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


def search_truepeoplesearch(address: str) -> List[Dict[str, object]]:
    """Searches TruePeopleSearch for the given address."""
    url = (
        "https://www.truepeoplesearch.com/results?" +
        f"streetaddress={quote_plus(address)}"
    )
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for card in soup.select("div.card"):  # best-effort selector
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
    return results


def search_fastpeoplesearch(address: str) -> List[Dict[str, object]]:
    """Searches FastPeopleSearch for the given address."""
    slug = quote_plus(address.lower().replace(",", "").replace(" ", "-"))
    url = f"https://www.fastpeoplesearch.com/address/{slug}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for card in soup.select("div.card"):  # best-effort selector
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
    return results


def skip_trace(address: str) -> List[Dict[str, object]]:
    """Returns matches for the given property address."""
    try:
        results = search_truepeoplesearch(address)
        if results:
            return results
    except Exception:
        pass

    try:
        results = search_fastpeoplesearch(address)
        if results:
            return results
    except Exception:
        pass

    return []


if __name__ == "__main__":
    import sys

    if not sys.argv[1:]:
        print("Usage: python skiptracer.py \"709 W High St, Portland, IN\"")
        sys.exit(1)

    address_input = " ".join(sys.argv[1:])
    matches = skip_trace(address_input)
    for match in matches:
        print(match)
