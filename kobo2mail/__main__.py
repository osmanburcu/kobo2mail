"""CLI entry point: python -m kobo2mail [options].

Never prints submission values, so GitHub Actions logs stay free of personal data
(except in --dry-run, which is meant for manual tests).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from .config import ConfigError, form_config, load_config
from .fields import find_recipient
from .mailer import MailError, build_message, send
from .pdf import PdfError, render_pdf
from .render import render_email

IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def log(message):
    print(f"[kobo2mail] {message}", flush=True)


def mask(value):
    if IN_ACTIONS and value:
        print(f"::add-mask::{value}", flush=True)


def _as_submission(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("submission must be a JSON object")
    return value


def load_submission(args):
    if args.submission:
        data = json.loads(Path(args.submission).read_text(encoding="utf-8"))
        # Accept either a bare submission or a saved dispatch event.
        return _as_submission(data.get("client_payload", {}).get("submission", data))

    event_path = args.event or os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise ValueError("No input: pass --submission FILE or --event PATH")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if "client_payload" in event:  # repository_dispatch from the Kobo REST Service
        return _as_submission(event["client_payload"].get("submission"))
    if "inputs" in event:  # manual workflow_dispatch test
        return _as_submission(event["inputs"].get("submission") or "")
    raise ValueError("Event has neither client_payload nor inputs")


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="kobo2mail", description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--event", help="GitHub event JSON (default: $GITHUB_EVENT_PATH)")
    source.add_argument("--submission", help="Kobo submission JSON file")
    parser.add_argument("--config", default="config.json", help="Config file (default: config.json)")
    parser.add_argument("--provider", choices=("gmail", "smtp"),
                        help="Override provider (default: $MAIL_PROVIDER, then config)")
    parser.add_argument("--template", help="Override the template from config (e.g. templates/modern.html)")
    parser.add_argument("--dry-run", action="store_true", help="Render and print, do not send")
    parser.add_argument("--preview", metavar="FILE", help="Write the HTML body to FILE, do not send")
    parser.add_argument("--pdf-out", metavar="FILE", help="Write the PDF copy to FILE, do not send")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        config = load_config(args.config)
        submission = load_submission(args)
    except (ConfigError, ValueError, OSError) as exc:
        log(f"ERROR: {exc}")
        return 1

    cfg = form_config(config, submission)
    if args.template:
        cfg["template"], cfg["template_path"] = args.template, Path(args.template)
    log(f"Form {submission.get('_xform_id_string', '?')}, submission {submission.get('_id', '?')}")

    recipient = find_recipient(submission, cfg["EMAIL_FIELD"])
    mask(recipient)
    if not recipient:
        where = f"field '{cfg['EMAIL_FIELD']}'" if cfg["EMAIL_FIELD"] else "any *email field"
        log(f"No valid recipient in {where}; nothing to send.")
        return 0

    try:
        template_text = cfg["template_path"].read_text(encoding="utf-8")
    except OSError:
        log(f"ERROR: template not found: {cfg['template']}")
        return 1
    subject, html, text = render_email(submission, cfg, template_text)

    if args.preview:
        Path(args.preview).write_text(html, encoding="utf-8")
        log(f"Preview written to {args.preview}")
        return 0

    if args.pdf_out:
        try:
            _, data = render_pdf(submission, cfg)
        except PdfError as exc:
            log(f"ERROR: {exc}")
            return 1
        Path(args.pdf_out).write_bytes(data)
        log(f"PDF written to {args.pdf_out}")
        return 0

    attachments = []
    if cfg["pdf"]:
        try:
            filename, data = render_pdf(submission, cfg)
            attachments.append((filename, data))
            log(f"PDF attached ({len(data) // 1024} KB).")
        except PdfError as exc:
            # The respondent still gets their copy, just without the PDF.
            log(f"WARNING: PDF skipped: {exc}")

    sender = os.environ.get("MAIL_FROM", "").strip() or os.environ.get("SMTP_USER", "").strip()
    msg = build_message(
        sender=sender or "sender@example.org",
        sender_name=cfg["from_name"],
        to=recipient,
        subject=subject,
        text=text,
        html=html,
        reply_to=os.environ.get("MAIL_REPLY_TO", "").strip(),
        bcc=os.environ.get("MAIL_BCC", "").strip(),
        attachments=attachments,
    )

    if args.dry_run:
        log("Dry run, not sending. Message:")
        for header in ("From", "To", "Reply-To", "Subject"):
            if msg[header]:
                print(f"{header}: {msg[header]}")
        for filename, _ in attachments:
            print(f"Attachment: {filename}")
        print()
        print(text)
        return 0

    provider = args.provider or os.environ.get("MAIL_PROVIDER", "").strip() or config["provider"]
    try:
        send(msg, provider)
    except MailError as exc:
        log(f"ERROR: {exc}")
        return 1
    log(f"Email sent via {provider}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
