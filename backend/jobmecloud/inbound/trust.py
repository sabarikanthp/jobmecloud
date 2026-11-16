"""Decide whether an inbound email may start a run. Every check must pass."""

from dataclasses import dataclass

from jobmecloud.inbound.parse import ParsedEmail


@dataclass(frozen=True)
class TrustConfig:
    address: str  # the one address reports are sent to
    sender: str  # the one address allowed to send them


def _dkim_covers(sender: str, domains: list[str]) -> bool:
    """A passing signature counts for the sender's own domain or a parent of it (never a lookalike)."""
    sender_domain = sender.rpartition("@")[2]
    return any(sender_domain == d or sender_domain.endswith("." + d) for d in domains)


def check_trust(email: ParsedEmail, config: TrustConfig) -> str | None:
    """A plain-language reason to reject the email, or None when it is trusted."""
    if email.truncated:
        return "The message is too large."
    if config.address.lower() not in {r.lower() for r in email.recipients}:
        return "The message was not addressed to the report address."
    if email.sender.lower() != config.sender.lower():
        return "The sender is not the allowed sender."
    if not (email.spam_pass and email.virus_pass):
        return "The spam or virus check did not pass."
    if not _dkim_covers(email.sender.lower(), [d.lower() for d in email.dkim_domains]):
        return "The sender's signature (DKIM) did not verify for the sender's domain."
    return None
