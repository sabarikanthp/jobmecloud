import getpass
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDES = ["deploy", "costs", "security", "operations", "account-recovery", "troubleshooting"]
DOC_FILES = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *(ROOT / "docs" / f"{g}.md" for g in GUIDES)]


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_all_guides_exist():
    for path in DOC_FILES:
        assert path.is_file(), f"missing {path.relative_to(ROOT)}"


def test_readme_links_every_guide():
    readme = text(ROOT / "README.md")
    for guide in GUIDES:
        assert f"docs/{guide}.md" in readme, guide
    assert "CONTRIBUTING.md" in readme


def test_deploy_guide_covers_required_steps():
    guide = text(ROOT / "docs" / "deploy.md").lower()
    for needle in ["billing alert", "root user", "iam identity center", "cdk bootstrap", "build_lambdas",
                   "cdk deploy", "migrate_db", "create_owner", "publish_site", "authenticator",
                   "verify", "region", "timezone", "api key"]:
        assert needle in guide, needle


def test_every_script_named_in_docs_exists():
    for path in DOC_FILES:
        for name in re.findall(r"scripts/([A-Za-z0-9_]+\.py)", text(path)):
            assert (ROOT / "scripts" / name).is_file(), f"{path.name} names scripts/{name}, which does not exist"


def test_internal_links_resolve():
    for path in DOC_FILES:
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text(path)):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            assert (path.parent / target).exists(), f"{path.relative_to(ROOT)} links to missing {target}"


def test_account_recovery_guide_covers_scenarios():
    guide = text(ROOT / "docs" / "account-recovery.md").lower()
    for needle in ["forgot", "lost my phone", "authenticator", "email code", "lost both", "reset_owner",
                   "change the owner email", "lockout", "why there is no", "aws admin"]:
        assert needle in guide, needle


def test_recovery_guide_linked_from_readme_deploy_ops_and_troubleshooting():
    for path in [ROOT / "README.md", ROOT / "docs" / "deploy.md", ROOT / "docs" / "operations.md",
                 ROOT / "docs" / "troubleshooting.md"]:
        assert "account-recovery.md" in text(path), path.name


def test_costs_doc_lists_each_service_and_the_budget_alert():
    costs = text(ROOT / "docs" / "costs.md")
    for service in ["Lambda", "Aurora DSQL", "Cognito", "CloudFront", "S3", "API Gateway", "SES",
                    "Parameter Store", "EventBridge Scheduler", "CloudWatch"]:
        assert service in costs, service
    assert "$5" in costs and "budget" in costs.lower()
    assert "https://aws.amazon.com/" in costs  # links to the official pricing pages


def test_operations_guide_covers_update_backup_and_uninstall():
    ops = text(ROOT / "docs" / "operations.md").lower()
    for needle in ["update", "backup", "uninstall", "cdk destroy", "deletion protection", "retain"]:
        assert needle in ops, needle


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


PUBLIC_MAIL = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "proton.me",
               "protonmail.com", "users.noreply.github.com", "example.com"}


def _own_identifiers() -> set[str]:
    """Who is running the tests: their git identity and login name, read at run time so nothing is hard-coded."""
    found: set[str] = set()
    name = _git("config", "--global", "user.name")
    email = _git("config", "--global", "user.email")
    found.update(word for word in re.split(r"\W+", name) if len(word) >= 4)
    if "@" in email:
        local, domain = email.lower().split("@", 1)
        found.add(local)
        if domain not in PUBLIC_MAIL:
            found.add(domain.split(".")[0])
    found.add(getpass.getuser())
    return {f.lower() for f in found if len(f) >= 4}


def test_no_personal_data_in_repo():
    files = _git("ls-files").split()
    if not files:
        pytest.skip("not a git checkout")
    skipped = {"LICENSE", "uv.lock", "frontend/package-lock.json"}
    identifiers = _own_identifiers()
    account_id = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")
    for name in files:
        path = ROOT / name
        if name in skipped or not path.is_file() or path.suffix in {".png", ".ico", ".docx", ".zip", ".svg"}:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = body.lower()
        for ident in identifiers:
            assert ident not in lowered, f"{name} contains {ident!r}, which identifies whoever ran the tests"
        for found in account_id.findall(body):
            assert found == "123456789012", f"possible AWS account id {found} in {name}"
