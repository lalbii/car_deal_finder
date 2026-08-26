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
retry/backoff behavior. They also control conservative request scheduling:

```yaml
runtime:
  detail_delay_seconds: 5
  detail_refresh_interval_hours: 6
  inactive_check_interval_hours: 24
  blocking_failure_threshold: 3
```

New listings receive an immediate detail fetch. A known listing visible in the
search results only receives another detail fetch when its latest persisted
detail observation is at least six hours old. Search visibility updates
`last_seen` without replacing detailed fields or creating a history row.

Active listings missing from a complete search run are status-checked only when
`last_checked_at` is at least 24 hours old. Missing from a search never marks a
listing inactive by itself. If search coverage is incomplete, missing-listing
status checks are deferred for that run.

Three consecutive HTTP 403/rate-limit, anti-bot challenge, or IP-block signals
open the run-level circuit breaker. A successful request or non-blocking failure
resets the consecutive count. An open breaker stops further network requests,
preserves completed writes, and is reported as `BLOCKING_SUSPECTED`.

## Run the scraper

```bash
python main.py --list-searches
python main.py
python main.py --search bmw_320d_nrw
```

All application paths are resolved from the project directory, not the current
working directory. It is therefore safe to invoke `main.py` by absolute path
from cron, systemd, or another directory.

Each invocation represents one finite scrape run. Run frequency must be managed
externally; the application does not contain a scheduler or infinite loop.

## Hourly systemd deployment

The version-controlled units in `deploy/systemd/` assume this VPS layout:

```text
Repository:          /opt/car_deal_finder
Virtual environment: /opt/car_deal_finder/.venv
Service user:        ubuntu
Saved search:        bmw_320d_nrw
```

The `ubuntu` user must be able to read the repository and virtual environment
and write the project-local `data/`, `logs/`, and lock file. The service does
not use an interactive shell, `.bashrc`, Conda activation, or environment files.
Google Chrome must already be installed on the host; systemd does not run
`playwright install chromium`.

### Install the units

From the repository:

```bash
cd /opt/car_deal_finder
sudo install -m 0644 deploy/systemd/car-deal-finder.service /etc/systemd/system/car-deal-finder.service
sudo install -m 0644 deploy/systemd/car-deal-finder.timer /etc/systemd/system/car-deal-finder.timer
sudo systemctl daemon-reload
```

Do not enable the service itself. It is a static `Type=oneshot` service that is
started by the timer or by an explicit manual command.

### First manual systemd test

Run one scrape through systemd before enabling automation:

```bash
sudo systemctl start car-deal-finder.service
sudo systemctl status car-deal-finder.service
sudo journalctl -u car-deal-finder.service --no-pager -n 100
```

A successfully completed oneshot service may appear as `inactive (dead)` after
it exits; the status and journal should show a successful result. The service
allows up to two hours for a legitimate catch-up run.

### Enable hourly automation

After the manual test succeeds:

```bash
sudo systemctl enable --now car-deal-finder.timer
```

Inspect timer state and execution times with:

```bash
sudo systemctl status car-deal-finder.timer
systemctl list-timers --all
```

`OnCalendar=hourly` runs at most once per hour. `Persistent=true` causes a
missed scheduled run to be triggered after the VPS returns. The application
lock remains the final protection against overlap with a direct/manual run.

### Monitoring and manual runs

```bash
sudo systemctl status car-deal-finder.service
sudo systemctl status car-deal-finder.timer
systemctl list-timers --all
sudo journalctl -u car-deal-finder.service --no-pager -n 100
sudo journalctl -u car-deal-finder.service -f
tail -f /opt/car_deal_finder/logs/car_deal_finder.log
```

Trigger a systemd run without waiting for the timer:

```bash
sudo systemctl start car-deal-finder.service
```

Direct CLI execution also remains available:

```bash
cd /opt/car_deal_finder
source .venv/bin/activate
python main.py --search bmw_320d_nrw
```

### Stop, disable, or re-enable automation

Stop the timer without changing its enabled-on-boot state:

```bash
sudo systemctl stop car-deal-finder.timer
```

Disable automatic execution across reboots:

```bash
sudo systemctl disable car-deal-finder.timer
```

Re-enable and start it:

```bash
sudo systemctl enable --now car-deal-finder.timer
```

### Updating the application

Stop the timer while changing application files, then update and validate using
the same virtual environment used by systemd:

```bash
sudo systemctl stop car-deal-finder.timer
cd /opt/car_deal_finder
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
sudo systemctl start car-deal-finder.service
sudo systemctl start car-deal-finder.timer
```

Application-only changes do not require `daemon-reload`. If either unit file
changed, reinstall both units before the manual test:

```bash
cd /opt/car_deal_finder
sudo install -m 0644 deploy/systemd/car-deal-finder.service /etc/systemd/system/car-deal-finder.service
sudo install -m 0644 deploy/systemd/car-deal-finder.timer /etc/systemd/system/car-deal-finder.timer
sudo systemctl daemon-reload
```

After reboot, the enabled timer returns with `timers.target`; the service starts
only when triggered, performs one run, writes to the existing SQLite database
and application log, then exits.

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
