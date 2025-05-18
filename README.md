# freedom-skiptracer

This project provides a simple skip tracing utility that searches free public data sources for phone numbers associated with a property address. It uses Playwright with a headless Chromium browser to better mimic real browsers and avoid simple anti-bot protections.

The scraper launches Chromium in a persistent context so cookies and TLS fingerprints survive across runs.

## Installation

Install the dependencies with pip:

```bash
pip install -r requirements.txt
```

## Usage

```bash
python skiptracer.py "709 W High St, Portland, IN"
```

Optional flags:

- `--debug` – Save the last HTML response to `logs/debug_last.html`
- `--visible` – Launch the browser in non-headless mode
- `--proxy url1,url2` – Rotate through proxies
- `--fast` – Include FastPeopleSearch (may trigger bot checks)
- `--save` – Write results to `results.json`
- `--inspect` – Print raw card data before parsing

Use `--debug` to print verbose logs and save the last HTML response when a request fails or is blocked.

## Output Format

The script looks up matches on TruePeopleSearch and optionally FastPeopleSearch and outputs a list of potential matches in the form:

```
[
  {
    "name": "John D Smith",
    "phones": ["+1 (260) 555-1234"],
    "city_state": "Portland, IN",
    "source": "TruePeopleSearch"
  }
]
```

Only publicly available information is queried and returned.
