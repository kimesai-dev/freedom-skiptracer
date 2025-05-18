import argparse
import json
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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
]

ACCEPTS = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
]
ACCEPT_LANGS = ["en-US,en;q=0.9", "en-US,en;q=0.8,fr;q=0.6", "en-US,en;q=0.7"]
REFERERS = ["https://www.google.com/", "https://duckduckgo.com/"]

BOT_TRAP_TEXT = "Server Error in '/' Application."


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
    plugin_count = random.randint(3, 5)
    hardware = random.choice([2, 4, 8])
    touch = random.choice([0, 1])
    page.add_init_script(
        f"""
        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
        window.chrome = window.chrome || {{ runtime: {{}} }};
        Object.defineProperty(navigator, 'plugins', {{ get: () => new Array({plugin_count}).fill(1) }});
        Object.defineProperty(navigator, 'languages', {{ get: () => ['en-US', 'en'] }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {hardware} }});
        Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {touch} }});
        """
    )


def fetch_html(context, url: str, debug: bool, wait: float = 0.0) -> str:
    page = context.new_page()
    apply_stealth(page)
    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(wait or random.uniform(0.3, 0.7))
    html = page.content()
    if debug:
        save_debug_html(html)
    if response and response.status >= 400:
        if debug:
            print(f"HTTP {response.status} — possible bot trap or error page.")
        page.close()
        return html
    page.close()
    return html


def search_truepeoplesearch(context, address: str, wait: float, debug: bool) -> List[Dict[str, object]]:
    if debug:
        print("Trying TruePeopleSearch...")

    url = "https://www.truepeoplesearch.com/results?streetaddress=" + address.replace(" ", "+")
    html = fetch_html(context, url, debug, wait)
    if BOT_TRAP_TEXT in html:
        if debug:
            print("Bot trap detected, retrying...")
        time.sleep(wait or random.uniform(1.0, 2.0))
        html = fetch_html(context, url, debug, wait)
        if BOT_TRAP_TEXT in html and debug:
            print("Bot trap page persisted after retry.")
            return []

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card")
    if debug:
        print(f"Found {len(cards)} cards on TruePeopleSearch")

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


def search_fastpeoplesearch(context, address: str, wait: float, debug: bool) -> List[Dict[str, object]]:
    if debug:
        print("Trying FastPeopleSearch...")

    slug = address.lower().replace(",", "").replace(" ", "-")
    url = f"https://www.fastpeoplesearch.com/address/{slug}"
    html = fetch_html(context, url, debug, wait)
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card")
    if debug:
        print(f"Found {len(cards)} cards on FastPeopleSearch")

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


def skip_trace(address: str, visible: bool = False, proxy: str | None = None, include_fastpeoplesearch: bool = False, wait: float = 0.0, debug: bool = False) -> List[Dict[str, object]]:
    ua = random.choice(USER_AGENTS)
    viewport = random.choice(VIEWPORTS)

    def pick_proxy(value: str | None) -> str | None:
        if not value:
            return None
        choices = [p.strip() for p in value.split(",") if p.strip()]
        return random.choice(choices) if choices else None

    with sync_playwright() as p:
        launch_args = {"headless": not visible}
        selected_proxy = pick_proxy(proxy)
        if selected_proxy:
            launch_args["proxy"] = {"server": selected_proxy}
        browser = p.chromium.launch(**launch_args)
        context = browser.new_context(user_agent=ua, viewport=viewport)
        results = search_truepeoplesearch(context, address, wait, debug)

        if include_fastpeoplesearch:
            try:
                fps_results = search_fastpeoplesearch(context, address, wait, debug)
                results.extend(fps_results)
            except Exception as exc:
                if debug:
                    print(f"FastPeopleSearch failed: {exc}")
        browser.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Free skip tracing")
    parser.add_argument("address", help="Property address")
    parser.add_argument("--debug", action="store_true", help="Save last HTML response")
    parser.add_argument("--visible", action="store_true", help="Run browser visibly")
    parser.add_argument("--proxy", help="Proxy server e.g. http://user:pass@host:port")
    parser.add_argument("--fast", action="store_true", help="Include FastPeopleSearch (may trigger bot checks)")
    parser.add_argument("--save", action="store_true", help="Write results to results.json")
    parser.add_argument("--wait", type=float, default=0.0, help="Seconds to wait after each page load")
    args = parser.parse_args()

    matches = skip_trace(
        args.address,
        visible=args.visible,
        proxy=args.proxy,
        include_fastpeoplesearch=args.fast,
        wait=args.wait,
        debug=args.debug,
    )

    if args.save:
        Path("results.json").write_text(json.dumps(matches, indent=2))

    if matches:
        print(json.dumps(matches, indent=2))
    else:
        print("No matches found for this address.")


if __name__ == "__main__":
    main()
