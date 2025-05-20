import argparse
import json
import logging
import os
import random
import re
import time
import threading
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import quote_plus, urlsplit
import urllib.robotparser

import numpy as np

from human_behavior_ml import (
    load_behavior_model,
    predict_hold_duration,
)
from playwright_stealth import stealth_sync
from stable_baselines3 import PPO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Preload ML model used for generating human-like timings. The helper functions
# handle the case where the model file does not exist and return ``None``.
BEHAVIOR_MODEL = load_behavior_model("models/behavior_model.zip")
# Preload advanced RL model used to generate realistic mouse paths.
try:
    MOUSE_MODEL: Optional[PPO] = PPO.load("models/mouse_model.zip")
except Exception:
    MOUSE_MODEL = None
    logger.debug("RL mouse model not loaded; falling back to bezier paths")

try:
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright
except ImportError as exc:
    missing = str(exc).split("'")[1]
    print(f"Missing dependency: install with `pip install {missing}`")
    raise SystemExit(1)

PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")

# Expanded list of modern user agents for stronger UA rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

# Browser fingerprint attributes for spoofing
PLATFORMS = [
    "Win32",
    "Linux x86_64",
    "MacIntel",
]
VENDORS = [
    "Google Inc.",
    "Apple Computer, Inc.",
    "",  # Some browsers report an empty vendor
]
PRODUCT_SUBS = [
    "20030107",
    "20100101",
]
LANGUAGE_SETS = [
    ["en-US", "en"],
    ["en-GB", "en"],
    ["en-US", "en-GB", "en"],

]

# Common timezones for fingerprint randomization
TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
]

# Accept-Language header values to rotate
LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.8",
    "de-DE,de;q=0.8,en-US;q=0.5",
]

# Scale factor that is increased when repeated blocks occur to add extra
# randomness to timings and mouse movement.
HUMANIZATION_SCALE = 1.0

# Lists of Decodo proxies separated by type for smart rotation
# Residential proxies are used by default
RESIDENTIAL_PROXIES = [
    "http://Sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10001",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10002",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10003",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10004",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10005",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10006",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10007",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10008",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10009",
    "http://sph9k2p5z9:ghI6z+qlegG6h4F8zE@gate.decodo.com:10010",
]

# Newly provided mobile proxies – used when residential pool is blocked
MOBILE_PROXIES = [
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10001",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10002",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10003",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10004",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10005",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10006",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10007",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10008",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10009",
    "http://spo5y5143p:4QrFon=3x9oPmmlC9k@gate.decodo.com:10010",
]

# For backwards compatibility with earlier versions
PROXIES = RESIDENTIAL_PROXIES


# Maximum concurrent browser contexts.
MAX_PARALLEL_CONTEXTS = 5
# Initial percentage of mobile proxies to allocate.
INITIAL_MOBILE_RATIO = 0.3

# Storage for reusable session cookies keyed by domain
SESSION_COOKIES: dict[str, list] = {}
SESSION_LOCK = threading.Lock()

# Cache of parsed robots.txt files keyed by domain
ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}


class RateLimiter:
    """Simple per-domain rate limiter."""

    def __init__(self, delay: float = 5.0):
        self.delay = delay
        self.last: Dict[str, float] = {}

    def wait(self, domain: str) -> None:
        now = time.time()
        last_time = self.last.get(domain, 0)
        sleep_for = self.delay - (now - last_time)
        if sleep_for > 0:
            logger.debug("Rate limiting %s for %.2fs", domain, sleep_for)
            time.sleep(sleep_for)
        self.last[domain] = time.time()


RATE_LIMITER = RateLimiter()


def is_allowed_by_robots(url: str, ua: str) -> bool:
    """Return True if the given URL is allowed by robots.txt."""
    parsed = urlsplit(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = ROBOTS_CACHE.get(base)
    if not rp:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.set_url(f"{base}/robots.txt")
            rp.read()
        except Exception as exc:
            logger.debug("robots.txt fetch failed for %s: %s", base, exc)
            ROBOTS_CACHE[base] = rp
            return True
        ROBOTS_CACHE[base] = rp
    return rp.can_fetch(ua, parsed.path)


def load_cookie_store(path: str | None) -> None:
    if not path or not Path(path).exists():
        return
    try:
        data = json.loads(Path(path).read_text())
        with SESSION_LOCK:
            SESSION_COOKIES.update(data)
        logger.debug("Loaded cookie store from %s", path)
    except Exception as exc:
        logger.debug("Cookie store load failed: %s", exc)


def save_cookie_store(path: str | None) -> None:
    if not path:
        return
    try:
        with SESSION_LOCK:
            data = SESSION_COOKIES
        Path(path).write_text(json.dumps(data))
        logger.debug("Saved cookie store to %s", path)
    except Exception as exc:
        logger.debug("Cookie store save failed: %s", exc)

from dataclasses import dataclass, field
import threading


@dataclass
class ProxyStats:
    """Runtime statistics for a single proxy."""

    success: int = 0
    failure: int = 0
    blocks: int = 0
    times: list = field(default_factory=list)
    cooldown_until: float = 0.0
    fail_streak: int = 0


class ParallelProxyManager:
    """Smart proxy allocator for concurrent workers."""

    def __init__(self, residential: List[str], mobile: List[str]):
        self.residential = residential[:]
        self.mobile = mobile[:]
        self.lock = threading.Lock()
        self.res_index = 0
        self.mob_index = 0
        self.mobile_ratio = INITIAL_MOBILE_RATIO
        self.in_use: set[str] = set()
        self.stats = {p: ProxyStats() for p in residential + mobile}

    def _next_from_pool(self, pool: List[str], idx: int) -> tuple[str | None, int]:
        if not pool:
            return None, idx
        start = idx
        while True:
            if idx >= len(pool):
                idx = 0
            proxy = pool[idx]
            idx += 1
            stat = self.stats.get(proxy)
            if (
                proxy not in self.in_use
                and stat
                and stat.cooldown_until <= time.time()
            ):
                self.in_use.add(proxy)
                return proxy, idx
            if idx == start:
                return None, idx

    def allocate(self) -> tuple[str | None, str]:
        """Return an available proxy and its type."""
        with self.lock:
            use_mobile = random.random() < self.mobile_ratio
            proxy = None
            ptype = ""
            if use_mobile:
                proxy, self.mob_index = self._next_from_pool(self.mobile, self.mob_index)
                ptype = "mobile"
            if not proxy:
                proxy, self.res_index = self._next_from_pool(self.residential, self.res_index)
                ptype = "residential"
            if not proxy and not use_mobile:
                proxy, self.mob_index = self._next_from_pool(self.mobile, self.mob_index)
                ptype = "mobile"
            if proxy:
                logger.info("[CTX] Allocated %s proxy %s", ptype, proxy)
            return proxy, ptype

    def release(self, proxy: str, ptype: str, success: bool, blocked: bool, duration: float) -> None:
        """Return proxy to pool and update health metrics."""
        with self.lock:
            if proxy in self.in_use:
                self.in_use.remove(proxy)
            stat = self.stats.get(proxy)
            if stat:
                stat.times.append(duration)
                if success:
                    stat.success += 1
                    stat.fail_streak = 0
                else:
                    stat.failure += 1
                    stat.fail_streak += 1
                if blocked:
                    stat.blocks += 1
                    stat.fail_streak += 1
                if stat.fail_streak >= 3:
                    stat.cooldown_until = time.time() + 120
                    stat.fail_streak = 0
                    logger.info("[CTX] Cooling down proxy %s for 120s", proxy)
            if ptype == "residential" and not success:
                self.mobile_ratio = min(0.7, self.mobile_ratio + 0.05)
            elif ptype == "residential" and success:
                self.mobile_ratio = max(INITIAL_MOBILE_RATIO, self.mobile_ratio - 0.02)
            logger.info(
                "[CTX] Released %s proxy %s success=%s blocked=%s ratio=%.2f",
                ptype,
                proxy,
                success,
                blocked,
                self.mobile_ratio,
            )

    def log_stats(self) -> None:
        """Output aggregated proxy health metrics."""
        with self.lock:
            for proxy, stat in self.stats.items():
                if stat.success or stat.failure:
                    avg = sum(stat.times) / len(stat.times) if stat.times else 0
                    logger.info(
                        "[STATS] %s succ=%d fail=%d blocks=%d avg_time=%.1fs cooldown=%.0f",
                        proxy,
                        stat.success,
                        stat.failure,
                        stat.blocks,
                        avg,
                        max(0, stat.cooldown_until - time.time()),
                    )


class ProxyRotator:
    """Rotate residential proxies first, then mobile on repeated failures."""

    def __init__(self, residential: List[str], mobile: List[str]):
        self.residential = residential
        self.mobile = mobile
        self.res_index = 0
        self.mob_index = 0
        self.mode = "residential"
        self.failures = 0
        self.success = 0
        self.last_mobile = 0.0
        self.stats = {p: ProxyStats() for p in residential + mobile}

    def _get_proxy(self, pool: List[str], idx: int) -> tuple[Optional[str], int]:
        if not pool:
            return None, idx
        if idx >= len(pool):
            idx = 0
        proxy = pool[idx]
        idx += 1
        return proxy, idx

    def next_proxy(self) -> tuple[Optional[str], str]:
        if self.mode == "residential":
            proxy, self.res_index = self._get_proxy(self.residential, self.res_index)
            ptype = "residential"
        else:
            proxy, self.mob_index = self._get_proxy(self.mobile, self.mob_index)
            ptype = "mobile"
        if proxy:
            logger.info("Switching to %s proxy %s", ptype, proxy)
        else:
            logger.warning("No %s proxies left to rotate", ptype)
        return proxy, ptype

    def record_failure(self, reason: str) -> None:
        global HUMANIZATION_SCALE
        self.failures += 1
        HUMANIZATION_SCALE = min(2.0, HUMANIZATION_SCALE + 0.1)
        logger.warning(
            "Proxy failure (%s) count=%d success=%d scale=%.2f mode=%s",
            reason,
            self.failures,
            self.success,
            HUMANIZATION_SCALE,
            self.mode,
        )

        proxy = self.residential[self.res_index - 1] if self.mode == "residential" else self.mobile[self.mob_index - 1]
        stat = self.stats.get(proxy)
        if stat:
            stat.failure += 1

        if self.mode == "residential" and self.failures >= 2:
            logger.warning("Switching to mobile proxies due to repeated failures")
            self.mode = "mobile"
            self.last_mobile = time.time()
            self.failures = 0

    def record_success(self) -> None:
        global HUMANIZATION_SCALE
        self.success += 1
        self.failures = 0
        HUMANIZATION_SCALE = max(1.0, HUMANIZATION_SCALE - 0.05)
        if self.mode == "mobile" and time.time() - self.last_mobile > 300:
            logger.info("Returning to residential proxies after cooldown")
            self.mode = "residential"
        logger.info(
            "Proxy success count=%d failures=%d mode=%s scale=%.2f",
            self.success,
            self.failures,
            self.mode,
            HUMANIZATION_SCALE,
        )
        proxy = self.residential[self.res_index - 1] if self.mode == "residential" else self.mobile[self.mob_index - 1]
        stat = self.stats.get(proxy)
        if stat:
            stat.success += 1

    def log_stats(self) -> None:
        for proxy, stat in self.stats.items():
            if stat.success or stat.failure:
                avg = sum(stat.times) / len(stat.times) if stat.times else 0
                logger.info(
                    "[STATS] %s succ=%d fail=%d blocks=%d avg_time=%.1fs",
                    proxy,
                    stat.success,
                    stat.failure,
                    stat.blocks,
                    avg,
                )


def _parse_proxy(proxy: str) -> dict:
    """Return server/username/password dict for Playwright."""
    match = re.match(r"(https?://)?(?:(.+?):(.+)@)?([^:]+:\d+)", proxy)
    if not match:
        return {"server": proxy}
    server = f"http://{match.group(4)}"
    username = match.group(2)
    password = match.group(3)
    cfg = {"server": server}
    if username and password:
        cfg.update({"username": username, "password": password})
    return cfg


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

def check_for_cloudflare(page, html: str, url: str) -> None:
    """Detect Cloudflare block pages and capture a screenshot."""
    lower = html.lower()
    if "you have been blocked" in lower or "cloudflare" in lower:
        Path("logs").mkdir(exist_ok=True)
        ts = int(time.time())
        screenshot = f"logs/cloudflare_{ts}.png"
        page.screenshot(path=screenshot)
        logger.warning("Cloudflare block detected at %s, screenshot %s", url, screenshot)

def check_security_service(page, html: str, url: str) -> bool:
    """Detect generic security service block pages."""
    lower = html.lower()
    if "security service" in lower and "protect itself" in lower:
        Path("logs").mkdir(exist_ok=True)
        screenshot = f"logs/security_service_{int(time.time())}.png"
        page.screenshot(path=screenshot)
        logger.warning("Security service block detected at %s, screenshot %s", url, screenshot)
        return True
    return False

def check_white_screen(page, html: str, url: str, selector: str | None = None) -> bool:
    """Detect Cloudflare white screen/blank page blocks."""
    short = len(html) < 1000
    missing = False
    if selector:
        try:
            soup = BeautifulSoup(html, "html.parser")
            if not soup.select_one(selector):
                missing = True
        except Exception:
            pass
    if short or missing:
        Path("logs").mkdir(exist_ok=True)
        screenshot = f"logs/white_screen_{int(time.time())}.png"
        page.screenshot(path=screenshot)
        logger.warning(
            "White screen detected at %s short=%s missing=%s screenshot=%s",
            url,
            short,
            missing,
            screenshot,
        )
        return True
    return False

def detect_js_challenge(page, html: str, url: str) -> bool:
    """Detect Cloudflare JavaScript challenge pages."""
    lower = html.lower()
    if "just a moment" in lower and "cloudflare" in lower:
        Path("logs").mkdir(exist_ok=True)
        screenshot = f"logs/js_challenge_{int(time.time())}.png"
        page.screenshot(path=screenshot)
        logger.warning("JS challenge at %s screenshot %s", url, screenshot)
        return True
    return False

def detect_turnstile(page, html: str, url: str) -> bool:
    """Detect Cloudflare Turnstile CAPTCHA."""
    if "cf-turnstile" in html.lower() or "challenges.cloudflare.com" in html.lower():
        Path("logs").mkdir(exist_ok=True)
        screenshot = f"logs/turnstile_{int(time.time())}.png"
        page.screenshot(path=screenshot)
        logger.warning("Turnstile CAPTCHA at %s screenshot %s", url, screenshot)
        solve_turnstile_captcha(page)
        return True
    return False


def handle_js_challenge(page, timeout: int = 15000) -> bool:
    """Wait for Cloudflare JS challenge to complete."""
    try:
        locator = page.locator("text=Checking your browser before accessing")
        if locator.first.is_visible(timeout=3000):
            logger.info("Waiting for JS challenge to finish")
            page.wait_for_load_state("networkidle", timeout=timeout)
            return True
    except Exception:
        pass
    return False


def solve_turnstile_captcha(page) -> None:
    """Placeholder for CAPTCHA solving integration."""
    api_key = os.getenv("CAPTCHA_API_KEY")
    if not api_key:
        logger.info("Manual CAPTCHA solve required")
        return
    logger.debug("Submitting CAPTCHA to external service")
    # Actual CAPTCHA solving logic would go here


def reset_storage(context) -> None:
    """Clear cookies and storage to avoid reuse across sessions."""
    try:
        context.clear_cookies()
        context.add_init_script("() => { localStorage.clear(); sessionStorage.clear(); }")
        logger.debug("Cleared cookies and storage for new context")
    except Exception as exc:
        logger.debug("Storage reset failed: %s", exc)

def restore_cookies(context, domain: str) -> None:
    """Load stored cookies for a domain into the context."""
    with SESSION_LOCK:
        cookies = SESSION_COOKIES.get(domain)
    if cookies:
        try:
            context.add_cookies(cookies)
            logger.debug("Restored %d cookies for %s", len(cookies), domain)
        except Exception as exc:
            logger.debug("Cookie restore failed: %s", exc)

def store_cookies(context, domain: str) -> None:
    """Persist cookies from the context for reuse."""
    try:
        cookies = context.cookies(f"https://{domain}")
        with SESSION_LOCK:
            SESSION_COOKIES[domain] = cookies
        logger.debug("Stored %d cookies for %s", len(cookies), domain)
    except Exception as exc:
        logger.debug("Cookie save failed: %s", exc)

def apply_stealth(page) -> None:
    """Spoof common fingerprint attributes using randomized values."""

    hw_concurrency = random.randint(4, 8)
    dev_mem = random.choice([4, 8])
    platform = random.choice(PLATFORMS)
    vendor = random.choice(VENDORS)
    product_sub = random.choice(PRODUCT_SUBS)
    languages = random.choice(LANGUAGE_SETS)
    plugins = [
        f"Plugin {i} {random.choice(['PDF','Video','Audio'])}"
        for i in range(random.randint(3, 6))
    ]

    page.add_init_script(
        f"""
        Object.defineProperty(navigator, 'webdriver', {{get: () => false}});
        window.chrome = window.chrome || {{ runtime: {{}} }};
        Object.defineProperty(navigator, 'plugins', {{ get: () => {json.dumps(plugins)} }});
        Object.defineProperty(navigator, 'languages', {{ get: () => {json.dumps(languages)} }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {hw_concurrency} }});
        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {dev_mem} }});
        Object.defineProperty(navigator, 'platform', {{ get: () => '{platform}' }});

        const originalQuery = navigator.permissions.query;
        navigator.permissions.__proto__.query = parameters => (
            parameters.name === 'notifications'
                ? Promise.resolve({{ state: Notification.permission }})
                : originalQuery.call(navigator.permissions, parameters)
        );

        Object.defineProperty(navigator, 'connection', {{ get: () => ({
            rtt: Math.floor(Math.random() * 100) + 50,
            downlink: (Math.random() * 10 + 1).toFixed(1),
            effectiveType: '4g'
        }) }});

        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {{
            if (param === 37445) return 'Intel Inc.';
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return getParameter.call(this, param);
        }};
        const toDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function() {{ return 'data:image/png;base64,AAAA'; }};
        Object.defineProperty(navigator, 'vendor', {{ get: () => '{vendor}' }});
        Object.defineProperty(navigator, 'productSub', {{ get: () => '{product_sub}' }});

        navigator.mediaDevices.getUserMedia = undefined;
        """
    )
    # Apply additional stealth modifications from playwright-stealth
    stealth_sync(page)
    logger.debug(
        "Stealth props platform=%s vendor=%s productSub=%s languages=%s", 
        platform,
        vendor,
        product_sub,
        languages,
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

def smooth_mouse_move_ml(
    page,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    duration: float = 1.0,
) -> None:
    """Move the mouse using a path predicted by the RL model."""
    logger.debug(
        "RL move from (%.1f, %.1f) to (%.1f, %.1f)", start_x, start_y, end_x, end_y
    )
    if not MOUSE_MODEL:
        # Fallback to Bezier movement when model not available
        smooth_mouse_move(page, start_x, start_y, end_x, end_y, duration)
        return

    # Predict a sequence of (dx, dy) offsets normalized to [-1,1] using the RL model
    path = []
    state = np.array([start_x, start_y, end_x, end_y], dtype=np.float32)
    for _ in range(20):
        action, _ = MOUSE_MODEL.predict(state, deterministic=True)
        dx, dy = action
        next_x = start_x + dx * (end_x - start_x)
        next_y = start_y + dy * (end_y - start_y)
        path.append((next_x, next_y))
        logger.debug("RL predicted step to %.1f,%.1f", next_x, next_y)
        state = np.array([next_x, next_y, end_x, end_y], dtype=np.float32)

    for i, (x, y) in enumerate(path):
        page.mouse.move(x, y)
        time.sleep(max(0.001, duration / len(path)) * random.uniform(0.7, 1.3))
        logger.debug(f"RL move {i}/{len(path)}: {x:.1f},{y:.1f}")
    CURRENT_MOUSE_POS[0] = end_x
    CURRENT_MOUSE_POS[1] = end_y

def random_mouse_movement(page, width: int = 1366, height: int = 768) -> None:
    """Perform several smooth mouse moves around the page."""
    start_x, start_y = CURRENT_MOUSE_POS
    move_count = int(random.randint(8, 15) * HUMANIZATION_SCALE)

    for _ in range(move_count):
        x = random.randint(0, width)
        y = random.randint(0, height)
        # Randomly choose between RL-generated and Bezier paths for variation
        if MOUSE_MODEL and random.random() < 0.6:
            smooth_mouse_move_ml(page, start_x, start_y, x, y)
        else:
            smooth_mouse_move(page, start_x, start_y, x, y)
        start_x, start_y = x, y

        time.sleep(random.uniform(0.05, 0.2) * HUMANIZATION_SCALE)


def handle_press_and_hold(page, debug: bool) -> None:
    """Attempt to solve the press and hold challenge if displayed."""

    try:
        btn = page.locator("text=Press & Hold").first
        btn.wait_for(timeout=3000)
        box = btn.bounding_box()
        if box:
            target_x = box["x"] + box["width"] / 2
            target_y = box["y"] + box["height"] / 2
            # Use RL-based movement for high-value interaction
            smooth_mouse_move_ml(page, CURRENT_MOUSE_POS[0], CURRENT_MOUSE_POS[1], target_x, target_y, duration=0.5)

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

def replay_telemetry(page, telemetry_file: str) -> None:
    """Replay previously captured network events to mimic real behavior."""
    if not Path(telemetry_file).exists():
        logger.debug("Telemetry file %s not found", telemetry_file)
        return
    with open(telemetry_file, "r") as f:
        events = json.load(f)
    for evt in events:
        method = evt.get("method")
        url = evt.get("url")
        payload = evt.get("payload")
        if method and url:
            logger.debug("Replaying %s %s", method, url)
            try:
                page.request.fetch(url, method=method, data=payload)
            except Exception as exc:
                logger.debug("Replay error %s", exc)

def intercept_beacon(context) -> None:
    """Intercept Cloudflare beacon.min.js requests."""

    def handler(route, request) -> None:
        action = random.choice(["block", "delay", "allow"])
        if action == "block":
            logger.debug("Blocking beacon %s", request.url)
            route.abort()
        elif action == "delay":
            delay = random.uniform(1000, 3000)
            logger.debug("Delaying beacon %.0fms %s", delay, request.url)
            time.sleep(delay / 1000)
            route.continue_()
        else:
            logger.debug("Allowing beacon %s", request.url)
            route.continue_()

    context.route("https://static.cloudflareinsights.com/beacon.min.js", handler)

def create_context(p, visible: bool, proxy: str | None) -> tuple:
    """Launch a browser with randomized context settings."""

    launch_args = {"headless": not visible}
    if not proxy:
        # Randomly select a residential proxy for rotation
        proxy = random.choice(PROXIES)
    if proxy:
        cfg = _parse_proxy(proxy)
        launch_args["proxy"] = cfg
        logger.info(
            "Using proxy server=%s username=%s password=%s",
            cfg.get("server"),
            cfg.get("username"),
            cfg.get("password"),
        )

    browser = p.chromium.launch(**launch_args)


    width = random.randint(1280, 1920)
    height = random.randint(720, 1080)
    logger.debug(f"Browser viewport {width}x{height}")
    CURRENT_MOUSE_POS[0] = width / 2
    CURRENT_MOUSE_POS[1] = height / 2

    ua = random.choice(USER_AGENTS)
    tz = random.choice(TIMEZONES)
    lang_header = random.choice(LANGUAGES)
    lat = random.uniform(25.0, 49.0)
    lon = random.uniform(-124.0, -66.0)
    context = browser.new_context(
        user_agent=ua,
        viewport={"width": width, "height": height},
        locale=lang_header.split(',')[0],
        timezone_id=tz,
        geolocation={"longitude": lon, "latitude": lat},
        permissions=["geolocation"],
        device_scale_factor=1,
        extra_http_headers={"Accept-Language": lang_header, "Referer": "https://www.google.com/"},
    )
    context._user_agent = ua
    stealth_sync(context)
    reset_storage(context)
    intercept_beacon(context)
    logger.debug(
        "Context UA=%s TZ=%s Lang=%s headers=%s",
        ua,
        tz,
        lang_header,
        {"Accept-Language": lang_header, "Referer": "https://www.google.com/"},
    )
    return browser, context

def fetch_html(context, url: str, debug: bool) -> str:
    """Navigate to a URL in a fresh page and return the HTML."""
    page = context.new_page()
    setup_telemetry_logging(page)
    apply_stealth(page)
    random_mouse_movement(page)
    reset_storage(context)
    restore_cookies(context, "www.truepeoplesearch.com")
    domain = urlsplit(url).netloc
    restore_cookies(context, domain)
    ua = getattr(context, "_user_agent", random.choice(USER_AGENTS))
    if not is_allowed_by_robots(url, ua):
        logger.warning("Robots.txt disallows %s", url)
        page.close()
        raise RuntimeError("ROBOTS")
    RATE_LIMITER.wait(domain)
    # Replay previously captured human telemetry to mimic authentic activity
    replay_telemetry(page, "telemetry.json")
    logger.info(f"Fetching {url}")
    wait_pre = random.uniform(500, 1500) * HUMANIZATION_SCALE
    logger.debug("Waiting %.0fms before navigation", wait_pre)
    page.wait_for_timeout(wait_pre)
    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if response:
        logger.debug(f"Navigation status {response.status} {response.url}")
    handle_js_challenge(page)
    for _ in range(random.randint(1, 2)):
        page.mouse.wheel(0, random.randint(200, 1200))
        time.sleep(random.uniform(0.2, 0.5) * HUMANIZATION_SCALE)
    delay_after = random.uniform(5000, 10000) * HUMANIZATION_SCALE

    logger.debug("Waiting %.0fms after navigation", delay_after)
    page.wait_for_timeout(delay_after)
    html = page.content()
    if debug:
        save_debug_html(html)
        logger.debug(f"Saved debug HTML for {url}")
    check_for_cloudflare(page, html, url)
    if check_white_screen(page, html, url):
        page.close()
        raise RuntimeError("WHITE_SCREEN")

    if check_security_service(page, html, url):
        page.close()
        raise RuntimeError("SECURITY_SERVICE")
    if detect_js_challenge(page, html, url):
        page.close()
        raise RuntimeError("JS_CHALLENGE")
    if detect_turnstile(page, html, url):
        page.close()
        raise RuntimeError("TURNSTILE")
    if response and response.status >= 400:
        Path("logs").mkdir(exist_ok=True)
        ts = int(time.time())
        screenshot = f"logs/error_{ts}.png"
        page.screenshot(path=screenshot)
        logger.debug(f"Saved error screenshot {screenshot}")

        raise ValueError(f"HTTP {response.status}")
    store_cookies(context, domain)
    page.close()
    return html


def search_truepeoplesearch(
    context,
    address: str,
    debug: bool,
    inspect: bool,
    visible: bool,
    manual: bool,
) -> tuple[List[Dict[str, object]], bool]:

    if debug:
        print("Trying TruePeopleSearch...")

    page = context.new_page()
    setup_telemetry_logging(page)
    apply_stealth(page)
    random_mouse_movement(page)
    reset_storage(context)

    inter_url = "https://www.google.com/"
    delay = random.uniform(5000, 10000) * HUMANIZATION_SCALE

    logger.debug("Navigating to intermediate %s after %.0fms", inter_url, delay)
    page.wait_for_timeout(delay)
    try:
        page.goto(inter_url, timeout=15000)
    except Exception as exc:
        logger.debug("Intermediate navigation failed: %s", exc)
    page.wait_for_timeout(random.uniform(5000, 10000) * HUMANIZATION_SCALE)


    try:
        resp = page.goto(
            "https://www.truepeoplesearch.com/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        if resp:
            logger.info(
                "Reached TruePeopleSearch via proxy (status %s)", resp.status
            )
        else:
            logger.error("Navigation returned no response")
    except Exception as exc:
        logger.error("Navigation to TruePeopleSearch failed: %s", exc)
        raise
    if resp and resp.status >= 400:
        logger.error("Access denied on initial page: %s", resp.status)
        page.screenshot(path="logs/access_denied_start.png")
    page.wait_for_timeout(random.uniform(5000, 10000) * HUMANIZATION_SCALE)

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
        return [], True

    try:
        city_input.press("Enter")
        time.sleep(random.uniform(5, 10) * HUMANIZATION_SCALE)

    except Exception:
        try:
            page.click("button[type='submit']")
        except Exception:
            if debug:
                print("Failed to submit address search")
            page.close()
            return [], True
    page.wait_for_load_state("domcontentloaded")
    time.sleep(random.uniform(5, 10) * HUMANIZATION_SCALE)

    time.sleep(random.uniform(5, 10) * HUMANIZATION_SCALE)
    page.wait_for_load_state("domcontentloaded")
    for _ in range(random.randint(1, 3)):
        page.mouse.wheel(0, random.randint(200, 1200))
        time.sleep(random.uniform(0.5, 1.0) * HUMANIZATION_SCALE)

    random_mouse_movement(page)

    html = page.content()
    if debug:
        Path("logs").mkdir(exist_ok=True)
        Path("logs/page_after_submit.html").write_text(html)
    check_for_cloudflare(page, html, "https://www.truepeoplesearch.com/")
    if check_white_screen(page, html, "https://www.truepeoplesearch.com/", "div.card"):
        page.close()
        return [], True

    if check_security_service(page, html, "https://www.truepeoplesearch.com/"):
        page.close()
        return [], True

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
        except RuntimeError as e:
            if debug:
                print(f"Security block on detail page: {e}")
            return results, True
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
    store_cookies(context, "www.truepeoplesearch.com")
    page.close()
    return results, bot_check

def search_fastpeoplesearch(context, address: str, debug: bool, inspect: bool) -> tuple[List[Dict[str, object]], bool]:
    if debug:
        print("Trying FastPeopleSearch...")

    slug = quote_plus(address.lower().replace(",", "").replace(" ", "-"))
    url = f"https://www.fastpeoplesearch.com/address/{slug}"

    page = context.new_page()
    setup_telemetry_logging(page)
    apply_stealth(page)
    restore_cookies(context, "www.fastpeoplesearch.com")
    replay_telemetry(page, "telemetry.json")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)

    time.sleep(random.uniform(5, 10) * HUMANIZATION_SCALE)

    try:
        page.wait_for_selector("div.card", timeout=int(8000 * HUMANIZATION_SCALE))
    except Exception:
        pass
    page.mouse.wheel(0, random.randint(200, 1200))
    html = page.content()
    if debug:
        save_debug_html(html)

    check_for_cloudflare(page, html, url)
    if check_white_screen(page, html, url, "div.card"):
        page.close()
        return [], True

    if check_security_service(page, html, url):
        page.close()
        return [], True
    if detect_js_challenge(page, html, url):
        page.close()
        return [], True
    if detect_turnstile(page, html, url):
        page.close()
        return [], True

    lower_html = html.lower()
    bot_check = False
    if (
        "press & hold" in lower_html
        or "robot check" in lower_html
        or ("verify" in lower_html and "robot" in lower_html)
        or "are you a human" in lower_html
    ):
        bot_check = True

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
        except RuntimeError as e:
            if debug:
                print(f"Security block on FPS detail page: {e}")
            return results, True
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
    store_cookies(context, "www.fastpeoplesearch.com")
    page.close()

    return results, bot_check


def run_sequential(p, args) -> List[Dict[str, object]]:
    """Original single-context execution preserved."""
    rotator = ProxyRotator([args.proxy] if args.proxy else RESIDENTIAL_PROXIES, MOBILE_PROXIES)
    results: List[Dict[str, object]] = []
    bot_block = True

    while bot_block:
        proxy, ptype = rotator.next_proxy()
        if proxy is None:
            logger.error("All proxies exhausted without bypassing bot protection")
            break

        start = time.time()
        browser, context = create_context(p, args.visible, proxy)

        try:
            res, bot_block = search_truepeoplesearch(
                context,
                args.address,
                args.debug,
                args.inspect,
                args.visible,
                args.manual,
            )
            results.extend(res)

            if args.fast and not bot_block:
                res2, bot2 = search_fastpeoplesearch(
                    context,
                    args.address,
                    args.debug,
                    args.inspect,
                )
                results.extend(res2)
                bot_block = bot_block or bot2
            if bot_block:
                rotator.record_failure("bot detection")
            else:
                rotator.record_success()

        except Exception as exc:
            bot_block = True
            rotator.record_failure(str(exc))
            if args.debug:
                print(f"Search error: {exc}")

        duration = time.time() - start
        context.close()
        browser.close()
        stat = rotator.stats.get(proxy)
        if stat:
            stat.times.append(duration)

        if bot_block:
            logger.warning("Bot protection triggered, rotating proxy")

    rotator.log_stats()
    return results


def _worker(ctx_id: int, manager: ParallelProxyManager, args, results: list, stop: threading.Event) -> None:
    """Worker function for parallel contexts."""
    while not stop.is_set():
        proxy, ptype = manager.allocate()
        if not proxy:
            logger.warning("Worker %d found no available proxy", ctx_id)
            return
        start = time.time()
        blocked = False
        success = False
        try:
            with sync_playwright() as p:
                browser, context = create_context(p, args.visible, proxy)
                res, bot_block = search_truepeoplesearch(
                    context,
                    args.address,
                    args.debug,
                    args.inspect,
                    args.visible,
                    args.manual,
                )
                if args.fast and not bot_block:
                    res2, bot2 = search_fastpeoplesearch(
                        context,
                        args.address,
                        args.debug,
                        args.inspect,
                    )
                    res.extend(res2)
                    bot_block = bot_block or bot2
                success = not bot_block
                blocked = bot_block
                if success:
                    results.extend(res)
                    stop.set()
        except Exception as exc:
            logger.error("Worker %d error %s", ctx_id, exc)
            blocked = True
        finally:
            duration = time.time() - start
            manager.release(proxy, ptype, success, blocked, duration)
        if success or stop.is_set():
            return


def run_parallel(args) -> List[Dict[str, object]]:
    """Launch multiple browser contexts concurrently using separate proxies."""
    manager = ParallelProxyManager(
        [args.proxy] if args.proxy else RESIDENTIAL_PROXIES,
        MOBILE_PROXIES,
    )
    results: List[Dict[str, object]] = []
    stop = threading.Event()
    threads = []

    worker_count = min(MAX_PARALLEL_CONTEXTS, args.parallel)
    for i in range(worker_count):
        t = threading.Thread(target=_worker, args=(i + 1, manager, args, results, stop), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
    manager.log_stats()
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
    parser.add_argument("--cookie-store", help="Path to persistent cookie store JSON")

    parser.add_argument("--save", action="store_true", help="Write results to results.json")
    parser.add_argument(
        "--parallel",
        type=int,
        nargs="?",
        const=5,
        default=5,
        help="Number of parallel browser contexts to run (default: 5)",
    )
    args = parser.parse_args()

    load_cookie_store(args.cookie_store)

    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    results: List[Dict[str, object]] = []
    if args.parallel and args.parallel > 1:
        results = run_parallel(args)
    else:
        with sync_playwright() as p:
            results = run_sequential(p, args)

    if args.save:
        Path("results.json").write_text(json.dumps(results, indent=2))

    save_cookie_store(args.cookie_store)

    if results:
        print(json.dumps(results, indent=2))
    else:
        print("No matches found for this address.")

if __name__ == "__main__":
    main()
