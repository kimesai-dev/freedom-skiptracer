# freedom-skiptracer

This project provides a simple skip tracing utility that searches free public data
sources for phone numbers associated with a property address.

## Usage

```
python skiptracer.py "709 W High St, Portland, IN"
```

Use `--debug` to save the raw HTML of the last request to `logs/debug_last.html`:

```
python skiptracer.py "709 W High St, Portland, IN" --debug
```

Install dependencies with:

```
pip install -r requirements.txt
```

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
