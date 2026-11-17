from jobmecloud.config.profile import MasterResume, ResumeRole
from jobmecloud.resumes.mapping import MappedParagraph, ResumeMapping, realign_mapping, role_keys

B = ["Grew the engineering organization from 15 to 20 engineers across three countries.",
     "Reduced deployment cycle time by about 30% through CI/CD improvements.",
     "Coached team members into technical leads and directed architecture reviews."]
C = ["Owned technology and product strategy for a multi-product SaaS portfolio.",
     "Managed technology budgets, vendor relationships and engineering allocation."]
SUMMARY = "Engineering executive leading enterprise SaaS and cloud platform engineering teams."
READING = MasterResume(summary=SUMMARY, roles=[
    ResumeRole(employer="Tailspin Cloud", title="Senior Director of Engineering", start="January 2024", end="October 2026", bullets=B),
    ResumeRole(employer="Fabrikam Systems", title="Chief Technology Officer", start="May 2015", end="December 2023", bullets=C),
], skills=["Python"])


def para(i, text, label):
    return MappedParagraph(index=i, text=text, label=label)


def broken_like_production() -> ResumeMapping:
    """What the AI drew for a real resume: the employer and dates line was counted as the first bullet,
    the last bullet was left unlabelled, and both the summary heading and its text were called the summary."""
    return ResumeMapping(role_keys=role_keys(READING), paragraphs=[
        para(0, "Jordan Example", "keep"),
        para(1, "Maryland | 555-0100 | jordan@example.com", "keep"),
        para(2, "Professional Summary", "summary"),
        para(3, SUMMARY, "summary"),
        para(4, "Professional Experience", "keep"),
        para(5, "Senior Director of Engineering", "keep"),
        para(6, "Tailspin Cloud | Remote | January 2024 – October 2026", "bullet:0:0"),
        para(7, B[0], "bullet:0:1"),
        para(8, B[1], "bullet:0:2"),
        para(9, B[2], "keep"),
        para(10, "Chief Technology Officer", "keep"),
        para(11, "Fabrikam Systems | Maryland | May 2015 – December 2023", "bullet:1:0"),
        para(12, C[0], "bullet:1:1"),
        para(13, C[1], "keep"),
    ])


def labels(m):
    return [p.label for p in m.paragraphs]


def test_the_employer_and_dates_line_is_no_longer_a_bullet_and_every_bullet_gets_its_own_slot():
    fixed = realign_mapping(broken_like_production(), READING)
    assert labels(fixed)[5:10] == ["keep", "keep", "bullet:0:0", "bullet:0:1", "bullet:0:2"]
    assert labels(fixed)[10:14] == ["keep", "keep", "bullet:1:0", "bullet:1:1"]


def test_only_the_summary_text_is_the_summary_not_its_heading():
    fixed = realign_mapping(broken_like_production(), READING)
    assert labels(fixed)[2:4] == ["keep", "summary"]


def test_other_labels_are_left_alone():
    fixed = realign_mapping(broken_like_production(), READING)
    assert labels(fixed)[:2] == ["keep", "keep"] and fixed.role_keys == role_keys(READING) and fixed.paragraphs[3].text == SUMMARY


def test_a_mapping_that_already_matches_the_reading_is_returned_unchanged():
    good = realign_mapping(broken_like_production(), READING)
    assert realign_mapping(good, READING) == good


def test_a_stale_mapping_is_not_touched():
    stale = broken_like_production().model_copy(update={"stale": True})
    assert realign_mapping(stale, READING) == stale


def test_a_mapping_that_cannot_be_matched_to_the_reading_is_left_as_it_was():
    other = MasterResume(summary="Something else entirely.", roles=[
        ResumeRole(employer="Zed", title="Dev", start="2000", end="2001", bullets=["Wrote entirely unrelated things."])])
    broken = broken_like_production()
    broken.paragraphs[2] = para(2, "Professional Summary", "keep")  # one summary only: nothing to repair there
    assert realign_mapping(broken, other) == broken


def test_a_repeated_bullet_is_matched_in_order_not_twice():
    reading = READING.model_copy(update={"roles": [READING.roles[0].model_copy(update={"bullets": [B[0], B[1], B[0]]})]})
    m = ResumeMapping(paragraphs=[para(0, B[0], "bullet:0:0"), para(1, B[1], "keep"), para(2, B[0], "keep")])
    assert labels(realign_mapping(m, reading)) == ["bullet:0:0", "bullet:0:1", "bullet:0:2"]


def test_small_wording_differences_between_the_file_and_the_reading_still_match():
    m = broken_like_production()
    m.paragraphs[7] = para(7, B[0].replace("three countries", "3 countries"), "bullet:0:1")
    assert labels(realign_mapping(m, READING))[7] == "bullet:0:0"


def test_a_mapping_made_for_different_jobs_is_left_for_the_remapping_to_handle():
    m = broken_like_production().model_copy(update={"role_keys": ["not|the|same|jobs"]})
    assert role_keys(READING) != m.role_keys
    assert realign_mapping(m, READING) == m


def test_reordered_jobs_in_the_reading_still_match_their_own_bullets():
    reordered = READING.model_copy(update={"roles": [READING.roles[1], READING.roles[0]]})
    m = broken_like_production().model_copy(update={"role_keys": []})
    fixed = realign_mapping(m, reordered)
    assert labels(fixed)[7:10] == ["bullet:1:0", "bullet:1:1", "bullet:1:2"]
    assert labels(fixed)[12:14] == ["bullet:0:0", "bullet:0:1"]
