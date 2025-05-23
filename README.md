# freedom-skiptracer

This project provides a simple skip tracing utility that searches free public data sources for phone numbers associated with a property address. It uses Playwright with a headless Chromium browser to better mimic real browsers and avoid simple anti-bot protections.

## Installation

Install the dependencies with pip:

```bash
pip install -r requirements.txt
```

Set your 2Captcha API key in the environment so CAPTCHA challenges can be solved automatically:

```bash
export 2CAPTCHA_API_KEY=YOUR_KEY
```

## Usage


```bash
python skiptracer.py "709 W High St, Portland, IN"
```

Optional flags:

- `--debug` – Save the last HTML response to `logs/debug_last.html`
- `--visible` – Launch the browser in non-headless mode
- `--proxy URL` – Launch the browser using a proxy. By default the script
  uses a Decodo residential proxy configured in `skiptracer.py`.
- `--fast` – Include FastPeopleSearch (may trigger bot checks)
- `--save` – Write results to `results.json`
- `--cookie-store PATH` – Persist session cookies across runs
- `--parallel [N]` – Run N browser contexts in parallel using separate proxies. If N is omitted, 5 contexts are used by default.

Use `--debug` to print verbose logs and save the last HTML response when a request fails or is blocked.

When running with `--parallel`, multiple browser contexts use separate proxies simultaneously. Each proxy's success rate and failures are logged so poor performers can be cooled down automatically.

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

## Batch scraping with the Decodo API

The `decodo_batch_scraper.py` script reads addresses from `input.csv` and writes the first
TruePeopleSearch result to `output.csv`. Create a `.env` file containing your
Decodo credentials:

```bash
DECODO_USERNAME=U0000272288
DECODO_PASSWORD=PW_1afbd74549ff7a4df66653256a992f20b
```

Run the scraper with:

```bash
python decodo_batch_scraper.py
```
