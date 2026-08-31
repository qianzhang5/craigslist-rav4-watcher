# Craigslist RAV4 Watcher

Created: 2026-08-31

Watches Craigslist daily for a specific search and appends any new matching
listings to [`log.md`](log.md):

- **Vehicle:** 2018 Toyota RAV4
- **Seller type:** by owner only
- **Price range:** $14,000–$20,000
- **Areas:** Los Angeles + Orange County (`losangeles.craigslist.org` and
  `orangecounty.craigslist.org`, category `cto` = cars & trucks by owner)
- **Recency filter:** only listings posted within the last 21 days are
  considered "active"; older ones are ignored even if still live

## How it works

Craigslist's classic RSS search feeds are blocked for automated requests
(`&format=rss` returns an HTTP 403 "blocked" page), and the plain HTML search
page no longer contains listings server-side — results are rendered
client-side by JavaScript after the page loads. Because of that,
`scripts/check_rav4.py` uses [Playwright](https://playwright.dev/python/) to
drive a real headless Chromium browser, load the search page exactly as a
normal browser would, and read the rendered listing cards out of the DOM.

Each run:
1. Loads both region searches with the filters above baked into the URL.
2. Parses each result card's title, price, location, URL, and posted date.
3. Drops anything older than 21 days.
4. Compares listing IDs (from the posting URL) against `state.json`, which
   remembers every listing ID already reported.
5. Appends a dated entry to `log.md` — always, even if nothing new was found,
   so the log is a complete daily record — listing any newly-seen postings.
6. Updates `state.json` with the newly-seen IDs, and prunes entries older
   than 35 days so the file doesn't grow forever.

## Running it yourself

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
python scripts/check_rav4.py
```

## Automation

This repo is checked out by a scheduled Anthropic cloud routine
(`claude.ai/code/routines`) that runs once a day. Each run:
installs the dependencies above, runs the script, and commits + pushes
`log.md` and `state.json` if they changed. Pull this repo locally
(`git pull`) any time to read the latest `log.md`.

## Adjusting the search

Edit the constants near the top of `scripts/check_rav4.py`:
`SEARCH_PARAMS` (price/year/keywords), `SEARCHES` (regions/category), and
`MAX_AGE_DAYS` (recency cutoff).
