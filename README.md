# freedom-skiptracer

This project provides a simple skip tracing utility that searches free public data sources for phone numbers associated with a property address.

## Installation

Install the dependencies with pip:

```
pip install -r requirements.txt
```

## Usage

```
python skiptracer.py "709 W High St, Portland, IN"
```

Optional flags:

- `--debug`   Save the last HTML response to `logs/debug_last.html`
- `--visible` Launch the browser in non-headless mode
- `--proxy`   Use the given proxy server (e.g. `http://user:pass@host:port`)

The script will attempt to look up matches on **TruePeopleSearch.com** and **FastPeopleSearch.com** and output a list of potential matches in the form:

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
