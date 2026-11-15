from jobmecloud.applydocs.check import code_check
from jobmecloud.applydocs.content import (
    CoverLetter,
    Draft,
    TailoredBullet,
    TailoredContent,
    TailoredRole,
)
from jobmecloud.config.profile import MasterResume, ResumeRole, SearchProfile

R = MasterResume(
    summary="Engineer since 2018.",
    skills=["Python", "SQL"],
    roles=[
        ResumeRole(
            employer="Northwind Labs",
            title="Senior Engineer",
            start="2021",
            end="2025",
            bullets=["Cut costs 20%", "Led a team of 5", "Built pipelines"],
        )
    ],
)


def mk(summary="Engineer since 2018.", bullets=((0, "Cut costs 20%"),), skills=("SQL",),
       paras=("I build pipelines.",), headline=""):
    return Draft(
        content=TailoredContent(
            headline=headline,
            summary=summary,
            roles=[TailoredRole(role=0, bullets=[TailoredBullet(source=s, text=t) for s, t in bullets])],
            skills=list(skills),
        ),
        letter=CoverLetter(greeting="Dear Hiring Manager,", paragraphs=list(paras), sign_off="Sincerely,"),
        changes=[],
    )


def test_new_number_reverts_bullet():
    out, notes = code_check(mk(bullets=((0, "Cut costs 40%"), (1, "Led a team of 5 engineers"))), R, SearchProfile())
    assert [b.text for b in out.content.roles[0].bullets] == ["Cut costs 20%", "Led a team of 5 engineers"]
    assert notes == ["Kept your original wording for a Senior Engineer bullet: it added a number."]


def test_do_not_claim_unknown_source_skill_and_letter():
    prof = SearchProfile(do_not_claim=["Kubernetes"])
    d = mk(summary="Kubernetes expert since 2018.", bullets=((7, "Invented"), (2, "Built pipelines on kubernetes")),
           skills=("SQL", "Rust"), paras=("I grew revenue 300%.", "I like data."))
    out, notes = code_check(d, R, prof)
    assert out.content.summary == "Engineer since 2018."
    assert [(b.source, b.text) for b in out.content.roles[0].bullets] == [(2, "Built pipelines")]
    assert out.content.skills == ["SQL"] and out.letter.paragraphs == ["I like data."]
    assert "Removed skill not in your resume: Rust." in notes and len(notes) == 5


def test_missing_role_is_restored():
    R2 = R.model_copy(update={"roles": R.roles + [ResumeRole(employer="Contoso Health", title="Engineer", bullets=["Did X"])]})
    out, _ = code_check(mk(), R2, SearchProfile())
    assert [r.role for r in out.content.roles] == [0, 1] and out.content.roles[1].bullets[0].text == "Did X"


def test_symbol_terms_are_caught_as_whole_terms():
    prof = SearchProfile(do_not_claim=["C++", "C#", ".NET"])
    d = mk(summary="I know C++ well.", bullets=((2, "C# dev"), (1, "I use .NET daily")))
    out, notes = code_check(d, R, prof)
    assert out.content.summary == "Engineer since 2018."
    assert [b.text for b in out.content.roles[0].bullets] == ["Built pipelines", "Led a team of 5"]
    assert len(notes) == 3


def test_ordinary_terms_match_whole_words_only():
    prof = SearchProfile(do_not_claim=["Java", ".NET"])
    out, notes = code_check(mk(paras=("I write JavaScript.", "I used java.", "ASP.NET apps.")), R, prof)
    assert out.letter.paragraphs == ["I write JavaScript.", "ASP.NET apps."]
    assert len(notes) == 1


def test_repeated_bullet_source_keeps_the_first():
    out, _ = code_check(mk(bullets=((0, "Cut costs 20%"), (2, "Built pipelines"), (0, "Cut costs 20% again"))),
                        R, SearchProfile())
    assert [(b.source, b.text) for b in out.content.roles[0].bullets] == [(0, "Cut costs 20%"), (2, "Built pipelines")]


def _letter(greeting, sign_off):
    d = mk()
    d.letter.greeting, d.letter.sign_off = greeting, sign_off
    return d


def test_greeting_and_sign_off_are_checked():
    out, notes = code_check(_letter("Dear Northwind team of 40,", "Yours, a certified Kubernetes admin"), R,
                            SearchProfile(do_not_claim=["Kubernetes"]))
    assert (out.letter.greeting, out.letter.sign_off) == ("Dear Hiring Manager,", "Sincerely,")
    assert notes == ["Used a standard greeting: the drafted one mentioned something not in your resume.",
                     "Used a standard sign-off: the drafted one mentioned something not in your resume."]


def test_long_greeting_and_sign_off_fall_back():
    out, notes = code_check(_letter("Dear " + "x" * 120, "Best " * 30), R, SearchProfile())
    assert (out.letter.greeting, out.letter.sign_off) == ("Dear Hiring Manager,", "Sincerely,")
    assert len(notes) == 2 and all("too long" in n for n in notes)


def test_supported_greeting_and_sign_off_are_kept():
    out, notes = code_check(_letter("Dear Northwind Labs team,", "Best regards,"), R, SearchProfile())
    assert (out.letter.greeting, out.letter.sign_off, notes) == ("Dear Northwind Labs team,", "Best regards,", [])


ORIGINAL_HEADLINE = "Engineering Leader | Data Platforms | Healthcare Technology"


def _headline(tailored, original=ORIGINAL_HEADLINE, terms=()):
    out, notes = code_check(mk(headline=tailored), R, SearchProfile(do_not_claim=list(terms)), original)
    return out.content.headline, notes


def test_headline_reordered_dropped_or_from_resume_is_kept():
    assert _headline("Data Platforms | Engineering Leader") == ("Data Platforms | Engineering Leader", [])
    assert _headline("Senior Engineer, SQL, Python") == ("Senior Engineer, SQL, Python", [])  # resume wording
    assert _headline("engineering leader · data platforms") == ("engineering leader · data platforms", [])


def test_headline_with_new_number_reverts():
    assert _headline("Engineering Leader | 15 years") == (
        ORIGINAL_HEADLINE, ["Kept your original headline: it added a number."])
    assert _headline("Engineer since 2018 | Data Platforms")[1] == []       # a number the resume has


def test_headline_with_do_not_claim_term_reverts():
    assert _headline("Engineering Leader | Data Platforms", terms=["Data"])[1] == [
        "Kept your original headline: it mentioned Data."]


def test_headline_with_invented_phrase_reverts():
    assert _headline("Engineering Leader | Blockchain Guru") == (
        ORIGINAL_HEADLINE, ["Kept your original headline: it used wording that isn't in your resume."])


def test_headline_too_long_reverts():
    long = " | ".join(["Data Platforms"] * 20)
    assert len(long) > 200
    assert _headline(long) == (ORIGINAL_HEADLINE, ["Kept your original headline: it was too long."])


def test_headline_empty_cases():
    assert _headline("Anything | at all", original="") == ("", [])           # no original: always empty
    assert _headline("", original=ORIGINAL_HEADLINE) == (ORIGINAL_HEADLINE, [])
    assert _headline("", original="") == ("", [])


R2 = MasterResume(
    summary="Leader of platform teams.",
    skills=["Python", "Airflow", "SQL"],
    roles=[ResumeRole(employer="Northwind Labs", title="Senior Engineer", start="2021", end="2025",
                      bullets=["Presented scalable JavaScript dashboards to the director of finance, trusted by 2 teams."])],
)
ORIG2 = "Engineering Leader | Data Platforms"


def _kept(tailored, original=ORIG2):
    out, notes = code_check(mk(headline=tailored), R2, SearchProfile(), original)
    return out.content.headline == tailored, [n for n in notes if "headline" in n]


def test_headline_fragments_and_new_skills_are_rejected():
    for bad in ["Engineering Leader | AI", "Engineering Leader | Rust", "Engineering Leader | Java",
                "Engineering Leader | Scala", "Engineering Leader | R", "Engineering Leader | ead",
                "Director, Engineering", "Director | Data Platforms"]:
        kept, notes = _kept(bad)
        assert not kept and notes == ["Kept your original headline: it used wording that isn't in your resume."], bad


def test_headline_allowed_phrases_are_accepted():
    for good, original in [
        ("Data Platforms | Engineering Leader", ORIG2),
        ("Data Platforms | Engineering Leader", "Engineering Leader - Data Platforms"),
        ("Engineering Leader | Data Platforms", "Engineering\u00a0Leader | Data Platforms"),
        ("Engineering Leader | Data Platforms.", ORIG2),
        ("Engineering   Leader |  Data Platforms", ORIG2),
        ("Engineering Leader | Airflow", ORIG2),                  # a listed skill
        ("Engineering Leader | Senior Engineer", ORIG2),  # a role title
        ("Engineering Leader | director of finance", ORIG2),     # two words, from a bullet
    ]:
        kept, notes = _kept(good, original)
        assert kept and notes == [], good
