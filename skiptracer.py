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
import os

from twocaptcha import TwoCaptcha

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException,
    ElementClickInterceptedException,
    WebDriverException,
)
from urllib.parse import urlparse

# Proxy lists (HTTP and SOCKS5)
HTTP_PROXIES = [
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10001",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10002",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10003",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10004",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10005",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10006",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10007",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10008",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10009",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decdoc.com:10010",
]

SOCKS5_PROXIES = [
    "socks5h://user-spo5y5143p-session-1:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-2:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-3:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-4:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-5:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-6:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-7:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-8:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-9:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
    "socks5h://user-spo5y5143p-session-10:4QrFon=3x9oPmmlC9k@gate.decdoc.com:7000",
]

ALL_PROXIES = HTTP_PROXIES + SOCKS5_PROXIES

# 2Captcha API key used to solve challenge pages
TWO_CAPTCHA_API_KEY = os.getenv("2CAPTCHA_API_KEY", "")

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


def solve_captcha(driver, wait_time: int = 120, retries: int = 2) -> bool:
    """Detect and solve CAPTCHA challenges using 2Captcha."""
    html = driver.page_source.lower()
    if (
        "captcha" not in html
        and "g-recaptcha" not in html
        and "hcaptcha" not in html
        and "turnstile" not in html
    ):
        return False

    if not TWO_CAPTCHA_API_KEY:
        logger.error("CAPTCHA detected but TWO_CAPTCHA_API_KEY is not set")
        return False

    logger.info("CAPTCHA detected, attempting to solve")
    soup = BeautifulSoup(driver.page_source, "html.parser")
    sitekey = None
    el = soup.find(attrs={"data-sitekey": True})
    if el:
        sitekey = el.get("data-sitekey")
    if not sitekey:
        match = re.search(r'data-sitekey="([^"]+)"', driver.page_source)
        if match:
            sitekey = match.group(1)
    if not sitekey:
        logger.error("Could not find sitekey for CAPTCHA")
        return False

    solver = TwoCaptcha(TWO_CAPTCHA_API_KEY)
    for attempt in range(retries):
        try:
            result = solver.recaptcha(sitekey=sitekey, url=driver.current_url)
            token = result.get("code")
            if not token:
                raise RuntimeError("No token returned")
            js = """
                var f = document.querySelector('textarea[name="g-recaptcha-response"], textarea[name="h-captcha-response"], input[name="cf-turnstile-response"]');
                if (f) { f.style.display=''; f.value = arguments[0]; }
            """
            driver.execute_script(js, token)
            logger.info("CAPTCHA token injected")
            time.sleep(2)
            driver.execute_script(
                "document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true}));"
            )
            WebDriverWait(driver, wait_time).until(
                lambda d: "captcha" not in d.page_source.lower()
            )
            logger.info("CAPTCHA solved successfully")
            return True
        except Exception as exc:
            logger.error(
                "CAPTCHA solving failed (attempt %s/%s): %s", attempt + 1, retries, exc
            )
            time.sleep(5)
    logger.error("Failed to solve CAPTCHA")
    return False


def random_proxy() -> str:
    """Return a random proxy from the combined pool."""
    return random.choice(ALL_PROXIES)



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
        parsed = urlparse(proxy)
        scheme = parsed.scheme or "http"
        scheme = scheme.replace("socks5h", "socks5")
        proxy_server = f"{scheme}://{parsed.netloc}"
        options.add_argument(f"--proxy-server={proxy_server}")
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
        # Wait for Cloudflare challenge delay
        time.sleep(random.uniform(10, 12))
        solve_captcha(driver)
    except Exception:
        traceback.print_exc()
        if debug:
            try:
                save_debug(driver.page_source, f"nav_error_{int(time.time())}.html")
            except Exception:
                pass
        raise
    html = driver.page_source
    if solve_captcha(driver):
        html = driver.page_source
    if debug:
        save_debug(html)
    lower = html.lower()
    if "cloudflare" in lower and ("attention" in lower or "blocked" in lower):
        if debug:
            save_debug(html, f"blocked_{int(time.time())}.html")
        raise RuntimeError("Cloudflare block detected")
    return html


def human_delay(min_seconds: float = 1.0, max_seconds: float = 2.5) -> None:
    """Sleep for a random duration to mimic natural pauses."""
    time.sleep(random.uniform(min_seconds, max_seconds))


def human_mouse_movements(driver, moves: int = 3) -> None:
    """Perform small random mouse movements."""
    try:
        size = driver.get_window_size()
        actions = ActionChains(driver)
        for _ in range(moves):
            x = random.randint(0, size["width"] - 1)
            y = random.randint(0, size["height"] - 1)
            actions.move_by_offset(x, y).perform()
            time.sleep(random.uniform(0.2, 0.5))
            actions.move_by_offset(-x, -y).perform()
    except WebDriverException:
        pass


def human_scroll(driver, scrolls: int = 2) -> None:
    """Randomly scroll up and down the page."""
    try:
        height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(scrolls):
            delta = random.randint(200, min(800, height))
            driver.execute_script(f"window.scrollBy(0, {delta});")
            time.sleep(random.uniform(0.3, 0.7))
            driver.execute_script(f"window.scrollBy(0, {-delta});")
    except WebDriverException:
        pass


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
        fetch_page(driver, "https://www.truepeoplesearch.com/", debug)
        human_mouse_movements(driver)
        human_scroll(driver)
        logger.info("TruePeopleSearch page loaded")

        # Accept cookie banner if present
        try:
            cookie_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "cc-btn"))
            )
            cookie_btn.click()
            logger.info("Cookie banner accepted")
            time.sleep(1)
        except TimeoutException:
            pass

        human_delay()

        # Navigate directly to the address lookup form
        try:
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href*='address-lookup']"))
            ).click()
            time.sleep(random.uniform(10, 12))
            solve_captcha(driver)
        except Exception:
            # Fallback to a direct URL in case the click is intercepted
            driver.get("https://www.truepeoplesearch.com/address-lookup")
            time.sleep(random.uniform(10, 12))
            solve_captcha(driver)
        logger.info("Address search link clicked")
        time.sleep(1)
        human_mouse_movements(driver)
        human_scroll(driver)

        # Wait for the address input fields to be visible
        try:
            street_input = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='123 Park Ave']"))
            )
            location_input = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='City']"))
            )
            logger.info("Address input fields located")
        except Exception:
            traceback.print_exc()
            if debug:
                capture_debug()
            raise

        # Accept cookie banner again if it reappears
        try:
            cookie_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "cc-btn"))
            )
            cookie_btn.click()
            logger.info("Cookie banner accepted")
            time.sleep(1)
        except TimeoutException:
            pass

        human_delay()

        # Type the full address in the first input only
        full_address = address.strip()
        logger.info("Typing address: %s", full_address)
        for ch in full_address:
            street_input.send_keys(ch)
            time.sleep(random.uniform(0.05, 0.15))
        logger.info("Address typed")

        # Wait for the autocomplete suggestion for the typed address
        try:
            WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".pac-item"))
            )
            logger.info("Address suggestion appeared")
        except TimeoutException:
            logger.debug("No suggestion appeared")

        # Confirm the parsed address
        try:
            street_input.send_keys(Keys.TAB)
            logger.info("[INFO] TAB sent")
            time.sleep(1)

        except Exception:
            traceback.print_exc()
            if debug:
                capture_debug()

        time.sleep(0.5)

        human_delay()

        # Click the search button by ID
        try:
            btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "btnSubmit-m-n"))
            )
            btn.click()
            logger.info("[INFO] Search button clicked")
            solve_captcha(driver)
        except Exception:
            traceback.print_exc()
            if debug:
                capture_debug()
            raise
        time.sleep(1)

        human_delay()

        # Wait for results
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.card"))
        )
        solve_captcha(driver)
        human_mouse_movements(driver)
        human_scroll(driver)

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
    except Exception:
        traceback.print_exc()
        if debug:
            capture_debug()
        logger.error("Search failed")
        raise
    finally:
        driver.quit()
    return results


def search_with_fallback(address: str, proxies: list[str], debug: bool = False, headless: bool = True) -> list:
    """Try each proxy until one succeeds."""
    shuffled = list(proxies)
    random.shuffle(shuffled)
    last_exc = None
    for proxy in shuffled:
        logger.info("Using proxy %s", proxy)
        try:
            return search_truepeoplesearch(address, proxy, debug=debug, headless=headless)
        except Exception as exc:
            last_exc = exc
            logger.error("Proxy %s failed: %s", proxy, exc)
    if last_exc:
        raise last_exc
    return []


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

    if args.proxy:
        proxies = [args.proxy]
    else:
        proxies = ALL_PROXIES
    try:
        results = search_with_fallback(
            args.address,
            proxies,
            debug=args.debug,
            headless=not args.visible,
        )
    except Exception:
        traceback.print_exc()
        logger.error("Search failed")
        results = []

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()