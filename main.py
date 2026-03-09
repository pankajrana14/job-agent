"""
main.py – Orchestrator for the Germany AI/Robotics Job Search Automation.

Run directly:
    python main.py

Or via Windows Task Scheduler (see README.md for setup).

Flow
----
1. Scrape enabled platforms: LinkedIn, StepStone, BA Jobbörse (in sequence).
2. AI evaluation: each job is scored 1–10 by an LLM against PROFILE.md.
3. Deduplicate matched jobs against jobs_database.json.
4. Send structured email via Gmail SMTP.
5. Persist newly sent jobs to jobs_database.json.
"""

import sys
import logging
from datetime import datetime

from config import (
    DATABASE_FILE,
    LINKEDIN_ENABLED,
    STEPSTONE_ENABLED,
    BA_ENABLED,
)
from database import JobDatabase
from email_sender import send_email
from utils import get_current_datetime, setup_logging

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
    start_time = datetime.now()
    logger.info("Job Agent started at %s", get_current_datetime())

    # ------------------------------------------------------------------
    # 1. Import scrapers here (after logging setup) to avoid circular issues
    # ------------------------------------------------------------------
    from scraper_linkedin  import scrape_linkedin
    from scraper_stepstone import scrape_stepstone
    from scraper_ba        import scrape_ba
    from evaluator         import evaluate_jobs

    # ------------------------------------------------------------------
    # 2. Scrape all enabled platforms
    # ------------------------------------------------------------------
    raw_jobs: list[dict] = []

    if LINKEDIN_ENABLED:
        raw_jobs.extend(_run_scraper("LinkedIn", scrape_linkedin))
    else:
        logger.info("LinkedIn scraper disabled (LINKEDIN_ENABLED=False).")

    if STEPSTONE_ENABLED:
        raw_jobs.extend(_run_scraper("StepStone", scrape_stepstone))
    else:
        logger.info("StepStone scraper disabled (STEPSTONE_ENABLED=False).")

    if BA_ENABLED:
        raw_jobs.extend(_run_scraper("BA Jobbörse", scrape_ba))
    else:
        logger.info("BA Jobbörse scraper disabled (BA_ENABLED=False).")

    logger.info("Total raw candidates across all platforms: %d", len(raw_jobs))

    # ------------------------------------------------------------------
    # 3. AI evaluation — replaces all keyword filters
    #    Each job is sent to the LLM with the candidate profile.
    #    Only jobs the LLM approves (score >= LLM_MATCH_THRESHOLD) continue.
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("Starting AI evaluation pass")
    logger.info("=" * 60)
    try:
        ai_matched = evaluate_jobs(raw_jobs)
    except Exception as exc:
        logger.error("AI evaluation crashed: %s – falling back to all raw jobs.", exc)
        ai_matched = raw_jobs   # safe fallback: don't drop everything on API error

    # ------------------------------------------------------------------
    # 4. Deduplication against database
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

    # Cross-query deduplication (same job from different queries)
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
    # 5. Send email
    # ------------------------------------------------------------------
    logger.info("Sending email update (%d new jobs) …", len(deduplicated))
    success = send_email(deduplicated)

    # ------------------------------------------------------------------
    # 6. Persist to database (only after successful email)
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
