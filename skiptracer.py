#!/usr/bin/env python3
"""Skip tracing TruePeopleSearch via Decodo Web-Scraping API (real-time flow-B)."""

import os, re, time, argparse
from typing import Dict, List
from urllib.parse import quote_plus
import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ── ENV ─────────────────────────────────────────────────────────────────────────
load_dotenv()
DECODO_USERNAME = os.getenv("DECODO_USERNAME")
DECODO_PASSWORD = os.getenv("DECODO_PASSWORD")
DECODO_API_TOKEN = os.getenv("DECODO_API_TOKEN")
if not DECODO_USERNAME or not DECODO_PASSWORD:
    raise RuntimeError("DECODO_USERNAME / DECODO_PASSWORD not set")

AUTH        = (DECODO_USERNAME, DECODO_PASSWORD)
SCRAPE_URL  = "https://scraper-api.decodo.com/v2/scrape"
HEADERS     = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
PHONE_RE    = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")

# ── HELPERS ─────────────────────────────────────────────────────────────────────
def _normalize_phone(num: str) -> str:
    digits = re.sub(r"\D", "", num)
    return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}" if len(digits) == 10 else num

def _parse_phones(text: str) -> List[str]:
    return sorted({ _normalize_phone(m) for m in PHONE_RE.findall(text or "") })

def fetch_tps_via_decodo(address, timeout):
    """
    Return raw HTML for a TruePeopleSearch results page using Decodo.
    No JS rendering, no extra params — exactly as support tested.
    """
    from urllib.parse import quote_plus
    import os, json, requests, logging

    token = os.getenv("DECODO_API_TOKEN")
    if not token:
        raise RuntimeError("DECODO_API_TOKEN not set")

    url = (
        "https://www.truepeoplesearch.com/results?"
        f"name=&citystatezip={quote_plus(address)}"
    )
    payload = {"target": "universal", "url": url}
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "User-Agent": "skiptracer/1.0 (+https://github.com/freedom-crm)"
    }
    logging.debug("\U0001f4e1 Decodo POST %s", payload)
    r = requests.post(
        "https://scraper-api.decodo.com/v2/scrape",
        headers=headers,
        data=json.dumps(payload),
        timeout=timeout,
    )
    logging.debug("\U0001f6e0  Decodo response %s bytes %s",
                  r.status_code, len(r.text))
    r.raise_for_status()
    return r.text

# ── FETCH ───────────────────────────────────────────────────────────────────────
def fetch_url(url: str, *, timeout: int = 150, visible: bool=False) -> str:
    payload = {
        "url": url,
        "headless": "html",
        "http_method": "GET",
        "geo": "US",
        "locale": "en-US",
        "session_id": "tsp-session-1",
        "wait_for": "networkidle",
        "render_wait_time_ms": 8000,          # 8 s JS settle
    }
    print(f"📡 Payload: {payload}")
    for attempt in range(3):
        try:
            r = requests.post(SCRAPE_URL, json=payload, auth=AUTH,
                              headers=HEADERS, timeout=timeout)
            print(f"🌐 fetch HTTP {r.status_code}")
            if r.status_code == 429 and attempt < 2:
                print("⏳ 429 → back-off 5 s"); time.sleep(5); continue
            r.raise_for_status()

            data  = r.json() if "application/json" in r.headers.get("Content-Type","") else {}
            html  = (
                data.get("results", [{}])[0].get("content") or
                data.get("body")      or data.get("content") or
                data.get("html")      or data.get("result")  or
                r.text
            )

            if not html:
                print("⚠️  Empty HTML (Render Timeout)")
            print(html if visible else html[:500])
            return html
        except Exception as exc:
            if attempt < 2:
                print(f"❌ {exc} – retrying in 5 s"); time.sleep(5); continue
            raise
    raise RuntimeError("Fetch failed after retries")

# ── PARSER ──────────────────────────────────────────────────────────────────────
def extract_data(html: str, *, timeout:int=150, visible:bool=False) -> Dict[str,str]:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one('a.detail-link[href^="/details"], a[href^="/details"]')
    if not link:
        return {"Result Name":"","Result Address":"","Phone Numbers":"","Status":"No Results"}

    name        = link.get_text(strip=True)
    addr_block  = link.find_parent("div") or link
    address_txt = addr_block.get_text(" ", strip=True)

    detail_url  = "https://www.truepeoplesearch.com" + link["href"]
    detail_html = fetch_url(detail_url, timeout=timeout, visible=visible)
    phones      = _parse_phones(detail_html)

    return {
        "Result Name": name,
        "Result Address": address_txt,
        "Phone Numbers": "; ".join(phones),
        "Status": "Success" if phones else "Partial"
    }

# ── MAIN ────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Batch skip-tracer via Decodo")
    ap.add_argument("--request-timeout", type=int, default=150, help="HTTP timeout seconds")
    ap.add_argument("--visible", action="store_true", help="Print full HTML")
    ap.add_argument("--no-decodo", action="store_true", help="Force Selenium fallback")
    args = ap.parse_args()

    df       = pd.read_csv("input.csv")
    results  = []
    for _, row in df.iterrows():
        raw_addr  = row["Address"].strip()
        raw_city  = row["City"].strip()
        raw_state = row["StateZip"].strip()
        full_addr = re.sub(r"\s{2,}", " ", f"{raw_addr}, {raw_city}, {raw_state}")
        target_url = (
            "https://www.truepeoplesearch.com/results?name=&citystatezip="
            + quote_plus(full_addr)
        )

        try:
            if args.no_decodo:
                html = fetch_url(target_url, timeout=args.request_timeout, visible=args.visible)
            else:
                try:
                    html = fetch_tps_via_decodo(full_addr, timeout=args.request_timeout)
                except Exception as dec_exc:
                    print(f"⚠️ Decodo failed: {dec_exc} – falling back")
                    html = fetch_url(target_url, timeout=args.request_timeout, visible=args.visible)

            data  = extract_data(html, timeout=args.request_timeout, visible=args.visible)
        except Exception as exc:
            data = {"Result Name":"","Result Address":"","Phone Numbers":"",
                    "Status":f"Error: {exc}"}

        data["Input Address"] = full_addr
        print(f"📍 Input:   {full_addr}")
        print(f"📄 Name:    {data['Result Name']}")
        print(f"🏠 Address: {data['Result Address']}")
        print(f"📞 Phones:  {data['Phone Numbers']}")
        print(f"📌 Status:  {data['Status']}\n")
        results.append(data)

    pd.DataFrame(results).to_csv("output.csv", index=False)

# ── RUN ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
