# Kleinanzeigen Deal Finder

A single-user vehicle market-data collector for saved Kleinanzeigen Germany
searches. It scrapes listings, preserves current and historical observations in
SQLite, and produces exploratory ranking CSVs for manual review.

## Python environment

Python 3.10 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For local development with Playwright-managed Chromium, leave
`runtime.browser_channel` unset (or set it to `null`) and install the bundled
browser separately:

```bash
playwright install chromium
```

## VPS setup with system Google Chrome

On this VPS, the scraper uses system-installed Google Chrome because downloads
of Playwright's bundled Chromium are blocked. On Debian or Ubuntu, install
Chrome from Google's package repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
  | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
  | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt-get update
sudo apt-get install -y google-chrome-stable
```

Then select that browser channel in `config/searches.yaml`:

```yaml
runtime:
  headless: true
  browser_channel: "chrome"
```

Do not run `playwright install chromium` as part of this VPS setup. Omitting
`browser_channel`, or setting it to `null` or an empty string, preserves the
Playwright-managed Chromium behavior for other environments.

## Configuration

Saved searches and shared runtime settings live in `config/searches.yaml`.
Runtime settings control headless mode, the optional browser channel,
navigation timeout, page-settle delay, polite detail-request delay, and bounded
retry/backoff behavior.

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
