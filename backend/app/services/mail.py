"""Outreach hand-off to Gmail.

MailSuite (formerly Mailtrack) is a Chrome extension and Workspace add-on, not
an API: its tracking pixel is injected when *you* send from Gmail, and its
Zapier integration pushes open-notifications outward. There is no endpoint to
push drafts in. That is fine, and it simplifies the design — anything that lands
a message in Gmail is tracked automatically once sent.

So the hand-off targets Gmail directly, two ways:

* a **compose deep link**, which opens Gmail with the message pre-filled and
  needs no OAuth at all;
* an **.eml download**, which drags into Gmail (or any mail client) as a draft.

`GmailApiProvider` in `integrations/mail/` is the server-side batch route, gated
on credentials like every other provider here.

Recipient addresses are deliberately left blank when we do not have a verified
one. Guessing `first.last@domain.com` would be fabrication, and a bounced first
touch costs more than the thirty seconds it takes a rep to look one up.
"""

from __future__ import annotations

import io
import zipfile
from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import quote

GMAIL_COMPOSE = "https://mail.google.com/mail/?view=cm&fs=1"


def gmail_compose_url(subject: str, body: str, to: str | None = None) -> str:
    """A one-click Gmail compose window, pre-filled. No auth, no setup."""
    parts = [GMAIL_COMPOSE]
    if to:
        parts.append(f"to={quote(to)}")
    parts.append(f"su={quote(subject)}")
    parts.append(f"body={quote(body)}")
    return "&".join(parts)


def build_eml(
    subject: str,
    body: str,
    to: str | None = None,
    to_name: str | None = None,
    company: str | None = None,
) -> bytes:
    """An RFC822 message that Gmail accepts as a draft when dragged in."""
    message = EmailMessage()
    message["Subject"] = subject
    if to:
        message["To"] = f"{to_name} <{to}>" if to_name else to
    elif to_name:
        # No verified address: carry the name so the rep knows who it is for.
        message["X-Intended-Recipient"] = to_name
    if company:
        message["X-Prospect-Company"] = company
    message["Date"] = formatdate(localtime=True)
    message["X-Generated-By"] = "Tedlar Lead Agent"
    message.set_content(body)
    return message.as_bytes()


def _safe(name: str) -> str:
    keep = [c if c.isalnum() or c in "-_ " else "-" for c in name]
    return "".join(keep).strip().replace(" ", "-")[:60] or "draft"


def build_eml_bundle(drafts: list[dict]) -> bytes:
    """A zip of .eml files, one per draft, named for the company.

    `drafts` items need: subject, body, company, and optionally to / to_name.
    """
    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for draft in drafts:
            stem = _safe(draft.get("company") or draft.get("subject") or "draft")
            name, n = f"{stem}.eml", 2
            while name in used:
                name, n = f"{stem}-{n}.eml", n + 1
            used.add(name)
            archive.writestr(
                name,
                build_eml(
                    subject=draft["subject"],
                    body=draft["body"],
                    to=draft.get("to"),
                    to_name=draft.get("to_name"),
                    company=draft.get("company"),
                ),
            )
        archive.writestr(
            "README.txt",
            "Tedlar Lead Agent — outreach drafts\n\n"
            "Drag any .eml into Gmail to create a draft, or open Gmail and use\n"
            "File > Import. Once you send it, MailSuite/Mailtrack tracks opens and\n"
            "forwards automatically — no extra setup needed.\n\n"
            "Recipient addresses are blank where no verified address was found.\n"
            "They were deliberately not guessed.\n",
        )
    return buffer.getvalue()
