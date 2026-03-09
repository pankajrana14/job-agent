"""
test_linkedin.py – Isolated LinkedIn scraper test.

Runs a single (or a few) LinkedIn query/queries, prints a detailed
per-card breakdown of every filter stage, and saves matched jobs to
test_results.json.  Never touches jobs_database.json or sends email.

Usage examples
--------------
# Run with defaults (first configured query, 1 page, headless)
python test_linkedin.py

# Custom query, 2 pages, visible browser window
python test_linkedin.py --query "Machine Learning Engineer Germany" --pages 2 --headed

# Run all configured queries (slow – same as production)
python test_linkedin.py --all-queries

# Relax filters: skip entry-level and skill checks (see raw card volume)
python test_linkedin.py --no-filter
"""

import argparse
import json
import re
import sys
import time

# Fix Windows console encoding so Unicode box-drawing characters render correctly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: logging must be set up before any project imports
# ---------------------------------------------------------------------------
from utils import setup_logging
logger = setup_logging()

# Now import the rest
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

from config import (
    LINKEDIN_SEARCH_QUERIES,
    LLM_MATCH_THRESHOLD,
    MAX_DELAY,
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
from evaluator import evaluate_job

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_BASE_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords={query}&location=Germany"
    "&f_E=2%2C3"
    "&f_TPR=r86400"
    "&start={offset}"
)
_JOBS_PER_PAGE = 25
_DIVIDER = "─" * 70
_RESULTS_FILE = Path("test_results.json")

# ANSI colours (skipped on Windows if not supported)
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


def _c(colour: str, text: str) -> str:
    """Wrap text in an ANSI colour code."""
    return f"{colour}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Navigation helper
# ---------------------------------------------------------------------------

def _navigate(page, url: str, retries: int = MAX_RETRIES) -> bool:
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            return True
        except PWTimeoutError:
            print(f"  [WARN] Timeout (attempt {attempt}/{retries}): {url}")
            random_delay(2, 3)
        except Exception as exc:
            print(f"  [WARN] Nav error (attempt {attempt}/{retries}): {exc}")
            random_delay(2, 3)
    return False


# ---------------------------------------------------------------------------
# Card extraction  (mirrors scraper_linkedin.py exactly)
# ---------------------------------------------------------------------------

def _extract_cards(page) -> list[dict]:
    cards_raw = page.query_selector_all("ul.jobs-search__results-list > li")
    if not cards_raw:
        cards_raw = page.query_selector_all("div.base-card")

    jobs = []
    for card in cards_raw:
        try:
            title_el    = card.query_selector("h3.base-search-card__title")
            company_el  = card.query_selector("h4.base-search-card__subtitle")
            location_el = card.query_selector("span.job-search-card__location")
            link_el     = card.query_selector("a.base-card__full-link")
            date_el     = card.query_selector("time")

            title        = title_el.inner_text().strip()    if title_el    else ""
            company      = company_el.inner_text().strip()  if company_el  else ""
            location     = location_el.inner_text().strip() if location_el else ""
            url          = link_el.get_attribute("href")    if link_el     else ""
            posting_date = date_el.get_attribute("datetime") if date_el    else ""

            if url and "?" in url:
                url = url.split("?")[0]

            # Normalise country-specific subdomains to www.linkedin.com
            if url:
                url = re.sub(r"https?://[a-z]{2}\.linkedin\.com", "https://www.linkedin.com", url)

            if not title or not url:
                continue

            jobs.append({
                "title": title, "company": company, "location": location,
                "url": url, "posting_date": posting_date, "platform": "LinkedIn",
                "experience_level": "", "description": "", "summary": "",
            })
        except Exception:
            pass
    return jobs


# ---------------------------------------------------------------------------
# Detail page  (mirrors scraper_linkedin.py exactly)
# ---------------------------------------------------------------------------

def _scrape_detail(page, job: dict) -> dict:
    if not _navigate(page, job["url"]):
        return job

    random_delay(MIN_DELAY, MAX_DELAY)

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

    exp_level = ""
    for item in page.query_selector_all("ul.description__job-criteria-list li"):
        try:
            label_el = item.query_selector("h3")
            value_el = item.query_selector("span")
            if label_el and value_el:
                if "seniority" in label_el.inner_text().lower() or \
                   "erfahrung" in label_el.inner_text().lower():
                    exp_level = value_el.inner_text().strip()
                    break
        except Exception:
            pass

    job["description"]      = desc
    job["experience_level"] = exp_level
    job["summary"]          = extract_summary(desc)
    return job


# ---------------------------------------------------------------------------
# Per-card verbose report
# ---------------------------------------------------------------------------

def _print_card_result(
    idx: int,
    job: dict,
    stage_failed: str,
    apply_filters: bool,
) -> None:
    passed = stage_failed == ""
    status = _c(_GREEN, "PASS") if passed else _c(_RED, f"FAIL [{stage_failed}]")

    print(f"\n  [{idx:>3}] {_c(_BOLD, job['title'])}")
    print(f"        Company  : {job['company']}")
    print(f"        Location : {job['location']}")
    print(f"        Posted   : {job.get('posting_date') or 'unknown'}")
    print(f"        URL      : {job['url']}")

    if apply_filters:
        loc_ok   = is_germany_location(job["location"])
        date_ok  = is_posted_within_24h(job.get("posting_date", ""))
        title_ok = is_relevant_title(job["title"])
        score    = job.get("llm_score", 0)
        reason   = job.get("llm_reason", "")
        print(
            f"        Pre-filter: "
            f"location={'✓' if loc_ok else '✗'}  "
            f"date24h={'✓' if date_ok else '✗'}  "
            f"title={'✓' if title_ok else '✗'}"
        )
        print(f"        AI Score  : {score}/10  (threshold: {LLM_MATCH_THRESHOLD})")
        if reason:
            short = reason[:130] + ("…" if len(reason) > 130 else "")
            print(f"        AI Verdict: {short}")
        exp = job.get("experience_level", "")
        if exp:
            print(f"        Exp.lvl   : {exp}")
    print(f"        Status   : {status}")


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def run_test(
    queries: list[str],
    pages_per_query: int,
    headed: bool,
    apply_filters: bool,
) -> list[dict]:

    all_matched: list[dict] = []
    seen_ids: set[str] = set()

    # Counters across all queries
    total_cards      = 0
    total_loc_pass   = 0
    total_date_pass  = 0
    total_title_pass = 0
    total_detail     = 0
    total_matched    = 0
    per_query_stats  = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not headed,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            slow_mo=200 if headed else 0,
        )

        try:
            for q_idx, query in enumerate(queries, start=1):
                print(f"\n{_DIVIDER}")
                print(f"  Query {q_idx}/{len(queries)}: {_c(_CYAN, _c(_BOLD, query))}")
                print(_DIVIDER)

                page = browser.new_page()
                page.set_extra_http_headers({"User-Agent": get_random_user_agent()})

                q_cards = q_loc = q_date = q_title = q_detail = q_matched = 0

                for page_num in range(pages_per_query):
                    offset = page_num * _JOBS_PER_PAGE
                    url = _BASE_URL.format(
                        query=query.replace(" ", "%20"), offset=offset
                    )
                    print(f"\n  Page {page_num + 1}/{pages_per_query}  →  {url}")

                    if not _navigate(page, url):
                        print("  [ERROR] Could not load search page – skipping.")
                        break

                    random_delay(MIN_DELAY, MAX_DELAY)

                    try:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1.0)
                    except Exception:
                        pass

                    cards = _extract_cards(page)
                    print(f"  Extracted {len(cards)} cards from page.")
                    q_cards += len(cards)

                    if not cards:
                        print("  No cards found – stopping pagination for this query.")
                        break

                    # ── Filter stage 1: location ──────────────────────────
                    loc_ok = [j for j in cards if is_germany_location(j["location"])]
                    q_loc += len(loc_ok)
                    print(f"  After location filter : {len(loc_ok)}/{len(cards)}")

                    # ── Filter stage 2: 24-hour date ──────────────────────
                    date_ok = [j for j in loc_ok if is_posted_within_24h(j["posting_date"])]
                    q_date += len(date_ok)
                    print(f"  After date filter     : {len(date_ok)}/{len(loc_ok)}")

                    # ── Filter stage 3: title pre-filter ──────────────────
                    title_ok = [j for j in date_ok if is_relevant_title(j["title"])]
                    q_title += len(title_ok)
                    print(f"  After title filter    : {len(title_ok)}/{len(date_ok)}")

                    candidates = title_ok if apply_filters else cards

                    # ── Detail page visits ────────────────────────────────
                    print(f"\n  Visiting {len(candidates)} detail pages …\n")
                    card_idx = 0

                    for job in candidates:
                        card_idx += 1
                        q_detail += 1

                        job = _scrape_detail(page, job)

                        if apply_filters:
                            try:
                                result = evaluate_job(job)
                            except Exception as exc:
                                print(f"  [WARN] LLM evaluation failed: {exc}")
                                result = {"match": False, "score": 0, "reason": ""}
                            job["llm_score"]  = result["score"]
                            job["llm_reason"] = result["reason"]
                            stage_failed = (
                                ""
                                if result["match"]
                                else f"AI score {result['score']}/10 < threshold {LLM_MATCH_THRESHOLD}"
                            )
                        else:
                            job["llm_score"]  = 0
                            job["llm_reason"] = ""
                            stage_failed      = ""

                        _print_card_result(card_idx, job, stage_failed, apply_filters)

                        if stage_failed == "":
                            q_matched += 1
                            job["job_id"] = generate_job_id(
                                job["title"], job["company"], job["location"]
                            )
                            jid = job["job_id"]
                            if jid not in seen_ids:
                                seen_ids.add(jid)
                                all_matched.append(job)

                        random_delay(MIN_DELAY, MAX_DELAY)

                page.close()

                # Per-query summary
                total_cards      += q_cards
                total_loc_pass   += q_loc
                total_date_pass  += q_date
                total_title_pass += q_title
                total_detail     += q_detail
                total_matched    += q_matched
                per_query_stats.append({
                    "query": query, "cards": q_cards, "loc": q_loc,
                    "date": q_date, "title": q_title,
                    "detail": q_detail, "matched": q_matched,
                })

                random_delay(MIN_DELAY + 0.5, MAX_DELAY + 1)

        finally:
            browser.close()

    # ── Final summary ─────────────────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print(f"  {'TEST SUMMARY':^66}")
    print(f"{'═' * 70}")
    print(f"  {'Query':<45} {'Cards':>5} {'Loc':>4} {'Date':>5} {'Title':>6} {'Det':>4} {'Match':>5}")
    print(f"  {'-'*45} {'-'*5} {'-'*4} {'-'*5} {'-'*6} {'-'*4} {'-'*5}")
    for s in per_query_stats:
        print(
            f"  {s['query']:<45} {s['cards']:>5} {s['loc']:>4} "
            f"{s['date']:>5} {s['title']:>6} {s['detail']:>4} {s['matched']:>5}"
        )
    print(f"  {'-'*45} {'-'*5} {'-'*4} {'-'*5} {'-'*6} {'-'*4} {'-'*5}")
    print(
        f"  {'TOTAL':<45} {total_cards:>5} {total_loc_pass:>4} "
        f"{total_date_pass:>5} {total_title_pass:>6} {total_detail:>4} "
        f"{_c(_GREEN, str(total_matched)):>5}"
    )
    print(f"{'═' * 70}\n")

    deduped = len(all_matched)
    print(f"  Unique matched jobs (cross-query dedup): {_c(_GREEN, _c(_BOLD, str(deduped)))}")
    print(f"  Results saved to: {_RESULTS_FILE.resolve()}\n")

    return all_matched


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Test the LinkedIn scraper in isolation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--query", "-q",
        default=None,
        help="Single search query to test (default: first configured query).",
    )
    p.add_argument(
        "--pages", "-p",
        type=int,
        default=1,
        metavar="N",
        help="Number of result pages to scrape per query (default: 1).",
    )
    p.add_argument(
        "--all-queries",
        action="store_true",
        help="Run all configured LinkedIn queries (same as production).",
    )
    p.add_argument(
        "--headed",
        action="store_true",
        help="Open a visible browser window (useful to debug bot-detection).",
    )
    p.add_argument(
        "--no-filter",
        action="store_true",
        help="Skip skill/experience filters — show all cards with raw data.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # Resolve query list
    if args.all_queries:
        queries = LINKEDIN_SEARCH_QUERIES
    elif args.query:
        queries = [args.query]
    else:
        queries = [LINKEDIN_SEARCH_QUERIES[0]]

    print(f"\n{'═' * 70}")
    print(f"  LinkedIn Scraper Test  –  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 70}")
    print(f"  Queries    : {len(queries)}")
    print(f"  Pages/query: {args.pages}")
    print(f"  Browser    : {'headed (visible)' if args.headed else 'headless'}")
    print(f"  Filters    : {'OFF (raw mode)' if args.no_filter else 'ON'}")
    print(f"  Queries    : {queries}")
    print(f"{'═' * 70}")

    matched_jobs = run_test(
        queries=queries,
        pages_per_query=args.pages,
        headed=args.headed,
        apply_filters=not args.no_filter,
    )

    # Save results
    output = {
        "test_run": datetime.now().isoformat(timespec="seconds"),
        "queries": queries,
        "pages_per_query": args.pages,
        "filters_applied": not args.no_filter,
        "total_matched": len(matched_jobs),
        "jobs": matched_jobs,
    }
    _RESULTS_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Test interrupted by user.")
        sys.exit(0)
