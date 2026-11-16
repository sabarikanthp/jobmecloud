from fakes import add_job, set_status


def test_each_row_in_the_job_list_says_which_status_moves_are_allowed(client, engine):
    new = add_job(engine, employer="Acme", title="Director")
    applied = add_job(engine, employer="Beta", title="VP")
    set_status(engine, applied, "Applied")
    skipped = add_job(engine, employer="Gamma", title="Lead")
    set_status(engine, skipped, "Skipped")

    rows = {r["id"]: r for r in client.get("/api/jobs").json()["rows"]}
    for job_id in (new, applied, skipped):
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert rows[job_id]["allowed_next"] == detail["allowed_next"]  # the list and the job page never disagree

    assert "Applied" in rows[new]["allowed_next"] and "Skipped" in rows[new]["allowed_next"]
    assert "Interviewing" in rows[applied]["allowed_next"]
    assert "Reopen" in rows[skipped]["allowed_next"]
