# Job Agent

**AI-powered job-search automation — search any country from a desktop GUI**

Scrapes LinkedIn, StepStone, Xing, and BA Jobbörse, evaluates every posting against
your candidate profile using an LLM, deduplicates results, and delivers a
structured digest email — all configurable through a desktop GUI.

<table>
  <tr>
    <td><img src="docs/screenshot_credentials.png" alt="Credentials tab" width="320"/></td>
    <td><img src="docs/screenshot.png" alt="Configuration tab" width="320"/></td>
    <td><img src="docs/screenshot_run.png" alt="Run Pipeline tab" width="320"/></td>
  </tr>
  <tr>
    <td align="center"><sub>Credentials</sub></td>
    <td align="center"><sub>Configuration</sub></td>
    <td align="center"><sub>Run Pipeline</sub></td>
  </tr>
</table>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![PySide6](https://img.shields.io/badge/PySide6-6.6+-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython)
[![LiteLLM](https://img.shields.io/badge/LiteLLM-Groq%20·%20Claude%20·%20Gemini%20·%20GPT-7C3AED)](https://github.com/BerriAI/litellm)
[![Playwright](https://img.shields.io/badge/Playwright-Chromium-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/python)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## How it works

```
LinkedIn ──┐
StepStone ─┼──► Playwright scraper ──► LiteLLM (score 1–10) ──► SHA-256 dedupe ──► Gmail digest
Xing ─────┤    headless Chromium       any model provider         JSON database     HTML email
BA Jobbörse┘
```

1. **Scrape** — Playwright navigates each platform headlessly, extracts job cards and detail pages.
2. **Evaluate** — Every job is sent to an LLM with your `PROFILE.md` and scored 1–10 for fit.
3. **Deduplicate** — A SHA-256 hash of `(title, company, location)` prevents re-sending the same job.
4. **Deliver** — Matched jobs above your threshold are bundled into a rich HTML email.

The desktop GUI lets you configure most settings without editing code.

---

## Quick start

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) (modern Python package manager).

```bash
git clone https://github.com/yourusername/job-agent
cd job-agent
uv sync                      # creates venv + installs all dependencies
uv run playwright install chromium
copy .env.example .env       # on PowerShell/cmd; use cp on Git Bash
uv run gui.py                # open the desktop GUI
```

Or with plain pip:

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env       # on PowerShell/cmd; use cp on Git Bash
python gui.py                # open the desktop GUI
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Scraping | [Playwright](https://playwright.dev/python) — headless Chromium |
| AI evaluation | [LiteLLM](https://github.com/BerriAI/litellm) — swap any model via one `.env` line, no code changes |
| Desktop GUI | [PySide6](https://doc.qt.io/qtforpython) — Qt 6 with Windows 11 Acrylic blur |
| Email delivery | Gmail SMTP via Python `smtplib` — HTML + plain-text fallback |
| Persistence | JSON flat-file with SHA-256 job IDs |
| Env management | `python-dotenv` — credentials never hard-coded |

---

## Features

- **Multi-country search** — set any country in the GUI; LinkedIn searches the specified country, StepStone switches to its national domain (Germany, Austria, Belgium, Netherlands), and Xing plus BA Jobbörse are auto-skipped for non-Germany searches
- **Four platforms** — LinkedIn, StepStone, Xing Jobs, and BA Jobbörse (Germany's federal employment agency)
- **AI match scoring** — jobs evaluated against a free-text candidate profile, not keyword lists; model and threshold are configurable
- **Multi-model fallback** — primary model + ordered fallback list across providers; if one hits a rate limit the next is tried automatically
- **Duplicate prevention** — SHA-256 content hash; the same posting is never emailed twice even across platforms
- **Desktop GUI** — PySide6 app with sidebar navigation, Windows 11 Acrylic glass effect, and live pipeline output
- **Scheduled runs** — integrates with Windows Task Scheduler for twice-daily automated execution
- **Per-scraper isolation** — one platform failing does not abort the others

---

## Project structure

```
job-agent/
├── gui.py                  # PySide6 desktop app — configure and run the pipeline
├── main.py                 # CLI entry point / pipeline orchestrator
├── config.py               # All tunable parameters
├── scraper_linkedin.py     # LinkedIn scraper (Playwright)
├── scraper_stepstone.py    # StepStone.de scraper (Playwright)
├── scraper_xing.py         # Xing Jobs scraper (Playwright, Germany-only)
├── scraper_ba.py           # BA Jobbörse scraper (REST API)
├── evaluator.py            # LiteLLM-based job scoring
├── email_sender.py         # Gmail SMTP — HTML + plain-text email
├── database.py             # JSON persistence + SHA-256 deduplication
├── utils.py                # Logging, delays, shared helpers
├── PROFILE.md              # Your CV / preferences — edit this for your search
├── .env.example            # Credential template (copy to .env)
├── pyproject.toml          # Dependencies (uv / pip)
└── docs/
    ├── screenshot.png
    ├── screenshot_credentials.png
    └── screenshot_run.png
```

---

## Configuration

### Credentials (`.env`)

```dotenv
GMAIL_USER=you@gmail.com
GMAIL_PASSWORD=xxxx xxxx xxxx xxxx   # Gmail App Password — not your account password
RECIPIENT_EMAIL=you@example.com

GROQ_API_KEY=gsk_...                 # groq.com — free tier, no credit card needed

LLM_MODEL=groq/llama-3.3-70b-versatile
LLM_FALLBACK_MODELS=groq/llama-3.1-8b-instant
LLM_PARALLEL_WORKERS=6
LLM_MATCH_THRESHOLD=7               # Jobs scored below this (1–10) are skipped
```

Generate a Gmail App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
(requires 2-Step Verification).

### Switching LLM models

The agent uses [LiteLLM](https://github.com/BerriAI/litellm) — switching providers requires **only `.env` changes, no code edits**.

Set the API key for your chosen provider, then update `LLM_MODEL` (and optionally `LLM_FALLBACK_MODELS`).
Keep Groq as the last fallback — it is always free and requires no credits.

#### Free tier (no cost)

| Provider | API key | `LLM_MODEL` |
|---|---|---|
| **Groq** (default) | `GROQ_API_KEY` at [groq.com](https://groq.com) | `groq/llama-3.3-70b-versatile` |
| Groq fast fallback | same key | `groq/llama-3.1-8b-instant` |

Groq free tier: 1,000 requests/day, 30 RPM — sufficient for a full run of ~600 jobs.

#### Paid models (higher quality)

| Provider | API key | `LLM_MODEL` |
|---|---|---|
| **Anthropic Claude Sonnet** | `ANTHROPIC_API_KEY` at [platform.anthropic.com](https://platform.anthropic.com) | `claude-sonnet-4-6` |
| Anthropic Claude Opus | same key | `claude-opus-4-8` |
| **OpenAI** | `OPENAI_API_KEY` at [platform.openai.com](https://platform.openai.com) | `gpt-5.5` |
| **Google Gemini** | `GEMINI_API_KEY` at [aistudio.google.com](https://aistudio.google.com) | `gemini/gemini-2.5-pro` |

Example — Claude Sonnet as primary with Groq as free fallback:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...

LLM_MODEL=claude-sonnet-4-6
LLM_FALLBACK_MODELS=claude-haiku-4-5-20251001,groq/llama-3.3-70b-versatile
LLM_PARALLEL_WORKERS=6
```

### Candidate profile (`PROFILE.md`)

Edit `PROFILE.md` with your background, skills, and preferences in plain English.
The LLM reads this file verbatim when evaluating each job — the more specific you are,
the better the filtering.

### Search location (`config.py` or GUI → Configuration tab → Search Location)

Set `SEARCH_COUNTRY` to any country name as recognised by LinkedIn's location filter
(e.g. `"Germany"`, `"United Kingdom"`, `"Netherlands"`, `"India"`).

Keep `LINKEDIN_SEARCH_QUERIES` as role/title keywords only. Do not include country
names such as `"Germany"` or `"Netherlands"` in those queries; LinkedIn already
receives `SEARCH_COUNTRY` through its separate `location` parameter.

| Platform | Country support |
|---|---|
| LinkedIn | Any country |
| StepStone | Germany, Austria, Belgium, Netherlands |
| Xing Jobs | Germany only (skipped automatically for other countries) |
| BA Jobbörse | Germany only (skipped automatically for other countries) |

### Scraping parameters (`config.py` or GUI → Configuration tab)

| Parameter | Default | Description |
|---|---|---|
| `MAX_POSTING_AGE_HOURS` | 36 | Ignore jobs older than this |
| `MAX_PAGES_PER_QUERY` | 2 | Result pages scraped per search |
| `MAX_DETAIL_PAGES_PER_QUERY` | 20 | Individual job pages visited per query |
| `MIN_DELAY` / `MAX_DELAY` | 1.5 / 3.5 s | Random delay between requests |

---

## Running the pipeline

**Via GUI** (recommended):
```bash
uv run gui.py          # open GUI → Run Pipeline tab → Run Now
```

**Via CLI:**
```bash
uv run main.py
```

**Automated — Windows Task Scheduler** (twice daily at 08:00 and 18:00):

1. Copy `run_job_agent.bat.example` to `run_job_agent.bat` and set `PROJECT_DIR` to your install path.
2. Register the tasks:
```powershell
$bat = "$PWD\run_job_agent.bat"
schtasks /create /tn "JobAgentAM" /tr "`"$bat`"" /sc daily /st 08:00 /f
schtasks /create /tn "JobAgentPM" /tr "`"$bat`"" /sc daily /st 18:00 /f
```

The bat file activates the venv, runs `main.py`, and writes a date-stamped log to `logs/`.

---

## How duplicate detection works

Each job produces a SHA-256 hash of `lower(title) + "|" + lower(company) + "|" + lower(location)`.
This ID is stored in `jobs_database.json` after the email is sent.
On every subsequent run the agent checks this ID — so the same posting found on multiple
platforms or across multiple runs is only ever emailed once.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: playwright` | Run `uv sync` then `uv run playwright install chromium` |
| Gmail authentication failed | Use an App Password, not your account password |
| No jobs found | Check `logs/job_agent.log` for selector errors; platform HTML may have changed |
| LinkedIn returns 0 results | Increase `MIN_DELAY` / `MAX_DELAY`; LinkedIn aggressively detects bots |
| Scheduled task fails silently | Task Scheduler → History; verify the working directory is set correctly |



