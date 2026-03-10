"""
scraper_stepstone.py – Scrape StepStone Germany (stepstone.de).

Uses Playwright (headless Chromium).  StepStone is more scraping-friendly
than LinkedIn and does not require a login.

Search URL template:
  https://www.stepstone.de/jobs/<ENCODED_QUERY>/in-deutschland
  ?sort=2&datePosted=1&page=<PAGE>

sort=2       → most recent first
datePosted=1 → posted in the last 24 hours
"""

import logging
import urllib.parse
from typing import Optional

from playwright.sync_api import Browser, Page, sync_playwright, TimeoutError as PWTimeoutError

from config import (
    MAX_DELAY,
    MAX_DETAIL_PAGES_PER_QUERY,
    MAX_PAGES_PER_QUERY,
    MAX_RETRIES,
    MIN_DELAY,
    PAGE_TIMEOUT,
    SEARCH_COUNTRY,
    STEPSTONE_COUNTRY_DOMAINS,
    STEPSTONE_SEARCH_QUERIES,
)
from utils import (
    extract_summary,
    generate_job_id,
    get_random_user_agent,
    is_posted_within_24h,
    is_relevant_title,
    random_delay,
)

logger = logging.getLogger("job_agent")

_BASE_URL = "https://{domain}/jobs/{query}/{location_path}?sort=2&datePosted=1&page={page}"


def _get_stepstone_domain() -> Optional[tuple[str, str]]:
    """Return (domain, location_path) for SEARCH_COUNTRY, or None if unsupported."""
    entry = STEPSTONE_COUNTRY_DOMAINS.get(SEARCH_COUNTRY)
    if entry is None:
        logger.warning(
            "StepStone: country '%s' is not supported. "
            "Supported: %s. Skipping StepStone scrape.",
            SEARCH_COUNTRY,
            ", ".join(STEPSTONE_COUNTRY_DOMAINS),
        )
    return entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _navigate_with_retry(page: Page, url: str, retries: int = MAX_RETRIES) -> bool:
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            return True
        except PWTimeoutError:
            logger.warning("StepStone timeout (attempt %d/%d): %s", attempt, retries, url)
            random_delay(2, 4)
        except Exception as exc:
            logger.warning("StepStone nav error (attempt %d/%d): %s – %s", attempt, retries, url, exc)
            random_delay(2, 4)
    return False


def _accept_cookies(page: Page) -> None:
    """Dismiss cookie banners if present (first visit only)."""
    for selector in [
        "button#ccmgt_explicit_accept",
        "button[data-genesis-element='ACCEPT_ALL']",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Accept all')",
        "[id*='accept'][class*='cookie']",
    ]:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click(timeout=3000)
                logger.debug("StepStone: cookie banner dismissed.")
                random_delay(0.5, 1.5)
                return
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Job-card extraction
# ---------------------------------------------------------------------------

def _extract_job_cards(page: Page, domain: str) -> list[dict]:
    jobs: list[dict] = []

    # StepStone renders job cards as <article> elements
    cards = page.query_selector_all("article[data-at='job-item']")
    if not cards:
        # Fallback: any article with class containing 'job'
        cards = page.query_selector_all("article[class*='job']")
    if not cards:
        cards = page.query_selector_all("li[class*='ResultList']")

    logger.debug("StepStone: found %d cards.", len(cards))

    for card in cards:
        try:
            # Title
            title_el = card.query_selector(
                "h2[data-at='job-item-title'], "
                "span[data-at='job-item-title'], "
                "a[data-at='job-item-title']"
            )
            title = title_el.inner_text().strip() if title_el else ""

            # Company
            company_el = card.query_selector(
                "[data-at='job-item-company-name'], "
                "span[class*='company']"
            )
            company = company_el.inner_text().strip() if company_el else ""

            # Location
            location_el = card.query_selector(
                "[data-at='job-item-location'], "
                "span[class*='location']"
            )
            location = location_el.inner_text().strip() if location_el else ""

            # URL – StepStone card links
            link_el = card.query_selector("a[href*='/stellenangebot/'], a[href*='/job/']")
            if not link_el:
                link_el = card.query_selector("a[data-at='job-item-title']")
            href = link_el.get_attribute("href") if link_el else ""
            if href and not href.startswith("http"):
                href = f"https://{domain}{href}"

            # Posting date (might be a <time> element or text)
            date_el = card.query_selector("time, [data-at='job-item-date']")
            posting_date = (
                date_el.get_attribute("datetime") or date_el.inner_text().strip()
                if date_el
                else ""
            )

            if not title or not href:
                continue

            jobs.append(
                {
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": href,
                    "posting_date": posting_date,
                    "platform": "StepStone",
                    "experience_level": "",
                    "description": "",
                    "summary": "",
                }
            )
        except Exception as exc:
            logger.debug("StepStone card parse error: %s", exc)

    return jobs


# ---------------------------------------------------------------------------
# Detail page
# ---------------------------------------------------------------------------

def _scrape_detail(page: Page, job: dict) -> dict:
    if not _navigate_with_retry(page, job["url"]):
        logger.warning("StepStone: skipping detail page: %s", job["url"])
        return job

    random_delay(MIN_DELAY, MAX_DELAY)
    _accept_cookies(page)

    desc = ""
    for sel in [
        "[data-at='job-ad-content']",       # current StepStone layout
        "[data-at='job-ad-details-body']",
        "div[class*='jobAdBody']",
        "div[class*='JobDescription']",
        "section[class*='jobad']",
        "div.job-ad-display-8mvuy0",
        "article.js-app-ld-ContentBlock",
    ]:
        try:
            el = page.query_selector(sel)
            if el:
                desc = el.inner_text().strip()
                break
        except Exception:
            pass

    # Try extracting experience level from structured data
    exp_level = ""
    for sel in [
        "[data-at='experience-requirements']",
        "span[class*='experience']",
        "li:has-text('Berufserfahrung')",
        "li:has-text('Experience')",
    ]:
        try:
            el = page.query_selector(sel)
            if el:
                exp_level = el.inner_text().strip()
                break
        except Exception:
            pass

    job["description"] = desc
    job["experience_level"] = exp_level
    job["summary"] = extract_summary(desc)
    return job


# ---------------------------------------------------------------------------
# Per-query scraper
# ---------------------------------------------------------------------------

def _scrape_query(browser: Browser, query: str, domain: str, location_path: str) -> list[dict]:
    page = browser.new_page()
    page.set_extra_http_headers({"User-Agent": get_random_user_agent()})
    results: list[dict] = []
    detail_count = 0
    limit_reached = False

    try:
        for page_num in range(1, MAX_PAGES_PER_QUERY + 1):
            if limit_reached:
                break
            encoded = urllib.parse.quote(query)
            url = _BASE_URL.format(
                domain=domain,
                query=encoded,
                location_path=location_path,
                page=page_num,
            )
            logger.info("StepStone | query='%s' | page %d", query, page_num)

            if not _navigate_with_retry(page, url):
                logger.error("StepStone: failed to load page for '%s'", query)
                break

            if page_num == 1:
                _accept_cookies(page)

            random_delay(MIN_DELAY, MAX_DELAY)

            cards = _extract_job_cards(page, domain)
            if not cards:
                logger.info("StepStone: no cards on page %d for '%s'.", page_num, query)
                break

            # StepStone URL already contains 'in-deutschland' – skip location check.
            # Discard anything posted outside the rolling age window.
            date_ok = [j for j in cards if is_posted_within_24h(j["posting_date"])]
            logger.debug(
                "StepStone: %d / %d cards pass date filter.",
                len(date_ok), len(cards),
            )

            # Title pre-filter: skip detail page if title is clearly irrelevant
            title_ok = [j for j in date_ok if is_relevant_title(j["title"])]
            logger.debug(
                "StepStone: %d / %d cards pass title pre-filter.",
                len(title_ok), len(date_ok),
            )

            for job in title_ok:
                if detail_count >= MAX_DETAIL_PAGES_PER_QUERY:
                    logger.info("Reached max detail pages (%d) for query.", detail_count)
                    limit_reached = True
                    break
                job = _scrape_detail(page, job)
                detail_count += 1

                # AI evaluator makes the final match decision in main.py
                job["job_id"] = generate_job_id(
                    job["title"], job["company"], job["location"]
                )
                results.append(job)
                logger.debug(
                    "Scraped '%s' @ %s – queued for AI evaluation.",
                    job["title"], job["company"],
                )

                random_delay(MIN_DELAY, MAX_DELAY)

    finally:
        page.close()

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape_stepstone() -> list[dict]:
    stepstone_entry = _get_stepstone_domain()
    if stepstone_entry is None:
        return []
    domain, location_path = stepstone_entry

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            for query in STEPSTONE_SEARCH_QUERIES:
                logger.info("=== StepStone scrape: %s ===", query)
                try:
                    jobs = _scrape_query(browser, query, domain, location_path)
                    for job in jobs:
                        jid = job.get("job_id", "")
                        if jid and jid not in seen_ids:
                            seen_ids.add(jid)
                            all_jobs.append(job)
                except Exception as exc:
                    logger.error("StepStone query '%s' failed: %s", query, exc)
                random_delay(MIN_DELAY + 1, MAX_DELAY + 2)
        finally:
            browser.close()

    logger.info("StepStone scrape complete. %d unique jobs.", len(all_jobs))
    return all_jobs
