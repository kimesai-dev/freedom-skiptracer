# freedom-skiptracer

This project provides a simple skip tracing tool powered by Decodo's Web Scraper API. It reads property addresses from `input.csv` and submits each one to Decodo as an asynchronous task that drives TruePeopleSearch with browser automation. The returned HTML is parsed for contact details and written to `output.csv`.

## Installation

Install the dependencies with pip:

```bash
pip install -r requirements.txt
```

Create a `.env` file containing your Decodo credentials:

```bash
DECODO_USERNAME=<your username>
DECODO_PASSWORD=<your password>
```

## Usage

Populate `input.csv` with three columns named `Address`, `City` and
`StateZip`. Each row is combined into a single search string in the form:

```
<Address>, <City>, <StateZip>
```

Run the script with:

```bash
python skiptracer.py [--request-timeout SECONDS] [--visible]
```
Running this command generates an `output.csv` file in the same directory. The
script writes the scraped owner name, address, and phone numbers for each row to this
file, overwriting any existing content. Use `--request-timeout` to change the HTTP timeout, which defaults to 120 seconds. Add `--visible` to print the full HTML response instead of only a snippet during scraping.

### Decodo API Request

The scraper sends a POST request to Decodo for each address using a payload similar to:

```json
{
  "url": "https://www.truepeoplesearch.com/results?name=&citystatezip=IN+47371",
  "headless": "html",
  "http_method": "GET",
  "geo": "US",
  "locale": "en-US",
  "session_id": "tsp-session-1",
  "wait_for": "networkidle",
  "render_wait_time_ms": 6000
}
```
Requests use HTTP basic authentication with the credentials from your `.env` file. Each
task is polled until completion using `GET /v2/task/{id}/results`.

Example command with a custom timeout:

```bash
python skiptracer.py --request-timeout 30 --visible
```

## Output Format

Each row in `output.csv` contains:

- Input Address
- Owner Name
- Owner Address
- Phone Numbers
- Status

Only publicly available information is queried and returned.

