# freedom-skiptracer

This project provides a simple skip tracing utility that searches free public data
sources for phone numbers associated with a property address. It uses
Playwright with a headless Chromium browser to better mimic real browsers and
avoid simple anti-bot protections.

## Installation

Install the dependencies with pip:

```bash
pip install -r requirements.txt
Usage

python skiptracer.py "709 W High St, Portland, IN"
Optional flags:
--debug
Save the last HTML response to logs/debug_last.html
--visible
Launch the browser in non-headless mode
--proxy URL
Launch the browser using a proxy (e.g., http://user:pass@host:port)
Use --debug to print verbose logs and save the last HTML response to logs/debug_last.html when a request fails or is blocked.

Output Format

The script will attempt to look up matches on TruePeopleSearch.com and FastPeopleSearch.com and output a list of potential matches in the form:

[
  {
    "name": "John D Smith",
    "phones": ["+1 (260) 555-1234"],
    "city_state": "Portland, IN",
    "source": "TruePeopleSearch"
  }
]
Only publicly available information is queried and returned.


---

### 🧠 After that:

1. Save the file.
2. In your terminal (still inside `freedom-skiptracer` folder), run:

```bash
git add README.md
git commit -m "Resolve merge conflict in README"