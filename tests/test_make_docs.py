import json
from datetime import timedelta

import pytest
from sqlmodel import Session

from docx_fixtures import FIXTURE_READING, make_resume_docx
from fakes import (
    NOW,
    FakeProvider,
    add_job,
    draft_json_for_fixture,
    fixture_mapping,
    get_status,
    ready_profile,
    set_status,
    setup_profile,
)
from jobmecloud.applydocs import make_docs as make_docs_module
from jobmecloud.applydocs.make_docs import (
    MISSING_FILE_COPY,
    NO_MAPPING_NOTE,
    NO_RESUME_COPY,
    PLAIN_LAYOUT_NOTE,
    STALE_MAPPING_COPY,
    DocsSetupError,
    make_docs,
    use_as_is,
)
from jobmecloud.applydocs.output import FileInUseError
from jobmecloud.applydocs.pages import UNCONFIRMED_NOTE
from jobmecloud.db.models import Job
from jobmecloud.llm.errors import ProviderError
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.config.profile import save_resume
from jobmecloud.resumes.docx_text import iter_paragraphs
from jobmecloud.resumes.mapping import MappedParagraph, ResumeMapping, remap_mapping, role_keys
from jobmecloud.resumes.store import add_resume, default_entry, file_path, load_mapping, save_mapping, save_reading


def run(data_dir, engine, job_id, p, **kw):
    return make_docs(data_dir, engine, job_id, provider=p, model="m", costs=CostTracker({}, 0),
                     counter=lambda d: 1, now=kw.pop("now", NOW), **kw)


def test_make_docs_writes_folder_and_sets_ready(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine, status="New", match_score=90)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    r = make_docs(data_dir, engine, job_id, provider=p, model="m", costs=CostTracker({}, 0),
                  counter=lambda d: 1, now=NOW)
    assert {f.name for f in r.folder.iterdir()} >= {"resume.docx", "cover-letter.docx", "job.md", "notes.md"}
    assert r.note == "1 page, same as your resume"
    with Session(engine) as s:
        j = s.get(Job, job_id)
        assert (j.status, j.docs_note, j.docs_folder) == ("Ready", r.note, str(r.folder))
    notes = (r.folder / "notes.md").read_text(encoding="utf-8")
    assert "- Put the cost bullet first." in notes and "1 page, same as your resume" in notes


def test_regenerate_archives_and_keeps_applied_status(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine, status="New", match_score=90)
    replies = [draft_json_for_fixture(), '{"problems": []}'] * 2
    p = FakeProvider(replies=replies)
    first = make_docs(data_dir, engine, job_id, provider=p, model="m", costs=CostTracker({}, 0), counter=lambda d: 1, now=NOW)
    set_status(engine, job_id, "Applied")
    make_docs(data_dir, engine, job_id, provider=p, model="m", costs=CostTracker({}, 0), counter=lambda d: 1,
              now=NOW + timedelta(minutes=1), feedback="lean into healthcare")
    assert (first.folder / "previous").is_dir() and get_status(engine, job_id) == "Applied"
    assert "The user asked: lean into healthcare" in p.calls[2]["messages"][0]["content"]


def test_no_resume_and_as_is(data_dir, engine):
    setup_profile(data_dir)
    job_id = add_job(engine, status="New")
    with pytest.raises(DocsSetupError, match="Add your resume"):
        make_docs(data_dir, engine, job_id, provider=FakeProvider(), model="m", costs=CostTracker({}, 0), counter=lambda d: 1, now=NOW)
    e = add_resume(data_dir, name="Short", filename="s.pdf", data=b"%PDF", reading=FIXTURE_READING, mapping=None, make_default=True, now=NOW)
    r = use_as_is(data_dir, engine, job_id, e.id, NOW)
    assert (r.folder / "resume.pdf").read_bytes() == b"%PDF" and r.note == "Using Short as-is"


def test_self_check_problems_trigger_one_revise_and_reach_notes(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": ["The summary overstates scope."]}',
                              draft_json_for_fixture()])
    r = run(data_dir, engine, job_id, p)
    assert p.replies == [] and len(p.calls) == 3
    notes = (r.folder / "notes.md").read_text(encoding="utf-8")
    assert "The summary overstates scope." in notes


def test_code_check_notes_reach_notes_md(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine)
    draft = json.loads(draft_json_for_fixture())
    draft["content"]["skills"].append("Kubernetes")
    p = FakeProvider(replies=[json.dumps(draft), '{"problems": []}'])
    r = run(data_dir, engine, job_id, p)
    notes = (r.folder / "notes.md").read_text(encoding="utf-8")
    assert "Removed skill not in your resume: Kubernetes." in notes


def test_plain_layout_for_non_docx_default(data_dir, engine):
    setup_profile(data_dir)
    add_resume(data_dir, name="PDF", filename="cv.pdf", data=b"%PDF", reading=FIXTURE_READING, mapping=None,
               make_default=True, now=NOW)
    job_id = add_job(engine)
    r = run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    assert r.note == f"{PLAIN_LAYOUT_NOTE} {UNCONFIRMED_NOTE}"
    assert (r.folder / "resume.docx").is_file() and (r.folder / "cover-letter.docx").is_file()


def test_plain_layout_for_docx_without_mapping(data_dir, engine):
    setup_profile(data_dir)
    add_resume(data_dir, name="Old", filename="cv.docx", data=make_resume_docx(), reading=FIXTURE_READING,
               mapping=None, make_default=True, now=NOW)
    job_id = add_job(engine)
    r = run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    assert r.note == f"{NO_MAPPING_NOTE} {UNCONFIRMED_NOTE}"
    assert NO_MAPPING_NOTE == ("JobMe couldn't map the parts of your resume, so it used a plain layout. "
                               "Check the mapping in Settings > Your resume.")


def test_plain_layout_for_docx_whose_mapping_is_all_keep(data_dir, engine):
    setup_profile(data_dir)
    keep = fixture_mapping()
    for p in keep.paragraphs:
        p.label = "keep"
    add_resume(data_dir, name="Old", filename="cv.docx", data=make_resume_docx(), reading=FIXTURE_READING,
               mapping=keep, make_default=True, now=NOW)
    job_id = add_job(engine)
    r = run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    assert r.note.startswith(NO_MAPPING_NOTE + " ")


def test_stale_mapping_is_a_setup_error_and_writes_nothing(data_dir, engine):
    setup_profile(data_dir)
    stale = ResumeMapping(paragraphs=[MappedParagraph(index=0, text="Jordan Example", label="contact")])
    add_resume(data_dir, name="Main", filename="cv.docx", data=make_resume_docx(), reading=FIXTURE_READING,
               mapping=stale, make_default=True, now=NOW)
    job_id = add_job(engine)
    with pytest.raises(DocsSetupError) as info:
        run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    assert str(info.value) == ("The resume file no longer matches its mapping. "
                               "Check the mapping again in Settings > Your resume.")
    assert not (data_dir / "applications").exists()
    with Session(engine) as s:
        assert s.get(Job, job_id).docs_folder is None


def test_failure_leaves_existing_files_untouched(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine)
    first = run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    before = (first.folder / "resume.docx").read_bytes()
    with pytest.raises(ProviderError):
        run(data_dir, engine, job_id, FakeProvider(replies=[ProviderError("boom")]), now=NOW + timedelta(minutes=1))
    assert (first.folder / "resume.docx").read_bytes() == before
    assert not (first.folder / "previous").exists()


def test_file_in_use_propagates_and_moves_nothing(data_dir, engine, monkeypatch):
    ready_profile(data_dir)
    job_id = add_job(engine)
    first = run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))

    def in_use(folder, now):
        raise FileInUseError("resume.docx")

    monkeypatch.setattr(make_docs_module, "archive_previous", in_use)
    with pytest.raises(FileInUseError):
        run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']),
            now=NOW + timedelta(minutes=1))
    assert (first.folder / "resume.docx").is_file()


def test_success_clears_docs_error(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine, docs_error="Earlier failure")
    run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    with Session(engine) as s:
        assert s.get(Job, job_id).docs_error is None


def test_as_is_archives_and_keeps_cover_letter(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine)
    first = run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    set_status(engine, job_id, "Interviewing")
    e = add_resume(data_dir, name="Short", filename="s.pdf", data=b"%PDF", reading=FIXTURE_READING, mapping=None,
                   make_default=False, now=NOW)
    r = use_as_is(data_dir, engine, job_id, e.id, NOW + timedelta(minutes=1))
    assert r.folder == first.folder
    assert (r.folder / "resume.pdf").read_bytes() == b"%PDF" and not (r.folder / "resume.docx").exists()
    assert (r.folder / "cover-letter.docx").is_file()
    assert any((r.folder / "previous").iterdir())
    assert "Used as-is, no changes." in (r.folder / "notes.md").read_text(encoding="utf-8")
    assert get_status(engine, job_id) == "Interviewing"
    with Session(engine) as s:
        assert s.get(Job, job_id).docs_note == "Using Short as-is"


def test_as_is_with_missing_file_is_a_setup_error_and_moves_nothing(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine)
    first = run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    e = add_resume(data_dir, name="Short", filename="s.pdf", data=b"%PDF", reading=FIXTURE_READING, mapping=None,
                   make_default=False, now=NOW)
    file_path(data_dir, e).unlink()
    with pytest.raises(DocsSetupError) as info:
        use_as_is(data_dir, engine, job_id, e.id, NOW + timedelta(minutes=1))
    assert str(info.value) == MISSING_FILE_COPY
    assert {"resume.docx", "cover-letter.docx", "notes.md"} <= {f.name for f in first.folder.iterdir()}
    assert not (first.folder / "previous").exists()


def _keyed_profile(data_dir):
    """ready_profile, with a mapping that records the jobs it was made for."""
    ready_profile(data_dir)
    entry = default_entry(data_dir)
    save_mapping(data_dir, entry.id, fixture_mapping().model_copy(update={"role_keys": role_keys(FIXTURE_READING)}))
    return entry


def _set_reading(data_dir, entry, reading):
    save_resume(data_dir, reading)
    save_reading(data_dir, entry.id, reading)


def _assert_refused_and_nothing_written(data_dir, engine, job_id):
    with pytest.raises(DocsSetupError) as info:
        run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    assert str(info.value) == STALE_MAPPING_COPY
    assert not (data_dir / "applications").exists()
    with Session(engine) as s:
        assert s.get(Job, job_id).docs_folder is None


def test_removed_role_marks_mapping_stale_and_make_docs_refuses(data_dir, engine):
    entry = _keyed_profile(data_dir)
    reading = FIXTURE_READING.model_copy(deep=True)
    reading.roles = reading.roles[1:]
    _set_reading(data_dir, entry, reading)
    mapping = remap_mapping(load_mapping(data_dir, entry.id), reading)
    assert mapping.stale is True
    save_mapping(data_dir, entry.id, mapping)
    _assert_refused_and_nothing_written(data_dir, engine, add_job(engine))


def test_mapping_keys_that_differ_from_the_reading_are_refused(data_dir, engine):
    entry = _keyed_profile(data_dir)
    reading = FIXTURE_READING.model_copy(deep=True)
    reading.roles = [reading.roles[1], reading.roles[0]]
    _set_reading(data_dir, entry, reading)          # the jobs moved but the mapping was not remapped
    _assert_refused_and_nothing_written(data_dir, engine, add_job(engine))


def test_remapped_mapping_after_reorder_makes_docs(data_dir, engine):
    entry = _keyed_profile(data_dir)
    reading = FIXTURE_READING.model_copy(deep=True)
    reading.roles = [reading.roles[1], reading.roles[0]]
    _set_reading(data_dir, entry, reading)
    save_mapping(data_dir, entry.id, remap_mapping(load_mapping(data_dir, entry.id), reading))
    draft = json.loads(draft_json_for_fixture())
    for role in draft["content"]["roles"]:
        role["role"] = 1 - role["role"]
    r = run(data_dir, engine, add_job(engine), FakeProvider(replies=[json.dumps(draft), '{"problems": []}']))
    t = [p.text for p in iter_paragraphs((r.folder / "resume.docx").read_bytes())]
    north = t.index("Northwind Labs — Senior Engineer — 2021–2025")
    contoso = t.index("Contoso Health — Engineer — 2018–2021")
    assert set(t[north + 1:contoso]) <= set(FIXTURE_READING.roles[0].bullets)
    assert t[contoso + 1] in FIXTURE_READING.roles[1].bullets


def test_legacy_mapping_without_keys_still_makes_docs(data_dir, engine):
    ready_profile(data_dir)
    assert load_mapping(data_dir, default_entry(data_dir).id).role_keys == []
    r = run(data_dir, engine, add_job(engine), FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    assert (r.folder / "resume.docx").is_file()


def test_missing_docx_file_with_mapping_is_a_setup_error(data_dir, engine):
    ready_profile(data_dir)
    file_path(data_dir, default_entry(data_dir)).unlink()
    with pytest.raises(DocsSetupError) as info:
        run(data_dir, engine, add_job(engine), FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']))
    assert str(info.value) == MISSING_FILE_COPY
    assert not (data_dir / "applications").exists()


def _resume_texts(folder):
    return [p.text for p in iter_paragraphs((folder / "resume.docx").read_bytes())]


def test_mapped_headline_is_sent_tailored_and_rendered(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    r = run(data_dir, engine, job_id, p)
    assert "Engineering Leader | Data Platforms | Healthcare Technology" in p.calls[0]["messages"][0]["content"]
    assert _resume_texts(r.folder)[2] == "Data Platforms | Engineering Leader"
    assert "Kept your original headline" not in (r.folder / "notes.md").read_text(encoding="utf-8")


def test_invented_headline_is_reverted_with_a_note(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine)
    draft = json.loads(draft_json_for_fixture())
    draft["content"]["headline"] = "Engineering Leader | Quantum Computing Guru"
    p = FakeProvider(replies=[json.dumps(draft), '{"problems": []}'])
    r = run(data_dir, engine, job_id, p)
    assert _resume_texts(r.folder)[2] == "Engineering Leader | Data Platforms | Healthcare Technology"
    notes = (r.folder / "notes.md").read_text(encoding="utf-8")
    assert "Kept your original headline: it used wording that isn't in your resume." in notes


def test_no_mapped_headline_means_an_empty_headline(data_dir, engine):
    ready_profile(data_dir)
    entry = default_entry(data_dir)
    m = load_mapping(data_dir, entry.id)
    save_mapping(data_dir, entry.id, m.model_copy(update={"paragraphs": [
        p.model_copy(update={"label": "keep"}) if p.label == "headline" else p for p in m.paragraphs]}))
    job_id = add_job(engine)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    r = run(data_dir, engine, job_id, p)
    assert "original headline" not in p.calls[0]["messages"][0]["content"]
    assert _resume_texts(r.folder)[2] == "Engineering Leader | Data Platforms | Healthcare Technology"
    assert "Kept your original headline" not in (r.folder / "notes.md").read_text(encoding="utf-8")


def _log_actions(engine):
    from jobmecloud.db.models import ActivityLog
    from sqlmodel import select
    with Session(engine) as s:
        return [(r.action, r.from_value, r.to_value, r.actor) for r in s.exec(select(ActivityLog).order_by(ActivityLog.id))]


def test_make_docs_logs_ready_then_regenerated_without_status_change(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine, status="New", match_score=90)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'] * 2)
    run(data_dir, engine, job_id, p)
    assert _log_actions(engine) == [("status_changed", "New", "Ready", "system"), ("docs_ready", None, None, "system")]
    run(data_dir, engine, job_id, p, now=NOW + timedelta(minutes=1))
    assert _log_actions(engine)[2:] == [("docs_regenerated", None, None, "system")]


def test_regenerate_for_applied_job_keeps_status_and_logs(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine, status="New", match_score=90)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'] * 2)
    run(data_dir, engine, job_id, p)
    set_status(engine, job_id, "Applied")
    run(data_dir, engine, job_id, p, now=NOW + timedelta(minutes=1))
    assert get_status(engine, job_id) == "Applied"
    assert _log_actions(engine)[2:] == [("docs_regenerated", None, None, "system")]


def test_as_is_logs_resume_name(data_dir, engine):
    setup_profile(data_dir)
    job_id = add_job(engine, status="New")
    e = add_resume(data_dir, name="Short", filename="s.pdf", data=b"%PDF", reading=FIXTURE_READING, mapping=None, make_default=True, now=NOW)
    use_as_is(data_dir, engine, job_id, e.id, NOW)
    from jobmecloud.db.models import ActivityLog
    from sqlmodel import select
    with Session(engine) as s:
        row = s.exec(select(ActivityLog).where(ActivityLog.action == "docs_as_is")).one()
        assert (row.note, row.actor, row.job_id) == ("Short", "system", job_id)


def _second_resume(data_dir):
    other = FIXTURE_READING.model_copy(update={"summary": "A COMPLETELY DIFFERENT SUMMARY about platform migrations."})
    return add_resume(data_dir, name="Platform version", filename="cv2.docx", data=make_resume_docx(), reading=other,
                      mapping=fixture_mapping(), make_default=False, now=NOW)


def test_docs_can_start_from_a_chosen_resume_instead_of_the_default(data_dir, engine):
    ready_profile(data_dir)
    chosen = _second_resume(data_dir)
    job_id = add_job(engine)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    r = run(data_dir, engine, job_id, p, resume_id=chosen.id)
    assert "COMPLETELY DIFFERENT SUMMARY" in p.calls[0]["messages"][0]["content"]
    assert "Platform version" in (r.folder / "notes.md").read_text(encoding="utf-8")
    assert default_entry(data_dir).name == "Main"  # choosing a source does not change the default


def test_without_a_choice_the_default_resume_is_still_used(data_dir, engine):
    ready_profile(data_dir)
    _second_resume(data_dir)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    run(data_dir, engine, add_job(engine), p)
    assert "COMPLETELY DIFFERENT SUMMARY" not in p.calls[0]["messages"][0]["content"]


def test_a_resume_that_is_no_longer_in_the_library_is_a_setup_error_and_writes_nothing(data_dir, engine):
    ready_profile(data_dir)
    job_id = add_job(engine)
    with pytest.raises(DocsSetupError) as info:
        run(data_dir, engine, job_id, FakeProvider(replies=[draft_json_for_fixture()]), resume_id="gone")
    assert "no longer" in str(info.value).lower()
    with Session(engine) as s:
        assert s.get(Job, job_id).docs_folder is None


# ---------------------------------------------------------------- feedback that the documents must honour


def _paragraphs(path):
    import docx
    return [(p.style.name, p.text) for p in docx.Document(str(path)).paragraphs]


def _draft_with(**extra):
    base = json.loads(draft_json_for_fixture())
    base.update(extra)
    return json.dumps(base)


def test_links_given_in_the_feedback_are_added_to_the_contact_line(data_dir, engine):
    ready_profile(data_dir)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    r = run(data_dir, engine, add_job(engine), p,
            feedback="Please add my GitHub https://github.com/jordanx?tab=repositories to the header.")
    contact = next(t for _, t in _paragraphs(r.folder / "resume.docx") if "jordan@example.com" in t)
    assert "jordan@example.com" in contact and "github.com/jordanx" in contact and "tab=" not in contact
    assert "github.com/jordanx" in r.note


def test_a_link_already_on_the_contact_line_is_not_added_twice(data_dir, engine):
    ready_profile(data_dir)
    fb = "add https://github.com/jordanx and https://github.com/jordanx/"
    r = run(data_dir, engine, add_job(engine), FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}']),
            feedback=fb)
    contact = next(t for _, t in _paragraphs(r.folder / "resume.docx") if "jordan@example.com" in t)
    assert contact.count("github.com/jordanx") == 1


def test_something_the_ai_could_not_do_is_reported_instead_of_dropped(data_dir, engine):
    ready_profile(data_dir)
    p = FakeProvider(replies=[_draft_with(not_applied=["Make the summary bold: formatting comes from your Word file."]),
                              '{"problems": []}'])
    r = run(data_dir, engine, add_job(engine), p, feedback="make the summary bold")
    assert "couldn't apply" in r.note.lower() and "summary bold" in r.note
    assert "summary bold" in (r.folder / "notes.md").read_text(encoding="utf-8")


def test_the_ai_is_told_what_it_can_and_cannot_change(data_dir, engine):
    ready_profile(data_dir)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    run(data_dir, engine, add_job(engine), p, feedback="lean into healthcare")
    prompt = p.calls[0]["messages"][0]["content"]
    assert "not_applied" in prompt and "lean into healthcare" in prompt
    assert "formatting" in prompt.lower()


def test_the_feedback_is_kept_when_the_draft_has_to_be_revised(data_dir, engine):
    ready_profile(data_dir)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": ["A claim is not in the resume."]}',
                              draft_json_for_fixture()])
    run(data_dir, engine, add_job(engine), p, feedback="lean into healthcare")
    revise_prompt = p.calls[2]["messages"][0]["content"]
    assert "lean into healthcare" in revise_prompt


def _role_docx(reading_bullets):
    import io

    import docx
    d = docx.Document()
    d.add_paragraph("Jordan Example", style="Title")
    d.add_paragraph("jordan@example.com · Springfield")
    d.add_paragraph("Professional Summary", style="Heading 1")
    d.add_paragraph("Data engineer with seven years of experience building reliable pipelines.")
    d.add_paragraph("Professional Experience", style="Heading 1")
    d.add_paragraph("Senior Engineer")
    d.add_paragraph("Northwind Labs | Remote | January 2021 – October 2025")
    for b in reading_bullets:
        d.add_paragraph(b, style="List Bullet")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_a_mapping_that_took_the_dates_line_for_a_bullet_no_longer_costs_the_dates_or_the_summary_style(data_dir, engine):
    from jobmecloud.config.profile import MasterResume, ResumeRole
    from jobmecloud.resumes.mapping import MappedParagraph, ResumeMapping
    setup_profile(data_dir)
    bullets = ["Built pipelines that moved 2 TB of data daily with Airflow.",
               "Cut warehouse spend by 30 percent through better partitioning.",
               "Moved reporting to a new warehouse without downtime."]
    summary = "Data engineer with seven years of experience building reliable pipelines."
    reading = MasterResume(summary=summary, roles=[ResumeRole(
        employer="Northwind Labs", title="Senior Engineer", start="January 2021", end="October 2025", bullets=bullets)],
        skills=[])
    texts = ["Jordan Example", "jordan@example.com · Springfield", "Professional Summary", summary,
             "Professional Experience", "Senior Engineer", "Northwind Labs | Remote | January 2021 – October 2025", *bullets]
    labels = ["keep", "contact", "summary", "summary", "keep", "keep", "bullet:0:0", "bullet:0:1", "bullet:0:2", "keep"]
    broken = ResumeMapping(paragraphs=[MappedParagraph(index=i, text=t, label=lab)
                                       for i, (t, lab) in enumerate(zip(texts, labels))])
    add_resume(data_dir, name="Main", filename="cv.docx", data=_role_docx(bullets), reading=reading, mapping=broken,
               make_default=True, now=NOW)
    save_user_for_test(data_dir)
    tailored = {"content": {"headline": "", "summary": "A fresh summary written in sentence case.",
                            "roles": [{"role": 0, "bullets": [{"source": 1, "text": bullets[1]}, {"source": 0, "text": bullets[0]},
                                                              {"source": 2, "text": bullets[2]}]}], "skills": []},
                "letter": {"greeting": "Dear Hiring Manager,", "paragraphs": ["Hello."], "sign_off": "Sincerely,"},
                "changes": [], "not_applied": []}
    p = FakeProvider(replies=[json.dumps(tailored), '{"problems": []}'])
    r = run(data_dir, engine, add_job(engine), p)
    paras = _paragraphs(r.folder / "resume.docx")
    texts_out = [t for _, t in paras]
    assert "Northwind Labs | Remote | January 2021 – October 2025" in texts_out  # the dates survive
    summary_style = next(s for s, t in paras if t.startswith("A fresh summary"))
    assert not summary_style.startswith("Heading")  # and the summary is not in a heading
    assert "Professional Summary" in texts_out
    assert sum(t == bullets[2] for t in texts_out) == 1  # nothing is left over from the original to repeat


def save_user_for_test(data_dir):
    from jobmecloud.config.profile import UserProfile, save_user
    save_user(data_dir, UserProfile(name="Jordan Example", email="jordan@example.com"))
