# freedom-skiptracer

This project provides a simple skip tracing utility that searches free public data
sources for phone numbers associated with a property address. It uses
Playwright with a headless Chromium browser to better mimic real browsers and
avoid simple anti-bot protections.

## Usage


python skiptracer.py "709 W High St, Portland, IN"
Optional flags:
--visible        # show the browser instead of running headless
--proxy URL      # launch the browser using a proxy
--debug          # save the last fetched HTML to logs/debug_last.html
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

✅ After pasting this:
1. Click **“Mark as resolved”**
2. Click **“Commit merge”**

Let me know if you want the updated `requirements.txt` or `skiptracer.py` next — you’re resolving this repo like a pro engineer.