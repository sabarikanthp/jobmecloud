import pytest

from jobmecloud.inbound.parse import ParsedEmail
from jobmecloud.inbound.trust import TrustConfig, check_trust

CONFIG = TrustConfig(address="reports@mail.example.com", sender="sender@example.com")


def good(**overrides) -> ParsedEmail:
    fields = dict(sender="sender@example.com", recipients=["reports@mail.example.com"], subject="s", text="t",
                  links=[], spam_pass=True, virus_pass=True, dkim_domains=["example.com"], truncated=False)
    return ParsedEmail(**{**fields, **overrides})


def test_everything_correct_passes():
    assert check_trust(good(), CONFIG) is None


def test_wrong_recipient_is_rejected():
    assert "address" in check_trust(good(recipients=["other@example.com"]), CONFIG)


def test_right_display_name_wrong_address_is_rejected():
    assert "sender" in check_trust(good(sender="other@example.com"), CONFIG)


@pytest.mark.parametrize("field", ["spam_pass", "virus_pass"])
def test_spam_or_virus_not_pass_is_rejected(field):
    assert check_trust(good(**{field: False}), CONFIG) is not None


def test_dkim_passing_for_a_different_domain_than_the_senders_is_rejected():
    assert "signature" in check_trust(good(dkim_domains=["other.example.net"]), CONFIG)


def test_no_dkim_result_is_rejected():
    assert "signature" in check_trust(good(dkim_domains=[]), CONFIG)


def test_dkim_for_the_parent_domain_of_the_sender_is_accepted():
    config = TrustConfig(address="reports@mail.example.com", sender="sender@mail.example.com")
    assert check_trust(good(sender="sender@mail.example.com", dkim_domains=["example.com"]), config) is None


def test_a_longer_lookalike_domain_is_not_a_parent():
    assert check_trust(good(dkim_domains=["notexample.com"]), CONFIG) is not None


def test_truncated_message_is_rejected():
    assert "large" in check_trust(good(truncated=True), CONFIG)


def test_address_comparison_ignores_case():
    config = TrustConfig(address="Reports@Mail.Example.com", sender="Sender@Example.com")
    assert check_trust(good(), config) is None
