"""
test_ba.py – Isolated Bundesagentur für Arbeit (BA) scraper test.

Tests the BA Jobbörse REST API directly (no browser, no CAPTCHA).

Usage examples
--------------
# Run with defaults (first configured query, 1 page)
python test_ba.py

# Custom query, 2 pages
python test_ba.py --query "Machine Learning Engineer" --pages 2

# Run all configured queries
python test_ba.py --all-queries

# Show all items without skill/experience filtering
python test_ba.py --no-filter
"""

import argparse
import json
import sys

# Fix Windows console encoding so Unicode box-drawing characters render correctly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime
from pathlib import Path

from utils import setup_logging
logger = setup_logging()

from config import BA_SEARCH_QUERIES, LLM_MATCH_THRESHOLD, MAX_DELAY, MIN_DELAY
from utils import (
    extract_summary,
    generate_job_id,
    is_posted_within_24h,
    is_relevant_title,
    random_delay,
)
from evaluator import evaluate_job
from scraper_ba import (
    _search_jobs,
    _get_detail,
    _parse_listing,
    _enrich_with_detail,
    _PAGE_SIZE,
)

_RESULTS_FILE = Path("test_results_ba.json")
_DIVIDER      = "─" * 70

_GREEN  = "\033[92m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


def _c(colour: str, text: str) -> str:
    return f"{colour}{text}{_RESET}"


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
        print(
            f"        Filters  : "
            f"date={'✓' if date_ok else '✗'}  "
            f"title={'✓' if title_ok else '✗'}"
        )
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

def run_test(queries: list[str], pages_per_query: int, apply_filters: bool) -> list[dict]:
    all_matched: list = []
    seen_ids: set = set()
    total_raw = total_date = total_title = total_detail = total_matched = 0
    per_query_stats = []

    for q_idx, query in enumerate(queries, start=1):
        print(f"\n{_DIVIDER}")
        print(f"  Query {q_idx}/{len(queries)}: {_c(_CYAN, _c(_BOLD, query))}")
        print(_DIVIDER)

        q_raw = q_date = q_title = q_detail = q_matched = 0

        for page_num in range(1, pages_per_query + 1):
            print(f"\n  Page {page_num}/{pages_per_query}")
            data  = _search_jobs(query, page=page_num)
            items = data.get("stellenangebote") or []
            total_hits = data.get("maxErgebnisse") or data.get("totalCount") or "?"
            print(f"  API items returned : {len(items)}  (total available: {total_hits})")
            q_raw += len(items)

            if not items:
                print("  No items – stopping pagination for this query.")
                break

            parsed = [j for j in (_parse_listing(i) for i in items) if j]
            print(f"  Parsed ok          : {len(parsed)}/{len(items)}")

            # BA API already scopes to Germany – no location filter needed.
            date_ok = [j for j in parsed if is_posted_within_24h(j["posting_date"])]
            q_date += len(date_ok)
            print(f"  After date filter  : {len(date_ok)}/{len(parsed)}")

            title_ok = [j for j in date_ok if is_relevant_title(j["title"])]
            q_title += len(title_ok)
            print(f"  After title filter : {len(title_ok)}/{len(date_ok)}")

            candidates = title_ok if apply_filters else parsed
            print(f"\n  Fetching {len(candidates)} detail pages …\n")

            for card_idx, job in enumerate(candidates, start=1):
                refnr  = job.pop("_refnr", "")
                detail = _get_detail(refnr) if refnr else {}
                job    = _enrich_with_detail(job, detail)
                q_detail += 1

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

                random_delay(MIN_DELAY * 0.3, MAX_DELAY * 0.3)

            if len(items) < _PAGE_SIZE:
                break   # last page

        total_raw     += q_raw
        total_date    += q_date
        total_title   += q_title
        total_detail  += q_detail
        total_matched += q_matched
        per_query_stats.append({
            "query": query, "raw": q_raw,
            "date": q_date, "title": q_title,
            "detail": q_detail, "matched": q_matched,
        })

    # ── Summary table ──────────────────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print(f"  {'TEST SUMMARY':^66}")
    print(f"{'═' * 70}")
    print(f"  {'Query':<40} {'Raw':>4} {'Date':>5} {'Title':>6} {'Det':>4} {'Match':>5}")
    print(f"  {'-'*40} {'-'*4} {'-'*5} {'-'*6} {'-'*4} {'-'*5}")
    for s in per_query_stats:
        print(
            f"  {s['query']:<40} {s['raw']:>4} "
            f"{s['date']:>5} {s['title']:>6} {s['detail']:>4} {s['matched']:>5}"
        )
    print(f"  {'-'*40} {'-'*4} {'-'*5} {'-'*6} {'-'*4} {'-'*5}")
    print(
        f"  {'TOTAL':<40} {total_raw:>4} "
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
        description="Test the Bundesagentur für Arbeit scraper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--query", "-q", default=None,
                   help="Single search query (default: first configured query).")
    p.add_argument("--pages", "-p", type=int, default=1, metavar="N",
                   help="API pages to fetch per query (default: 1).")
    p.add_argument("--all-queries", action="store_true",
                   help="Run all configured BA queries.")
    p.add_argument("--no-filter", action="store_true",
                   help="Skip LLM evaluation – show all raw items.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.all_queries:
        queries = BA_SEARCH_QUERIES
    elif args.query:
        queries = [args.query]
    else:
        queries = [BA_SEARCH_QUERIES[0]]

    print(f"\n{'═' * 70}")
    print(f"  Bundesagentur für Arbeit Scraper Test  –  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Method: BA REST API (no browser, no CAPTCHA)")
    print(f"{'═' * 70}")
    print(f"  Queries    : {len(queries)}")
    print(f"  Pages/query: {args.pages}")
    print(f"  LLM Filter : {'OFF (raw mode)' if args.no_filter else 'ON'}")
    print(f"  Queries    : {queries}")
    print(f"{'═' * 70}")

    matched = run_test(
        queries=queries,
        pages_per_query=args.pages,
        apply_filters=not args.no_filter,
    )

    _RESULTS_FILE.write_text(
        json.dumps({
            "test_run":        datetime.now().isoformat(timespec="seconds"),
            "method":          "BA-REST-API",
            "queries":         queries,
            "pages_per_query": args.pages,
            "filters_applied": not args.no_filter,
            "total_matched":   len(matched),
            "jobs":            matched,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Test interrupted by user.")
        sys.exit(0)
