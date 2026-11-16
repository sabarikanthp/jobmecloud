"""Build raw email messages for the inbound-mail tests. Only example.com names are used."""

from email.message import EmailMessage
from email.utils import formataddr

GOOD_AUTH = "amazonses.com; spf=pass smtp.mailfrom=example.com; dkim=pass header.d=example.com"


def make_email(
    *,
    sender: str = "sender@example.com",
    display: str = "Sender Name",
    to: str = "reports@mail.example.com",
    cc: str | None = None,
    subject: str = "Daily report",
    text: str | None = "Hello",
    html: str | None = None,
    spam: str | None = "PASS",
    virus: str | None = "PASS",
    auth: str | None = GOOD_AUTH,
    cte: str | None = None,
    extra_headers: list[tuple[str, str]] | None = None,
    raw_from: str | None = None,
) -> bytes:
    """The headers SES adds (verdicts and Authentication-Results) go first, as SES prepends them."""
    msg = EmailMessage()
    if auth is not None:
        msg["Authentication-Results"] = auth
    if spam is not None:
        msg["X-SES-Spam-Verdict"] = spam
    if virus is not None:
        msg["X-SES-Virus-Verdict"] = virus
    msg["From"] = raw_from or formataddr((display, sender))
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    for name, value in extra_headers or []:
        msg[name] = value
    kwargs = {"cte": cte} if cte else {}
    if text is not None and html is not None:
        msg.set_content(text, **kwargs)
        msg.add_alternative(html, subtype="html")
    elif html is not None:
        msg.set_content(html, subtype="html", **kwargs)
    else:
        msg.set_content(text or "", **kwargs)
    return msg.as_bytes()
