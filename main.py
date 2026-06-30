"""
main.py – Orchestrator for the Germany AI/Robotics Job Search Automation.

Run directly:
    python main.py                # full run: scrape + evaluate + email
    python main.py --from-cache   # skip scraping, re-evaluate from scraped_cache.json

Or via Windows Task Scheduler (see README.md for setup).

Flow
----
1. Scrape enabled platforms: LinkedIn, StepStone, BA Jobbörse (in sequence).
   → Raw jobs saved to scraped_cache.json immediately after scraping.
2. AI evaluation: each job is scored 1–10 by an LLM against PROFILE.md.
3. Deduplicate matched jobs against jobs_database.json.
4. Send structured email via Gmail SMTP.
5. Persist newly sent jobs to jobs_database.json.
"""

import sys
import json
import logging
from datetime import datetime
from pathlib import Path

from config import (
    DATABASE_FILE,
    LINKEDIN_ENABLED,
    STEPSTONE_ENABLED,
    XING_ENABLED,
    BA_ENABLED,
)
from database import JobDatabase
from email_sender import send_email
from utils import get_current_datetime, setup_logging

SCRAPE_CACHE_FILE = Path("scraped_cache.json")

# Ensure logging is initialised before importing scrapers
logger = setup_logging()


def _run_scraper(name: str, scraper_fn) -> list[dict]:
    """Run a single scraper, catching all exceptions so others can continue."""
    logger.info("=" * 60)
    logger.info("Starting scraper: %s", name)
    logger.info("=" * 60)
    try:
        jobs = scraper_fn()
        logger.info("%s returned %d candidate jobs.", name, len(jobs))
        return jobs
    except Exception as exc:
        logger.error("%s scraper crashed: %s", name, exc, exc_info=True)
        return []


def main() -> None:
    from_cache = "--from-cache" in sys.argv

    start_time = datetime.now()
    logger.info("Job Agent started at %s", get_current_datetime())

    from evaluator import evaluate_jobs
    from config import LLM_MODEL, LLM_FALLBACK_MODELS, LLM_PARALLEL_WORKERS

    logger.info(
        "LLM config  model=%s  fallbacks=%s  workers=%d",
        LLM_MODEL, LLM_FALLBACK_MODELS, LLM_PARALLEL_WORKERS,
    )

    # ------------------------------------------------------------------
    # 1. Scrape all enabled platforms  (or load from cache)
    # ------------------------------------------------------------------
    if from_cache:
        if not SCRAPE_CACHE_FILE.exists():
            logger.error(
                "--from-cache specified but %s not found. Run without --from-cache first.",
                SCRAPE_CACHE_FILE,
            )
            sys.exit(1)
        raw_jobs = json.loads(SCRAPE_CACHE_FILE.read_text(encoding="utf-8"))
        logger.info("Loaded %d jobs from cache (%s).", len(raw_jobs), SCRAPE_CACHE_FILE)
    else:
        from scraper_linkedin  import scrape_linkedin
        from scraper_stepstone import scrape_stepstone
        from scraper_xing      import scrape_xing
        from scraper_ba        import scrape_ba

        raw_jobs: list[dict] = []

        if LINKEDIN_ENABLED:
            raw_jobs.extend(_run_scraper("LinkedIn", scrape_linkedin))
        else:
            logger.info("LinkedIn scraper disabled (LINKEDIN_ENABLED=False).")

        if STEPSTONE_ENABLED:
            raw_jobs.extend(_run_scraper("StepStone", scrape_stepstone))
        else:
            logger.info("StepStone scraper disabled (STEPSTONE_ENABLED=False).")

        if XING_ENABLED:
            raw_jobs.extend(_run_scraper("Xing", scrape_xing))
        else:
            logger.info("Xing scraper disabled (XING_ENABLED=False).")

        if BA_ENABLED:
            raw_jobs.extend(_run_scraper("BA Jobbörse", scrape_ba))
        else:
            logger.info("BA Jobbörse scraper disabled (BA_ENABLED=False).")

        logger.info("Total raw candidates across all platforms: %d", len(raw_jobs))

        # Save cache immediately so a failed evaluation can be re-run cheaply.
        SCRAPE_CACHE_FILE.write_text(
            json.dumps(raw_jobs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Scrape cache saved to %s.", SCRAPE_CACHE_FILE)

    # ------------------------------------------------------------------
    # 2. AI evaluation
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("Starting AI evaluation pass")
    logger.info("=" * 60)
    try:
        ai_matched = evaluate_jobs(raw_jobs)
    except Exception as exc:
        logger.error("AI evaluation crashed: %s – falling back to all raw jobs.", exc)
        ai_matched = raw_jobs

    # ------------------------------------------------------------------
    # 3. Deduplication against database
    # ------------------------------------------------------------------
    db = JobDatabase(DATABASE_FILE)

    new_jobs: list[dict] = []
    for job in ai_matched:
        job_id = job.get("job_id")
        if not job_id:
            logger.debug("Job missing job_id – skipping: %s", job.get("title", "?"))
            continue
        if db.is_duplicate(job_id):
            logger.debug(
                "Duplicate skipped: '%s' @ %s", job.get("title"), job.get("company")
            )
        else:
            new_jobs.append(job)

    seen: set[str] = set()
    deduplicated: list[dict] = []
    for job in new_jobs:
        jid = job["job_id"]
        if jid not in seen:
            seen.add(jid)
            deduplicated.append(job)

    logger.info(
        "After deduplication: %d new jobs (database has %d total records).",
        len(deduplicated), db.total_count(),
    )

    # ------------------------------------------------------------------
    # 4. Send email
    # ------------------------------------------------------------------
    logger.info("Sending email update (%d new jobs) …", len(deduplicated))
    success = send_email(deduplicated)

    # ------------------------------------------------------------------
    # 5. Persist to database (only after successful email)
    # ------------------------------------------------------------------
    if success and deduplicated:
        db.add_jobs_batch(deduplicated)
        logger.info(
            "Persisted %d new jobs. Database now has %d records.",
            len(deduplicated), db.total_count(),
        )
    elif not success:
        logger.error(
            "Email delivery failed – NOT persisting jobs to avoid missed notifications."
        )

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(
        "Job Agent finished in %.1f s.  New jobs found: %d.", elapsed, len(deduplicated)
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Job Agent interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        logger.critical("Unhandled exception in main(): %s", exc, exc_info=True)
        sys.exit(1)
