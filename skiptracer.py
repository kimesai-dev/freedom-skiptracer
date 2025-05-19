import argparse
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import quote_plus

import numpy as np

from human_behavior_ml import (
    load_behavior_model,
    predict_hold_duration,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Preload ML model used for generating human-like timings. The helper functions
# handle the case where the model file does not exist and return ``None``.
BEHAVIOR_MODEL = load_behavior_model("models/behavior_model.zip")

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

def save_debug_html(html: str, name: str = "debug_last.html") -> None:
    Path("logs").mkdir(exist_ok=True)
    Path(f"logs/{name}").write_text(html)

def apply_stealth(page) -> None:
    """Spoof common fingerprint attributes using randomized values."""

    hw_concurrency = random.randint(4, 8)
    dev_mem = random.choice([4, 8])

    page.add_init_script(
        f"""
        Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
        window.chrome = window.chrome || {{ runtime: {{}} }};
        Object.defineProperty(navigator, 'plugins', {{ get: () => [1, 2, 3, 4] }});
        Object.defineProperty(navigator, 'languages', {{ get: () => ['en-US', 'en'] }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {hw_concurrency} }});
        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {dev_mem} }});
        """
    )

def _cubic_bezier(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    """Return a single dimension of a cubic Bezier curve."""
    return (
        (1 - t) ** 3 * p0
        + 3 * (1 - t) ** 2 * t * p1
        + 3 * (1 - t) * t ** 2 * p2
        + t ** 3 * p3
    )


CURRENT_MOUSE_POS = [0.0, 0.0]


def smooth_mouse_move(
    page,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    duration: float = 1.0,
    steps: int = 20,
) -> None:
    """Move the mouse along a randomized Bezier path."""

    # Random control points generate curved paths with subtle variation
    cp1_x = start_x + random.uniform(-100, 100)
    cp1_y = start_y + random.uniform(-100, 100)
    cp2_x = end_x + random.uniform(-100, 100)
    cp2_y = end_y + random.uniform(-100, 100)

    for i, t in enumerate(np.linspace(0, 1, steps)):
        x = _cubic_bezier(start_x, cp1_x, cp2_x, end_x, t)
        y = _cubic_bezier(start_y, cp1_y, cp2_y, end_y, t)
        page.mouse.move(x, y)
        # Introduce slight per-step delays to mimic natural movement
        time.sleep(max(0.001, duration / steps) * random.uniform(0.7, 1.3))
        logger.debug(f"Bezier move {i}/{steps}: {x:.1f},{y:.1f}")
    CURRENT_MOUSE_POS[0] = end_x
    CURRENT_MOUSE_POS[1] = end_y

def random_mouse_movement(page, width: int = 1366, height: int = 768) -> None:
    """Perform several smooth mouse moves around the page."""
    start_x, start_y = CURRENT_MOUSE_POS
    for _ in range(random.randint(5, 10)):
        x = random.randint(0, width)
        y = random.randint(0, height)
        smooth_mouse_move(page, start_x, start_y, x, y)
        start_x, start_y = x, y

        time.sleep(random.uniform(0.05, 0.2))


def handle_press_and_hold(page, debug: bool) -> None:
    """Attempt to solve the press and hold challenge if displayed."""

    try:
        btn = page.locator("text=Press & Hold").first
        btn.wait_for(timeout=3000)
        box = btn.bounding_box()
        if box:
            target_x = box["x"] + box["width"] / 2
            target_y = box["y"] + box["height"] / 2
            smooth_mouse_move(page, CURRENT_MOUSE_POS[0], CURRENT_MOUSE_POS[1], target_x, target_y, duration=0.5)

            page.mouse.down()

            # Determine hold duration via ML model if available; otherwise use a
            # randomized 3-6 second range.  This adds subtle variation between
            # sessions to better mimic genuine user behavior.
            hold = random.uniform(3, 6)
            if BEHAVIOR_MODEL:
                hold = predict_hold_duration(BEHAVIOR_MODEL, hold)
            logger.debug(f"Holding press for {hold:.2f}s")
            page.wait_for_timeout(int(hold * 1000))

            page.mouse.up()
            page.wait_for_load_state("domcontentloaded")
            if debug:
                save_debug_html(page.content())

    except Exception as exc:
        if debug:
            print(f"Failed to handle press-and-hold: {exc}")


def setup_telemetry_logging(page) -> None:
    """Attach listeners to log network telemetry for debugging/replay."""

    def log_request(request) -> None:
        logger.debug(
            "REQ %s %s payload=%s",
            request.method,
            request.url,
            request.post_data,
        )

    def log_response(response) -> None:
        logger.debug("RES %s %s", response.status, response.url)

    page.on("request", log_request)
    page.on("response", log_response)

def create_context(p, visible: bool, proxy: str | None) -> tuple:
    """Launch a browser with randomized context settings."""

    launch_args = {"headless": not visible}
    if proxy:
        # Proxies can be rotated/residential to reduce IP bans.
        launch_args["proxy"] = {"server": proxy}
        logger.info(f"Using proxy {proxy}")
    browser = p.chromium.launch(**launch_args)
    width = random.randint(1280, 1920)
    height = random.randint(720, 1080)
    CURRENT_MOUSE_POS[0] = width / 2
    CURRENT_MOUSE_POS[1] = height / 2
    context = browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": width, "height": height},
        locale="en-US",
        timezone_id="America/New_York",
    )
    return browser, context

def fetch_html(context, url: str, debug: bool) -> str:
    """Navigate to a URL in a fresh page and return the HTML."""
    page = context.new_page()
    setup_telemetry_logging(page)
    apply_stealth(page)
    random_mouse_movement(page)
    logger.info(f"Fetching {url}")
    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    for _ in range(random.randint(1, 2)):
        page.mouse.wheel(0, random.randint(200, 800))
        time.sleep(random.uniform(0.2, 0.5))
    time.sleep(random.uniform(0.3, 0.7))
    html = page.content()
    if debug:
        save_debug_html(html)
        logger.debug(f"Saved debug HTML for {url}")
    if response and response.status >= 400:
        raise ValueError(f"HTTP {response.status}")
    page.close()
    return html


def search_truepeoplesearch(
    context,
    address: str,
    debug: bool,
    inspect: bool,
    visible: bool,
    manual: bool,
) -> List[Dict[str, object]]:

    if debug:
        print("Trying TruePeopleSearch...")

    page = context.new_page()
    setup_telemetry_logging(page)
    apply_stealth(page)
    random_mouse_movement(page)
    page.goto("https://www.truepeoplesearch.com/", wait_until="domcontentloaded", timeout=30000)
    random_mouse_movement(page)

    try:
        page.click("a[href*='Address']", timeout=5000)
    except Exception:
        if debug:
            print("Failed to click Address tab")

    try:
        street, cityzip = [part.strip() for part in address.split(",", 1)]
    except ValueError:
        street, cityzip = address.strip(), ""

    try:
        address_input = page.locator("input[placeholder*='Enter name']").first
        city_input = page.locator("input[placeholder*='City']").first
        address_input.wait_for(timeout=5000)
        city_input.wait_for(timeout=5000)

        address_input.fill(street.strip())
        if cityzip:
            city_input.fill(cityzip.strip())
        else:
            city_input.fill("")
    except Exception:
        if debug:
            print("Failed to locate or type into address fields")
        html = page.content()
        if debug:
            save_debug_html(html)
        page.close()
        return []

    try:
        city_input.press("Enter")
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
    time.sleep(3)

    time.sleep(3)
    page.wait_for_load_state("domcontentloaded")
    for _ in range(random.randint(1, 3)):
        page.mouse.wheel(0, random.randint(200, 800))
        time.sleep(random.uniform(0.3, 0.8))
    random_mouse_movement(page)

    html = page.content()
    if debug:
        Path("logs").mkdir(exist_ok=True)
        Path("logs/page_after_submit.html").write_text(html)

    lower_html = html.lower()

    if "press & hold" in lower_html:
        print("Press & Hold challenge detected")
        if manual and visible:
            page.pause()
        else:
            handle_press_and_hold(page, debug)
            page.wait_for_load_state("domcontentloaded")
            html = page.content()
            lower_html = html.lower()

    bot_check = False
    if (
        "are you a human" in lower_html
        or "robot check" in lower_html
        or "press & hold" in lower_html
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
            save_debug_html(html)
        if manual and visible:
            page.pause()
        time.sleep(10)
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        random_mouse_movement(page)

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
    if debug:
        print("Trying FastPeopleSearch...")

    slug = quote_plus(address.lower().replace(",", "").replace(" ", "-"))
    url = f"https://www.fastpeoplesearch.com/address/{slug}"

    page = context.new_page()
    setup_telemetry_logging(page)
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
    parser.add_argument("--proxy", help="Proxy server e.g. http://user:pass@host:port")
    parser.add_argument("--fast", action="store_true", help="Include FastPeopleSearch")
    parser.add_argument("--manual", action="store_true", help="Pause on bot wall for manual solve")

    parser.add_argument("--save", action="store_true", help="Write results to results.json")
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    with sync_playwright() as p:
        browser, context = create_context(p, args.visible, args.proxy)

        results: List[Dict[str, object]] = []
        try:
            results.extend(search_truepeoplesearch(
                    context,
                    args.address,
                    args.debug,
                    args.inspect,
                    args.visible,
                    args.manual,
                )
            )

        except Exception as exc:
            if args.debug:
                print(f"TruePeopleSearch failed: {exc}")

        if args.fast:
            try:
                results.extend(search_fastpeoplesearch(context, args.address, args.debug, args.inspect))
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
