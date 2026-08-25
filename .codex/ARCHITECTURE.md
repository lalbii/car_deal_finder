# Kleinanzeigen Deal Finder — Architecture Context

## Project Goal

This project is a personal vehicle sourcing and market-intelligence tool focused exclusively on **Kleinanzeigen Germany**.

The purpose of the system is:

> Continuously collect vehicle listings from Kleinanzeigen, build reliable historical market data, identify genuinely comparable vehicles, estimate relative market value, and surface listings that appear meaningfully underpriced or otherwise interesting for manual review.

The system is currently intended for **one user**.

It is NOT currently intended to be:

* a dealer ERP
* an inventory management system
* a CRM
* a customer-facing platform
* a multi-marketplace aggregator
* a France/Germany arbitrage system
* a vehicle sales platform

Keep the scope narrow unless explicitly instructed otherwise.

---

# Current System

The current repository already implements an early version of the following pipeline:

```text
Kleinanzeigen
    ↓
Search page scraping
    ↓
Search result parsing
    ↓
Detail page scraping
    ↓
Detail parsing
    ↓
SQLite persistence
    ├── listings
    └── listing_history
    ↓
pandas analytics
    ↓
deal ranking CSVs
    ↓
manual review
```

The current codebase is a working prototype, not a production architecture.

The goal is to improve it incrementally rather than rewrite it unnecessarily.

---

# Current Important Modules

```text
main.py
    Main scraping entry point.

check_active.py
    Existing listing-status checking entry point.

config/settings.py
    Current search configuration and title filters.

scrapers/
    Kleinanzeigen-specific data acquisition.

    kleinanzeigen_scraper.py
        Main scraping orchestration.

    kleinanzeigen_search.py
        Search URL creation and search-page retrieval.

    kleinanzeigen_detail.py
        Individual listing page retrieval.

    active_checker.py
        Re-checks known listings.

parsers/
    Kleinanzeigen HTML parsing.

    search_parser.py
        Parses listing cards from search pages.

    detail_parser.py
        Parses vehicle/listing details.

    status_parser.py
        Detects unavailable/reserved/deleted listing states.

storage/sqlite.py
    SQLite schema and persistence functions.

analytics/deal_score.py
    Current experimental opportunity-ranking logic.

utils/text.py
    Text and numeric parsing helpers.

backup/
    Historical/obsolete implementation.
    Do not use for new functionality unless explicitly requested.

data/
    Local database, cached HTML, and generated CSV artifacts.
```

---

# System Scope

The system currently has one external source:

```text
Kleinanzeigen Germany
```

Do not add abstraction for multiple marketplaces unless explicitly requested.

However, marketplace-specific HTML and scraping logic should remain separated from core analytics so that the rest of the application does not depend directly on CSS selectors or page structure.

---

# Core Pipeline

The intended near-term pipeline is:

```text
Kleinanzeigen search
        ↓
Fetch pages
        ↓
Parse raw listing data
        ↓
Normalize vehicle attributes
        ↓
Validate data
        ↓
Persist current state
        ↓
Persist historical observations
        ↓
Select comparable listings
        ↓
Estimate market position/value
        ↓
Calculate opportunity metrics
        ↓
Rank candidates
        ↓
Manual review
```

Each stage should have a clear responsibility.

---

# Domain Concepts

## Listing

A Kleinanzeigen advertisement.

Important concepts include:

```text
listing_id
url
title
location
asking_price
posted_date
first_seen
last_seen
last_checked_at
status
```

A listing represents an advertisement, not necessarily a unique physical vehicle.

---

## Vehicle Attributes

Vehicle-related data extracted from a listing.

Important normalized attributes may include:

```text
make
model
generation
body_type
engine
fuel
power
transmission
first_registration
mileage_km
trim
```

Only add attributes when they can be extracted or inferred with acceptable reliability.

Do not silently invent missing vehicle information.

---

## Listing Observation

A historical snapshot of a listing.

Examples:

```text
listing_id
scraped_at
asking_price
mileage_km
view_count
status
```

Historical observations are important because the project should eventually understand:

* price changes
* listing age
* listing activity
* market velocity
* seller behavior
* how quickly attractive listings disappear

Preserve historical data whenever possible.

---

# Current Source of Truth

The current operational source of truth is:

```text
data/listings.db
```

SQLite is appropriate for the current stage of the project.

CSV files are exports and analysis artifacts.

They should NOT become the main application state.

---

# Data Quality

Data quality is one of the highest priorities.

Bad data must not silently influence valuation or ranking.

Examples of suspicious data:

```text
price <= 0

implausibly low vehicle price

implausibly high vehicle price

implausibly low mileage

implausibly high mileage

invalid registration date

missing required vehicle identity fields

unrecognized transmission/fuel values

unexpected parser output
```

When possible, distinguish between:

```text
valid
suspect
invalid
missing
```

Do not automatically replace suspicious values with zero.

Do not silently treat parsing failure as legitimate missing vehicle data.

---

# Normalization

Raw Kleinanzeigen text should gradually be converted into consistent canonical values.

Examples:

```text
"Automatik"
"Automatikgetriebe"
"automatic"

→ AUTOMATIC
```

Similarly for:

```text
fuel
body type
make
model
engine
power
registration date
mileage
```

Normalization must happen before comparable selection.

Avoid performing meaningful valuation directly on inconsistent raw strings.

---

# Listing Lifecycle

Marketplace listing state and scraper failure are different concepts.

The application should eventually use a consistent status model such as:

```text
ACTIVE
INACTIVE
UNKNOWN
```

Rules:

* HTTP/network failure does NOT automatically mean inactive.
* Parser failure does NOT automatically mean inactive.
* Listing disappearance should be confirmed reliably.
* Reactivated/reposted listings must be handled consistently.
* There should be one canonical implementation of listing-status interpretation.

Avoid multiple conflicting definitions across modules.

---

# Comparable Selection

This is one of the most important components of the project.

The goal is:

> Compare a listing against vehicles that a real buyer would reasonably consider equivalent.

The existing broad grouping by year band and transmission is only an exploratory baseline.

Comparable selection should gradually consider relevant attributes such as:

```text
make
model
generation
engine
fuel
power
body type
transmission
registration year
mileage
trim
```

Not every attribute must always be mandatory.

The comparison algorithm may use:

* exact matching
* acceptable ranges
* weighted similarity
* hierarchical fallback groups

The system should explicitly track comparable quality.

Useful future outputs include:

```text
comparable_count
comparison_confidence
median_price
median_mileage
price_percentile
estimated_market_value
```

Never claim high confidence from a very small or poor comparable group.

---

# Market Value

The current project does not know true transaction prices.

Therefore:

> The system estimates market asking value, not confirmed sale value.

This distinction must remain explicit.

Do not label Kleinanzeigen asking-price statistics as actual realized sale prices.

Possible future metrics:

```text
estimated_market_asking_value
lower_market_range
upper_market_range
confidence
```

These estimates should be based only on sufficiently valid and comparable listings.

---

# Opportunity Evaluation

The goal of the ranking layer is:

> Surface listings that appear attractive relative to their relevant Kleinanzeigen market.

Possible opportunity signals include:

```text
asking price discount
mileage advantage
listing freshness
view activity
price reduction history
listing age
comparable confidence
market rarity
```

The current `deal_score` is an experimental heuristic.

Its current meaning is approximately:

```text
cheap
+
lower mileage
+
fresh
+
relatively few views
```

It must NOT be treated as:

```text
profit
ROI
guaranteed market value
buy recommendation
```

unless the methodology is explicitly changed.

---

# Opportunity Output

A useful future candidate result might look conceptually like:

```text
BMW 320d Touring
2017
Automatic
145,000 km

Asking price:             €12,300
Comparable median:        €14,100
Estimated discount:       12.8%
Comparable count:         34
Valuation confidence:     HIGH
Listing age:              2 days
Price changes:            none

Opportunity score:        82 / 100
```

The purpose is to help manual decision-making.

The application is not expected to automatically purchase or contact sellers.

---

# Scraper Responsibilities

Scrapers should handle:

```text
navigation
fetching
HTTP/browser state
raw HTML retrieval
```

They should NOT contain:

```text
valuation logic
deal ranking
business decisions
market statistics
```

Preferred conceptual flow:

```text
fetch
→ parse
→ normalize
→ validate
→ persist
```

---

# Parser Responsibilities

Parsers should transform Kleinanzeigen HTML into structured raw data.

They should:

* detect unexpected layouts
* make extraction failures observable
* avoid silently returning believable but incorrect values
* be testable against cached HTML

Live-site scraping should not be required to test parser correctness.

---

# Storage Responsibilities

The storage layer should only handle persistence.

It should not contain:

* HTML parsing
* scraping logic
* valuation formulas
* ranking formulas

As the schema evolves:

* preserve history
* add indexes where useful
* introduce schema migrations
* avoid destructive schema resets
* use constraints where they improve data integrity

---

# Analytics Responsibilities

Analytics should operate on validated, normalized persisted data.

Current pandas scripts are acceptable for exploration.

Core logic that becomes important to the system should gradually become explicit tested functions rather than existing only inside ad-hoc DataFrame transformations.

---

# Configuration

The current hard-coded BMW 320d / NRW search should gradually become configurable.

Near-term configuration may include:

```text
query
region
max_pages
headless
search filters
```

Later, saved searches may contain:

```text
make
model
region
price range
year range
mileage range
fuel
transmission
```

Do not build an unnecessarily complex configuration framework yet.

---

# Testing Priorities

Testing should focus first on the highest-risk areas:

```text
1. search-page parsing
2. detail-page parsing
3. numeric parsing
4. normalization
5. data validation
6. listing lifecycle
7. comparable selection
8. valuation
9. opportunity scoring
```

Prefer cached real HTML fixtures for parser regression tests.

---

# Reliability Priorities

Current risks in priority order:

```text
1. Incorrect parsing
2. Invalid data entering analytics
3. Weak vehicle normalization
4. Poor comparable selection
5. Listing lifecycle errors
6. Lack of regression tests
7. Hard-coded runtime configuration
8. Lack of retry/error classification
9. Database schema evolution
10. Scraping performance
```

Correctness is more important than scraping speed.

---

# Current Development Direction

Work should proceed incrementally.

Preferred sequence:

```text
PHASE 1
Data quality and parser reliability

PHASE 2
Vehicle normalization

PHASE 3
Reliable listing lifecycle/history

PHASE 4
Comparable selection

PHASE 5
Market valuation

PHASE 6
Opportunity ranking

PHASE 7
Monitoring/alerts and usability improvements
```

Do not jump directly into UI, APIs, distributed systems, or complex infrastructure.

---

# Engineering Rules for Codex

When working in this repository:

1. Inspect existing behavior before changing it.

2. Do not rewrite working code unnecessarily.

3. Prefer small, reviewable changes.

4. Preserve existing database/history data.

5. Do not modify `backup/` unless explicitly requested.

6. Keep Kleinanzeigen HTML-specific logic inside scraper/parser boundaries.

7. Keep analytics independent from Playwright and HTML.

8. Do not allow obviously invalid values to influence analytics.

9. Do not treat scraper failure as listing inactivity.

10. Do not treat asking price as actual sale price.

11. Do not treat the existing `deal_score` as profitability.

12. Prefer explicit typed structures at important module boundaries.

13. Add tests when changing parsing, normalization, lifecycle, or analytics behavior.

14. Avoid unrelated refactors.

15. Avoid premature architecture and unnecessary infrastructure.

16. Before making a significant architectural change, explain:

    * why it is necessary
    * current behavior
    * proposed behavior
    * files affected
    * database impact
    * compatibility risks

17. New functionality should serve the core goal:

> Find better vehicle opportunities on Kleinanzeigen using trustworthy market data.

---

# Immediate Goal

The immediate goal is NOT to add more features.

The immediate goal is to make the existing data trustworthy enough to build valuation on top of it.

The next desired pipeline is:

```text
Kleinanzeigen
    ↓
Reliable scraper
    ↓
Reliable parsers
    ↓
Validated data
    ↓
Normalized vehicle attributes
    ↓
Historical SQLite dataset
```

Only after this foundation is reliable should we build a stronger comparable and valuation system.
