#!/usr/bin/env python3
"""Skip tracing TruePeopleSearch via Decodo Web-Scraping API (real-time flow-B)."""

import os, re, time, argparse, json, logging
from typing import Dict, List
from urllib.parse import quote_plus
from pathlib import Path
import pandas as pd
import requests
from bs4 import BeautifulSoup
try:
    from dotenv import load_dotenv
except Exception as exc:
    raise SystemExit(
        "python-dotenv is required. Install via 'pip install python-dotenv'"
    ) from exc

# ── ENV ─────────────────────────────────────────────────────────────────────────
# Optional: directly place your Decodo API token in this variable
_BUILTIN_DECODO_API_TOKEN = ""

# Token resolved at runtime via get_decodo_token()
DECODO_API_TOKEN: str | None = None

SCRAPE_URL = "https://scraper-api.decodo.com/v2/scrape"
PHONE_RE    = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
def get_decodo_token(cli_arg: str | None) -> str:
    token = (
        cli_arg
        or os.getenv("DECODO_API_TOKEN")
        or os.getenv("DECODO_API_KEY")
        or _BUILTIN_DECODO_API_TOKEN
    )
    if not token:
        raise RuntimeError("Decodo API token not found. Set DECODO_API_TOKEN in .env or pass --api-token")
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug(f"Using Decodo token {token[:4]}****")
    return token

# ── HELPERS ─────────────────────────────────────────────────────────────────────
def _normalize_phone(num: str) -> str:
    digits = re.sub(r"\D", "", num)
    return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}" if len(digits) == 10 else num

def _parse_phones(text: str) -> List[str]:
    return sorted({ _normalize_phone(m) for m in PHONE_RE.findall(text or "") })

def fetch_tps_via_decodo(address: str, timeout: int) -> str:
    from urllib.parse import quote_plus
    import json, requests, logging

    token = DECODO_API_TOKEN
    if not token:
        raise RuntimeError(
            "Decodo API token not found. Set DECODO_API_TOKEN in .env or pass --api-token"
        )

    url = (
        "https://www.truepeoplesearch.com/results"
        f"?name=&citystatezip={quote_plus(address)}"
    )
    payload = {"target": "universal", "url": url}

    # 🔒  HARD STOP if anyone tries to add more keys
    forbidden = set(payload.keys()) - {"target", "url"}
    if forbidden:
        raise ValueError(f"Extra Decodo params detected: {forbidden}")

    r = requests.post(
        "https://scraper-api.decodo.com/v2/scrape",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "User-Agent": "skiptracer/1.0"
        },
        data=json.dumps(payload),
        timeout=timeout,
    )
    logging.debug("🛰  Decodo TPS %s → %s bytes", r.status_code, len(r.text))
    r.raise_for_status()
    return r.text

# ── FETCH ───────────────────────────────────────────────────────────────────────
def fetch_url(url: str, *, timeout: int = 150, visible: bool = False) -> str:
    payload = {"target": "universal", "url": url}

    # enforce minimal Decodo payload
    forbidden = set(payload.keys()) - {"target", "url"}
    if forbidden:
        raise ValueError(f"Extra Decodo params detected: {forbidden}")

    print(f"📡 Payload: {payload}")
    token = DECODO_API_TOKEN
    if not token:
        raise RuntimeError(
            "Decodo API token not found. Set DECODO_API_TOKEN in .env or pass --api-token"
        )
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "User-Agent": "skiptracer/1.0",
    }
    for attempt in range(3):
        try:
            r = requests.post(SCRAPE_URL, headers=headers,
                              data=json.dumps(payload), timeout=timeout)
            print(f"🌐 fetch HTTP {r.status_code}")
            if r.status_code == 429 and attempt < 2:
                print("⏳ 429 → back-off 5 s"); time.sleep(5); continue
            r.raise_for_status()
            html = r.text
            if not html:
                print("⚠️  Empty HTML")
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
    ap.add_argument("--api-token", help="Decodo API token")
    args = ap.parse_args()

    load_dotenv(dotenv_path=Path(__file__).parent / ".env")

    global DECODO_API_TOKEN
    DECODO_API_TOKEN = get_decodo_token(args.api_token)

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
            try:
                html = fetch_tps_via_decodo(full_addr, timeout=args.request_timeout)
            except Exception as dec_exc:
                print(f"⚠️ Decodo failed: {dec_exc} – retrying")
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
