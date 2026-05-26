"""
test_xing.py - Isolated Xing scraper smoke test.

Runs one or more Xing Germany queries, prints filter-stage counts, and saves
matched jobs to test_results_xing.json. Never touches jobs_database.json or
sends email.

Usage examples
--------------
python test_xing.py
python test_xing.py --query "Machine Learning Engineer" --pages 2 --headed
python test_xing.py --all-queries --no-filter
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from utils import setup_logging
logger = setup_logging()

from playwright.sync_api import sync_playwright

from config import LLM_MATCH_THRESHOLD, MAX_DELAY, MIN_DELAY, XING_SEARCH_QUERIES
from evaluator import evaluate_job
from scraper_xing import (
    _accept_cookies,
    _build_search_url,
    _extract_job_cards,
    _navigate_with_retry,
    _scrape_detail,
)
from utils import (
    generate_job_id,
    get_random_user_agent,
    is_posted_within_24h,
    is_relevant_title,
    random_delay,
)

_RESULTS_FILE = Path("test_results_xing.json")
_DIVIDER = "-" * 70


def run_test(queries: list[str], pages_per_query: int, headed: bool, apply_filters: bool) -> list[dict]:
    all_matched: list[dict] = []
    seen_ids: set[str] = set()
    per_query_stats = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not headed,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            slow_mo=200 if headed else 0,
        )
        try:
            for q_idx, query in enumerate(queries, start=1):
                print(f"\n{_DIVIDER}")
                print(f"  Query {q_idx}/{len(queries)}: {query}")
                print(_DIVIDER)

                page = browser.new_page()
                page.set_extra_http_headers({"User-Agent": get_random_user_agent()})
                q_cards = q_date = q_title = q_detail = q_matched = 0

                for page_num in range(1, pages_per_query + 1):
                    url = _build_search_url(query, page_num)
                    print(f"\n  Page {page_num}/{pages_per_query} -> {url}")
                    if not _navigate_with_retry(page, url):
                        print("  [ERROR] Could not load page - skipping.")
                        break
                    if page_num == 1:
                        _accept_cookies(page)
                    random_delay(MIN_DELAY, MAX_DELAY)

                    cards = _extract_job_cards(page)
                    print(f"  Extracted cards     : {len(cards)}")
                    q_cards += len(cards)
                    if not cards:
                        break

                    date_ok = [j for j in cards if is_posted_within_24h(j["posting_date"])]
                    q_date += len(date_ok)
                    print(f"  After date filter   : {len(date_ok)}/{len(cards)}")

                    title_ok = [j for j in date_ok if is_relevant_title(j["title"])]
                    q_title += len(title_ok)
                    print(f"  After title filter  : {len(title_ok)}/{len(date_ok)}")

                    candidates = title_ok if apply_filters else cards
                    print(f"\n  Visiting {len(candidates)} detail pages\n")
                    for idx, job in enumerate(candidates, start=1):
                        q_detail += 1
                        job = _scrape_detail(page, job)
                        stage_failed = ""
                        if apply_filters:
                            try:
                                result = evaluate_job(job)
                                job["llm_score"] = result["score"]
                                job["llm_reason"] = result["reason"]
                                if not result["match"]:
                                    stage_failed = f"LLM rejected ({result['score']}/{LLM_MATCH_THRESHOLD})"
                            except Exception as exc:
                                stage_failed = f"LLM error: {exc}"

                        print(f"  [{idx:>2}] {job['title']} @ {job['company']} - {stage_failed or 'PASS'}")
                        if stage_failed == "":
                            q_matched += 1
                            job["job_id"] = generate_job_id(job["title"], job["company"], job["location"])
                            if job["job_id"] not in seen_ids:
                                seen_ids.add(job["job_id"])
                                all_matched.append(job)
                        random_delay(MIN_DELAY, MAX_DELAY)

                page.close()
                per_query_stats.append({
                    "query": query,
                    "cards": q_cards,
                    "date": q_date,
                    "title": q_title,
                    "detail": q_detail,
                    "matched": q_matched,
                })
        finally:
            browser.close()

    print(f"\n{_DIVIDER}")
    print("  TEST SUMMARY")
    print(_DIVIDER)
    for stats in per_query_stats:
        print(
            f"  {stats['query']}: cards={stats['cards']} "
            f"date={stats['date']} title={stats['title']} "
            f"detail={stats['detail']} matched={stats['matched']}"
        )
    print(f"  Unique matched jobs: {len(all_matched)}")
    print(f"  Results saved to: {_RESULTS_FILE.resolve()}\n")
    return all_matched


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test the Xing scraper in isolation.")
    parser.add_argument("--query", "-q", default=None, help="Single search query.")
    parser.add_argument("--pages", "-p", type=int, default=1, help="Pages per query.")
    parser.add_argument("--all-queries", action="store_true", help="Run all configured Xing queries.")
    parser.add_argument("--headed", action="store_true", help="Open a visible browser window.")
    parser.add_argument("--no-filter", action="store_true", help="Skip LLM evaluation.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.all_queries:
        queries = XING_SEARCH_QUERIES
    elif args.query:
        queries = [args.query]
    else:
        queries = [XING_SEARCH_QUERIES[0]]

    print(f"\nXing Scraper Test - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Queries: {queries}")
    print(f"Pages/query: {args.pages}")
    print(f"Browser: {'headed' if args.headed else 'headless'}")
    print(f"Filters: {'OFF' if args.no_filter else 'ON'}")

    matched = run_test(queries, args.pages, args.headed, not args.no_filter)
    _RESULTS_FILE.write_text(
        json.dumps(
            {
                "test_run": datetime.now().isoformat(timespec="seconds"),
                "queries": queries,
                "pages_per_query": args.pages,
                "filters_applied": not args.no_filter,
                "total_matched": len(matched),
                "jobs": matched,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Test interrupted by user.")
        sys.exit(0)
