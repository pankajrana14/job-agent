"""
config.py – Centralised configuration for the job-search automation system.
All tunable parameters live here; credentials are loaded from the .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# LLM evaluation (LiteLLM)
# ---------------------------------------------------------------------------
LLM_MODEL: str           = os.getenv("LLM_MODEL", "groq/llama-3.3-70b-versatile")
LLM_MATCH_THRESHOLD: int = int(os.getenv("LLM_MATCH_THRESHOLD", "7"))
# Groq free tier: 30 RPM, 12K TPM. At ~2K tokens/request, 6 workers saturates TPM safely.
LLM_PARALLEL_WORKERS: int = max(1, int(os.getenv("LLM_PARALLEL_WORKERS", "6")))

# Fallback models tried in order if the primary model fails (rate limit / auth error).
# Comma-separated list of LiteLLM model strings.
LLM_FALLBACK_MODELS: list[str] = [
    m.strip()
    for m in os.getenv(
        "LLM_FALLBACK_MODELS",
        "groq/llama-3.1-8b-instant",
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
    "Graduate Trainee",
    "Trainee Program",
]

# ---------------------------------------------------------------------------
# Search location
# ---------------------------------------------------------------------------
# Country name as it appears in LinkedIn's location param; use the full,
# human-readable country name, matching the keys in STEPSTONE_COUNTRY_DOMAINS.
# Examples of valid values: "Germany", "United Kingdom" (not "UK"),
# "Netherlands", "Austria", "Belgium".  StepStone and BA Jobbörse are mapped
# separately below; BA only supports Germany.
SEARCH_COUNTRY: str = "Germany"

# StepStone country → (domain, in-path segment).
# Countries not listed here will be skipped by the StepStone scraper.
# URL path segments are based on StepStone's structure as of 2026-03 and may
# need updating if the scraper stops returning results for a given country.
STEPSTONE_COUNTRY_DOMAINS: dict[str, tuple[str, str]] = {
    "Germany":     ("www.stepstone.de",  "in-deutschland"),
    "Austria":     ("www.stepstone.at",  "in-oesterreich"),
    "Belgium":     ("www.stepstone.be",  "in-belgien"),
    "Netherlands": ("www.stepstone.nl",  "in-nederland"),
}

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
# LinkedIn gets the country from SEARCH_COUNTRY via its location parameter.
# Keep these as role/title keywords only; do not add "Germany", "Netherlands",
# or other country names here.
LINKEDIN_SEARCH_QUERIES: list[str] = [
    "AI Engineer",
    "Machine Learning Engineer",
    "Robotics Engineer",
    "Computer Vision Engineer",
    "C++ Developer",
    "Python Developer",
    "Data Engineer",
    "Data Analyst",
    "Research Engineer",
    "Perception Engineer",
    "Embedded Software Engineer",
    "Graduate Trainee Program",
    "Trainee Program Engineering",
    "Deep Learning Engineer",
    "Sensor Fusion Engineer",
    "Development Engineer",
    "Autonomous Systems Engineer",
    "Perception Software Engineer",
    "Algorithm Engineer",
    "ADAS Software Engineer",
    "Robotics Software Engineer",
    "Junior Application Engineer",
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
    "Development Engineer",
    "Embedded Software Engineer",
    "Research Engineer",
    "Trainee Programm",
    "Graduate Trainee",
    "Sensorfusion Ingenieur",
    "Algorithmenentwickler",
    "Autonomes Fahren Softwareentwickler",
    "Softwareentwickler Bildverarbeitung",
    "Deep Learning Entwickler",
    "Softwareentwickler Fahrerassistenz",
]

# Xing Jobs is Germany-only in this project; German terms improve recall.
XING_SEARCH_QUERIES: list[str] = [
    "AI Engineer",
    "Machine Learning Engineer",
    "Robotics Engineer",
    "Computer Vision Engineer",
    "C++ Entwickler",
    "Python Entwickler",
    "Data Engineer",
    "Data Analyst",
    "Perception Engineer",
    "Development Engineer",
    "Embedded Software Engineer",
    "Research Engineer",
    "Trainee Programm",
    "Graduate Trainee",
    "Sensorfusion Ingenieur",
    "Algorithmenentwickler",
    "Autonomes Fahren Softwareentwickler",
    "Softwareentwickler Bildverarbeitung",
    "Deep Learning Entwickler",
    "Softwareentwickler Fahrerassistenz",
]

# Bundesagentur für Arbeit – German terms work best with this API
BA_SEARCH_QUERIES: list[str] = [
    "AI Engineer",
    "Machine Learning Engineer",
    "Robotics Engineer",
    "Computer Vision Engineer",
    "C++ Entwickler",
    "Python Entwickler",
    "Research Engineer",
    "Data Engineer",
    "Data Analyst",
    "Development Engineer",
    "Perception Engineer",
    "Embedded Software Engineer",
    "Trainee Programm",
    "Graduate Trainee",
    "Sensorfusion Ingenieur",
    "Algorithmenentwickler",
    "Autonomes Fahren Softwareentwickler",
    "Softwareentwickler Bildverarbeitung",
    "Deep Learning Entwickler",
    "Softwareentwickler Fahrerassistenz",
]

# ---------------------------------------------------------------------------
# Platform on/off switches
# ---------------------------------------------------------------------------
LINKEDIN_ENABLED:   bool = True
STEPSTONE_ENABLED:  bool = True
XING_ENABLED:       bool = True

# Bundesagentur für Arbeit – Germany's federal employment agency.
# Uses a public REST API (no CAPTCHA, no bot-detection).
BA_ENABLED:         bool = True

# ---------------------------------------------------------------------------
# Scraping behaviour
# ---------------------------------------------------------------------------
MIN_DELAY: float = 1.5
MAX_DELAY: float = 3.5
MAX_RETRIES: int = 3
PAGE_TIMEOUT: int = 30_000  # milliseconds (Playwright)

# Only accept jobs posted within this many hours.
# 48h (not 24h) because some platforms use a calendar-day filter that can
# include jobs posted up to ~48h ago (e.g. StepStone's datePosted=1).
MAX_POSTING_AGE_HOURS: int = 48

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
