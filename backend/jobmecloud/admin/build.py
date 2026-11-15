"""Package the Lambdas: one shared layer of dependencies, and one small zip of our code per function."""

import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

MB = 1024 * 1024
ZIPPED_LIMIT = 50 * MB  # Lambda's limit for a directly uploaded zip
UNZIPPED_LIMIT = 250 * MB  # code plus layers, unzipped
# zip name (also the CDK function name) -> handler module
HANDLERS = {"api": "api", "run-worker": "run_worker", "docs-worker": "docs_worker"}
# Already in the Lambda Python runtime, so they are left out to keep the layer small.
RUNTIME_PACKAGES = ("boto3", "botocore", "s3transfer", "jmespath")
TARGET_PLATFORM = "aarch64-manylinux_2_28"  # arm64 Lambdas run Amazon Linux 2023 (glibc 2.34)


class BuildError(Exception):
    pass


def _is_runtime_requirement(line: str) -> bool:
    name = line.split("==")[0].split(";")[0].strip().lower().replace("_", "-")
    return name in RUNTIME_PACKAGES


def uv_install(root: Path) -> Callable[[Path], None]:
    """Install the locked dependencies as arm64 Linux wheels, whatever computer this runs on."""

    def install(target: Path) -> None:
        exported = subprocess.run(
            ["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "--frozen"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        wanted = [ln for ln in exported.splitlines() if ln and not ln.startswith("#") and not _is_runtime_requirement(ln)]
        with tempfile.TemporaryDirectory() as tmp:
            requirements = Path(tmp) / "requirements.txt"
            requirements.write_text("\n".join(wanted) + "\n", encoding="utf-8")
            subprocess.run(
                ["uv", "pip", "install", "--target", str(target), "--python-platform", TARGET_PLATFORM,
                 "--python-version", "3.12", "--only-binary", ":all:", "-r", str(requirements)],
                cwd=root, check=True,
            )

    return install


def _prune(target: Path) -> None:
    for name in RUNTIME_PACKAGES:
        for leftover in list(target.glob(name)) + list(target.glob(f"{name}-*.dist-info")):
            shutil.rmtree(leftover, ignore_errors=True)
    for folder in [p for p in target.rglob("*") if p.is_dir() and p.name in ("__pycache__", "tests")]:
        shutil.rmtree(folder, ignore_errors=True)
    for pyc in target.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)


def _zip(source: Path, destination: Path, prefix: str = "") -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            relative = path.relative_to(source).as_posix()
            if "__pycache__" in relative or relative.endswith(".pyc"):
                continue
            z.write(path, f"{prefix}{relative}")


def build_layer(dist: Path, install: Callable[[Path], None] | None = None, root: Path | None = None) -> Path:
    dist = Path(dist)
    dist.mkdir(parents=True, exist_ok=True)
    install = install or uv_install(Path(root or Path.cwd()))
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "python"
        target.mkdir()
        install(target)
        _prune(target)
        out = dist / "layer.zip"
        _zip(Path(tmp), out)
    return out


def build_code(dist: Path, backend: Path) -> list[Path]:
    dist = Path(dist)
    dist.mkdir(parents=True, exist_ok=True)
    package = Path(backend) / "jobmecloud"
    outputs = []
    for name, module in HANDLERS.items():
        if not (package / "handlers" / f"{module}.py").is_file():
            raise BuildError(f"Missing handler module jobmecloud/handlers/{module}.py")
        out = dist / f"{name}.zip"
        _zip(package, out, prefix="jobmecloud/")
        outputs.append(out)
    return outputs


def _unzipped(path: Path) -> int:
    with zipfile.ZipFile(path) as z:
        return sum(i.file_size for i in z.infolist())


def check_sizes(paths: list[Path], zipped_limit: int = ZIPPED_LIMIT, unzipped_limit: int = UNZIPPED_LIMIT) -> None:
    for p in paths:
        if os.path.getsize(p) > zipped_limit:
            raise BuildError(f"{Path(p).name} is over Lambda's 50 MB upload limit. Remove a heavy dependency.")
    layers = [p for p in paths if Path(p).name == "layer.zip"]
    code = [p for p in paths if Path(p).name != "layer.zip"]
    total = sum(_unzipped(p) for p in layers) + max((_unzipped(p) for p in code), default=0)
    if total > unzipped_limit:
        raise BuildError("Code and dependencies together are over Lambda's 250 MB unzipped limit.")


def build_all(dist: Path, root: Path, install: Callable[[Path], None] | None = None) -> list[Path]:
    root = Path(root)
    outputs = [build_layer(dist, install, root), *build_code(dist, root / "backend")]
    check_sizes(outputs)
    return outputs
