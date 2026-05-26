"""
evaluator.py – LiteLLM-powered job evaluator.

Reads the candidate profile from PROFILE.md once at import time, then uses
an LLM (default: gpt-4o-mini) to evaluate each scraped job against that profile.

Output per job
--------------
  match  – True if score >= LLM_MATCH_THRESHOLD
  score  – 1–10 fit score
  reason – one paragraph explaining the verdict
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import TypedDict

import litellm

from config import LLM_FALLBACK_MODELS, LLM_MATCH_THRESHOLD, LLM_MODEL, SEARCH_COUNTRY

logger = logging.getLogger("job_agent")

# Let LiteLLM silently drop unsupported provider parameters instead of failing hard.
litellm.drop_params = True

# ---------------------------------------------------------------------------
# Load candidate profile (read once at startup)
# ---------------------------------------------------------------------------

_PROFILE_PATH = Path(__file__).parent / "PROFILE.md"

if _PROFILE_PATH.exists():
    _PROFILE_TEXT = _PROFILE_PATH.read_text(encoding="utf-8").strip()
else:
    logger.warning(
        "PROFILE.md not found at %s – using empty profile. "
        "Create PROFILE.md to get accurate AI matching.",
        _PROFILE_PATH,
    )
    _PROFILE_TEXT = "No profile provided."


def get_profile_text() -> str:
    """Return the loaded candidate profile text (public accessor)."""
    return _PROFILE_TEXT


def _profile_for_search_country(profile_text: str) -> str:
    """Return profile text with obvious country preferences adjusted for this run."""
    text = profile_text
    replacements = [
        (
            r"Germany only\. Remote positions are acceptable if the employer is clearly a German company or the role is contractually based in Germany\.",
            (
                f"{SEARCH_COUNTRY} only. Remote positions are acceptable if the employer "
                f"is clearly tied to {SEARCH_COUNTRY} or the role is contractually based "
                f"in {SEARCH_COUNTRY}."
            ),
        ),
        (
            r"based in Germany",
            f"based in {SEARCH_COUNTRY}",
        ),
        (
            r"full-time permanent positions in Germany",
            f"full-time permanent positions in {SEARCH_COUNTRY}",
        ),
        (
            r"full-time permanent roles in Germany",
            f"full-time permanent roles in {SEARCH_COUNTRY}",
        ),
        (
            r"Germany only\. Remote positions are acceptable if the employer is clearly a German company\n"
            r"\(German address, German job board, or German language in posting\)\.",
            (
                f"{SEARCH_COUNTRY} only. Remote positions are acceptable if the employer "
                f"is clearly tied to {SEARCH_COUNTRY}."
            ),
        ),
        (
            r"Roles outside Germany unless remote for a confirmed German employer",
            f"Roles outside {SEARCH_COUNTRY} unless remote for a confirmed {SEARCH_COUNTRY} employer",
        ),
        (
            r"Roles outside Germany \(unless remote for a confirmed German employer\)",
            (
                f"Roles outside {SEARCH_COUNTRY} "
                f"(unless remote for a confirmed {SEARCH_COUNTRY} employer)"
            ),
        ),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text

# ---------------------------------------------------------------------------
# System prompt sent to the LLM before every job evaluation
# ---------------------------------------------------------------------------

_SEARCH_PROFILE_TEXT = _profile_for_search_country(_PROFILE_TEXT)

_SYSTEM_PROMPT = f"""You are an expert career advisor evaluating job postings for a specific candidate.

CANDIDATE PROFILE:
{_SEARCH_PROFILE_TEXT}

YOUR TASK:
For each job posting I give you, decide whether it is a good fit for this candidate.
Base your decision on the full job DESCRIPTION content, not just the title.
A job titled "Autonomy Engineer" or "Softwareentwickler autonome Systeme" can be a
perfect match even if it doesn't say "AI Engineer" explicitly.

RESPOND with a single JSON object — no extra text, no markdown fences:
{{
  "score": <integer 1–10>,
  "reason": "<one concise paragraph: why it matches or doesn't, referencing specific details from both the job and the profile>"
}}

SCORING GUIDE:
  9–10 : Excellent fit – role, level, and tech stack align almost perfectly
  7–8  : Good fit – most requirements match, minor gaps
  5–6  : Partial fit – relevant domain but notable mismatches
  3–4  : Poor fit – wrong domain or wrong seniority level
  1–2  : No fit – unrelated to the candidate's background

HARD REJECTION RULES (score ≤ 3 regardless of other signals):
- Role requires 4+ years of experience AND description gives no junior pathway
- Role is outside {SEARCH_COUNTRY} and not remote for an employer clearly tied to {SEARCH_COUNTRY}
- Role has no software/engineering component (sales, HR, finance, legal, etc.)
""".strip()

# Maximum characters of job description sent to the LLM.
# Keeps token cost predictable while still covering the bulk of most postings.
_MAX_DESC_CHARS = 2000

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class EvalResult(TypedDict):
    match: bool
    score: int
    reason: str


_FALLBACK: EvalResult = {
    "match": False,
    "score": 0,
    "reason": "Evaluation unavailable (API error).",
}


def _extract_json_object(raw: str) -> dict:
    """
    Parse a model response into JSON, tolerating markdown fences and extra text.
    Raises json.JSONDecodeError if no valid JSON object can be found.
    """
    text = (raw or "").strip()
    if not text:
        raise json.JSONDecodeError("Empty response", text, 0)

    # Fast path: response is already plain JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Common case: ```json { ... } ```
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

    # Last resort: extract the first JSON object substring.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start:end + 1]
        return json.loads(snippet)

    raise json.JSONDecodeError("No JSON object found", text, 0)


def _build_completion_params(model: str, user_message: str) -> dict:
    """Build provider-safe completion params for the selected model."""
    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 500,
    }

    # gpt-5 family currently enforces temperature=1.
    if model.lower().startswith("gpt-5"):
        params["temperature"] = 1
    else:
        params["temperature"] = 0.1

    return params

# ---------------------------------------------------------------------------
# Core evaluation call
# ---------------------------------------------------------------------------

def _call_model(model: str, user_message: str) -> EvalResult:
    """
    Call a single LiteLLM model.  Retries once on rate-limit (5s wait).
    Raises on all other errors so the caller can try the next fallback.
    """
    for attempt in range(1, 3):  # 2 attempts per model
        try:
            response = litellm.completion(**_build_completion_params(model, user_message))
            raw = response.choices[0].message.content
            data = _extract_json_object(raw)
            score = max(1, min(10, int(data.get("score", 0))))
            return EvalResult(
                match  = score >= LLM_MATCH_THRESHOLD,
                score  = score,
                reason = str(data.get("reason", "")).strip(),
            )

        except litellm.RateLimitError:
            if attempt == 1:
                logger.warning("Rate limit on '%s' – retrying in 5s …", model)
                time.sleep(5)
            else:
                raise   # let caller try next model


def evaluate_job(job: dict) -> EvalResult:
    """
    Evaluate a single job dict against the candidate profile via LiteLLM.

    Tries LLM_MODEL first, then each model in LLM_FALLBACK_MODELS in order.
    Returns _FALLBACK only if every model fails.
    """
    desc = job.get("description", "No description available.")
    if len(desc) > _MAX_DESC_CHARS:
        # Truncate at the last sentence boundary to avoid cutting mid-sentence.
        boundary = max(
            desc.rfind(".", 0, _MAX_DESC_CHARS),
            desc.rfind("!", 0, _MAX_DESC_CHARS),
            desc.rfind("?", 0, _MAX_DESC_CHARS),
        )
        cut = boundary + 1 if boundary != -1 else _MAX_DESC_CHARS
        desc = desc[:cut] + "\n[description truncated]"

    user_message = "\n".join([
        f"Job Title: {job.get('title', 'N/A')}",
        f"Company: {job.get('company', 'N/A')}",
        f"Location: {job.get('location', 'N/A')}",
        f"Platform: {job.get('platform', 'N/A')}",
        f"Experience Level (from job board): {job.get('experience_level', 'N/A') or 'N/A'}",
        "",
        "Job Description:",
        desc,
    ])

    title = job.get("title", "?")
    for model in [LLM_MODEL] + LLM_FALLBACK_MODELS:
        try:
            result = _call_model(model, user_message)
            if model != LLM_MODEL:
                logger.info("Fallback model '%s' succeeded for '%s'.", model, title)
            return result
        except json.JSONDecodeError as exc:
            logger.warning("Non-JSON response from '%s' for '%s': %s", model, title, exc)
            continue
        except Exception as exc:
            logger.warning("Model '%s' failed for '%s': %s – trying next …", model, title, exc)

    logger.error("All models failed for '%s'. Returning fallback.", title)
    return _FALLBACK


# ---------------------------------------------------------------------------
# Batch evaluation with rate-limit awareness
# ---------------------------------------------------------------------------

def evaluate_jobs(jobs: list[dict], delay_between: float = 1.0) -> list[dict]:
    """
    Evaluate a list of job dicts.  Attaches llm_score and llm_reason fields
    to each job, then returns only the matched ones.

    Parameters
    ----------
    jobs          : list of job dicts from scrapers
    delay_between : seconds to wait between LLM calls (default 1s).
    """
    matched: list[dict] = []
    total = len(jobs)

    logger.info("AI evaluation: %d jobs to evaluate with model '%s'.", total, LLM_MODEL)

    for idx, job in enumerate(jobs, start=1):
        title   = job.get("title", "?")
        company = job.get("company", "?")

        result = evaluate_job(job)

        job["llm_score"]  = result["score"]
        job["llm_reason"] = result["reason"]

        if result["match"]:
            matched.append(job)
            logger.info(
                "✓ AI match [%d/%d] score=%d  '%s' @ %s",
                idx, total, result["score"], title, company,
            )
        else:
            logger.debug(
                "✗ AI reject [%d/%d] score=%d  '%s' @ %s  – %s",
                idx, total, result["score"], title, company,
                result["reason"][:80],
            )

        if idx < total:
            time.sleep(delay_between)

    logger.info(
        "AI evaluation complete: %d / %d jobs matched (threshold=%d/10).",
        len(matched), total, LLM_MATCH_THRESHOLD,
    )
    return matched
