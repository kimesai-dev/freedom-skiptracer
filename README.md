# freedom-skiptracer

This project provides a simple skip tracing utility that searches free public data
sources for phone numbers associated with a property address. It uses
Playwright with a headless Chromium browser to better mimic real browsers and
avoid simple anti-bot protections.

## Usage

```bash
pip install -r requirements.txt
python skiptracer.py "709 W High St, Portland, IN" --debug
Use --debug to print verbose logs and save the last HTML response to
logs/debug_last.html when a request fails or is blocked.

The script will attempt to look up matches on TruePeopleSearch.com and
FastPeopleSearch.com and output a list of potential matches in the form:

[
  {
    "name": "John D Smith",
    "phones": ["+1 (260) 555-1234"],
    "city_state": "Portland, IN",
    "source": "TruePeopleSearch"
  },
  ...
]
Only publicly available information is queried and returned.


---

### ✅ `requirements.txt` (Final Version)

playwright
beautifulsoup4
requests


> Note: After pulling this, you should run:
> ```bash
> pip install -r requirements.txt
> playwright install
> ```

---

### ✅ `skiptracer.py` — Clean Version Summary

If Codex has already pushed the Playwright-based version, don’t re-resolve it by hand — just choose the full Codex version during conflict resolution.

But if you want to fully overwrite it manually, use this command:

```bash
git checkout --theirs skiptracer.py
Or copy-paste the full clean version from earlier (with _fetch(), debug handling, Playwright logic, etc.)