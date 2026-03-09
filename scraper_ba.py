"""
scraper_ba.py – Scrape Bundesagentur für Arbeit (BA) Jobbörse.

The BA Jobbörse is Germany's official federal employment agency job board
(arbeitsagentur.de).  It exposes a public REST API used by its own website —
no Cloudflare, no CAPTCHA, no browser needed; plain HTTPS requests work fine.

API flow
--------
1. GET  /jobboerse/jobsuche-service/pc/v4/jobs  →  paginated job listings (JSON)
2. GET  /jobboerse/jobsuche-service/pc/v4/jobdetails/<ref_nr>  →  full description

Authentication: simple X-API-Key header (no OAuth needed).

Search URL (web equivalent for manual inspection):
  https://www.arbeitsagentur.de/jobsuche/suche?was=<QUERY>&wo=Deutschland&angebotsart=1
"""

import logging
import urllib.parse
import urllib.request
import json
from typing import Optional

from config import (
    BA_SEARCH_QUERIES,
    MAX_DELAY,
    MAX_DETAIL_PAGES_PER_QUERY,
    MAX_PAGES_PER_QUERY,
    MAX_RETRIES,
    MIN_DELAY,
)
from utils import (
    extract_summary,
    generate_job_id,
    is_posted_within_24h,
    is_relevant_title,
    random_delay,
)

logger = logging.getLogger("job_agent")

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

_SEARCH_URL  = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
_DETAIL_URL  = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{refnr}"

# Public API key used by the BA Jobbörse frontend (no OAuth required)
_HEADERS = {
    "X-API-Key":    "jobboerse-jobsuche",
    "User-Agent":   "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; iOS 15.1.0)",
    "Accept":       "application/json",
}

_PAGE_SIZE   = 25   # items per API response page


# ---------------------------------------------------------------------------
# Job search  (listings)
# ---------------------------------------------------------------------------

def _search_jobs(query: str, page: int = 1) -> dict:
    """Call the BA jobs search endpoint.  Returns the parsed JSON dict or {}."""
    params = urllib.parse.urlencode({
        "was":              query,
        "wo":               "Deutschland",
        "angebotsart":      1,        # 1 = Stellenangebot (job offer)
        "veroeffentlichtseit": 1,     # published within last 1 day
        "page":             page,
        "size":             _PAGE_SIZE,
    })
    url = f"{_SEARCH_URL}?{params}"

    req = urllib.request.Request(url, headers=_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.warning("BA search error (query='%s', page=%d): %s", query, page, exc)
        return {}


# ---------------------------------------------------------------------------
# Job details
# ---------------------------------------------------------------------------

def _get_detail(refnr: str) -> dict:
    """Fetch full job details for a given reference number.  Returns {} on error."""
    url = _DETAIL_URL.format(refnr=urllib.parse.quote(refnr, safe=""))
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.debug("BA detail error (refnr=%s): %s", refnr, exc)
        return {}


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _safe(d: dict, *keys, default: str = "") -> str:
    """Safely navigate nested dict keys, returning a string value."""
    val = d
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return str(val).strip() if val else default


def _build_job_url(refnr: str) -> str:
    return (
        "https://www.arbeitsagentur.de/jobsuche/jobdetail/"
        + urllib.parse.quote(refnr, safe="")
    )


def _parse_listing(item: dict) -> Optional[dict]:
    """Convert a BA API listing item to our standard job dict."""
    try:
        refnr   = _safe(item, "refnr")
        title   = _safe(item, "titel")
        company = _safe(item, "arbeitgeber")
        pub_date = _safe(item, "aktuelleVeroeffentlichungsdatum") or _safe(item, "eintrittsdatum")

        # Location: item may have hashMap fields or a top-level arbeitsort
        ao = item.get("arbeitsort") or {}
        city    = _safe(ao, "ort")
        plz     = _safe(ao, "plz")
        land    = _safe(ao, "land", default="Deutschland")
        location = ", ".join(filter(None, [city, land])) or "Deutschland"

        url = _build_job_url(refnr) if refnr else ""

        if not title or not refnr:
            return None

        return {
            "title":            title,
            "company":          company,
            "location":         location,
            "url":              url,
            "posting_date":     pub_date,
            "platform":         "BA Jobbörse",
            "experience_level": "",
            "description":      "",
            "summary":          "",
            "_refnr":           refnr,    # internal; stripped before final output
        }
    except Exception as exc:
        logger.debug("BA listing parse error: %s", exc)
        return None


def _enrich_with_detail(job: dict, detail: dict) -> dict:
    """Add description and experience level from the detail API response."""
    # Description: BA uses 'stellenbeschreibung' in the top-level or inside
    # 'stellenbeschreibungHtml'.  We prefer plain text.
    desc = (
        _safe(detail, "stellenbeschreibung")
        or _safe(detail, "beschreibung")
    )
    # Some detail responses nest info under 'stellenangebot'
    if not desc and isinstance(detail.get("stellenangebot"), dict):
        sa = detail["stellenangebot"]
        desc = _safe(sa, "stellenbeschreibung") or _safe(sa, "beschreibung")

    # Experience level hint
    exp_level = _safe(detail, "berufserfahrung") or _safe(detail, "qualifikationsniveau")

    job["description"]      = desc
    job["experience_level"] = exp_level
    job["summary"]          = extract_summary(desc)
    return job


# ---------------------------------------------------------------------------
# Per-query scraper
# ---------------------------------------------------------------------------

def _scrape_query(query: str) -> list[dict]:
    results: list[dict] = []
    detail_count = 0
    limit_reached = False

    for page_num in range(1, MAX_PAGES_PER_QUERY + 1):
        if limit_reached:
            break

        logger.info("BA | query='%s' | page %d", query, page_num)

        data = _search_jobs(query, page=page_num)
        items = data.get("stellenangebote") or []

        if not items:
            logger.info("BA: no items on page %d for '%s'.", page_num, query)
            break

        logger.debug("BA: %d items on page %d for '%s'.", len(items), page_num, query)

        # ── Filter funnel (lightweight – no detail page yet) ──────────────
        parsed = [j for j in (_parse_listing(i) for i in items) if j]

        # BA Jobbörse API already scopes results to Germany – skip location filter.
        date_ok = [j for j in parsed if is_posted_within_24h(j["posting_date"])]
        logger.debug("BA: %d / %d pass date filter.", len(date_ok), len(parsed))

        title_ok = [j for j in date_ok if is_relevant_title(j["title"])]
        logger.debug("BA: %d / %d pass title pre-filter.", len(title_ok), len(date_ok))

        for job in title_ok:
            if detail_count >= MAX_DETAIL_PAGES_PER_QUERY:
                logger.info(
                    "BA: reached max detail pages (%d) for query '%s'.",
                    MAX_DETAIL_PAGES_PER_QUERY, query,
                )
                limit_reached = True
                break

            # Fetch full description
            refnr  = job.pop("_refnr", "")
            detail = _get_detail(refnr) if refnr else {}
            job    = _enrich_with_detail(job, detail)
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

            random_delay(MIN_DELAY * 0.5, MAX_DELAY * 0.5)   # API – no need for long delays

        # Stop if fewer results than a full page (last page reached)
        if len(items) < _PAGE_SIZE:
            break

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape_ba() -> list[dict]:
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for query in BA_SEARCH_QUERIES:
        logger.info("=== BA scrape: %s ===", query)
        try:
            jobs = _scrape_query(query)
            for job in jobs:
                jid = job.get("job_id", "")
                if jid and jid not in seen_ids:
                    seen_ids.add(jid)
                    all_jobs.append(job)
        except Exception as exc:
            logger.error("BA query '%s' failed: %s", query, exc)
        random_delay(0.5, 1.5)   # short inter-query delay for an API

    logger.info("BA scrape complete. %d unique jobs.", len(all_jobs))
    return all_jobs
