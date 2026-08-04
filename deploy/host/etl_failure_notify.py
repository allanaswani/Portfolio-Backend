#!/usr/bin/env python3
"""Email an ETL failure alert — RUNS ON THE HOST (python3.6, alongside the ETLs).

When ``etl_request_watcher.sh`` sees a report exit non-zero (or the script is
missing), it calls this notifier with the script name and the captured
stdout/stderr log. We email that error to the ops recipients so a failed
"Send Report" / trigger is visible instead of silently doing nothing.

SMTP config is reused VERBATIM from the data team's ``app_settings`` (the same
``app.hf_email`` dict the reports themselves send with) — so there are NO secrets
in this repo and no separate mail config to keep in sync. ``app_settings.py``
lives on the host in the ETL dir and is imported the same way the reports do
(``import app_settings as app``).

Usage (from the watcher):
    python3 etl_failure_notify.py <script_name> <log_file> [exit_code]

Environment:
    ETL_DIR                 dir containing app_settings.py (default
                            /data/apps/datascience/etls)
    ETL_ALERT_RECIPIENTS    comma-separated To: list (default below)
    ETL_ALERT_MAX_LOG_BYTES tail size of the log to include (default 8000)
"""
import os
import sys
import socket
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

DEFAULT_RECIPIENTS = "datateam@hfcb.co.ke"


def _load_app_settings(etl_dir):
    """Import the data team's app_settings (carries hf_email SMTP creds)."""
    if etl_dir and etl_dir not in sys.path:
        sys.path.insert(0, etl_dir)
    import app_settings as app  # noqa: E402  (host-only module, not in this repo)
    return app


def _read_log_tail(log_file, max_bytes):
    if not log_file or not os.path.isfile(log_file):
        return "(no log captured)"
    try:
        size = os.path.getsize(log_file)
        with open(log_file, "rb") as fh:
            if size > max_bytes:
                fh.seek(-max_bytes, os.SEEK_END)
                data = b"...(truncated; showing last %d bytes)...\n" % max_bytes + fh.read()
            else:
                data = fh.read()
        return data.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — never let log-reading break the alert
        return "(could not read log %s: %s)" % (log_file, exc)


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: etl_failure_notify.py <script_name> <log_file> [exit_code]\n")
        return 2

    script_name = sys.argv[1]
    log_file = sys.argv[2]
    exit_code = sys.argv[3] if len(sys.argv) > 3 else "?"

    etl_dir = os.environ.get("ETL_DIR", "/data/apps/datascience/etls")
    recipients = [
        r.strip() for r in os.environ.get("ETL_ALERT_RECIPIENTS", DEFAULT_RECIPIENTS).split(",")
        if r.strip()
    ]
    max_bytes = int(os.environ.get("ETL_ALERT_MAX_LOG_BYTES", "8000"))

    try:
        app = _load_app_settings(etl_dir)
    except Exception as exc:  # noqa: BLE001
        # Can't load creds → at least surface it in the watcher log; the report
        # failure is already recorded there.
        sys.stderr.write("etl_failure_notify: could not import app_settings from %s: %s\n"
                         % (etl_dir, exc))
        return 1

    from_addr = app.hf_email["user"]
    host = socket.gethostname()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_tail = _read_log_tail(log_file, max_bytes)

    subject = "[ETL FAILED] %s (exit %s) on %s" % (script_name, exit_code, host)
    body = (
        "An ETL report triggered from the portfolio tool FAILED.\n\n"
        "  Report:    %s\n"
        "  Exit code: %s\n"
        "  Host:      %s\n"
        "  Time:      %s\n\n"
        "This means the corresponding 'Send Report' / trigger did NOT send its\n"
        "output. Error output (tail) below:\n\n"
        "%s\n"
    ) % (script_name, exit_code, host, stamp, log_tail)

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        s = smtplib.SMTP(app.hf_email["host"], app.hf_email["port"])
        s.starttls()
        s.login(from_addr, app.hf_email["password"])
        s.sendmail(from_addr, recipients, msg.as_string())
        s.quit()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("etl_failure_notify: send failed: %s\n" % exc)
        return 1

    sys.stdout.write("etl_failure_notify: alert sent to %s\n" % ", ".join(recipients))
    return 0


if __name__ == "__main__":
    sys.exit(main())
