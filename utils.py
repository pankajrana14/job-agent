"""
utils.py – Shared helpers: logging, delays, user-agent rotation,
           job-ID hashing, location/date/title filters.
"""

import hashlib
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import (
    GERMANY_CITY_KEYWORDS,
    LOG_FILE,
    MAX_DELAY,
    MAX_POSTING_AGE_HOURS,
    MIN_DELAY,
    SEARCH_COUNTRY,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    """Configure a dual-output (file + console) logger."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    logger = logging.getLogger("job_agent")
    if logger.handlers:          # avoid duplicate handlers on re-import
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


logger = setup_logging()

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

# Keep these in sync with current browser releases (check ~quarterly).
# Chrome and Firefox each release a new major version roughly every 4 weeks.
_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
]


def get_random_user_agent() -> str:
    return random.choice(_USER_AGENTS)


def random_delay(min_s: float = MIN_DELAY, max_s: float = MAX_DELAY) -> None:
    """Sleep a random amount of time to mimic human browsing."""
    delay = random.uniform(min_s, max_s)
    logger.debug("Sleeping %.1f s …", delay)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# Job identity
# ---------------------------------------------------------------------------

def generate_job_id(title: str, company: str, location: str) -> str:
    """Stable SHA-256 fingerprint so the same job is never re-sent."""
    raw = f"{title.lower().strip()}|{company.lower().strip()}|{location.lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Text analysis helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return text.lower()


# ---------------------------------------------------------------------------
# Title pre-filter (scraper efficiency only — NOT the final match decision)
# ---------------------------------------------------------------------------
# This filter's only job is to avoid fetching detail pages for titles that
# are clearly outside the tech/engineering space (e.g. "Buchhalter",
# "Pflegefachkraft").  The LLM evaluator makes the real match decision.
# When in doubt, err heavily on the side of inclusion.

# Block list: non-tech job families to skip outright (case-insensitive substrings)
_NONTECH_TITLE_BLOCKS: list[str] = [
    # Finance / accounting
    "buchhalter", "steuerberat", "wirtschaftsprüf", "finanzberater", "controller",
    "accountant", "steuerrecht",
    # Sales / marketing
    "verkäufer", "vertriebsmitarbeiter", "außendienst", "sales manager",
    "account manager", "marketing manager", "social media manager",
    "copywriter", "texter", "seo ",
    # HR / recruiting
    "recruiter", "personalref", "personalberater", "hr manager", "talent acquisition",
    "personalentwicklung",
    # Legal
    "rechtsanwalt", "rechtsanwältin", "jurist", "legal counsel", "notar",
    # Healthcare / care
    "arzt", "ärztin", "krankenpfleger", "pflegefachkraft", "pflegekraft",
    "therapeut", "apotheker", "nurse ", "physician", "erzieher", "hebamme",
    # Logistics / trades
    "fahrer", "lagerist", "speditions", "zusteller", "elektriker",
    "sanitärinstallateur", "klempner", "maurer", "schreiner", "maler",
    # Education (non-technical)
    "lehrer", "lehrerin", "grundschul", "gymnasiallehrer",
    # Customer service (non-technical)
    "kassierer", "kassiererin",
]

# Direct keyword match list: these alone in the title are sufficient to accept
_TITLE_ACCEPT_KEYWORDS: list[str] = [
    # Classic tech role names
    "machine learning", "deep learning", "computer vision", "robotics", "robot",
    "perception", "embedded software", "embedded systems", "embedded engineer",
    "data engineer", "data analyst", "data scientist", "data science",
    "c++ developer", "c++ engineer", "c++ programm",
    "python developer", "python engineer",
    "ai engineer", "ai developer", "ml engineer", "ml researcher",
    "software engineer", "software developer", "software entwickler",
    # Autonomous / self-driving
    "autonom", "self-driving", "adas", "fahrerassistenz", "autonomous driving",
    # Robotics / sensing
    "lidar", "slam", "sensor fusion", "point cloud",
    # Research
    "research engineer", "research scientist", "research developer",
    # Modern AI
    "nlp engineer", "llm engineer", "generative ai", "computer scientist",
    # German variants
    "softwareentwickler", "softwareingenieur", "entwickler", "ingenieur",
]

# Broad role words that pass when paired with a tech signal
_TITLE_BROAD_TERMS: list[str] = [
    "engineer", "developer", "analyst", "scientist", "architect",
    "researcher", "specialist", "ingenieur", "entwickler",
]
_TITLE_TECH_SIGNALS: list[str] = [
    "ai", "ml", "robot", "vision", "lidar", "slam", "sensor", "embedded",
    "data", "python", "c++", "perception", "autonom", "adas", "cloud",
    "nlp", "llm", "cuda", "gpu", "neural", "deep", "learning", "software",
    "backend", "hardware", "firmware", "autonomous",
]


def is_relevant_title(title: str) -> bool:
    """
    Lightweight pre-filter run on the job *title* before visiting the detail page.

    Returns False ONLY when the title is clearly from a non-tech profession
    (e.g. "Buchhalter", "Pflegefachkraft", "Verkäufer").

    This is intentionally very permissive — the LLM evaluator makes the real
    match / reject decision after reading the full description.
    """
    norm = title.lower()

    # Block clearly non-tech job families first
    if any(block in norm for block in _NONTECH_TITLE_BLOCKS):
        return False

    # Accept on a direct keyword match
    if any(kw in norm for kw in _TITLE_ACCEPT_KEYWORDS):
        return True

    # Accept when a broad role word is paired with any tech signal
    has_broad = any(b in norm for b in _TITLE_BROAD_TERMS)
    has_tech  = any(t in norm for t in _TITLE_TECH_SIGNALS)
    if has_broad and has_tech:
        return True

    # When genuinely ambiguous (no signals at all), accept and let the LLM decide
    # This catches e.g. "Autonomy Stack Engineer" where "autonom" IS in the list
    # but also "Research Intern" which should be reviewed
    return True


def is_germany_location(location_text: str) -> bool:
    """Return True if the location string indicates a German context via city keywords or country identifiers."""
    norm = _normalise(location_text)
    return any(kw in norm for kw in GERMANY_CITY_KEYWORDS)


def is_target_location(location_text: str) -> bool:
    """
    Return True if the location string matches the configured SEARCH_COUNTRY.

    For Germany the detailed city-keyword list is used (high precision).
    For other countries we accept if the country name appears in the string,
    or if the listing is marked remote/hybrid (the scraper URL already scopes
    results to the right country, so we err on the side of inclusion).
    """
    norm = _normalise(location_text)
    if SEARCH_COUNTRY.lower() == "germany":
        return is_germany_location(location_text)
    country_norm = SEARCH_COUNTRY.lower()
    # Accept if the country name appears as a complete phrase. For multi-word
    # country names we allow flexible separators (whitespace / punctuation)
    # between words while still anchoring the phrase with word boundaries at
    # both ends to avoid false positives like "Austria" matching "Australia".
    country_tokens = re.split(r"\s+", country_norm.strip())
    if len(country_tokens) == 1:
        country_pattern = rf"\b{re.escape(country_tokens[0])}\b"
    else:
        joined = r"\W+".join(re.escape(tok) for tok in country_tokens)
        country_pattern = rf"\b{joined}\b"
    if re.search(country_pattern, norm):
        return True
    if "remote" in norm or "hybrid" in norm:
        return True
    # If location field is empty, give benefit of the doubt
    if not norm.strip():
        return True
    return False


# ---------------------------------------------------------------------------
# Text summarisation
# ---------------------------------------------------------------------------

def extract_summary(description: str, max_sentences: int = 5) -> str:
    """
    Extract the first *max_sentences* sentences from a job description
    to form a short summary.
    """
    if not description:
        return "No description available."

    # Collapse excessive whitespace / newlines
    cleaned = re.sub(r"\s+", " ", description).strip()

    # Split on sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

    summary = " ".join(sentences[:max_sentences])
    if len(summary) > 700:
        summary = summary[:697] + "…"

    return summary or "No description available."


# ---------------------------------------------------------------------------
# Date helper
# ---------------------------------------------------------------------------

def get_current_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_current_datetime() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Posting-age filter
# ---------------------------------------------------------------------------

def _parse_relative_hours(text: str) -> Optional[int]:
    """
    Convert a relative-date string to an approximate age in hours.
    Returns None if the format is not recognised.
    """
    t = text.strip().lower()

    # "just posted" / "heute" / "today" / "gerade"
    if re.search(r"just\s*posted|gerade|^heute$|^today$", t, re.I):
        return 0

    # Minutes → treat as < 1 h
    m = re.search(r"(\d+)\s*(?:minute|min|minuten?)", t, re.I)
    if m:
        return 0

    # Hours
    m = re.search(r"(\d+)\s*(?:hours?|stunden?|std\.?)", t, re.I)
    if m:
        return int(m.group(1))

    # Days
    m = re.search(r"(\d+)\s*(?:days?|tagen?|tag)", t, re.I)
    if m:
        return int(m.group(1)) * 24

    # Weeks
    m = re.search(r"(\d+)\s*(?:weeks?|wochen?|woche)", t, re.I)
    if m:
        return int(m.group(1)) * 168

    return None


def is_posted_within_24h(posting_date: str) -> bool:
    """
    Return True if *posting_date* is within the last MAX_POSTING_AGE_HOURS hours.

    Handles three input formats:
    - ISO 8601 datetime strings  ("2024-01-15T08:32:00", "2024-01-15")
    - Relative strings           ("2 hours ago", "vor 3 Stunden", "heute")
    - Empty / unrecognised       → returns True (give benefit of the doubt
                                   so the job is not silently dropped)
    """
    if not posting_date or not posting_date.strip():
        # No date information – don't reject the job on this criterion alone
        return True

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=MAX_POSTING_AGE_HOURS)
    text = posting_date.strip()

    # ── ISO / structured date ──────────────────────────────────────────────
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d %b %Y",
        "%b %d, %Y",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff
        except ValueError:
            pass

    # ── Relative date string ───────────────────────────────────────────────
    age_hours = _parse_relative_hours(text)
    if age_hours is not None:
        return age_hours <= MAX_POSTING_AGE_HOURS

    # ── Unrecognised format – log and accept ──────────────────────────────
    logger.debug("Unrecognised posting_date format '%s' – accepting job.", text)
    return True
