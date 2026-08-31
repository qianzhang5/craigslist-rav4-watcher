"""
Daily Craigslist watcher for a specific search:
  2018 Toyota RAV4, by owner, $14,000-$20,000, Los Angeles + Orange County,
  listings no older than 3 weeks.

Run manually with:  python scripts/check_rav4.py
Requires:           pip install playwright  &&  playwright install --with-deps chromium

State is kept in state.json (which listing IDs we've already reported) so that
re-running only surfaces genuinely NEW postings. New findings (and a daily
summary even when there's nothing new) are appended to log.md.
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

# Listing titles can contain emoji; avoid crashing on consoles with a
# non-UTF-8 default encoding (e.g. Windows cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "log.md"

PACIFIC = ZoneInfo("America/Los_Angeles")
MAX_AGE_DAYS = 21

SEARCHES = {
    "losangeles": "https://losangeles.craigslist.org/search/cto",
    "orangecounty": "https://orangecounty.craigslist.org/search/cto",
}
SEARCH_PARAMS = {
    "query": "toyota rav4",
    "min_price": "14000",
    "max_price": "20000",
    "min_auto_year": "2018",
    "max_auto_year": "2018",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def build_url(base: str) -> str:
    from urllib.parse import urlencode

    return f"{base}?{urlencode(SEARCH_PARAMS)}"


def parse_posted_date(text: str, now: datetime) -> datetime:
    """Best-effort parse of Craigslist's relative/short date strings into an
    absolute datetime, anchored to `now` (Pacific time)."""
    text = text.strip().lower()

    m = re.match(r"(\d+)\s*m(in)?\s*ago", text)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    m = re.match(r"(\d+)\s*h(r)?\s*ago", text)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    m = re.match(r"(\d+)\s*d(ay)?s?\s*ago", text)
    if m:
        return now - timedelta(days=int(m.group(1)))

    if text in ("just now", "today"):
        return now

    if text == "yesterday":
        return now - timedelta(days=1)

    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        month, day, year = map(int, m.groups())
        return datetime(year, month, day, tzinfo=PACIFIC)

    m = re.match(r"(\d{1,2})/(\d{1,2})$", text)
    if m:
        month, day = map(int, m.groups())
        candidate = datetime(now.year, month, day, tzinfo=PACIFIC)
        if candidate > now + timedelta(days=1):
            candidate = candidate.replace(year=now.year - 1)
        return candidate

    # Unknown format: assume recent so we don't silently drop a listing.
    return now


def scrape_region(playwright, region: str, url: str, now: datetime) -> list[dict]:
    browser = playwright.chromium.launch()
    try:
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(url, wait_until="networkidle", timeout=30000)

        try:
            page.wait_for_selector(".cl-search-result, .no-results-title", timeout=10000)
        except Exception:
            pass

        if page.query_selector(".no-results-title") and not page.query_selector(
            ".cl-search-result"
        ):
            return []

        listings = []
        for card in page.query_selector_all(".cl-search-result"):
            link_el = card.query_selector("a.posting-title, a.cl-app-anchor")
            if not link_el:
                continue
            href = link_el.get_attribute("href") or ""
            listing_id = href.rstrip("/").split("/")[-1]
            if not listing_id:
                continue

            title_el = card.query_selector(".posting-title")
            price_el = card.query_selector(".priceinfo")
            date_el = card.query_selector(".result-posted-date, time")
            loc_el = card.query_selector(".result-location")

            posted_text = date_el.inner_text().strip() if date_el else ""
            posted_at = parse_posted_date(posted_text, now)

            listings.append(
                {
                    "id": f"{region}:{listing_id}",
                    "region": region,
                    "title": title_el.inner_text().strip() if title_el else "(no title)",
                    "price": price_el.inner_text().strip() if price_el else "?",
                    "location": loc_el.inner_text().strip() if loc_el else region,
                    "url": href,
                    "posted_text": posted_text,
                    "posted_at": posted_at.isoformat(),
                }
            )
        return listings
    finally:
        browser.close()


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def append_log(now: datetime, active: list[dict], new: list[dict]) -> None:
    lines = []
    lines.append(f"## Run: {now.strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append("")
    lines.append(
        f"Search: 2018 Toyota RAV4, by owner, $14,000-$20,000, "
        f"Los Angeles + Orange County, posted within {MAX_AGE_DAYS} days."
    )
    lines.append(f"Active matching listings seen this run: {len(active)}")
    lines.append(f"New listings since last run: {len(new)}")
    lines.append("")

    if new:
        lines.append("### New listings")
        lines.append("")
        for item in sorted(new, key=lambda x: x["posted_at"], reverse=True):
            lines.append(
                f"- **{item['price']}** — {item['title']} "
                f"({item['location']}, posted {item['posted_text']}) — {item['url']}"
            )
        lines.append("")
    else:
        lines.append("_No new listings today._")
        lines.append("")

    lines.append("---")
    lines.append("")

    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    now = datetime.now(PACIFIC)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)

    state = load_state()
    all_active: list[dict] = []
    new_items: list[dict] = []

    with sync_playwright() as p:
        for region, base_url in SEARCHES.items():
            url = build_url(base_url)
            listings = scrape_region(p, region, url, now)
            for item in listings:
                posted_at = datetime.fromisoformat(item["posted_at"])
                if posted_at < cutoff:
                    continue
                all_active.append(item)
                if item["id"] not in state:
                    new_items.append(item)
                    state[item["id"]] = {
                        "first_seen": now.isoformat(),
                        "title": item["title"],
                        "price": item["price"],
                        "url": item["url"],
                    }

    # Prune state entries older than a generous buffer so the file doesn't
    # grow forever (listings older than MAX_AGE_DAYS + 14 are dropped).
    prune_cutoff = now - timedelta(days=MAX_AGE_DAYS + 14)
    state = {
        k: v
        for k, v in state.items()
        if datetime.fromisoformat(v["first_seen"]) >= prune_cutoff
    }

    save_state(state)
    append_log(now, all_active, new_items)

    print(f"Active: {len(all_active)}, New: {len(new_items)}")
    for item in new_items:
        print(f"NEW: {item['price']} {item['title']} - {item['url']}")


if __name__ == "__main__":
    main()
