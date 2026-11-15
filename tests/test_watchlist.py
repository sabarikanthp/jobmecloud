NAME_COPY = "Please enter the employer's name."
URL_COPY = "The careers page address should start with https://"
DUP_COPY = "That employer is already on your list."


def test_add_list_sorted(client):
    for name, pri in [("Cee", 3), ("Aye", 1), ("Bee", 2)]:
        r = client.post("/api/watchlist", json={"name": name, "priority": pri})
        assert r.status_code == 201
        assert r.json()["name"] == name
    rows = client.get("/api/watchlist").json()
    assert [r["priority"] for r in rows] == [1, 2, 3]
    assert set(rows[0]) == {
        "id", "name", "priority", "careers_url", "rotation_day", "last_checked_at",
    }


def test_sorted_by_name_ignoring_case(client):
    for name in ["beta", "Alpha", "Gamma"]:
        client.post("/api/watchlist", json={"name": name, "priority": 2})
    names = [r["name"] for r in client.get("/api/watchlist").json()]
    assert names == ["Alpha", "beta", "Gamma"]


def test_duplicate_name_409(client):
    assert client.post("/api/watchlist", json={"name": "Acme"}).status_code == 201
    r = client.post("/api/watchlist", json={"name": "acme"})
    assert r.status_code == 409
    assert r.json()["detail"] == DUP_COPY


def test_bad_url_and_blank_name(client):
    r = client.post("/api/watchlist", json={"name": "  "})
    assert r.status_code == 400
    assert r.json()["detail"] == NAME_COPY
    r = client.post("/api/watchlist", json={"name": "X", "careers_url": "ftp://x.com"})
    assert r.status_code == 400
    assert r.json()["detail"] == URL_COPY


def test_blank_url_becomes_none(client):
    r = client.post("/api/watchlist", json={"name": "X", "careers_url": "  "})
    assert r.status_code == 201
    assert r.json()["careers_url"] is None


def test_update_and_delete(client):
    row = client.post("/api/watchlist", json={"name": "Acme"}).json()
    r = client.put(
        f"/api/watchlist/{row['id']}", json={"name": "Acme", "rotation_day": "wed"}
    )
    assert r.status_code == 200
    assert r.json()["rotation_day"] == "wed"
    assert client.delete(f"/api/watchlist/{row['id']}").status_code == 204
    r = client.delete(f"/api/watchlist/{row['id']}")
    assert r.status_code == 404
    assert r.json()["detail"] == "No employer with that id"


def test_update_duplicate_ignores_self_and_unknown_404(client):
    a = client.post("/api/watchlist", json={"name": "Acme"}).json()
    b = client.post("/api/watchlist", json={"name": "Beta"}).json()
    assert client.put(f"/api/watchlist/{a['id']}", json={"name": "ACME"}).status_code == 200
    r = client.put(f"/api/watchlist/{b['id']}", json={"name": "acme"})
    assert r.status_code == 409
    assert client.put("/api/watchlist/999", json={"name": "Z"}).status_code == 404
