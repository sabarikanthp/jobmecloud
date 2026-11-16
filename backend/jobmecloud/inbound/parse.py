"""Read a raw email (as SES stores it) into text, links, and the checks SES already made.

The message is untrusted: a sender can write any header. Only the *first* Authentication-Results header counts,
and only when it names SES as the one that checked it, because SES puts its own headers at the top.
"""

import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses

from bs4 import BeautifulSoup

SES_AUTHSERV_ID = "amazonses.com"  # confirm against a real message (plan Task 11)
_URL = re.compile(r"https?://[^\s<>\"'\[\]()]+", re.IGNORECASE)
_RECEIVED_FOR = re.compile(r"\bfor\s+<?([^\s<>;]+@[^\s<>;]+)>?", re.IGNORECASE)
_BLOCK_TAGS = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"]


@dataclass
class ParsedEmail:
    sender: str
    recipients: list[str]
    subject: str
    text: str
    links: list[str]
    spam_pass: bool
    virus_pass: bool
    dkim_domains: list[str]
    truncated: bool = False


def _urls_in(text: str) -> list[str]:
    return [u.rstrip(".,;:!?") for u in _URL.findall(text)]


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _addresses(*values: str | None) -> list[str]:
    found = [addr.lower() for _, addr in getaddresses([v for v in values if v]) if "@" in addr]
    return _dedupe(found)


def _html_to_text(html: str) -> tuple[str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    hrefs = [a["href"].strip() for a in soup.find_all("a", href=True) if a["href"].lower().startswith(("http://", "https://"))]
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    text = re.sub(r"[ \t]+", " ", soup.get_text())
    return re.sub(r"\n{3,}", "\n\n", text).strip(), hrefs


def _body(msg: EmailMessage) -> tuple[str, list[str]]:
    plain, html = msg.get_body(preferencelist=("plain",)), msg.get_body(preferencelist=("html",))
    html_text, hrefs = _html_to_text(html.get_content()) if html is not None else ("", [])
    text = plain.get_content() if plain is not None else html_text
    return text, hrefs


def _verdict(msg: EmailMessage, name: str) -> bool:
    return str(msg.get(name) or "").strip().upper() == "PASS"  # the first copy, which is SES's


def _dkim_domains(msg: EmailMessage) -> list[str]:
    headers = msg.get_all("Authentication-Results") or []
    if not headers:
        return []
    segments = str(headers[0]).split(";")
    server = segments[0].split()
    if not server or server[0].lower() != SES_AUTHSERV_ID:
        return []
    domains: list[str] = []
    for seg in segments[1:]:
        if not re.search(r"\bdkim=pass\b", seg, re.IGNORECASE):
            continue
        m = re.search(r"header\.d=([^\s;]+)", seg, re.IGNORECASE) or re.search(
            r"header\.i=@?(?:[^@\s;]*@)?([^\s;]+)", seg, re.IGNORECASE)
        if m:
            domains.append(m.group(1).lower())
    return _dedupe(domains)


def _sender(msg: EmailMessage) -> str:
    """The one From address, or "" when the header is missing, malformed or names several people."""
    header = msg["From"]
    addresses = getattr(header, "addresses", ())
    if len(addresses) != 1 or getattr(header, "defects", ()):
        return ""
    return addresses[0].addr_spec.lower()


def parse_email(raw: bytes, *, max_chars: int = 1_000_000) -> ParsedEmail:
    msg = message_from_bytes(raw, policy=policy.default)
    text, hrefs = _body(msg)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    received = [m for h in (msg.get_all("Received") or []) for m in _RECEIVED_FOR.findall(str(h))]
    return ParsedEmail(
        sender=_sender(msg),
        recipients=_addresses(str(msg.get("To") or ""), str(msg.get("Cc") or ""), str(msg.get("Delivered-To") or ""),
                              str(msg.get("X-Original-To") or ""), *received),
        subject=str(msg.get("Subject") or ""),
        text=text,
        links=_dedupe(_urls_in(text) + hrefs),
        spam_pass=_verdict(msg, "X-SES-Spam-Verdict"),
        virus_pass=_verdict(msg, "X-SES-Virus-Verdict"),
        dkim_domains=_dkim_domains(msg),
        truncated=truncated,
    )
