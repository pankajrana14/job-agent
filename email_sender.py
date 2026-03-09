"""
email_sender.py – Send structured job-update emails via Gmail SMTP.

Credentials are read from environment variables (see .env.example).
Uses TLS (port 587) — the recommended approach with Gmail App Passwords.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import GMAIL_PASSWORD, GMAIL_USER, RECIPIENT_EMAIL
from utils import get_current_date

logger = logging.getLogger("job_agent")

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


# ---------------------------------------------------------------------------
# Email body builders
# ---------------------------------------------------------------------------

def _build_plain_text_body(jobs: list[dict]) -> str:
    lines: list[str] = []
    date_str = get_current_date()

    if not jobs:
        lines.append("No new relevant jobs found in this cycle.")
        lines.append("")
        lines.append(f"Date: {date_str}")
        return "\n".join(lines)

    lines.append(f"NEW JOBS FOUND  ({date_str})")
    lines.append("=" * 60)
    lines.append("")

    for idx, job in enumerate(jobs, start=1):
        lines.append(f"[{idx}]  {job.get('title', 'N/A')}")
        lines.append(f"  Company   : {job.get('company', 'N/A')}")
        lines.append(f"  Location  : {job.get('location', 'N/A')}")
        lines.append(f"  Platform  : {job.get('platform', 'N/A')}")
        lines.append(f"  Experience: {job.get('experience_level', 'N/A')}")
        lines.append(f"  Posted    : {job.get('posting_date', 'N/A')}")
        lines.append(f"  Link      : {job.get('url', 'N/A')}")
        lines.append("")

        score  = job.get("llm_score", 0)
        reason = job.get("llm_reason", "")

        if score:
            lines.append(f"  AI Score  : {score}/10")
        if reason:
            lines.append(f"  AI Verdict: {reason}")
        lines.append("")
        lines.append("-" * 60)
        lines.append("")

    lines.append(f"Total new jobs: {len(jobs)}")
    lines.append("")
    lines.append("-- Germany Job Agent --")
    return "\n".join(lines)


def _build_html_body(jobs: list[dict]) -> str:
    date_str = get_current_date()

    css = """
    body { font-family: Arial, sans-serif; color: #222; background: #f9f9f9; }
    .container { max-width: 700px; margin: 20px auto; background: #fff;
                 border: 1px solid #ddd; border-radius: 6px; padding: 24px; }
    h1 { color: #1a73e8; font-size: 22px; border-bottom: 2px solid #1a73e8;
         padding-bottom: 8px; }
    .job-card { border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px;
                margin-bottom: 20px; background: #fafafa; }
    .job-title { font-size: 17px; font-weight: bold; color: #0d47a1;
                 margin-bottom: 8px; }
    .score-bar { display: inline-block; font-size: 13px; font-weight: bold;
                 color: #fff; background: #1a73e8; border-radius: 12px;
                 padding: 2px 10px; margin-bottom: 8px; }
    .meta-table { border-collapse: collapse; width: 100%; margin-bottom: 10px; }
    .meta-table td { padding: 3px 8px; vertical-align: top; }
    .meta-table td:first-child { color: #555; font-weight: bold;
                                  width: 100px; white-space: nowrap; }
    .ai-reason { font-size: 14px; color: #333; line-height: 1.6; margin-top: 8px;
                 background: #e8f0fe; border-left: 3px solid #1a73e8;
                 padding: 8px 12px; border-radius: 0 4px 4px 0; }
    .ai-reason-label { font-size: 11px; font-weight: bold; color: #1a73e8;
                       text-transform: uppercase; letter-spacing: 0.5px;
                       margin-bottom: 4px; }
    .link-btn { display: inline-block; margin-top: 12px; padding: 7px 14px;
                background: #1a73e8; color: #fff; border-radius: 4px;
                text-decoration: none; font-size: 13px; }
    .footer { font-size: 12px; color: #888; text-align: center;
              margin-top: 20px; border-top: 1px solid #eee; padding-top: 12px; }
    .empty { color: #888; font-style: italic; }
    """

    parts = [
        f"<html><head><style>{css}</style></head><body>",
        '<div class="container">',
        f'<h1>Germany Job Update &ndash; {date_str}</h1>',
    ]

    if not jobs:
        parts.append(
            '<p class="empty">No new relevant jobs found in this cycle.</p>'
        )
    else:
        parts.append(
            f"<p><strong>{len(jobs)} new job(s)</strong> matched your profile:</p>"
        )
        for idx, job in enumerate(jobs, start=1):
            title      = job.get("title", "N/A")
            company    = job.get("company", "N/A")
            location   = job.get("location", "N/A")
            platform   = job.get("platform", "N/A")
            experience = job.get("experience_level", "N/A") or "N/A"
            posted     = job.get("posting_date", "N/A") or "N/A"
            url        = job.get("url", "#")
            score      = job.get("llm_score", 0)
            reason     = job.get("llm_reason", "")

            score_stars = "★" * score + "☆" * (10 - score)
            score_html  = f'<div class="score-bar">AI Score: {score}/10 &nbsp;{score_stars}</div>'

            reason_html = ""
            if reason:
                reason_html = (
                    f'<div class="ai-reason">'
                    f'<div class="ai-reason-label">Why it matches</div>'
                    f'{reason}'
                    f'</div>'
                )

            parts.append(
                f"""
                <div class="job-card">
                  <div class="job-title">{idx}. {title}</div>
                  {score_html}
                  <table class="meta-table">
                    <tr><td>Company</td><td>{company}</td></tr>
                    <tr><td>Location</td><td>{location}</td></tr>
                    <tr><td>Platform</td><td>{platform}</td></tr>
                    <tr><td>Experience</td><td>{experience}</td></tr>
                    <tr><td>Posted</td><td>{posted}</td></tr>
                  </table>
                  {reason_html}
                  <a class="link-btn" href="{url}" target="_blank">View Job &rarr;</a>
                </div>
                """
            )

        parts.append(f"<p><strong>Total new jobs: {len(jobs)}</strong></p>")

    parts.append(
        f'<div class="footer">Germany Job Agent &bull; {date_str}</div>'
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# SMTP sender
# ---------------------------------------------------------------------------

def send_email(jobs: list[dict]) -> bool:
    """
    Send the job-update email.

    Parameters
    ----------
    jobs : list of job dicts (may be empty – in that case a "no new jobs" email is sent)

    Returns
    -------
    bool – True on success, False on failure.
    """
    if not GMAIL_USER or not GMAIL_PASSWORD or not RECIPIENT_EMAIL:
        logger.error(
            "Email credentials not set. Check GMAIL_USER, GMAIL_PASSWORD, "
            "and RECIPIENT_EMAIL in your .env file."
        )
        return False

    date_str = get_current_date()
    subject = f"Germany AI/Robotics Job Update – {date_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL

    plain = _build_plain_text_body(jobs)
    html = _build_html_body(jobs)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        logger.info("Connecting to Gmail SMTP (%s:%d) …", _SMTP_HOST, _SMTP_PORT)
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

        logger.info(
            "Email sent to %s: '%s' (%d jobs).",
            RECIPIENT_EMAIL, subject, len(jobs),
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. Make sure you are using an App Password, "
            "not your regular Gmail password. See README for setup instructions."
        )
    except smtplib.SMTPException as exc:
        logger.error("SMTP error while sending email: %s", exc)
    except OSError as exc:
        logger.error("Network error while sending email: %s", exc)

    return False
