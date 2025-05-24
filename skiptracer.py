#!/usr/bin/env python3
"""Skip tracing using Decodo's asynchronous task API."""

import os
import re
import time
import argparse
from typing import Dict, List

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

DECODO_USERNAME = os.getenv("DECODO_USERNAME")
DECODO_PASSWORD = os.getenv("DECODO_PASSWORD")

if not DECODO_USERNAME or not DECODO_PASSWORD:
    raise RuntimeError(
        "DECODO_USERNAME and DECODO_PASSWORD must be set in the environment"
    )

TASK_URL = "https://scraper-api.decodo.com/v2/task"
RESULT_URL = "https://scraper-api.decodo.com/v2/task/{}/results"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
PHONE_RE = re.compile(r"\b(\d{3})[\s.-]?(\d{3})[\s.-]?(\d{4})\b")

auth = (DECODO_USERNAME, DECODO_PASSWORD)

def _normalize_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number

def _parse_phones(text: str) -> List[str]:
    return list({_normalize_phone(''.join(m)) for m in PHONE_RE.findall(text or "")})

def create_task(full_addr: str, timeout: int = 120) -> str:
    payload = {
        "url": "https://www.truepeoplesearch.com",
        "target": "universal",
        "headless": "html",
        "http_method": "GET",
        "geo": "US",
        "locale": "en-US",
        "device_type": "desktop_chrome",
        "session_id": "tsp-session-1",
        "browser_actions": [
            {
                "type": "input",
                "selector": {"type": "css", "query": "#search"},
                "text": full_addr,
            },
            {
                "type": "click",
                "selector": {"type": "css", "query": "#btnSearch"},
                "wait_time_s": 2,
            },
            {
                "type": "click",
                "selector": {
                    "type": "xpath",
                    "query": "(//a[contains(@href,'/details')])[1]",
                },
                "wait_time_s": 2,
            },
        ],
    }
    print(f"📡 Payload: {payload}")
    for attempt in range(3):
        try:
            resp = requests.post(
                TASK_URL,
                json=payload,
                auth=auth,
                headers=HEADERS,
                timeout=timeout,
            )
            print(f"🆔 create_task HTTP {resp.status_code}")
            if resp.status_code == 429 and attempt < 2:
                print("⏳ Received 429, retrying in 5s")
                time.sleep(5)
                continue
            resp.raise_for_status()
            data = resp.json() if "application/json" in resp.headers.get("Content-Type", "") else {}
            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                raise RuntimeError("No task_id in response")
            print(f"🆔 Task queued: {task_id}")
            return task_id
        except Exception as exc:
            if attempt < 2:
                print(f"❌ {exc} - retrying in 5s")
                time.sleep(5)
                continue
            print(f"❌ {exc}")
            raise
    raise RuntimeError("Failed to create task")

def poll_task(task_id: str, timeout: int = 120, *, visible: bool = False) -> str:
    url = RESULT_URL.format(task_id)
    while True:
        try:
            resp = requests.get(url, auth=auth, headers=HEADERS, timeout=timeout)
            status_code = resp.status_code
            if status_code == 429:
                print(f"⏳ Task {task_id} hit 429, waiting 5s")
                time.sleep(5)
                continue
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            print(f"🔄 {task_id} status={status} HTTP={status_code}")
            if status == "completed":
                html = (
                    data.get("content")
                    or data.get("html")
                    or data.get("result")
                    or ""
                )
                if visible:
                    print(html)
                else:
                    print(html[:500])
                return html
            if status == "failed":
                raise RuntimeError(f"Task {task_id} failed")
        except Exception as exc:
            print(f"❌ {exc}")
            raise
        time.sleep(5)

def parse_html(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    name_el = soup.find("h1") or soup.select_one("div.result-name")
    name = name_el.get_text(strip=True) if name_el else ""
    addr = ""
    for card in soup.select("div.card"):
        if "Current Address" in card.get_text():
            addr = card.get_text(strip=True)
            break
    phones = _parse_phones(soup.get_text(" "))
    phone_str = "; ".join(phones)
    status = "Success" if any([name, addr, phone_str]) else "No Results"
    return {
        "Owner Name": name,
        "Owner Address": addr,
        "Phone Numbers": phone_str,
        "Status": status,
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Skip tracer using Decodo's asynchronous API")
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=120,
        help="Timeout in seconds for HTTP requests",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Print the entire HTML response instead of just a snippet",
    )
    args = parser.parse_args()

    df = pd.read_csv("input.csv")
    results = []
    for _, row in df.iterrows():
        full_addr = f"{row['Address']}, {row['City']}, {row['StateZip']}"
        try:
            task_id = create_task(full_addr, timeout=args.request_timeout)
            html = poll_task(
                task_id,
                timeout=args.request_timeout,
                visible=args.visible,
            )
            data = parse_html(html)
        except Exception as exc:
            data = {
                "Owner Name": "",
                "Owner Address": "",
                "Phone Numbers": "",
                "Status": f"Error: {exc}",
            }
        data["Input Address"] = full_addr
        print(f"📍 Input: {full_addr}")
        print(f"📄 Name: {data.get('Owner Name')}")
        print(f"🏠 Address: {data.get('Owner Address')}")
        print(f"📞 Phones: {data.get('Phone Numbers')}")
        print(f"📌 Status: {data.get('Status')}")
        results.append(data)

    pd.DataFrame(results).to_csv("output.csv", index=False)

if __name__ == "__main__":
    main()
