# freedom-skiptracer

This project provides a simple skip tracing tool powered by Decodo's Web Scraper API. It reads property addresses from `input.csv`, scrapes TruePeopleSearch with JavaScript rendering, and writes the first result to `output.csv`.

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

Populate `input.csv` with a single column named `Address` and run:

```bash
python skiptracer.py [--request-timeout SECONDS] [--visible] [--batch-size N]
```
Running this command generates an `output.csv` file in the same directory. The
script writes the scraped name, address, and phone number for each row to this
file, overwriting any existing content.
Use `--request-timeout` to change the HTTP timeout, which defaults to 60 seconds.
Pass `--visible` to print the full HTML returned by the scraper for each address.
Set `--batch-size` to send multiple addresses in a single request using
Decodo's batch API.

### Decodo API Request

The scraper sends a POST request to Decodo with options that match the
following JSON payload:

```json
{
  "url": "https://www.truepeoplesearch.com/results?name=&citystatezip=IN+47371",
  "headless": "html",
  "geo": "United States",
  "locale": "en-us",
  "device_type": "desktop_chrome",
  "session_id": "Skip 1",
  "headers": {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
  }
}
```
Requests use HTTP basic authentication with the credentials from your `.env` file.

### Decodo API options

The scraper normally sends a POST request to
`https://scraper-api.decodo.com/v2/scrape`. The JSON payload specifies the
target `url` and sets `headless` to `"html"` so Decodo returns the fully
rendered HTML. When `--batch-size` is greater than 1, requests are sent to
`https://scraper-api.decodo.com/v2/task/batch` with a list of tasks so multiple
addresses can be scraped in a single API call. The tool parses the returned HTML
to extract the contact information.

Example command with a custom timeout:

```bash
python skiptracer.py --request-timeout 30
```

## Output Format

Each row in `output.csv` contains:

- Input Address
- Result Name
- Result Address
- Phone Number
- Status

Only publicly available information is queried and returned.

