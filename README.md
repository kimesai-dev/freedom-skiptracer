# freedom-skiptracer

This project provides a simple skip tracing utility that searches free public data
sources for phone numbers associated with a property address.

## Installation

```
pip install -r requirements.txt
```

## Usage

```
python skiptracer.py "709 W High St, Portland, IN"
```

Add `--debug` to print verbose scraping information and save the raw HTML
response to `logs/debug_last.html` when no cards are found.

The script will attempt to look up matches on **TruePeopleSearch.com** and
**FastPeopleSearch.com** and output a list of potential matches in the form:

```
[
  {
    "name": "John D Smith",
    "phones": ["+1 (260) 555-1234"],
    "city_state": "Portland, IN",
    "source": "TruePeopleSearch"
  },
  ...
]
```

Only publicly available information is queried and returned.
