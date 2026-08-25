# Kleinanzeigen Deal Finder

A single-user vehicle market-data collector for saved Kleinanzeigen Germany
searches. It scrapes listings, preserves current and historical observations in
SQLite, and produces exploratory ranking CSVs for manual review.

## Local or Linux server setup

Python 3.10 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
playwright install chromium
```

On a typical Ubuntu or Debian server, Playwright can install Chromium and its
required operating-system packages together:

```bash
playwright install --with-deps chromium
```

The default runtime configuration launches Chromium headlessly, so no desktop
session is required.

## Configuration

Saved searches and shared runtime settings live in `config/searches.yaml`.
Runtime settings control headless mode, navigation timeout, page-settle delay,
polite detail-request delay, and bounded retry/backoff behavior.

## Run the scraper

```bash
python main.py --list-searches
python main.py
python main.py --search bmw_320d_nrw
```

All application paths are resolved from the project directory, not the current
working directory. It is therefore safe to invoke `main.py` by absolute path
from cron, systemd, or another directory.

## Check known active listings

Check every listing currently marked active:

```bash
python check_active.py
```

Limit a debugging run without editing source:

```bash
python check_active.py --limit 20
```

## Analytics

```bash
python -m analytics.deal_score
```

## Logging and locking

Operational logs go to the console and `logs/car_deal_finder.log`. The file
rotates at 5 MiB and keeps three backups. A project-local `fcntl` lock prevents
the scraper and active checker from running concurrently.

## Tests

The test suite is fully offline:

```bash
python -m unittest discover -s tests -v
```
