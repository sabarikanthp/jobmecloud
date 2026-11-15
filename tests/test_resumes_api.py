import json

from docx_fixtures import FIXTURE_LABELS, FIXTURE_READING, make_resume_docx, set_app_pages
from fakes import FakeProvider, fixture_mapping, setup_profile
from jobmecloud.resumes.store import save_mapping


def test_upload_review_and_save(client):
    reading = FIXTURE_READING.model_dump(mode="json")
    mapping = json.dumps({"labels": [{"index": i, "label": l} for i, l in FIXTURE_LABELS.items()]})
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[json.dumps(reading), mapping])
    setup_profile(client.app.state.data_dir)
    r = client.post("/api/resumes/draft", files={"file": ("cv.docx", make_resume_docx())}).json()
    assert r["kind"] == "docx" and r["map_error"] is None and r["mapping"]["paragraphs"][7]["label"] == "bullet:0:0"
    saved = client.post("/api/resumes", json={"upload_id": r["upload_id"], "name": "Main", "reading": r["reading"],
                                              "mapping": r["mapping"], "make_default": False})
    assert saved.status_code == 201 and saved.json()["is_default"] is True and saved.json()["has_mapping"] is True
    listing = client.get("/api/resumes").json()
    assert listing["default_id"] == saved.json()["id"]
    assert client.get("/api/profile/resume").json()["summary"] == FIXTURE_READING.summary


def test_pdf_has_no_mapping_and_errors(client, monkeypatch):
    setup_profile(client.app.state.data_dir)
    monkeypatch.setattr("jobmecloud.api.routes_resumes.extract_text", lambda name, data: "Jordan Example resume text")
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[json.dumps(FIXTURE_READING.model_dump(mode="json"))])
    r = client.post("/api/resumes/draft", files={"file": ("cv.pdf", b"%PDF")}).json()
    assert r["kind"] == "pdf" and r["mapping"] is None and r["map_error"] is None
    bad = client.post("/api/resumes", json={"upload_id": r["upload_id"], "name": " ", "reading": r["reading"],
                                            "mapping": None, "make_default": True})
    assert bad.status_code == 400 and bad.json()["detail"] == "Please give this resume a name."
    assert client.post("/api/resumes", json={"upload_id": "nope", "name": "x", "reading": r["reading"],
                                             "mapping": None, "make_default": True}).status_code == 404
    assert client.delete("/api/resumes/nope").status_code == 404


def test_unmappable_docx_says_so(client):
    setup_profile(client.app.state.data_dir)
    keep_all = json.dumps({"labels": []})
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[json.dumps(FIXTURE_READING.model_dump(mode="json")), keep_all])
    r = client.post("/api/resumes/draft", files={"file": ("cv.docx", make_resume_docx())}).json()
    assert r["mapping"] is None and r["map_error"] == "JobMe couldn't find the parts of this resume. You can still use it as-is."


def test_mapping_failure_keeps_reading(client):
    setup_profile(client.app.state.data_dir)
    reading = json.dumps(FIXTURE_READING.model_dump(mode="json"))
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[reading, "not json", "not json", "not json"])
    r = client.post("/api/resumes/draft", files={"file": ("cv.docx", make_resume_docx())}).json()
    assert r["reading"]["summary"] == FIXTURE_READING.summary
    assert r["mapping"] is None and r["map_error"]


def test_manage_resumes(client):
    setup_profile(client.app.state.data_dir)
    reading = FIXTURE_READING.model_dump(mode="json")
    mapping = json.dumps({"labels": [{"index": i, "label": l} for i, l in FIXTURE_LABELS.items()]})
    ids = []
    for name in ("One", "Two"):
        client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[json.dumps(reading), mapping])
        d = client.post("/api/resumes/draft", files={"file": ("cv.docx", make_resume_docx())}).json()
        ids.append(client.post("/api/resumes", json={"upload_id": d["upload_id"], "name": name, "reading": d["reading"],
                                                     "mapping": d["mapping"], "make_default": False}).json()["id"])
    one, two = ids
    listing = client.get("/api/resumes").json()
    assert listing["default_id"] == one and [x["pages"] for x in listing["resumes"]] == [1, 1]
    m = client.get(f"/api/resumes/{two}/mapping").json()
    m["paragraphs"][0]["label"] = "bogus"
    assert client.put(f"/api/resumes/{two}/mapping", json=m).json()["paragraphs"][0]["label"] == "keep"
    assert client.delete(f"/api/resumes/{one}").status_code == 400
    assert client.post(f"/api/resumes/{two}/default").status_code == 204
    assert client.delete(f"/api/resumes/{one}").status_code == 204
    assert client.get("/api/resumes/nope/mapping").status_code == 404
    assert client.post("/api/resumes/nope/default").status_code == 404


def test_no_mapping_is_404(client, monkeypatch):
    setup_profile(client.app.state.data_dir)
    monkeypatch.setattr("jobmecloud.api.routes_resumes.extract_text", lambda name, data: "text")
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[json.dumps(FIXTURE_READING.model_dump(mode="json"))])
    d = client.post("/api/resumes/draft", files={"file": ("cv.pdf", b"%PDF")}).json()
    rid = client.post("/api/resumes", json={"upload_id": d["upload_id"], "name": "P", "reading": d["reading"],
                                            "mapping": None, "make_default": False}).json()["id"]
    r = client.get(f"/api/resumes/{rid}/mapping")
    assert r.status_code == 404 and r.json()["detail"] == "This resume has no mapping."


def test_mapping_ignored_for_non_docx(client, monkeypatch):
    setup_profile(client.app.state.data_dir)
    monkeypatch.setattr("jobmecloud.api.routes_resumes.extract_text", lambda name, data: "text")
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[json.dumps(FIXTURE_READING.model_dump(mode="json"))])
    d = client.post("/api/resumes/draft", files={"file": ("cv.pdf", b"%PDF")}).json()
    mapping = {"paragraphs": [{"index": 0, "text": "x", "label": "summary"}]}
    saved = client.post("/api/resumes", json={"upload_id": d["upload_id"], "name": "P", "reading": d["reading"],
                                              "mapping": mapping, "make_default": False}).json()
    assert saved["has_mapping"] is False
    assert not list((client.app.state.data_dir / "profile" / "resumes").glob("*.map.json"))
    r = client.put(f"/api/resumes/{saved['id']}/mapping", json=mapping)
    assert r.status_code == 404 and r.json()["detail"] == "This resume has no mapping."


def test_list_reports_docx_page_count(client):
    setup_profile(client.app.state.data_dir)
    data = set_app_pages(make_resume_docx(), 2)
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[json.dumps(FIXTURE_READING.model_dump(mode="json")), json.dumps({"labels": []})])
    r = client.post("/api/resumes/draft", files={"file": ("cv.docx", data)}).json()
    client.post("/api/resumes", json={"upload_id": r["upload_id"], "name": "Main", "reading": r["reading"],
                                      "mapping": None, "make_default": True})
    assert [x["pages"] for x in client.get("/api/resumes").json()["resumes"]] == [2]


def test_reading_round_trip_and_unknown_id(client):
    setup_profile(client.app.state.data_dir)
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[json.dumps(FIXTURE_READING.model_dump(mode="json"))])
    d = client.post("/api/resumes/draft", files={"file": ("cv.txt", b"text")}).json()
    rid = client.post("/api/resumes", json={"upload_id": d["upload_id"], "name": "T", "reading": d["reading"],
                                            "mapping": None, "make_default": False}).json()["id"]
    r = client.get(f"/api/resumes/{rid}/reading")
    assert r.status_code == 200 and r.json() == FIXTURE_READING.model_dump(mode="json")
    assert client.get("/api/resumes/nope/reading").status_code == 404



def _draft_docx(client):
    reading = json.dumps(FIXTURE_READING.model_dump(mode="json"))
    labels = json.dumps({"labels": [{"index": i, "label": l} for i, l in FIXTURE_LABELS.items()]})
    client.app.state.provider_builder = lambda cfg: FakeProvider(replies=[reading, labels])
    return client.post("/api/resumes/draft", files={"file": ("cv.docx", make_resume_docx())}).json()


def _bullets(mapping) -> dict[int, str]:
    return {p["index"]: p["label"] for p in mapping["paragraphs"] if p["label"].startswith("bullet:")}


SWAPPED_BULLETS = {7: "bullet:1:0", 8: "bullet:1:1", 9: "bullet:1:2", 11: "bullet:0:0", 12: "bullet:0:1"}


def _swapped(reading: dict) -> dict:
    return {**reading, "roles": [reading["roles"][1], reading["roles"][0]]}


def test_save_with_reordered_roles_remaps_the_mapping(client):
    setup_profile(client.app.state.data_dir)
    d = _draft_docx(client)
    assert d["mapping"]["role_keys"] and d["mapping"]["stale"] is False
    saved = client.post("/api/resumes", json={"upload_id": d["upload_id"], "name": "Main",
                                              "reading": _swapped(d["reading"]), "mapping": d["mapping"],
                                              "make_default": True}).json()
    m = client.get(f"/api/resumes/{saved['id']}/mapping").json()
    assert _bullets(m) == SWAPPED_BULLETS and m["stale"] is False
    assert m["role_keys"] == ["contoso health|engineer|2018|2021", "northwind labs|senior engineer|2021|2025"]


def test_editing_the_reading_remaps_or_marks_the_default_mapping_stale(client):
    setup_profile(client.app.state.data_dir)
    d = _draft_docx(client)
    rid = client.post("/api/resumes", json={"upload_id": d["upload_id"], "name": "Main", "reading": d["reading"],
                                            "mapping": d["mapping"], "make_default": True}).json()["id"]
    assert client.put("/api/profile/resume", json=_swapped(d["reading"])).status_code == 200
    m = client.get(f"/api/resumes/{rid}/mapping").json()
    assert _bullets(m) == SWAPPED_BULLETS and m["stale"] is False

    one_job = {**d["reading"], "roles": d["reading"]["roles"][:1]}   # Contoso removed (now role 0 after the swap)
    client.put("/api/profile/resume", json=one_job)
    stale = client.get(f"/api/resumes/{rid}/mapping").json()
    assert stale["stale"] is True and _bullets(stale) == SWAPPED_BULLETS   # labels are kept for the review

    # Saving the mapping review is the user's check: it clears stale and records the current jobs.
    for p in stale["paragraphs"]:
        if p["index"] in (11, 12):
            p["label"] = "keep"
        elif p["index"] in (7, 8, 9):
            p["label"] = f"bullet:0:{p['index'] - 7}"
    reviewed = client.put(f"/api/resumes/{rid}/mapping", json=stale).json()
    assert reviewed["stale"] is False and reviewed["role_keys"] == ["northwind labs|senior engineer|2021|2025"]
    assert client.get(f"/api/resumes/{rid}/mapping").json()["stale"] is False


def test_editing_the_reading_keeps_a_legacy_mapping_working(client):
    setup_profile(client.app.state.data_dir)
    d = _draft_docx(client)
    rid = client.post("/api/resumes", json={"upload_id": d["upload_id"], "name": "Main", "reading": d["reading"],
                                            "mapping": d["mapping"], "make_default": True}).json()["id"]
    save_mapping(client.app.state.data_dir, rid, fixture_mapping())             # saved before role keys existed
    edited = {**d["reading"], "summary": "Data engineer building reliable pipelines."}
    assert client.put("/api/profile/resume", json=edited).status_code == 200
    m = client.get(f"/api/resumes/{rid}/mapping").json()
    assert m["stale"] is False and m["role_keys"] and _bullets(m)[7] == "bullet:0:0"
