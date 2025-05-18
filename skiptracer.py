import argparse
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Dict, List

try:
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright
except ImportError as exc:
    missing = str(exc).split("'")[1]
    print(f"Missing dependency: install with `pip install {missing}`")
    raise SystemExit(1)

PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
BOT_TRAP_TEXT = "Server Error in '/' Application."

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
        Object.defineProperty(navigator, 'plugins', { get: () => new Array(5).fill(0) });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
        Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
        """
    )

def simulate_interaction(page) -> None:
    page.mouse.move(random.randint(100, 500), random.randint(100, 500))
    page.mouse.wheel(0, random.randint(200, 800))
    time.sleep(random.uniform(1, 2))

def fetch_html(context, url: str, debug: bool) -> str:
    page = context.new_page()
    apply_stealth(page)
    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    simulate_interaction(page)
    html = page.content()
    if debug:
        save_debug_html(html)
        if response and response.status >= 400:
            print(f"HTTP {response.status} returned")
    if response and response.status == 403:
        page.close()
        raise ValueError("HTTP 403")
    if BOT_TRAP_TEXT in html:
        page.close()
        raise ValueError("Bot trap detected")
    page.close()
    return html

def search_truepeoplesearch(context, address: str, debug: bool, inspect: bool) -> List[Dict[str, object]]:
    if debug:
        print("Trying TruePeopleSearch...")
    url = "https://www.truepeoplesearch.com/results?streetaddress=" + address.replace(" ", "+")
    try:
        html = fetch_html(context, url, debug)
    except Exception as e:
        if debug:
            print(f"TruePeopleSearch failed: {e}")
        return []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card")
    if debug:
        print(f"Found {len(cards)} cards on TruePeopleSearch")
    if inspect:
        for card in cards:
            print("TPS card:\n", card.get_text(" ", strip=True))
    results = []
    for card in cards:
        name_el = card.find("a", href=re.compile("/details"))
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        loc_el = card.find("div", class_=re.compile("address"))
        location = loc_el.get_text(strip=True) if loc_el else ""
        phones = _parse_phones(card.get_text(" "))
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "TruePeopleSearch",
            })
    return results

def search_fastpeoplesearch(context, address: str, debug: bool, inspect: bool) -> List[Dict[str, object]]:
    if debug:
        print("Trying FastPeopleSearch...")
    slug = address.lower().replace(",", "").replace(" ", "-")
    url = f"https://www.fastpeoplesearch.com/address/{slug}"
    try:
        html = fetch_html(context, url, debug)
    except Exception as e:
        if debug:
            print(f"FastPeopleSearch failed: {e}")
        return []
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card")
    if debug:
        print(f"Found {len(cards)} cards on FastPeopleSearch")
    if inspect:
        for card in cards:
            print("FPS card:\n", card.get_text(" ", strip=True))
    results = []
    for card in cards:
        name_el = card.find("a", href=re.compile("/person"))
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        loc_el = card.find("div", class_=re.compile("address"))
        location = loc_el.get_text(strip=True) if loc_el else ""
        phones = _parse_phones(card.get_text(" "))
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "FastPeopleSearch",
            })
    return results

def _run_scrape(address: str, visible: bool, proxy: str | None, include_fps: bool, debug: bool, inspect: bool) -> List[Dict[str, object]]:
    ua = random.choice(USER_AGENTS)
    user_data_dir = f"/tmp/persistent-profile-{random.randint(0, 1_000_000)}"
    os.makedirs(user_data_dir, exist_ok=True)
    with sync_playwright() as p:
        launch_args = {"headless": not visible}
        if proxy:
            launch_args["proxy"] = {"server": proxy}
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            user_agent=ua,
            viewport={"width": 1366, "height": 768},
            **launch_args,
        )
        results = search_truepeoplesearch(context, address, debug, inspect)
        if include_fps:
            fps_results = search_fastpeoplesearch(context, address, debug, inspect)
            results.extend(fps_results)
        context.close()
    return results

def skip_trace(address: str, visible: bool = False, proxies: List[str] | None = None, include_fastpeoplesearch: bool = False, debug: bool = False, inspect: bool = False) -> List[Dict[str, object]]:
    proxies = proxies or [None]
    for proxy in proxies:
        try:
            if debug:
                print(f"Using proxy: {proxy}" if proxy else "Using direct connection")
            results = _run_scrape(address, visible, proxy, include_fastpeoplesearch, debug, inspect)
            if results:
                return results
        except Exception as exc:
            if debug:
                print(f"Attempt with {proxy or 'no proxy'} failed: {exc}")
    return []

def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous skip tracing tool")
    parser.add_argument("address", help="Property address")
    parser.add_argument("--debug", action="store_true", help="Save HTML and log status codes")
    parser.add_argument("--visible", action="store_true", help="Show browser during scrape")
    parser.add_argument("--proxy", help="Comma-separated proxies (http://host1:port,http://host2:port)")
    parser.add_argument("--fast", action="store_true", help="Include FastPeopleSearch")
    parser.add_argument("--save", action="store_true", help="Write results to results.json")
    parser.add_argument("--inspect", action="store_true", help="Print raw HTML card text")
    args = parser.parse_args()

    proxy_list = args.proxy.split(",") if args.proxy else None
    matches = skip_trace(
        args.address,
        visible=args.visible,
        proxies=proxy_list,
        include_fastpeoplesearch=args.fast,
        debug=args.debug,
        inspect=args.inspect,
    )

    if args.save:
        Path("results.json").write_text(json.dumps(matches, indent=2))

    if matches:
        print(json.dumps(matches, indent=2))
    else:
        print("No matches found for this address.")

if __name__ == "__main__":
    main()
