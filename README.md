# Kleinanzeigen Deal Finder

A single-user vehicle market-data collector for saved Kleinanzeigen Germany
searches. It scrapes listings, preserves current and historical observations in
SQLite, and produces exploratory ranking CSVs for manual review.

# Runtime Architecture

The application runs continuously on a small VPS.

The scraper itself is not a long-running daemon. Instead, a systemd timer starts a one-shot scraper process once per hour.

```text
                 VPS
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
 systemd timer        Streamlit service
   every hour               │
        │                   │
        ▼                   │
car-deal-finder.service     │
        │                   │
        ▼                   │
   Python scraper           │
        │                   │
        ▼                   │
   Kleinanzeigen            │
        │                   │
        ▼                   │
      SQLite ◄──────────────┘
        │
        ▼
Historical listings,
observations and analytics
        │
        ▼
   User browser
```

## Scraper lifecycle

The scheduled collection pipeline is:

```text
systemd timer
    ↓
car-deal-finder.service
    ↓
Python scraper
    ↓
Kleinanzeigen search pages
    ↓
new / stale listing selection
    ↓
detail or status requests
    ↓
normalize + validate
    ↓
SQLite persistence
    ↓
process exits
```

The systemd timer starts a new run once per hour. The application-level process lock prevents accidental overlapping scraper executions.

## Dashboard lifecycle

The dashboard runs separately as a persistent Streamlit service:

```text
Browser
   ↓
Streamlit dashboard
   ↓
read-only SQLite queries
   ↓
listings + history + analytics
```

The scraper writes market data to SQLite while the dashboard reads the same database.

The first dashboard version is intended to remain read-only so it does not interfere with scraper state.

## Operational model

This design allows the system to continue operating when:

* the developer laptop is turned off
* no SSH connection is open
* no tmux session exists
* the VPS is rebooted

After reboot, the persistent systemd timer is restored automatically and scheduled scraping resumes.

# How Valuation and Opportunity Scoring Work

The analytics pipeline estimates how attractive a listing appears relative to
the observed Kleinanzeigen asking market:

```text
listing
→ validation / eligibility
→ comparable selection
→ similarity weighting
→ weighted-median asking-market estimate
→ valuation confidence
→ market gap / discount
→ Opportunity Score v2.1
```

Estimated market value is derived from advertised asking prices. It is not a
final transaction price. Opportunity Score is a sourcing heuristic, not a
probability, expected profit, ROI, or purchase recommendation.

## Valuation eligibility

Every target and candidate receives one canonical status:

```text
ELIGIBLE            clean enough for valuation and comparable use
ELIGIBLE_WITH_RISK  may be valued, but receives an explicit risk adjustment
INELIGIBLE          excluded from valuation
```

The versioned semantic vocabulary in `config/valuation_vocabulary.yaml` covers
concepts such as leasing takeover, parts-only listings, severe mechanical
damage, project or scrap vehicles, accident indications, and missing TÜV. The
configuration is the source of vocabulary, rule class, action, and reason; the
Python implementation owns text normalization, matching, negation handling,
and hard-rule precedence. The README intentionally does not duplicate the full
term list because that vocabulary evolves independently.

Eligibility also validates core price, mileage, registration, and transmission
data. Derived conditions such as placeholder prices, extreme mileage, and
suspiciously low prices participate in the same canonical result.

## Generic vehicle semantics

Title-derived vehicle semantics are generic and brand-independent. The current
body-style classes are:

```text
WAGON
SEDAN
COUPE
CONVERTIBLE
HATCHBACK
SUV
VAN
UNKNOWN
```

The extractor also recognizes drivetrain evidence such as `AWD` and `RWD`, but
drivetrain is currently not used by comparable filtering or Opportunity Score.
There is no BMW chassis-code or brand-specific generation inference. When the
persisted title does not provide clear evidence—or provides conflicting
evidence—`UNKNOWN` is intentional and preferred over guessing. The versioned
terms live in `config/vehicle_semantics.yaml`.

## Comparable selection

Comparable Engine v3 requires candidates to be:

- active;
- canonically `ELIGIBLE` (risk-flagged candidates are not used as comparables);
- in the same normalized transmission group;
- within three registration years by default;
- within 100,000 km by default; and
- compatible under the body-style guardrails.

The default engine retains at most 20 highest-ranked comparables and requires
at least five for an available estimate. Body-style compatibility is explicit:

```text
known + same known      → allowed
known + different known → excluded
known + UNKNOWN         → allowed with penalty
UNKNOWN + known         → allowed with penalty
UNKNOWN + UNKNOWN       → allowed with penalty
```

Drivetrain is currently ignored by comparable selection.

## Similarity weight

Year proximity contributes:

```text
year_weight =
    1 / (1 + year_distance)
```

Mileage proximity contributes:

```text
mileage_weight =
    1 / (1 + mileage_distance_km / 50000)
```

The body-style factor is:

```text
1.00 → same known body style
0.75 → exactly one side UNKNOWN
0.65 → both UNKNOWN
0.00 → known mismatch
```

The final weight is:

```text
similarity_weight =
    year_weight
    × mileage_weight
    × body_style_factor
```

A larger value represents a more similar comparable. Candidates are ordered
deterministically by descending similarity weight, then year distance, mileage
distance, and listing ID.

## Estimated asking-market price

The estimator does not use an arithmetic mean. It uses the
similarity-weighted median asking price:

```text
estimated_market_price =
    similarity-weighted median asking price
```

The algorithm is:

1. Keep valid comparable asking prices with positive weights.
2. Sort the comparables by price ascending.
3. Sum their similarity weights.
4. Calculate 50% of the total weight.
5. Walk cumulative weight in ascending price order.
6. Use the first asking price that reaches the 50% threshold.

This is less sensitive than a mean to isolated extreme asking prices, while
still giving more influence to the most similar vehicles.

## Valuation confidence

Confidence depends on comparable coverage and consistency, not comparable count
alone. A strong comparable has:

```text
similarity_weight >= 0.5
```

The current thresholds are:

```text
HIGH:
comparable_count >= 10
strong_comparable_count >= 3
total_similarity_weight >= 5.0
dispersion <= 0.20

MEDIUM:
comparable_count >= 5
strong_comparable_count >= 1
total_similarity_weight >= 2.0
dispersion <= 0.35

LOW:
an estimate exists, but the HIGH and MEDIUM conditions are not met

UNAVAILABLE:
no usable valuation exists
```

Price dispersion is:

```text
dispersion =
    (Q3 - Q1) / unweighted_median_price
```

It describes the interquartile spread of comparable asking prices relative to
their unweighted median. Lower dispersion indicates a tighter comparable-price
cluster.

## Economic opportunity metrics

For an available valuation:

```text
market_gap_eur =
    estimated_market_price - asking_price

discount_percent =
    market_gap_eur
    / estimated_market_price
    × 100
```

The UI-facing sign convention is:

```text
positive → below estimated asking market
zero     → at estimated asking market
negative → above estimated asking market
```

For example, an €8,000 asking price against a €10,000 estimate produces a
+€2,000 market gap and a +20% discount.

Market gap is not profit. It excludes repairs, taxes, registration, transport,
negotiation, financing, dealer costs, and the realized resale price.

## Opportunity Score v2.1

Opportunity Score is a bounded 0–100 sourcing heuristic. Its direct inputs are
discount percentage, asking-market gap, valuation confidence, and canonical
valuation risk/eligibility.

It does **not** directly use views, freshness, listing age, drivetrain, year, or
mileage. Year and mileage already influence the valuation through comparable
selection; adding them directly to the score would count the same evidence
twice.

The discount component uses piecewise-linear interpolation between these
points and is bounded to 0–100:

| Discount | Component |
| -------: | --------: |
| <= -15% | 0 |
| 0% | 40 |
| +10% | 58 |
| +20% | 72 |
| +30% | 84 |
| +45% | 94 |
| >= +60% | 100 |

The asking-market-gap component uses the same bounded interpolation approach:

| Asking-market gap | Component |
| ----------------: | --------: |
| <= €0 | 0 |
| €500 | 20 |
| €1,000 | 35 |
| €2,000 | 55 |
| €3,000 | 68 |
| €5,000 | 82 |
| €8,000 | 92 |
| >= €12,000 | 100 |

The two components form the base score:

```text
base_opportunity =
    0.70 × discount_component
    + 0.30 × margin_component
```

Confidence multipliers are:

```text
HIGH        → 1.00
MEDIUM      → 0.85
LOW         → 0.65
UNAVAILABLE → no score
```

Eligibility-risk behavior is:

```text
ELIGIBLE           → 1.00
ELIGIBLE_WITH_RISK → 0.60
INELIGIBLE         → no score
```

The final calculation is:

```text
opportunity_score =
    clamp(
        base_opportunity
        × confidence_multiplier
        × risk_multiplier,
        0,
        100
    )
```

## Worked example

```text
Asking price:           €12,000
Estimated market price: €15,000
Market gap:             +€3,000
Discount:               +20%
Confidence:             HIGH
Eligibility:            ELIGIBLE

discount_component = 72
margin_component   = 68

base =
    0.70 × 72
    + 0.30 × 68
    = 70.8

final score =
    70.8 × 1.00 × 1.00
    = 70.8
```

## Comparable count and statistical context

The dashboard exposes comparable count because the estimate should be reviewed
with its evidence. For example:

```text
Estimated Market:   €18,000
Confidence:         HIGH
Comparables:        20
Strong Comparables: 8
```

This is more informative than the estimate alone. Review `Comparable Count`,
`Strong Comparable Count`, `Valuation Confidence`, and `Price Dispersion`
together; comparable count by itself does not determine confidence.

## Current limitations

- Observed asking prices are not realized transaction prices.
- Sparse titles may produce `UNKNOWN` body style.
- Body style is title-derived and may be absent or ambiguous.
- Equipment and trim are not fully modeled.
- Brand-specific generations are not modeled.
- Drivetrain is currently not used in valuation.
- Repair costs are not modeled.
- Vehicle condition may be omitted from the listing title and description.
- `INACTIVE` does not necessarily mean `SOLD`.
- Valuations and scores are computed dynamically and are not persisted.

## Dashboard analytics performance

The dashboard prepares one in-memory comparable universe per source snapshot:

```text
load once
→ normalize / classify / extract semantics once
→ reuse across target valuations
```

On one measurement with approximately 500 active listings, an uncached
analytics build took about 7.7 seconds and a cached reload about 0.003 seconds.
These timings are observations, not guarantees. Streamlit caches the dashboard
dataset and invalidates it using source-data freshness signals.


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

NOW
 ↓
1. Eligibility / risk flags
 ↓
2. Comparable Engine v2
 ↓
3. Estimated Market Price
 ↓
4. Margin + Discount + Opportunity
 ↓
5. Score snapshots/versioning
 ↓
6. Survival tracking/backtest
 ↓
7. Liquidity
 ↓
8. Urgency
 ↓
9. Dashboard v2
 ↓
10. ML calibration
