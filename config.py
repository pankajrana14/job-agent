"""
config.py – Centralised configuration for the job-search automation system.
All tunable parameters live here; credentials are loaded from the .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# LLM evaluation (LiteLLM + Groq)
# ---------------------------------------------------------------------------
LLM_MODEL: str           = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_MATCH_THRESHOLD: int = int(os.getenv("LLM_MATCH_THRESHOLD", "6"))

# Fallback models tried in order if the primary model fails (rate limit / auth error).
# Comma-separated list of LiteLLM model strings.
LLM_FALLBACK_MODELS: list[str] = [
    m.strip()
    for m in os.getenv(
        "LLM_FALLBACK_MODELS",
        "claude-haiku-4-5-20251001,gemini/gemini-2.0-flash",
    ).split(",")
    if m.strip()
]

# ---------------------------------------------------------------------------
# Email / SMTP
# ---------------------------------------------------------------------------
GMAIL_USER: str = os.getenv("GMAIL_USER", "")
GMAIL_PASSWORD: str = os.getenv("GMAIL_PASSWORD", "")        # App-password, not account pw
RECIPIENT_EMAIL: str = os.getenv("RECIPIENT_EMAIL", "")

# ---------------------------------------------------------------------------
# Target job titles
# ---------------------------------------------------------------------------
TARGET_ROLES: list[str] = [
    "AI Engineer",
    "Machine Learning Engineer",
    "Robotics Engineer",
    "Computer Vision Engineer",
    "C++ Developer",
    "Python Developer",
    "Data Engineer",
    "Data Analyst",
    "Perception Engineer",
    "Embedded Software Engineer",
]

# ---------------------------------------------------------------------------
# Location filters (lowercase)
# ---------------------------------------------------------------------------
LOCATION_KEYWORDS: list[str] = [
    "germany",
    "deutschland",
    "berlin",
    "munich",
    "münchen",
    "hamburg",
    "frankfurt",
    "cologne",
    "köln",
    "stuttgart",
    "düsseldorf",
    "dortmund",
    "essen",
    "bremen",
    "hannover",
    "nuremberg",
    "nürnberg",
    "remote",          # accepted only when combined with DE company signals
    "hybrid",
]

# These substrings in a location field confirm Germany even for remote jobs
GERMANY_CITY_KEYWORDS: list[str] = [
    "berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne",
    "köln", "stuttgart", "düsseldorf", "dortmund", "essen", "bremen",
    "hannover", "nuremberg", "nürnberg", "germany", "deutschland",
    "de ",    # e.g. "Remote – DE"
]

# ---------------------------------------------------------------------------
# Search queries per platform
# ---------------------------------------------------------------------------
LINKEDIN_SEARCH_QUERIES: list[str] = [
    "AI Engineer Germany",
    "Machine Learning Engineer Germany",
    "Robotics Engineer Germany",
    "Computer Vision Engineer Germany",
    "C++ Developer Germany",
    "Python Developer Germany",
    "Data Engineer Germany",
    "Data Analyst Germany",
    "Perception Engineer Germany",
    "Embedded Software Engineer Germany",
]

STEPSTONE_SEARCH_QUERIES: list[str] = [
    "AI Engineer",
    "Machine Learning Engineer",
    "Robotics Engineer",
    "Computer Vision Engineer",
    "C++ Entwickler",
    "Python Entwickler",
    "Data Engineer",
    "Data Analyst",
    "Perception Engineer",
    "Embedded Software Engineer",
]

# Bundesagentur für Arbeit – German terms work best with this API
BA_SEARCH_QUERIES: list[str] = [
    "AI Engineer",
    "Machine Learning Engineer",
    "Robotics Engineer",
    "Computer Vision Engineer",
    "C++ Entwickler",
    "Python Entwickler",
    "Data Engineer",
    "Data Analyst",
    "Perception Engineer",
    "Embedded Software Engineer",
]

# ---------------------------------------------------------------------------
# Platform on/off switches
# ---------------------------------------------------------------------------
LINKEDIN_ENABLED:   bool = True
STEPSTONE_ENABLED:  bool = True

# Bundesagentur für Arbeit – Germany's federal employment agency.
# Uses a public REST API (no CAPTCHA, no bot-detection).
BA_ENABLED:         bool = True

# ---------------------------------------------------------------------------
# Scraping behaviour
# ---------------------------------------------------------------------------
MIN_DELAY: float = 1.5     # seconds between requests
MAX_DELAY: float = 3.5
MAX_RETRIES: int = 3
PAGE_TIMEOUT: int = 30_000  # milliseconds (Playwright)

# Only accept jobs posted within this many hours.
# 36h (not 24h) because some platforms use a calendar-day filter that can
# include jobs posted up to ~36h ago (e.g. StepStone's datePosted=1).
MAX_POSTING_AGE_HOURS: int = 36

# How many result pages to scrape per query.
# 24-hour filter means very few results per page → 2 pages is enough.
MAX_PAGES_PER_QUERY: int = 2

# Max detail pages visited per query AFTER the title pre-filter.
# The title pre-filter discards ~60-70% of irrelevant cards before
# any detail page is opened, so 20 here is safe and prevents missing
# real results while keeping per-query time reasonable.
MAX_DETAIL_PAGES_PER_QUERY: int = 20

# ---------------------------------------------------------------------------
# Storage / logging
# ---------------------------------------------------------------------------
DATABASE_FILE: str = "jobs_database.json"
LOG_FILE: str = "logs/job_agent.log"
