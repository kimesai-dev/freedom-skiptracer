import argparse
import json
import os
import random
import re
import time
from pathlib import Path
from typing import List, Dict
from urllib.parse import quote_plus

try:
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright
except ImportError as exc:
    missing = str(exc).split("'")[1]
    print(f"Missing dependency: install with `pip install {missing}`")
    raise SystemExit(1)

PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
]

def _normalize_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number

def _parse_phones(text: str) -> List[str]:
    phones = set()
    for match in PHONE_RE.findall(text or ""):
        phones.add(_normalize_phone(match))
    return list(phones)

def save_debug_html(html: str) -> None:
    Path("logs").mkdir(exist_ok=True)
    Path("logs/debug_last.html").write_text(html)

def apply_stealth(page) -> None:
    page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = window.chrome || { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """
    )

def fetch_html(context, url: str, debug: bool) -> str:
    """Navigate to a URL in a fresh page and return the HTML."""
    page = context.new_page()
    apply_stealth(page)
    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(random.uniform(0.3, 0.7))
    html = page.content()
    if debug:
        save_debug_html(html)
    if response and response.status >= 400:
        raise ValueError(f"HTTP {response.status}")
    page.close()
    return html

def search_truepeoplesearch(context, address: str, debug: bool, inspect: bool) -> List[Dict[str, object]]:
    if debug:
        print("Trying TruePeopleSearch...")

    page = context.new_page()
    apply_stealth(page)
    page.goto("https://www.truepeoplesearch.com/", wait_until="domcontentloaded", timeout=30000)

    try:
        page.click("a[href*='Address']", timeout=5000)
    except Exception:
        if debug:
            print("Failed to click Address tab")

    try:
        address_input = page.locator("input[placeholder*='Enter name']").first
        address_input.wait_for(timeout=5000)
        address_input.type(address, delay=random.randint(50, 100))
    except Exception:
        if debug:
            print("Failed to locate or type into address input field")
        html = page.content()
        if debug:
            save_debug_html(html)
        page.close()
        return []

    try:
        address_input.press("Enter")
        time.sleep(3)
    except Exception:
        try:
            page.click("button[type='submit']")
        except Exception:
            if debug:
                print("Failed to submit address search")
            page.close()
            return []

    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_selector("div.card", timeout=8000)
    except Exception:
        pass
    page.mouse.wheel(0, random.randint(200, 800))
    html = page.content()
    if debug:
        Path("logs").mkdir(exist_ok=True)
        Path("logs/page_after_submit.html").write_text(html)

    lower_html = html.lower()
    bot_check = False
    if (
        "are you a human" in lower_html
        or "robot check" in lower_html
        or ("verify" in lower_html and "robot" in lower_html)
    ):
        bot_check = True
    else:
        try:
            if page.locator("text=verify", has_text="robot").first.is_visible(timeout=1000):
                bot_check = True
        except Exception:
            pass

    if bot_check:
        print("Bot check detected — waiting 10s and retrying...")
        if debug:
            Path("logs/page_after_submit.html").write_text(html)
        page.pause()
        time.sleep(10)
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        html = page.content()
        if debug:
            save_debug_html(html)

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card a[href*='/details']")
    if debug:
        print(f"Found {len(cards)} cards on TruePeopleSearch")
    if len(cards) == 0:
        print("No cards found — likely bot block or bad selector.")
    if inspect:
        for card in cards:
            print("TPS card:\n", card.get_text(" ", strip=True))

    results = []
    for link in cards:
        href = link.get("href")
        if not href:
            continue
        detail_url = href if href.startswith("http") else f"https://www.truepeoplesearch.com{href}"
        try:
            detail_html = fetch_html(context, detail_url, debug)
        except Exception as e:
            if debug:
                print(f"Error loading detail page: {e}")
            continue
        detail_soup = BeautifulSoup(detail_html, "html.parser")
        name_el = detail_soup.find(["h1", "h2", "strong"])
        name = name_el.get_text(strip=True) if name_el else ""
        loc_el = detail_soup.find(string=re.compile("Current Address", re.I))
        if loc_el and loc_el.find_parent("div"):
            location_div = loc_el.find_parent("div").find_next_sibling("div")
            location = location_div.get_text(strip=True) if location_div else ""
        else:
            location = ""
        phones = _parse_phones(detail_soup.get_text(" "))
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "TruePeopleSearch",
            })
    page.close()
    return results


def search_fastpeoplesearch(context, address: str, debug: bool, inspect: bool) -> List[Dict[str, object]]:
    """Searches FastPeopleSearch for the given address."""
    if debug:
        print("Trying FastPeopleSearch...")

    slug = quote_plus(address.lower().replace(",", "").replace(" ", "-"))
    url = f"https://www.fastpeoplesearch.com/address/{slug}"

    page = context.new_page()
    apply_stealth(page)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    try:
        page.wait_for_selector("div.card", timeout=8000)
    except Exception:
        pass
    page.mouse.wheel(0, random.randint(200, 800))
    html = page.content()
    if debug:
        save_debug_html(html)

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card a[href*='/person']")
    if debug:
        print(f"Found {len(cards)} cards on FastPeopleSearch")
    if len(cards) == 0:
        print("No cards found — likely bot block or bad selector.")
    if inspect:
        for card in cards:
            print("FPS card:\n", card.get_text(" ", strip=True))

    results = []
    for link in cards:
        href = link.get("href")
        if not href:
            continue
        detail_url = href if href.startswith("http") else f"https://www.fastpeoplesearch.com{href}"
        try:
            detail_html = fetch_html(context, detail_url, debug)
        except Exception as e:
            if debug:
                print(f"Error loading detail page: {e}")
            continue
        detail_soup = BeautifulSoup(detail_html, "html.parser")
        name_el = detail_soup.find(["h1", "h2", "strong"])
        name = name_el.get_text(strip=True) if name_el else ""
        loc_el = detail_soup.find(string=re.compile("Current Address", re.I))
        if loc_el and loc_el.find_parent("div"):
            location_div = loc_el.find_parent("div").find_next_sibling("div")
            location = location_div.get_text(strip=True) if location_div else ""
        else:
            location = ""
        phones = _parse_phones(detail_soup.get_text(" "))
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "FastPeopleSearch",
            })
    page.close()
    return results

def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous skip tracing tool")
    parser.add_argument("address", help="Property address")
    parser.add_argument("--debug", action="store_true", help="Save HTML and log status codes")
    parser.add_argument("--visible", action="store_true", help="Show browser during scrape")
    parser.add_argument("--inspect", action="store_true", help="Print raw HTML card text")
    parser.add_argument("--fast", action="store_true", help="Include FastPeopleSearch")
    parser.add_argument("--save", action="store_true", help="Write results to results.json")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.visible)
        context = browser.new_context(user_agent=random.choice(USER_AGENTS), viewport={"width": 1366, "height": 768})

        results: List[Dict[str, object]] = []
        try:
            results.extend(search_truepeoplesearch(context, args.address, args.debug, args.inspect))
        except Exception as e:
            if args.debug:
                print(f"TruePeopleSearch failed: {e}")

        if args.fast:
            try:
                results.extend(
                    search_fastpeoplesearch(context, args.address, args.debug, args.inspect)
                )
            except Exception as e:
                if args.debug:
                    print(f"FastPeopleSearch failed: {e}")

        context.close()
        browser.close()

    if args.save:
        Path("results.json").write_text(json.dumps(results, indent=2))

    if results:
        print(json.dumps(results, indent=2))
    else:
        print("No matches found for this address.")

if __name__ == "__main__":
    main()
