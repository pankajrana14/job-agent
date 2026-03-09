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
import time
from pathlib import Path
from typing import TypedDict

import litellm

from config import LLM_FALLBACK_MODELS, LLM_MATCH_THRESHOLD, LLM_MODEL

logger = logging.getLogger("job_agent")

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

# ---------------------------------------------------------------------------
# System prompt sent to the LLM before every job evaluation
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""You are an expert career advisor evaluating job postings for a specific candidate.

CANDIDATE PROFILE:
{_PROFILE_TEXT}

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
- Role is outside Germany and not remote for a German employer
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
            response = litellm.completion(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=500,
            )
            raw   = response.choices[0].message.content
            data  = json.loads(raw)
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
            return _FALLBACK   # bad JSON is not a provider issue – don't retry
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
