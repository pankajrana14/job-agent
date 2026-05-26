"""
scraper_xing.py - Scrape Xing Jobs for Germany.

Uses Playwright (headless Chromium). Xing is focused on the German-speaking
market, so this scraper intentionally runs only when SEARCH_COUNTRY is Germany.

Search URL template:
  https://www.xing.com/jobs/search?keywords=<QUERY>&location=Germany&page=<PAGE>
"""

import logging
import json
import re
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
    XING_SEARCH_QUERIES,
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

_BASE_URL = "https://www.xing.com/jobs/search?keywords={query}&location=Germany&page={page}"


def _build_search_url(query: str, page: int) -> str:
    """Build a Xing Jobs search URL for Germany."""
    return _BASE_URL.format(query=urllib.parse.quote(query), page=page)


def _navigate_with_retry(page: Page, url: str, retries: int = MAX_RETRIES) -> bool:
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            return True
        except PWTimeoutError:
            logger.warning("Xing timeout (attempt %d/%d): %s", attempt, retries, url)
            random_delay(2, 4)
        except Exception as exc:
            logger.warning("Xing nav error (attempt %d/%d): %s - %s", attempt, retries, url, exc)
            random_delay(2, 4)
    return False


def _accept_cookies(page: Page) -> None:
    """Dismiss Xing consent banners if present."""
    for selector in [
        "button:has-text('Accept all')",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button[id*='accept']",
        "button[class*='accept']",
    ]:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click(timeout=3000)
                logger.debug("Xing: cookie banner dismissed.")
                random_delay(0.5, 1.5)
                return
        except Exception:
            pass


def _first_text(card, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            el = card.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if text:
                    return text
        except Exception:
            pass
    return ""


def _first_attr(card, selectors: list[str], attr: str) -> str:
    for selector in selectors:
        try:
            el = card.query_selector(selector)
            if el:
                value = el.get_attribute(attr) or ""
                if value:
                    return value.strip()
        except Exception:
            pass
    return ""


def _normalise_job_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("/"):
        href = f"https://www.xing.com{href}"
    if "?" in href:
        href = href.split("?", 1)[0]
    return href


def _extract_job_cards(page: Page) -> list[dict]:
    """Extract basic job info from Xing search results."""
    jobs: list[dict] = []
    cards = page.query_selector_all("[data-testid*='job-card'], article")
    if not cards:
        cards = page.query_selector_all("li:has(a[href*='/jobs/'])")
    if not cards:
        cards = page.query_selector_all("div:has(a[href*='/jobs/'])")

    logger.debug("Xing: found %d cards.", len(cards))

    seen_urls: set[str] = set()
    for card in cards:
        try:
            href = _first_attr(card, ["a[href*='/jobs/']"], "href")
            url = _normalise_job_url(href)
            if not url or url in seen_urls or "/jobs/search" in url:
                continue

            title = _first_text(
                card,
                [
                    "[data-testid*='job-title']",
                    "h2",
                    "h3",
                    "a[href*='/jobs/']",
                ],
            )
            company = _first_text(
                card,
                [
                    "[data-testid*='company']",
                    "[class*='company']",
                    "p",
                ],
            )
            location = _first_text(
                card,
                [
                    "[data-testid*='location']",
                    "[class*='location']",
                    "span:has-text('Germany')",
                    "span:has-text('Deutschland')",
                ],
            )
            posting_date = _first_attr(card, ["time"], "datetime") or _first_text(
                card,
                [
                    "time",
                    "span:has-text('heute')",
                    "span:has-text('Heute')",
                    "span:has-text('Stunde')",
                    "span:has-text('Tag')",
                    "span:has-text('day')",
                    "span:has-text('hour')",
                ],
            )

            if not title:
                continue

            seen_urls.add(url)
            jobs.append(
                {
                    "title": title,
                    "company": company,
                    "location": location or "Germany",
                    "url": url,
                    "posting_date": posting_date,
                    "platform": "Xing",
                    "experience_level": "",
                    "description": "",
                    "summary": "",
                }
            )
        except Exception as exc:
            logger.debug("Xing card parse error: %s", exc)

    return jobs


def _extract_json_ld_description(page: Page) -> str:
    try:
        scripts = page.query_selector_all("script[type='application/ld+json']")
    except Exception:
        return ""
    for script in scripts:
        try:
            text = script.inner_text().strip()
            match = re.search(r'"description"\s*:\s*"((?:\\.|[^"\\])*)"', text)
            if match:
                return bytes(match.group(1), "utf-8").decode("unicode_escape").strip()
        except Exception:
            pass
    return ""


def _extract_json_ld_posting_date(page: Page) -> str:
    try:
        scripts = page.query_selector_all("script[type='application/ld+json']")
    except Exception:
        return ""
    for script in scripts:
        try:
            text = script.inner_text().strip()
            data = json.loads(text)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("datePosted"):
                    return str(item["datePosted"]).strip()
        except Exception:
            match = re.search(r'"datePosted"\s*:\s*"([^"]+)"', text)
            if match:
                return match.group(1).strip()
    return ""


def _scrape_detail(page: Page, job: dict) -> dict:
    if not _navigate_with_retry(page, job["url"]):
        logger.warning("Xing: skipping detail page: %s", job["url"])
        return job

    random_delay(MIN_DELAY, MAX_DELAY)
    _accept_cookies(page)

    desc = ""
    for selector in [
        "[data-testid*='job-description']",
        "[class*='job-description']",
        "[class*='JobDescription']",
        "section:has-text('Deine Aufgaben')",
        "section:has-text('Your tasks')",
        "main",
    ]:
        try:
            el = page.query_selector(selector)
            if el:
                desc = el.inner_text().strip()
                if desc:
                    break
        except Exception:
            pass
    if not desc:
        desc = _extract_json_ld_description(page)

    if not job.get("posting_date", "").strip():
        job["posting_date"] = _extract_json_ld_posting_date(page)

    exp_level = ""
    for selector in [
        "[data-testid*='career-level']",
        "[data-testid*='experience']",
        "li:has-text('Berufserfahrung')",
        "li:has-text('Experience')",
        "span:has-text('Berufseinsteiger')",
        "span:has-text('Entry')",
        "span:has-text('Junior')",
    ]:
        try:
            el = page.query_selector(selector)
            if el:
                exp_level = el.inner_text().strip()
                break
        except Exception:
            pass

    job["description"] = desc
    job["experience_level"] = exp_level
    job["summary"] = extract_summary(desc)
    return job


def _scrape_query(browser: Browser, query: str) -> list[dict]:
    page = browser.new_page()
    page.set_extra_http_headers({"User-Agent": get_random_user_agent()})
    results: list[dict] = []
    detail_count = 0
    limit_reached = False

    try:
        for page_num in range(1, MAX_PAGES_PER_QUERY + 1):
            if limit_reached:
                break
            url = _build_search_url(query, page_num)
            logger.info("Xing | query='%s' | page %d | %s", query, page_num, url)

            if not _navigate_with_retry(page, url):
                logger.error("Xing: failed to load page for '%s'", query)
                break

            if page_num == 1:
                _accept_cookies(page)

            random_delay(MIN_DELAY, MAX_DELAY)

            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                random_delay(0.5, 1.0)
            except Exception:
                pass

            cards = _extract_job_cards(page)
            if not cards:
                logger.info("Xing: no cards on page %d for '%s'.", page_num, query)
                break

            date_ok = [j for j in cards if is_posted_within_24h(j["posting_date"])]
            logger.debug("Xing: %d / %d pass date filter.", len(date_ok), len(cards))

            title_ok = [j for j in date_ok if is_relevant_title(j["title"])]
            logger.debug("Xing: %d / %d pass title pre-filter.", len(title_ok), len(date_ok))

            for job in title_ok:
                if detail_count >= MAX_DETAIL_PAGES_PER_QUERY:
                    logger.info("Xing: reached max detail pages (%d).", detail_count)
                    limit_reached = True
                    break

                job = _scrape_detail(page, job)
                detail_count += 1
                if not is_posted_within_24h(job.get("posting_date", "")):
                    logger.debug(
                        "Xing: skipping '%s' @ %s after detail date filter (%s).",
                        job.get("title", "?"),
                        job.get("company", "?"),
                        job.get("posting_date", ""),
                    )
                    continue
                job["job_id"] = generate_job_id(job["title"], job["company"], job["location"])
                results.append(job)
                logger.debug("Scraped '%s' @ %s - queued for AI evaluation.", job["title"], job["company"])

                random_delay(MIN_DELAY, MAX_DELAY)
    finally:
        page.close()

    return results


def scrape_xing() -> list[dict]:
    """Scrape Xing Jobs for Germany and return deduplicated job dicts."""
    if SEARCH_COUNTRY.lower() != "germany":
        logger.info(
            "Xing scraper is Germany-only. Current SEARCH_COUNTRY='%s' - skipping Xing scrape.",
            SEARCH_COUNTRY,
        )
        return []

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    with sync_playwright() as pw:
        browser: Optional[Browser] = None
        try:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            for query in XING_SEARCH_QUERIES:
                logger.info("=== Xing scrape: %s ===", query)
                try:
                    jobs = _scrape_query(browser, query)
                    for job in jobs:
                        jid = job.get("job_id", "")
                        if jid and jid not in seen_ids:
                            seen_ids.add(jid)
                            all_jobs.append(job)
                except Exception as exc:
                    logger.error("Xing query '%s' failed: %s", query, exc)
                random_delay(MIN_DELAY + 1, MAX_DELAY + 2)
        finally:
            if browser is not None:
                browser.close()

    logger.info("Xing scrape complete. %d unique jobs.", len(all_jobs))
    return all_jobs
