def test_fresh_state(client):
    assert client.get("/api/setup").json() == {
        "completed": [], "skipped": [], "next_step": 1, "finished": False
    }


def test_requirements_block_completion(client):
    r = client.post("/api/setup/3/complete")
    assert r.status_code == 400 and r.json()["detail"] == "Please enter your name and email."
    client.put("/api/profile/user", json={"name": "Jordan", "email": "j@example.com"})
    assert 3 in client.post("/api/setup/3/complete").json()["completed"]


def test_non_claude_search_needs_key(client):
    client.put(
        "/api/providers/o",
        json={"id": "o", "kind": "openai_compatible", "label": "Local",
              "base_url": "http://localhost:11434/v1"},
    )
    s = client.get("/api/settings").json()
    s["steps"] = {
        k: {"provider_id": "o", "model": "m"}
        for k in ["search", "extract", "liveness", "score", "tailor"]
    }
    client.put("/api/settings", json=s)
    assert "no built-in search" in client.post("/api/setup/2/complete").json()["detail"]


def test_step_two_needs_provider(client):
    r = client.post("/api/setup/2/complete")
    assert r.status_code == 400
    assert r.json()["detail"] == "Add an AI connection and choose its models first."


def test_skip_and_resume_point(client):
    client.post("/api/setup/1/complete")
    assert client.post("/api/setup/2/skip").json()["detail"] == "This step can't be skipped."
    state = client.post("/api/setup/6/skip").json()
    assert state["skipped"] == [6] and state["next_step"] == 2
    assert 6 not in client.post("/api/setup/6/complete").json()["skipped"]


def test_done_requires_required_steps(client):
    assert (
        client.post("/api/setup/9/complete").json()["detail"]
        == 'Finish the "Welcome" step first.'
    )
    assert client.post("/api/setup/9/skip").json()["detail"] == "This step can't be skipped."


def test_unknown_step(client):
    assert client.post("/api/setup/12/complete").status_code == 404
    assert client.post("/api/setup/0/skip").json()["detail"] == "No such setup step"
