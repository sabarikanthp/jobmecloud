import base64
import json

import boto3
import pytest

from jobmecloud.handlers import api as api_handler


def event(method, path, body=None, headers=None, base64_body=False):
    return {
        "version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "",
        "headers": {"host": "testserver", **(headers or {})},
        "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1",
                                    "sourceIp": "1.2.3.4", "userAgent": "pytest"}, "stage": "$default"},
        "body": body, "isBase64Encoded": base64_body,
    }


@pytest.fixture(autouse=True)
def fresh_app(data_dir, monkeypatch):
    monkeypatch.setattr(api_handler, "_handler", None)


def test_health_through_handler():
    out = api_handler.handler(event("GET", "/api/health"), None)
    assert out["statusCode"] == 200 and json.loads(out["body"])["ok"] is True


def test_post_json_roundtrip():
    payload = json.dumps({"name": "Acme Corp", "priority": 1})
    out = api_handler.handler(
        event("POST", "/api/watchlist", payload, {"content-type": "application/json"}), None)
    assert out["statusCode"] == 201
    listed = api_handler.handler(event("GET", "/api/watchlist"), None)
    assert [e["name"] for e in json.loads(listed["body"])] == ["Acme Corp"]


def test_multipart_upload_roundtrip():
    boundary = "XBOUNDARY"
    raw = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"t.csv\"\r\n"
           f"Content-Type: text/csv\r\n\r\nCompany,Title\r\nAcme,Engineer\r\n--{boundary}--\r\n").encode()
    out = api_handler.handler(
        event("POST", "/api/import/tracker/preview", base64.b64encode(raw).decode(),
              {"content-type": f"multipart/form-data; boundary={boundary}"}, base64_body=True), None)
    assert out["statusCode"] == 200
    assert json.loads(out["body"])["sheets"][0]["columns"] == ["Company", "Title"]


def test_workspace_pushed_after_post(data_dir, monkeypatch):
    boto3.client("s3").create_bucket(Bucket="jobmecloud-b")
    monkeypatch.setenv("JOBMECLOUD_BUCKET", "jobmecloud-b")
    monkeypatch.setenv("JOBMECLOUD_PREFIX", "ws")
    current = json.loads(api_handler.handler(event("GET", "/api/settings"), None)["body"])
    current["followup_default_days"] = 11
    out = api_handler.handler(
        event("PUT", "/api/settings", json.dumps(current), {"content-type": "application/json"}), None)
    assert out["statusCode"] == 200
    keys = [o["Key"] for o in boto3.client("s3").list_objects_v2(Bucket="jobmecloud-b")["Contents"]]
    assert "ws/settings.yaml" in keys
