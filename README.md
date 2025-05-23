# freedom-skiptracer

This project provides a simple skip tracing tool powered by Decodo's Web Scraper API. It reads property addresses from `input.csv`, scrapes TruePeopleSearch with JavaScript rendering, and writes the first result to `output.csv`.

## Installation

Install the dependencies with pip:

```bash
pip install -r requirements.txt
```

Create a `.env` file containing your Decodo credentials:

```bash
DECODO_USERNAME=U0000272288
DECODO_PASSWORD=PW_1afbd74549ff7a4df66653256a992f20b
```

## Usage

Populate `input.csv` with a single column named `Address` and run:

```bash
python skiptracer.py [--request-timeout SECONDS]
```
Running this command generates an `output.csv` file in the same directory. The
script writes the scraped name, address, and phone number for each row to this
file, overwriting any existing content.
Use `--request-timeout` to change the HTTP timeout, which defaults to 60 seconds.

## Output Format

Each row in `output.csv` contains:

- Input Address
- Result Name
- Result Address
- Phone Number
- Status

Only publicly available information is queried and returned.

