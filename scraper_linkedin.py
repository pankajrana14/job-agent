"""
scraper_linkedin.py – Scrape LinkedIn's public job-search pages.

Uses Playwright (headless Chromium) with random user-agents and delays.
No login required – the public search endpoint is used.

LinkedIn experience-level filter codes:
  2 = Entry Level
  3 = Associate

URL template:
  https://www.linkedin.com/jobs/search/?keywords=<QUERY>&location=Germany
  &f_E=2%2C3&f_TPR=r86400&start=<OFFSET>

f_TPR=r86400 → posted in the last 24 hours (86 400 s)
"""

import logging
import re
import time

from playwright.sync_api import Page, Browser, sync_playwright, TimeoutError as PWTimeoutError

from config import (
    LINKEDIN_SEARCH_QUERIES,
    MAX_DELAY,
    MAX_DETAIL_PAGES_PER_QUERY,
    MAX_PAGES_PER_QUERY,
    MAX_RETRIES,
    MIN_DELAY,
    PAGE_TIMEOUT,
)
from utils import (
    extract_summary,
    generate_job_id,
    get_random_user_agent,
    is_germany_location,
    is_posted_within_24h,
    is_relevant_title,
    random_delay,
)

logger = logging.getLogger("job_agent")

_BASE_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords={query}&location=Germany"
    "&f_E=2%2C3"           # Entry Level + Associate
    "&f_TPR=r86400"         # Last 24 h
    "&start={offset}"
)
_JOBS_PER_PAGE = 25


def _navigate_with_retry(page: Page, url: str, retries: int = MAX_RETRIES) -> bool:
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            return True
        except PWTimeoutError:
            logger.warning("Timeout on %s (attempt %d/%d)", url, attempt, retries)
            random_delay(2, 4)
        except Exception as exc:
            logger.warning("Navigation error %s (attempt %d/%d): %s", url, attempt, retries, exc)
            random_delay(2, 4)
    return False


# ---------------------------------------------------------------------------
# Job-card extraction (search results page)
# ---------------------------------------------------------------------------

def _extract_job_cards(page: Page) -> list[dict]:
    """
    Pull basic job info from the listing page without visiting each detail URL.
    Returns a list of partial job dicts.
    """
    jobs: list[dict] = []

    # LinkedIn renders cards as <div class="base-card"> or <li> elements
    cards = page.query_selector_all("ul.jobs-search__results-list > li")
    if not cards:
        cards = page.query_selector_all("div.base-card")

    logger.debug("Found %d job cards on page.", len(cards))

    for card in cards:
        try:
            title_el = card.query_selector("h3.base-search-card__title")
            company_el = card.query_selector("h4.base-search-card__subtitle")
            location_el = card.query_selector("span.job-search-card__location")
            link_el = card.query_selector("a.base-card__full-link")
            date_el = card.query_selector("time")

            title = title_el.inner_text().strip() if title_el else ""
            company = company_el.inner_text().strip() if company_el else ""
            location = location_el.inner_text().strip() if location_el else ""
            url = link_el.get_attribute("href") if link_el else ""
            posting_date = date_el.get_attribute("datetime") if date_el else ""

            # Strip query params for a cleaner canonical link
            if url and "?" in url:
                url = url.split("?")[0]

            # Normalise country-specific subdomains (de.linkedin.com, fr.linkedin.com …)
            # to www.linkedin.com — country domains redirect inconsistently in headless mode
            if url:
                url = re.sub(r"https?://[a-z]{2}\.linkedin\.com", "https://www.linkedin.com", url)

            if not title or not url:
                continue

            jobs.append(
                {
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": url,
                    "posting_date": posting_date,
                    "platform": "LinkedIn",
                    "experience_level": "",
                    "description": "",
                    "summary": "",
                }
            )
        except Exception as exc:
            logger.debug("Error parsing job card: %s", exc)

    return jobs


# ---------------------------------------------------------------------------
# Job detail page
# ---------------------------------------------------------------------------

def _scrape_detail(page: Page, job: dict) -> dict:
    """Visit a job's detail page and enrich the dict with description / exp."""
    url = job["url"]
    if not _navigate_with_retry(page, url):
        logger.warning("Skipping detail page (navigation failed): %s", url)
        return job

    random_delay(MIN_DELAY, MAX_DELAY)

    # Description
    desc = ""
    for sel in [
        "div.description__text",
        "div.show-more-less-html__markup",
        "section.show-more-less-html",
        "div#job-details",
    ]:
        try:
            el = page.query_selector(sel)
            if el:
                desc = el.inner_text().strip()
                break
        except Exception:
            pass

    # Experience level listed in the criteria section
    exp_level = ""
    criteria_items = page.query_selector_all("ul.description__job-criteria-list li")
    for item in criteria_items:
        try:
            label_el = item.query_selector("h3")
            value_el = item.query_selector("span")
            if label_el and value_el:
                label = label_el.inner_text().strip().lower()
                if "seniority" in label or "erfahrung" in label:
                    exp_level = value_el.inner_text().strip()
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

def _scrape_query(browser: Browser, query: str) -> list[dict]:
    page = browser.new_page()
    page.set_extra_http_headers({"User-Agent": get_random_user_agent()})
    results: list[dict] = []
    detail_count = 0
    limit_reached = False

    try:
        for page_num in range(MAX_PAGES_PER_QUERY):
            if limit_reached:
                break
            offset = page_num * _JOBS_PER_PAGE
            url = _BASE_URL.format(query=query.replace(" ", "%20"), offset=offset)
            logger.info("LinkedIn | query='%s' | page %d | %s", query, page_num + 1, url)

            if not _navigate_with_retry(page, url):
                logger.error("LinkedIn: could not load search page for '%s'", query)
                break

            random_delay(MIN_DELAY, MAX_DELAY)

            # Scroll to trigger lazy-loading
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.5)
            except Exception:
                pass

            cards = _extract_job_cards(page)
            if not cards:
                logger.info("No more cards for query '%s' at offset %d.", query, offset)
                break

            # Filter by location before visiting detail pages
            location_filtered = [
                j for j in cards if is_germany_location(j["location"])
            ]
            logger.debug(
                "%d / %d cards pass location filter.", len(location_filtered), len(cards)
            )

            # Discard anything posted outside the rolling age window
            date_filtered = [
                j for j in location_filtered
                if is_posted_within_24h(j["posting_date"])
            ]
            logger.debug(
                "%d / %d cards pass 24-hour date filter.",
                len(date_filtered), len(location_filtered),
            )

            # Title pre-filter: skip detail page if title is clearly irrelevant
            title_filtered = [j for j in date_filtered if is_relevant_title(j["title"])]
            logger.debug(
                "%d / %d cards pass title pre-filter.",
                len(title_filtered), len(date_filtered),
            )

            # Visit detail pages for skill / experience extraction
            for job in title_filtered:
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

def scrape_linkedin() -> list[dict]:
    """
    Run all configured LinkedIn queries and return a deduplicated list
    of matching job dicts.

    A fresh browser is launched per query so that a Chromium crash or
    MemoryError on one query does not block the remaining ones.
    """
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    with sync_playwright() as pw:
        for query in LINKEDIN_SEARCH_QUERIES:
            logger.info("=== LinkedIn scrape: %s ===", query)
            browser = None
            try:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ],
                )
                jobs = _scrape_query(browser, query)
                for job in jobs:
                    jid = job.get("job_id", "")
                    if jid and jid not in seen_ids:
                        seen_ids.add(jid)
                        all_jobs.append(job)
            except Exception as exc:
                logger.error("LinkedIn query '%s' failed: %s", query, exc)
            finally:
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
            random_delay(MIN_DELAY + 1, MAX_DELAY + 2)

    logger.info("LinkedIn scrape complete. %d unique jobs found.", len(all_jobs))
    return all_jobs
