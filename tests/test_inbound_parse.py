from inbound_fixtures import GOOD_AUTH, make_email

from jobmecloud.inbound.parse import parse_email


def test_plain_text_body_and_links_are_returned():
    e = parse_email(make_email(text="See https://jobs.example.com/a and (https://jobs.example.com/b)."))
    assert "See https://jobs.example.com/a" in e.text
    assert e.links == ["https://jobs.example.com/a", "https://jobs.example.com/b"]
    assert e.subject == "Daily report"


def test_html_only_body_becomes_text_and_keeps_link_targets():
    e = parse_email(make_email(text=None, html='<p>Apply <a href="https://jobs.example.com/x">here</a></p>'))
    assert "Apply here" in e.text
    assert e.links == ["https://jobs.example.com/x"]


def test_base64_and_quoted_printable_bodies_are_decoded():
    for cte in ("base64", "quoted-printable"):
        e = parse_email(make_email(text="Café — https://jobs.example.com/café", cte=cte))
        assert "Café —" in e.text


def test_text_part_is_preferred_over_html_and_html_links_are_added():
    e = parse_email(make_email(text="plain version https://jobs.example.com/p",
                               html='<p>html version <a href="https://jobs.example.com/h">h</a></p>'))
    assert "plain version" in e.text and "html version" not in e.text
    assert e.links == ["https://jobs.example.com/p", "https://jobs.example.com/h"]


def test_body_over_the_limit_is_cut_and_marked_truncated():
    e = parse_email(make_email(text="x" * 500), max_chars=50)
    assert len(e.text) == 50 and e.truncated is True
    assert parse_email(make_email(text="short")).truncated is False


def test_ses_verdict_and_authentication_headers_are_read():
    auth = "amazonses.com; dkim=pass header.d=example.com header.s=a; dkim=fail header.d=other.example.net"
    e = parse_email(make_email(auth=auth))
    assert e.spam_pass and e.virus_pass
    assert e.dkim_domains == ["example.com"]  # the failing signature is not listed


def test_dkim_identity_form_header_i_is_read_too():
    e = parse_email(make_email(auth="amazonses.com; dkim=pass header.i=@example.com"))
    assert e.dkim_domains == ["example.com"]


def test_missing_verdict_headers_count_as_not_passed():
    e = parse_email(make_email(spam=None, virus=None, auth=None))
    assert (e.spam_pass, e.virus_pass, e.dkim_domains) == (False, False, [])


def test_verdicts_other_than_pass_are_not_passed():
    e = parse_email(make_email(spam="FAIL", virus="GRAY"))
    assert e.spam_pass is False and e.virus_pass is False


def test_authentication_result_not_added_by_ses_is_ignored():
    """A sender can write their own Authentication-Results line; only SES's (the first, from amazonses.com) counts."""
    e = parse_email(make_email(auth="mx.other.example; dkim=pass header.d=example.com"))
    assert e.dkim_domains == []
    forged = make_email(auth="amazonses.com; dkim=fail header.d=example.com",
                        extra_headers=[("Authentication-Results", "amazonses.com; dkim=pass header.d=example.com")])
    assert parse_email(forged).dkim_domains == []


def test_display_name_is_ignored_only_the_address_is_used():
    e = parse_email(make_email(sender="Sender@Example.COM", display="boss@elsewhere.example.net"))
    assert e.sender == "sender@example.com"


def test_ambiguous_or_malformed_from_header_gives_no_sender():
    """An unquoted display name that contains an address must never be mistaken for the sender."""
    e = parse_email(make_email(raw_from="boss@elsewhere.example.net <sender@example.com>"))
    assert e.sender == ""


def test_recipients_come_from_to_cc_and_the_received_header():
    e = parse_email(make_email(to="Someone <a@example.com>", cc="b@example.com",
                               extra_headers=[("Received", "from mail.example.com by smtp for reports@mail.example.com; Mon")]))
    assert {"a@example.com", "b@example.com", "reports@mail.example.com"} <= set(e.recipients)
