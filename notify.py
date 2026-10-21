"""Email alerts for the power monitor.

Sent over plain SMTP (stdlib only) so any mailbox with an app password works:
Gmail (smtp.gmail.com:465) or Yahoo (smtp.mail.yahoo.com:465). Configured
entirely through environment variables / repository secrets; when SMTP_USER is
unset nothing is sent and the check carries on as before.
"""
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from zoneinfo import ZoneInfo

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
ALERT_FROM = os.environ.get("ALERT_FROM", "").strip() or SMTP_USER
ALERT_TO = [a.strip() for a in os.environ.get("ALERT_TO", "").split(",") if a.strip()]
STATUS_URL = os.environ.get("STATUS_URL", "https://milanoleonardo.github.io/nassau-power-monitor/")

TZ = ZoneInfo("America/Nassau")


def enabled():
    return bool(SMTP_USER and SMTP_PASSWORD and ALERT_TO)


def local(ts):
    """'2026-10-21T11:26:36Z' -> 'Tue 21 Oct, 07:26' in Nassau time."""
    d = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)
    return d.strftime("%a %-d %b, %H:%M")


def duration(seconds):
    m = int(seconds) // 60
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} h {m:02d} min"
    d, h = divmod(h, 24)
    return f"{d} d {h} h"


def send(subject, body):
    if not enabled():
        print("email alerts not configured (SMTP_USER / SMTP_PASSWORD / ALERT_TO); skipping")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Nassau power monitor <{ALERT_FROM}>"
    msg["To"] = ", ".join(ALERT_TO)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="nassau-power-monitor")
    msg.set_content(body)
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30, context=ssl.create_default_context()) as s:
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        # Never let a mail problem break the check itself; surface it in the Actions log.
        print(f"::warning::email alert failed: {e}", file=sys.stderr)
        return False
    print(f"email sent to {', '.join(ALERT_TO)}: {subject}")
    return True


def outage_started(status):
    since = status["since"]
    confirmed = status["last_check"]
    subject = f"⚡ Power OUT at the Nassau house since {local(since)}"
    body = (
        f"The house router stopped answering from the internet.\n\n"
        f"First failed check:  {local(since)} Nassau time\n"
        f"Confirmed at:        {local(confirmed)} Nassau time "
        f"({status['confirm_checks']} consecutive failed checks)\n\n"
        f"This usually means the electricity is off. It can also be an internet (Aliv) "
        f"outage or a router reboot, so take it as a strong hint rather than proof.\n\n"
        f"You will get another email when the router answers again.\n\n"
        f"Status page: {STATUS_URL}\n"
    )
    return send(subject, body)


def outage_ended(status):
    outage = status["outages"][0]  # most recent first
    subject = f"✅ Power is back at the Nassau house after {duration(outage['duration_s'])}"
    body = (
        f"The house router is answering from the internet again.\n\n"
        f"Outage started:  {local(outage['start'])} Nassau time\n"
        f"Back online:     {local(outage['end'])} Nassau time\n"
        f"Duration:        {duration(outage['duration_s'])}\n\n"
        f"Status page: {STATUS_URL}\n"
    )
    return send(subject, body)


def on_transition(before, after):
    """Called by check.py with the status before and after the latest check."""
    prev = (before or {}).get("state")
    new = after.get("state")
    if new == "down" and prev != "down":
        return outage_started(after)
    if new == "up" and prev == "down":
        return outage_ended(after)
    return None


if __name__ == "__main__":
    # `python3 notify.py` sends a test message so the SMTP settings can be verified.
    ok = send(
        "Test: Nassau power monitor alerts are working",
        f"If you are reading this, outage alerts from the Nassau power monitor are set up.\n\n"
        f"Status page: {STATUS_URL}\n",
    )
    sys.exit(0 if ok else 1)
