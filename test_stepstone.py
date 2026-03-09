"""
test_stepstone.py – Isolated StepStone scraper test.

Runs a single (or a few) StepStone query/queries, prints a detailed
per-card breakdown of every filter stage, and saves matched jobs to
test_results_stepstone.json.  Never touches jobs_database.json or sends email.

Usage examples
--------------
# Run with defaults (first configured query, 1 page, headless)
python test_stepstone.py

# Custom query, 2 pages, visible browser window
python test_stepstone.py --query "Machine Learning Engineer" --pages 2 --headed

# Run all configured queries (slow – same as production)
python test_stepstone.py --all-queries

# Relax filters: skip entry-level and skill checks (see raw card volume)
python test_stepstone.py --no-filter
"""

import argparse
import json
import sys
import urllib.parse

# Fix Windows console encoding so Unicode box-drawing characters render correctly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime
from pathlib import Path

from utils import setup_logging
logger = setup_logging()

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

from config import (
    LLM_MATCH_THRESHOLD,
    MAX_DELAY,
    MAX_RETRIES,
    MIN_DELAY,
    PAGE_TIMEOUT,
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
from evaluator import evaluate_job

_BASE_URL     = "https://www.stepstone.de/jobs/{query}/in-deutschland?sort=2&datePosted=1&page={page}"
_RESULTS_FILE = Path("test_results_stepstone.json")
_DIVIDER      = "─" * 70

_GREEN  = "\033[92m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


def _c(colour: str, text: str) -> str:
    return f"{colour}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Navigation
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


def _accept_cookies(page) -> None:
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
                print("  [INFO] Cookie banner dismissed.")
                random_delay(0.5, 1.5)
                return
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Card extraction  (mirrors scraper_stepstone.py exactly)
# ---------------------------------------------------------------------------

def _extract_cards(page) -> list[dict]:
    cards_raw = page.query_selector_all("article[data-at='job-item']")
    if not cards_raw:
        cards_raw = page.query_selector_all("article[class*='job']")
    if not cards_raw:
        cards_raw = page.query_selector_all("li[class*='ResultList']")

    jobs = []
    for card in cards_raw:
        try:
            title_el = card.query_selector(
                "h2[data-at='job-item-title'], "
                "span[data-at='job-item-title'], "
                "a[data-at='job-item-title']"
            )
            company_el = card.query_selector(
                "[data-at='job-item-company-name'], span[class*='company']"
            )
            location_el = card.query_selector(
                "[data-at='job-item-location'], span[class*='location']"
            )
            link_el = card.query_selector("a[href*='/stellenangebot/'], a[href*='/job/']")
            if not link_el:
                link_el = card.query_selector("a[data-at='job-item-title']")
            date_el = card.query_selector("time, [data-at='job-item-date']")

            title    = title_el.inner_text().strip()    if title_el    else ""
            company  = company_el.inner_text().strip()  if company_el  else ""
            location = location_el.inner_text().strip() if location_el else "Germany"
            href     = link_el.get_attribute("href")    if link_el     else ""
            if href and not href.startswith("http"):
                href = "https://www.stepstone.de" + href
            posting_date = (
                date_el.get_attribute("datetime") or date_el.inner_text().strip()
                if date_el else ""
            )

            if not title or not href:
                continue

            jobs.append({
                "title": title, "company": company, "location": location,
                "url": href, "posting_date": posting_date, "platform": "StepStone",
                "experience_level": "", "description": "", "summary": "",
            })
        except Exception:
            pass
    return jobs


# ---------------------------------------------------------------------------
# Detail page  (mirrors scraper_stepstone.py exactly)
# ---------------------------------------------------------------------------

def _scrape_detail(page, job: dict) -> dict:
    if not _navigate(page, job["url"]):
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

    job["description"]      = desc
    job["experience_level"] = exp_level
    job["summary"]          = extract_summary(desc)
    return job


# ---------------------------------------------------------------------------
# Per-card report
# ---------------------------------------------------------------------------

def _print_card_result(
    idx: int, job: dict, stage_failed: str, apply_filters: bool,
) -> None:
    passed = stage_failed == ""
    status = _c(_GREEN, "PASS") if passed else _c(_RED, f"FAIL [{stage_failed}]")

    print(f"\n  [{idx:>3}] {_c(_BOLD, job['title'])}")
    print(f"        Company  : {job['company']}")
    print(f"        Location : {job['location']}")
    print(f"        Posted   : {job['posting_date'] or 'unknown'}")
    print(f"        URL      : {job['url']}")

    if apply_filters:
        date_ok  = is_posted_within_24h(job["posting_date"])
        title_ok = is_relevant_title(job["title"])
        print(f"        Filters  : "
              f"date={'✓' if date_ok else '✗'}  "
              f"title={'✓' if title_ok else '✗'}")
        score  = job.get("llm_score", 0)
        reason = job.get("llm_reason", "")
        if score:
            verdict = _c(_GREEN, f"MATCH {score}/10") if passed else _c(_RED, f"REJECT {score}/10")
            print(f"        AI Score : {verdict}")
        if reason:
            print(f"        AI Reason: {reason[:100]}{'…' if len(reason) > 100 else ''}")
        if job.get("experience_level"):
            print(f"        Exp.lvl  : {job['experience_level']}")

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

    total_cards = total_date = total_title = total_detail = total_matched = 0
    per_query_stats = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not headed,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            slow_mo=200 if headed else 0,
        )

        try:
            for q_idx, query in enumerate(queries, start=1):
                print(f"\n{_DIVIDER}")
                print(f"  Query {q_idx}/{len(queries)}: {_c(_CYAN, _c(_BOLD, query))}")
                print(_DIVIDER)

                page = browser.new_page()
                page.set_extra_http_headers({"User-Agent": get_random_user_agent()})

                q_cards = q_date = q_title = q_detail = q_matched = 0
                first_page = True

                for page_num in range(1, pages_per_query + 1):
                    encoded = urllib.parse.quote(query)
                    url = _BASE_URL.format(query=encoded, page=page_num)
                    print(f"\n  Page {page_num}/{pages_per_query}  →  {url}")

                    if not _navigate(page, url):
                        print("  [ERROR] Could not load page – skipping.")
                        break

                    if first_page:
                        _accept_cookies(page)
                        first_page = False

                    random_delay(MIN_DELAY, MAX_DELAY)

                    cards = _extract_cards(page)
                    print(f"  Extracted {len(cards)} cards from page.")
                    q_cards += len(cards)

                    if not cards:
                        print("  No cards found – stopping pagination for this query.")
                        break

                    # URL is already scoped to 'in-deutschland' – no location filter needed.
                    date_ok = [j for j in cards if is_posted_within_24h(j["posting_date"])]
                    q_date += len(date_ok)
                    print(f"  After date filter     : {len(date_ok)}/{len(cards)}")

                    title_ok = [j for j in date_ok if is_relevant_title(j["title"])]
                    q_title += len(title_ok)
                    print(f"  After title filter    : {len(title_ok)}/{len(date_ok)}")

                    candidates = title_ok if apply_filters else cards
                    print(f"\n  Visiting {len(candidates)} detail pages …\n")

                    for card_idx, job in enumerate(candidates, start=1):
                        q_detail += 1
                        job = _scrape_detail(page, job)

                        stage_failed = ""
                        if apply_filters:
                            try:
                                result = evaluate_job(job)
                                job["llm_score"]  = result["score"]
                                job["llm_reason"] = result["reason"]
                                if not result["match"]:
                                    stage_failed = f"LLM rejected (score={result['score']}/{LLM_MATCH_THRESHOLD})"
                            except Exception as exc:
                                print(f"  [WARN] LLM evaluation failed: {exc}")

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

                total_cards   += q_cards
                total_date    += q_date
                total_title   += q_title
                total_detail  += q_detail
                total_matched += q_matched
                per_query_stats.append({
                    "query": query, "cards": q_cards,
                    "date": q_date, "title": q_title,
                    "detail": q_detail, "matched": q_matched,
                })

                random_delay(MIN_DELAY + 0.5, MAX_DELAY + 1)

        finally:
            browser.close()

    # ── Summary table ─────────────────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print(f"  {'TEST SUMMARY':^66}")
    print(f"{'═' * 70}")
    print(f"  {'Query':<40} {'Cards':>5} {'Date':>5} {'Title':>6} {'Det':>4} {'Match':>5}")
    print(f"  {'-'*40} {'-'*5} {'-'*5} {'-'*6} {'-'*4} {'-'*5}")
    for s in per_query_stats:
        print(
            f"  {s['query']:<40} {s['cards']:>5} "
            f"{s['date']:>5} {s['title']:>6} {s['detail']:>4} {s['matched']:>5}"
        )
    print(f"  {'-'*40} {'-'*5} {'-'*5} {'-'*6} {'-'*4} {'-'*5}")
    print(
        f"  {'TOTAL':<40} {total_cards:>5} "
        f"{total_date:>5} {total_title:>6} {total_detail:>4} "
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
        description="Test the StepStone scraper in isolation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--query", "-q", default=None,
                   help="Single search query (default: first configured query).")
    p.add_argument("--pages", "-p", type=int, default=1, metavar="N",
                   help="Result pages to scrape per query (default: 1).")
    p.add_argument("--all-queries", action="store_true",
                   help="Run all configured StepStone queries.")
    p.add_argument("--headed", action="store_true",
                   help="Open a visible browser window.")
    p.add_argument("--no-filter", action="store_true",
                   help="Skip LLM evaluation – show all cards with raw data.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.all_queries:
        queries = STEPSTONE_SEARCH_QUERIES
    elif args.query:
        queries = [args.query]
    else:
        queries = [STEPSTONE_SEARCH_QUERIES[0]]

    print(f"\n{'═' * 70}")
    print(f"  StepStone Scraper Test  –  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 70}")
    print(f"  Queries    : {len(queries)}")
    print(f"  Pages/query: {args.pages}")
    print(f"  Browser    : {'headed (visible)' if args.headed else 'headless'}")
    print(f"  LLM Filter : {'OFF (raw mode)' if args.no_filter else 'ON'}")
    print(f"  Queries    : {queries}")
    print(f"{'═' * 70}")

    matched = run_test(
        queries=queries,
        pages_per_query=args.pages,
        headed=args.headed,
        apply_filters=not args.no_filter,
    )

    _RESULTS_FILE.write_text(
        json.dumps({
            "test_run": datetime.now().isoformat(timespec="seconds"),
            "queries": queries,
            "pages_per_query": args.pages,
            "filters_applied": not args.no_filter,
            "total_matched": len(matched),
            "jobs": matched,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Test interrupted by user.")
        sys.exit(0)
