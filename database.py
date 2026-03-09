"""
database.py – Persistent job store (jobs_database.json).

Each record:
{
    "job_id":   "<sha256>",
    "url":      "https://...",
    "platform": "LinkedIn | StepStone | Indeed",
    "date_sent": "2024-01-15T08:32:00"
}

The same job_id (title+company+location hash) is never inserted twice,
guaranteeing that the same posting is never emailed more than once even
if it appears on multiple platforms or scraping runs.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("job_agent")


class JobDatabase:
    """Thread-unsafe but single-process-safe job record store."""

    def __init__(self, db_file: str) -> None:
        self.db_file = db_file
        self._data: Dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self.db_file):
            logger.info("No database file found – starting with empty store.")
            return
        try:
            with open(self.db_file, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
            logger.info("Loaded %d job records from %s.", len(self._data), self.db_file)
        except (json.JSONDecodeError, IOError) as exc:
            logger.error(
                "Could not read database (%s). Starting with empty store.", exc
            )
            self._data = {}

    def _save(self) -> None:
        try:
            with open(self.db_file, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
        except IOError as exc:
            logger.error("Failed to persist database: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_duplicate(self, job_id: str) -> bool:
        """Return True if this job has been sent before."""
        return job_id in self._data

    def add_job(self, job_id: str, url: str, platform: str) -> None:
        """Mark a single job as sent and persist immediately."""
        self._data[job_id] = {
            "job_id": job_id,
            "url": url,
            "platform": platform,
            "date_sent": datetime.now().isoformat(timespec="seconds"),
        }
        self._save()

    def add_jobs_batch(self, jobs: List[dict]) -> None:
        """Mark a list of job dicts as sent in one atomic write."""
        for job in jobs:
            job_id = job.get("job_id")
            if not job_id:
                continue
            self._data[job_id] = {
                "job_id": job_id,
                "url": job.get("url", ""),
                "platform": job.get("platform", ""),
                "date_sent": datetime.now().isoformat(timespec="seconds"),
            }
        self._save()
        logger.info("Persisted %d new job records.", len(jobs))

    def total_count(self) -> int:
        return len(self._data)

    def get_record(self, job_id: str) -> Optional[dict]:
        return self._data.get(job_id)
