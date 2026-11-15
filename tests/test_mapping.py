import io
import json

import docx

from docx_fixtures import FIXTURE_LABELS, FIXTURE_READING, make_resume_docx
from fakes import FakeProvider, fixture_mapping
from jobmecloud.applydocs.content import original_content
from jobmecloud.applydocs.render import render_resume
from jobmecloud.resumes.docx_text import iter_paragraphs
from jobmecloud.resumes.mapping import (
    MAPPING_SCHEMA,
    MappedParagraph,
    ResumeMapping,
    clean_mapping,
    draft_mapping,
    keys_match,
    remap_mapping,
    role_key,
    role_keys,
)


def test_draft_mapping_and_clean():
    reply = json.dumps({"labels": [{"index": i, "label": l} for i, l in FIXTURE_LABELS.items()]
                                  + [{"index": 4, "label": "bullet:9:0"}]})
    p = FakeProvider(replies=[reply])
    m = draft_mapping(p, "m", make_resume_docx(), FIXTURE_READING)
    labels = {x.index: x.label for x in m.paragraphs}
    assert labels[1] == "contact" and labels[2] == "headline" and labels[7] == "bullet:0:0"
    assert labels[14] == "skills" and labels[3] == "keep" and labels[6] == "title"
    assert len(m.paragraphs) == 17 and m.mapped()
    assert "6: " in p.calls[0]["messages"][0]["content"]


def test_draft_mapping_missing_indexes_and_empty_paragraphs_are_keep():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    doc.paragraphs[0].insert_paragraph_before("")
    buf = io.BytesIO()
    doc.save(buf)
    reply = json.dumps({"labels": [{"index": 0, "label": "contact"}, {"index": 1, "label": "contact"}]})
    p = FakeProvider(replies=[reply])
    m = draft_mapping(p, "m", buf.getvalue(), FIXTURE_READING)
    assert [x.label for x in m.paragraphs[:3]] == ["keep", "contact", "keep"]
    assert len(m.paragraphs) == 18
    sent = p.calls[0]["messages"][0]["content"]
    assert "\n0: " not in sent and "\n2: jordan@example.com" in sent


def test_clean_mapping_drops_bad_labels():
    m = ResumeMapping(paragraphs=[MappedParagraph(index=0, text="a", label="bullet:0:5"),
                                  MappedParagraph(index=1, text="b", label="bullet:0:0"),
                                  MappedParagraph(index=2, text="c", label="bullet:0:0"),
                                  MappedParagraph(index=3, text="d", label="nonsense")])
    assert [x.label for x in clean_mapping(m, FIXTURE_READING).paragraphs] == ["keep", "bullet:0:0", "keep", "keep"]


def test_mapped_false_when_all_keep_and_schema_strict():
    m = ResumeMapping(paragraphs=[MappedParagraph(index=0, text="a", label="keep")])
    assert not m.mapped()
    assert MAPPING_SCHEMA["additionalProperties"] is False


# ---------------------------------------------------------------- role keys and remap

NORTHWIND_LINE = "Northwind Labs — Senior Engineer — 2021–2025"
CONTOSO_LINE = "Contoso Health — Engineer — 2018–2021"


def keyed_mapping(data=None) -> ResumeMapping:
    return fixture_mapping(data).model_copy(update={"role_keys": role_keys(FIXTURE_READING)})


def swapped_reading():
    reading = FIXTURE_READING.model_copy(deep=True)
    reading.roles = [reading.roles[1], reading.roles[0]]
    return reading


def bullet_labels(m: ResumeMapping) -> list[str]:
    return [p.label for p in m.paragraphs if p.label.startswith("bullet:")]


def test_role_key_ignores_case_and_spacing():
    role = FIXTURE_READING.roles[0]
    assert role_key(role) == "northwind labs|senior engineer|2021|2025"
    assert role_key(role.model_copy(update={"employer": "  NORTHWIND   labs ", "bullets": []})) == role_key(role)
    assert role_keys(FIXTURE_READING) == ["northwind labs|senior engineer|2021|2025", "contoso health|engineer|2018|2021"]


def test_draft_mapping_records_role_keys():
    reply = json.dumps({"labels": [{"index": i, "label": l} for i, l in FIXTURE_LABELS.items()]})
    m = draft_mapping(FakeProvider(replies=[reply]), "m", make_resume_docx(), FIXTURE_READING)
    assert m.role_keys == role_keys(FIXTURE_READING) and m.stale is False


def test_remap_follows_swapped_roles_and_each_employer_keeps_its_bullets():
    data = make_resume_docx()
    reading = swapped_reading()
    m = remap_mapping(keyed_mapping(data), reading)
    labels = {p.index: p.label for p in m.paragraphs}
    assert [labels[i] for i in (7, 8, 9, 11, 12)] == ["bullet:1:0", "bullet:1:1", "bullet:1:2", "bullet:0:0", "bullet:0:1"]
    assert m.role_keys == role_keys(reading) and m.stale is False and keys_match(m, reading)
    out = render_resume(data, clean_mapping(m, reading), original_content(reading))
    t = [p.text for p in iter_paragraphs(out)]
    north, contoso = t.index(NORTHWIND_LINE), t.index(CONTOSO_LINE)
    assert t[north + 1:contoso] == FIXTURE_READING.roles[0].bullets
    assert t[contoso + 1:contoso + 3] == FIXTURE_READING.roles[1].bullets


def test_remap_renumbers_bullets_by_document_order():
    m = keyed_mapping()
    for p in m.paragraphs:
        if p.index == 7:
            p.label = "bullet:0:2"
        elif p.index == 9:
            p.label = "bullet:0:0"
    assert bullet_labels(remap_mapping(m, FIXTURE_READING)) == [
        "bullet:0:0", "bullet:0:1", "bullet:0:2", "bullet:1:0", "bullet:1:1"]


def test_remap_marks_stale_when_a_used_role_is_removed_or_changed():
    m = keyed_mapping()
    removed = FIXTURE_READING.model_copy(deep=True)
    removed.roles = removed.roles[1:]
    gone = remap_mapping(m, removed)
    assert gone.stale is True and bullet_labels(gone) == bullet_labels(m) and gone.role_keys == m.role_keys
    retitled = FIXTURE_READING.model_copy(deep=True)
    retitled.roles[1].title = "Lead Engineer"
    assert remap_mapping(m, retitled).stale is True


def test_remap_with_duplicate_keys_uses_each_new_role_once():
    reading = FIXTURE_READING.model_copy(deep=True)
    reading.roles = [reading.roles[0], reading.roles[0].model_copy(deep=True)]
    m = keyed_mapping().model_copy(update={"role_keys": role_keys(reading)})
    moved = reading.model_copy(deep=True)
    moved.roles.insert(0, FIXTURE_READING.roles[1])
    out = remap_mapping(m, moved)
    assert not out.stale and bullet_labels(out) == ["bullet:1:0", "bullet:1:1", "bullet:1:2", "bullet:2:0", "bullet:2:1"]


def test_remap_of_a_legacy_mapping_only_records_the_keys():
    legacy = fixture_mapping()
    assert legacy.role_keys == [] and keys_match(legacy, swapped_reading())
    out = remap_mapping(legacy, FIXTURE_READING)
    assert out.paragraphs == legacy.paragraphs and out.role_keys == role_keys(FIXTURE_READING) and not out.stale


def test_clean_mapping_keeps_keys_and_stale():
    m = keyed_mapping().model_copy(update={"stale": True})
    cleaned = clean_mapping(m, FIXTURE_READING)
    assert cleaned.role_keys == m.role_keys and cleaned.stale is True


def test_clean_mapping_accepts_headline_and_title_and_they_count_as_mapped():
    labels = ["headline", "title", "contact", "bullet:0:0", "Headline", "headline:1"]
    m = ResumeMapping(paragraphs=[MappedParagraph(index=i, text="x", label=l) for i, l in enumerate(labels)])
    assert [p.label for p in clean_mapping(m, FIXTURE_READING).paragraphs] == [
        "headline", "title", "contact", "bullet:0:0", "keep", "keep"]
    only = ResumeMapping(paragraphs=[MappedParagraph(index=0, text="x", label="headline"),
                                     MappedParagraph(index=1, text="y", label="title")])
    assert only.mapped()


def test_mapping_prompt_describes_headline_and_title_and_prefers_keep():
    reply = json.dumps({"labels": []})
    p = FakeProvider(replies=[reply])
    draft_mapping(p, "m", make_resume_docx(), FIXTURE_READING)
    system = p.calls[0]["system"]
    assert "'headline'" in system and "'title'" in system and "tagline" in system
    assert "unsure" in system and "'keep'" in system
