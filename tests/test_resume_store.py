from datetime import datetime, timezone

import pytest

from jobmecloud.config.profile import MasterResume, ResumeRole, load_resume
from jobmecloud.resumes.store import (
    add_resume,
    default_entry,
    file_path,
    get_entry,
    kind_for,
    load_index,
    load_mapping,
    load_reading,
    remove_resume,
    set_default,
)

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
R1 = MasterResume(summary="One", roles=[ResumeRole(employer="Northwind Labs", title="Engineer", bullets=["Built A"])])
R2 = MasterResume(summary="Two")


def test_first_resume_becomes_default_and_master(data_dir):
    e = add_resume(data_dir, name="Main", filename="cv.docx", data=b"PK", reading=R1, mapping=None,
                   make_default=False, now=NOW)
    assert e.kind == "docx" and file_path(data_dir, e).read_bytes() == b"PK"
    assert load_index(data_dir).default_id == e.id
    assert load_resume(data_dir) == R1
    assert load_index(data_dir).resumes[0].uploaded_at == NOW
    assert default_entry(data_dir) == e


def test_switch_default_and_remove_rules(data_dir):
    a = add_resume(data_dir, name="Main", filename="a.docx", data=b"a", reading=R1, mapping=None, make_default=False, now=NOW)
    with pytest.raises(ValueError, match="only resume"):
        remove_resume(data_dir, a.id)
    b = add_resume(data_dir, name="Short", filename="b.pdf", data=b"b", reading=R2, mapping=None, make_default=False, now=NOW)
    assert load_index(data_dir).default_id == a.id and b.kind == "pdf"
    with pytest.raises(ValueError, match="Make another resume the default"):
        remove_resume(data_dir, a.id)
    set_default(data_dir, b.id)
    assert load_resume(data_dir) == R2
    remove_resume(data_dir, a.id)
    assert [r.id for r in load_index(data_dir).resumes] == [b.id] and not file_path(data_dir, a).exists()
    with pytest.raises(KeyError):
        get_entry(data_dir, a.id)


def test_make_default_true_and_no_mapping(data_dir):
    add_resume(data_dir, name="A", filename="a.txt", data=b"a", reading=R1, mapping=None, make_default=False, now=NOW)
    b = add_resume(data_dir, name="B", filename="b.md", data=b"b", reading=R2, mapping=None, make_default=True, now=NOW)
    assert b.kind == "text" and load_index(data_dir).default_id == b.id
    assert load_resume(data_dir) == R2
    assert load_mapping(data_dir, b.id) is None and not b.has_mapping


def test_kind_for():
    assert [kind_for(n) for n in ("a.DOCX", "a.pdf", "a.txt", "a.md")] == ["docx", "pdf", "text", "text"]


def test_load_index_empty(data_dir):
    idx = load_index(data_dir)
    assert idx.default_id is None and idx.resumes == []
    assert default_entry(data_dir) is None


def test_save_and_load_mapping_round_trip(data_dir):
    from jobmecloud.resumes.mapping import MappedParagraph, ResumeMapping
    from jobmecloud.resumes.store import save_mapping

    m = ResumeMapping(paragraphs=[MappedParagraph(index=0, text="Jordan", label="contact")])
    e = add_resume(data_dir, name="A", filename="a.docx", data=b"a", reading=R1, mapping=None, make_default=False, now=NOW)
    assert not e.has_mapping
    save_mapping(data_dir, e.id, m)
    assert load_mapping(data_dir, e.id) == m
    assert get_entry(data_dir, e.id).has_mapping
    b = add_resume(data_dir, name="B", filename="b.docx", data=b"b", reading=R2, mapping=m, make_default=False, now=NOW)
    assert b.has_mapping and load_mapping(data_dir, b.id) == m


def test_load_mapping_unknown_id_raises_not_found(data_dir):
    with pytest.raises(KeyError, match="No resume with that id"):
        load_mapping(data_dir, "../../etc/passwd")
