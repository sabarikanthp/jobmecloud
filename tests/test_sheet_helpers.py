import pytest

from jobmecloud.importers.sheet_helpers import (
    KIND_FIELDS, default_status, guess_field_type, guess_kind, parse_pay, split_location_mode,
    suggest_for,
)

JOB_HEADERS = ["Employer", "Role", "Requisition / LinkedIn ID", "Application Status", "Decision",
               "Applied Date", "Posted Base Pay", "Location / Work Mode", "Source / ATS URL",
               "Assessment & Historical Notes"]


def test_kind_fields_have_the_spec_keys_and_required_flags():
    keys = {k: [f.key for f in v] for k, v in KIND_FIELDS.items()}
    assert keys["jobs"] == ["employer", "title", "requisition", "location", "pay", "status",
                            "applied_date", "first_response_date", "url", "notes"]
    assert keys["applications"] == ["employer", "title", "requisition", "status", "applied_date",
                                    "first_response_date", "contact", "last_outreach", "next_followup",
                                    "interview_stage", "notes"]
    assert keys["contacts"] == ["name", "employer", "related_role", "outreach_date", "status_text",
                                "next_action", "source", "notes"]
    required = {k: [f.key for f in v if f.required] for k, v in KIND_FIELDS.items()}
    assert required == {"jobs": ["employer", "title"], "applications": ["employer", "title"],
                        "contacts": ["name"]}


@pytest.mark.parametrize("name,columns,kind", [
    ("Job Master", JOB_HEADERS, "jobs"),
    ("Applications & Followups", ["Employer", "Role", "Applied Date", "Next Follow-up"], "applications"),
    ("Contacts & Referrals", ["Employer / Network", "Contact", "Related Role"], "contacts"),
    ("Sheet1", ["Employer", "Role", "Last Outreach"], "applications"),
    ("Sheet1", ["Employer", "Role", "Status"], "jobs"),
])
def test_guess_kind(name, columns, kind):
    assert guess_kind(name, columns) == kind


def test_suggest_for_jobs_matches_the_workbook_style_headers():
    m = suggest_for("jobs", JOB_HEADERS)
    assert m["employer"] == "Employer"
    assert m["title"] == "Role"
    assert m["requisition"] == "Requisition / LinkedIn ID"
    assert m["status"] == "Application Status"
    assert m["applied_date"] == "Applied Date"
    assert m["pay"] == "Posted Base Pay"
    assert m["location"] == "Location / Work Mode"
    assert m["url"] == "Source / ATS URL"
    assert m["notes"] == "Assessment & Historical Notes"
    assert "work_mode" not in m and "backup_status" not in m and m["first_response_date"] is None
    used = [c for c in m.values() if c]
    assert len(used) == len(set(used))  # a column is never used twice


def test_suggest_for_contacts_and_applications():
    m = suggest_for("contacts", ["Employer / Network", "Contact", "Related Role", "Outreach Date",
                                 "Contact / Referral Status", "Next Action", "Source"])
    assert m == {"name": "Contact", "employer": "Employer / Network", "related_role": "Related Role",
                 "outreach_date": "Outreach Date", "status_text": "Contact / Referral Status",
                 "next_action": "Next Action", "source": "Source", "notes": None}
    a = suggest_for("applications", ["Employer", "Role", "Requisition", "Applied Date", "Current Status",
                                     "Recruiter / Contact", "Last Outreach", "Next Follow-up",
                                     "Response Date", "Interview Stage", "Notes"])
    assert a["status"] == "Current Status" and a["contact"] == "Recruiter / Contact"
    assert a["last_outreach"] == "Last Outreach" and a["next_followup"] == "Next Follow-up"
    assert a["first_response_date"] == "Response Date" and a["interview_stage"] == "Interview Stage"
    assert a["applied_date"] == "Applied Date" and a["notes"] == "Notes"


@pytest.mark.parametrize("text,expected", [
    ("$150,000 - $180,000", (150000, 180000)),
    ("150k-180k", (150000, 180000)),
    ("$165,000", (165000, 165000)),
    ("$95/hr", None),
    ("", None),
    ("negotiable", None),
])
def test_parse_pay(text, expected):
    assert parse_pay(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Remote", (None, "Remote")),
    ("Springfield, IL hybrid", ("Springfield, IL", "Hybrid")),
    ("Portland, OR", ("Portland, OR", None)),
    ("Onsite", (None, "On-site")),
    ("Boston on site", ("Boston", "On-site")),
    ("", (None, None)),
])
def test_split_location_mode(text, expected):
    assert split_location_mode(text) == expected


def test_guess_field_type():
    assert guess_field_type(["2026-03-01", "03/04/2026"]) == ("date", [])
    assert guess_field_type(["1", "2.5", "300"]) == ("number", [])
    kind, options = guess_field_type(["Yes", "No", "Yes", "No", "Yes"])
    assert kind == "choice" and options == ["No", "Yes"]
    assert guess_field_type(["a", "b", "c"]) == ("text", [])  # nothing repeats
    assert guess_field_type([]) == ("text", [])
    long_ones = ["x" * 31, "x" * 31, "y" * 31]
    assert guess_field_type(long_ones)[0] == "text"


@pytest.mark.parametrize("word,status", [
    ("Applied", "Applied"), ("REJECTED", "Rejected"), ("closed", "Closed"), ("Interview", "Interviewing"),
    ("SKIPPED", "Skipped"), ("skip recommended", "Skipped"), ("RECOMMENDED SKIP / PRIOR DECISION", "Skipped"),
    ("DEPRIORITIZED", "Skipped"), ("pass", "Skipped"),
    ("REVIEWED", ""), ("HOLD", ""), ("HISTORICAL / UNVERIFIED", ""), ("not decided", ""),
    ("saved for later", ""), ("referral first", ""), ("whatever", ""), ("", ""),
])
def test_default_status(word, status):
    assert default_status(word) == status
