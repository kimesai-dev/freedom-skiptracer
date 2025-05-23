#!/usr/bin/env python3
"""Batch skip tracer using Decodo's Web Scraper API."""

import pandas as pd

from skiptracer_helpers import scrape_address


def main() -> None:
    df = pd.read_csv("input.csv")
    results = [
        scrape_address(addr)
        for addr in df.get("Address", [])
        if isinstance(addr, str)
    ]
    pd.DataFrame(results).to_csv("output.csv", index=False)


if __name__ == "__main__":
    main()
