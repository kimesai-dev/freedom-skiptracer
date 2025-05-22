#!/usr/bin/env python3
"""TruePeopleSearch scraper using Selenium + undetected-chromedriver."""

import argparse
import json
import logging
import random
import re
import time
from pathlib import Path
import subprocess
import shutil
import traceback

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys

# List of mobile proxies that must be used
MOBILE_PROXIES = [
    f"http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:{port}"
    for port in range(10001, 10011)
]

# User-Agent and language pools for header rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
]

LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.8",
    "de-DE,de;q=0.8,en-US;q=0.5",
]

TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Europe/London",
]

PLATFORMS = ["Win32", "Linux x86_64", "MacIntel"]
VENDORS = ["Google Inc.", "Apple Computer, Inc.", ""]

PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Global flag toggled by --debug to enable extra logging and HTML capture
DEBUG = False


def _normalize_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number


def _parse_phones(text: str):
    return list({_normalize_phone(m) for m in PHONE_RE.findall(text or "")})


def random_proxy() -> str:
    return random.choice(MOBILE_PROXIES)


def detect_chrome_version() -> int | None:
    """Return the installed Chrome major version or None if not found."""
    candidates = [
        "google-chrome",
        "chrome",
        "chromium-browser",
        "chromium",
        "google-chrome-stable",
    ]

    # macOS default installation path
    mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(mac_path).exists():
        candidates.insert(0, mac_path)

    for cmd in candidates:
        path = shutil.which(cmd) if cmd != mac_path else mac_path
        if not path:
            continue
        try:
            out = subprocess.check_output([path, "--version"], stderr=subprocess.STDOUT)
            match = re.search(r"(\d+)\.", out.decode())
            if match:
                return int(match.group(1))
        except Exception:
            continue
    return None


def create_driver(proxy: str, headless: bool = True):
    """Launch Chrome with stealth tweaks and optional proxy."""
    ua = random.choice(USER_AGENTS)
    lang = random.choice(LANGUAGES)
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--incognito")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-agent={ua}")
    options.add_argument(f"--lang={lang}")
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")
    version = detect_chrome_version()
    try:
        driver = uc.Chrome(options=options, version_main=version)
    except Exception:
        traceback.print_exc()
        raise
    width = random.randint(800, 1366)
    height = random.randint(600, 900)
    driver.set_window_size(width, height)

    tz = random.choice(TIMEZONES)
    try:
        driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": tz})
    except Exception:
        pass

    platform = random.choice(PLATFORMS)
    vendor = random.choice(VENDORS)
    langs = [lang.split(',')[0].split(';')[0], "en"]
    stealth_js = f"""
        Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
        Object.defineProperty(navigator, 'platform', {{get: () => '{platform}'}});
        Object.defineProperty(navigator, 'vendor', {{get: () => '{vendor}'}});
        Object.defineProperty(navigator, 'languages', {{get: () => {json.dumps(langs)}}});
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {{
            if (param === 37445) return 'Intel Inc.';
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return getParameter.call(this, param);
        }};
    """
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
    return driver


def clear_storage(driver):
    driver.delete_all_cookies()
    try:
        driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    except Exception:
        pass


def save_debug(html: str, name: str = "debug_last.html"):
    Path("logs").mkdir(exist_ok=True)
    Path(f"logs/{name}").write_text(html)


def fetch_page(driver, url: str, debug: bool = False) -> str:
    try:
        driver.get(url)
    except Exception:
        traceback.print_exc()
        if debug:
            try:
                save_debug(driver.page_source, f"nav_error_{int(time.time())}.html")
            except Exception:
                pass
        raise
    html = driver.page_source
    if debug:
        save_debug(html)
    lower = html.lower()
    if "cloudflare" in lower and ("attention" in lower or "blocked" in lower):
        if debug:
            save_debug(html, f"blocked_{int(time.time())}.html")
        raise RuntimeError("Cloudflare block detected")
    return html


def search_truepeoplesearch(address: str, proxy: str, debug: bool = False, headless: bool = True) -> list:
    driver = create_driver(proxy, headless=headless)
    clear_storage(driver)
    results = []

    def capture_debug():
        """Save page HTML and screenshot to help diagnose failures."""
        try:
            Path("debug_page.html").write_text(driver.page_source, encoding="utf-8")
            driver.save_screenshot("debug_screenshot.png")
        except Exception:
            pass

    try:
        # Load home page
        try:
            fetch_page(driver, "https://www.truepeoplesearch.com/", debug)
            logger.info("TruePeopleSearch page loaded")
        except Exception:
            capture_debug()
            traceback.print_exc()
            raise

        # Wait for the address input
        try:
            addr_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "home-input"))
            )
            logger.info("Address input found")
        except Exception:
            capture_debug()
            traceback.print_exc()
            raise

        # Type the full address
        try:
            addr_input.clear()
            addr_input.send_keys(address)
        except Exception:
            capture_debug()
            traceback.print_exc()
            raise

        # Click the search button
        try:
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "btnSearch"))
            ).click()
            logger.info("Search submitted")
        except Exception:
            capture_debug()
            traceback.print_exc()
            raise

        # Wait for results
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.card"))
            )
        except Exception:
            capture_debug()
            traceback.print_exc()
            raise

        html = driver.page_source
        if debug:
            save_debug(html)
        soup = BeautifulSoup(html, "html.parser")
        for card in soup.select("div.card"):
            name_el = card.select_one("a[href*='/details']")
            name = name_el.get_text(strip=True) if name_el else ""
            phones = _parse_phones(card.get_text(" "))
            loc_el = card.find(string=re.compile("Current Address", re.I))
            city_state = (
                loc_el.find_parent("div").get_text(strip=True) if loc_el else ""
            )
            if name or phones:
                results.append(
                    {
                        "name": name,
                        "phones": phones,
                        "city_state": city_state,
                        "source": "TruePeopleSearch",
                    }
                )
    finally:
        driver.quit()
    return results


def main():
    parser = argparse.ArgumentParser(description="Search TruePeopleSearch using mobile proxies")
    parser.add_argument("address", help="Address to search")
    parser.add_argument("--debug", action="store_true", help="Save HTML and verbose logs on failure")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    parser.add_argument("--proxy", help="Proxy URL to use instead of random choice")
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)
    global DEBUG
    DEBUG = args.debug

    proxy = args.proxy or random_proxy()
    logger.info("Using proxy %s", proxy)
    try:
        results = search_truepeoplesearch(args.address, proxy, debug=args.debug, headless=not args.visible)
    except Exception:
        traceback.print_exc()
        logger.error("Search failed")
        results = []

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
