"""
test_email.py – Test Gmail SMTP credentials and delivery in isolation.

Sends a single test email without running any scrapers.
Run this first to confirm email works before running main.py.

Usage:
    python test_email.py
"""

import os
import smtplib
import sys

# Fix Windows console encoding so Unicode box-drawing characters render correctly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

GMAIL_USER      = os.getenv("GMAIL_USER", "")
GMAIL_PASSWORD  = os.getenv("GMAIL_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587

# ---------------------------------------------------------------------------
# Step 1 – Validate .env values before attempting any connection
# ---------------------------------------------------------------------------

def validate_credentials() -> bool:
    ok = True

    print("\n── Credential check ──────────────────────────────────────────")

    if not GMAIL_USER:
        print("  [FAIL] GMAIL_USER is empty in .env")
        ok = False
    else:
        print(f"  [OK]   GMAIL_USER      = {GMAIL_USER}")

    if not RECIPIENT_EMAIL:
        print("  [FAIL] RECIPIENT_EMAIL is empty in .env")
        ok = False
    else:
        print(f"  [OK]   RECIPIENT_EMAIL = {RECIPIENT_EMAIL}")

    if not GMAIL_PASSWORD:
        print("  [FAIL] GMAIL_PASSWORD is empty in .env")
        ok = False
    else:
        # Strip spaces – App Passwords are sometimes written as "xxxx xxxx xxxx xxxx"
        clean_pw = GMAIL_PASSWORD.replace(" ", "")
        length   = len(clean_pw)
        if length == 16:
            print(f"  [OK]   GMAIL_PASSWORD  = {'*' * 16}  (length {length} – looks like a valid App Password)")
        else:
            print(f"  [WARN] GMAIL_PASSWORD  = {'*' * length}  (length {length})")
            print()
            print("  !! Expected 16 characters (a Gmail App Password).")
            print("  !! A regular Gmail password will be REJECTED by Gmail SMTP.")
            print()
            print("  How to create an App Password:")
            print("    1. Go to https://myaccount.google.com/security")
            print("    2. Enable 2-Step Verification (required)")
            print("    3. Go to https://myaccount.google.com/apppasswords")
            print("    4. Select Mail → Windows Computer → Generate")
            print("    5. Copy the 16-character code into .env as GMAIL_PASSWORD")
            ok = False

    print()
    return ok


# ---------------------------------------------------------------------------
# Step 2 – Test SMTP connection (no email sent yet)
# ---------------------------------------------------------------------------

def test_smtp_connection() -> bool:
    print("── SMTP connection test ───────────────────────────────────────")
    try:
        print(f"  Connecting to {_SMTP_HOST}:{_SMTP_PORT} …")
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            print("  [OK]   TLS handshake succeeded.")

            print("  Logging in …")
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            print("  [OK]   Login successful!\n")
        return True

    except smtplib.SMTPAuthenticationError as exc:
        print(f"\n  [FAIL] Authentication error: {exc}")
        print()
        print("  Most common causes:")
        print("   • You used your regular Gmail password instead of an App Password.")
        print("   • 2-Step Verification is not enabled on the account.")
        print("   • The App Password was revoked or re-generated.")
        print("   • Less secure app access is disabled (use App Password instead).")
        return False

    except smtplib.SMTPConnectError as exc:
        print(f"\n  [FAIL] Could not connect to Gmail SMTP: {exc}")
        print("   • Check your internet connection.")
        print("   • Make sure port 587 is not blocked by a firewall or VPN.")
        return False

    except smtplib.SMTPException as exc:
        print(f"\n  [FAIL] SMTP error: {exc}")
        return False

    except OSError as exc:
        print(f"\n  [FAIL] Network error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Step 3 – Send a real test email
# ---------------------------------------------------------------------------

def send_test_email() -> bool:
    now     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"[Job Agent] Email Test – {now}"

    plain = f"""\
This is a test email from the Germany AI/Robotics Job Agent.

If you received this, your Gmail SMTP setup is working correctly.

Sent: {now}
From: {GMAIL_USER}
To:   {RECIPIENT_EMAIL}
"""

    html = f"""\
<html><body style="font-family:Arial,sans-serif;color:#222;padding:20px;">
  <h2 style="color:#1a73e8;">Job Agent – Email Test</h2>
  <p>This is a test email from the <strong>Germany AI/Robotics Job Agent</strong>.</p>
  <p>If you received this, your Gmail SMTP setup is working correctly.</p>
  <table style="margin-top:16px;border-collapse:collapse;">
    <tr><td style="color:#555;padding:4px 12px 4px 0;"><b>Sent</b></td><td>{now}</td></tr>
    <tr><td style="color:#555;padding:4px 12px 4px 0;"><b>From</b></td><td>{GMAIL_USER}</td></tr>
    <tr><td style="color:#555;padding:4px 12px 4px 0;"><b>To</b></td><td>{RECIPIENT_EMAIL}</td></tr>
  </table>
</body></html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))

    print("── Sending test email ─────────────────────────────────────────")
    print(f"  From    : {GMAIL_USER}")
    print(f"  To      : {RECIPIENT_EMAIL}")
    print(f"  Subject : {subject}")

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

        print()
        print("  [OK]   Email sent successfully!")
        print(f"  Check {RECIPIENT_EMAIL} (including Spam folder).")
        print()
        return True

    except smtplib.SMTPAuthenticationError as exc:
        print(f"\n  [FAIL] Auth failed during send: {exc}")
        return False
    except smtplib.SMTPException as exc:
        print(f"\n  [FAIL] SMTP error during send: {exc}")
        return False
    except OSError as exc:
        print(f"\n  [FAIL] Network error during send: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 64)
    print("  Gmail SMTP Test")
    print("=" * 64)

    # Step 1
    if not validate_credentials():
        print("Fix the .env issues above, then re-run this script.")
        sys.exit(1)

    # Step 2
    if not test_smtp_connection():
        print("SMTP connection failed. Fix the issue above, then re-run.")
        sys.exit(1)

    # Step 3
    if not send_test_email():
        print("Email delivery failed.")
        sys.exit(1)

    print("=" * 64)
    print("  All checks passed. Email is working correctly.")
    print("=" * 64)


if __name__ == "__main__":
    main()
