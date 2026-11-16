import zipfile
from pathlib import Path

import pytest

from jobmecloud.admin import build

ROOT = Path(__file__).resolve().parents[1]


def fake_install(target: Path) -> None:
    """Stands in for `uv pip install`: a few packages, including ones the layer must not carry."""
    for name in ("fastapi", "boto3", "botocore", "s3transfer", "jmespath"):
        (target / name).mkdir(parents=True)
        (target / name / "__init__.py").write_text("x = 1\n")
    (target / "fastapi" / "tests").mkdir()
    (target / "fastapi" / "tests" / "test_x.py").write_text("")
    (target / "fastapi" / "__pycache__").mkdir()
    (target / "fastapi" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\0")
    (target / "fastapi-1.0.dist-info").mkdir()
    (target / "fastapi-1.0.dist-info" / "METADATA").write_text("Name: fastapi\n")


def names(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as z:
        return z.namelist()


def test_layer_excludes_boto3_and_tests(tmp_path):
    layer = build.build_layer(tmp_path, install=fake_install)
    files = names(layer)
    assert "python/fastapi/__init__.py" in files
    assert not any(f.startswith(("python/boto3", "python/botocore", "python/s3transfer", "python/jmespath")) for f in files)
    assert not any("/tests/" in f or "__pycache__" in f or f.endswith(".pyc") for f in files)


def test_each_handler_zip_has_entry_module(tmp_path):
    zips = build.build_code(tmp_path, ROOT / "backend")
    assert sorted(z.name for z in zips) == ["api.zip", "docs-worker.zip", "ingest.zip", "run-worker.zip"]
    assert "jobmecloud/handlers/api.py" in names(tmp_path / "api.zip")
    assert "jobmecloud/handlers/run_worker.py" in names(tmp_path / "run-worker.zip")
    assert "jobmecloud/handlers/docs_worker.py" in names(tmp_path / "docs-worker.zip")
    assert "jobmecloud/handlers/ingest.py" in names(tmp_path / "ingest.zip")
    assert "jobmecloud/inbound/parse.py" in names(tmp_path / "ingest.zip")
    assert not any("__pycache__" in f for f in names(tmp_path / "api.zip"))


def test_handler_names_match_what_the_stack_expects():
    assert set(build.HANDLERS) == {"api", "run-worker", "docs-worker", "ingest"}


def test_size_limit_enforced(tmp_path):
    big = tmp_path / "big.zip"
    with zipfile.ZipFile(big, "w") as z:
        z.writestr("blob", "0")
    with pytest.raises(build.BuildError, match="50 MB"):
        build.check_sizes([big], zipped_limit=0)
    with pytest.raises(build.BuildError, match="250 MB"):
        build.check_sizes([big], unzipped_limit=0)
    build.check_sizes([big])  # a tiny package is fine


def test_build_all_writes_the_files_the_stack_loads(tmp_path):
    out = build.build_all(tmp_path, root=ROOT, install=fake_install)
    assert sorted(p.name for p in out) == ["api.zip", "docs-worker.zip", "ingest.zip", "layer.zip", "run-worker.zip"]
