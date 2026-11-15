"""Mirror an S3 prefix to a local folder.

The app's code reads and writes plain files under a data folder. In Lambda that folder is /tmp, so each
invocation pulls what S3 holds and pushes back what changed, instead of every call site learning about S3.
A file this workspace pulled and later finds missing locally is deleted from S3 on the next push.
Files another Lambda added after the last pull are left alone.
"""

import hashlib
import json
from pathlib import Path

import boto3

MANIFEST = ".workspace-manifest.json"
SKIPPED_SUFFIXES = (".db", ".db-wal", ".db-shm")


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class Workspace:
    def __init__(self, bucket: str, prefix: str, local_dir: Path):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.local_dir = Path(local_dir)
        self._s3 = boto3.client("s3")
        self._manifest: dict[str, dict] = self._load_manifest()

    # -- manifest: what S3 and the local copy looked like at the last sync -------------------------
    def _manifest_path(self) -> Path:
        return self.local_dir / MANIFEST

    def _load_manifest(self) -> dict[str, dict]:
        try:
            return json.loads(self._manifest_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_manifest(self) -> None:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path().write_text(json.dumps(self._manifest), encoding="utf-8")

    def _key(self, rel: str) -> str:
        return f"{self.prefix}/{rel}" if self.prefix else rel

    # -- sync ----------------------------------------------------------------------------------------
    def pull(self) -> None:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        for page in self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self.prefix + "/" if self.prefix else ""
        ):
            for obj in page.get("Contents", []):
                rel = obj["Key"][len(self.prefix) + 1:] if self.prefix else obj["Key"]
                if not rel or rel.endswith("/"):
                    continue
                dest = (self.local_dir / rel).resolve()
                if not dest.is_relative_to(self.local_dir.resolve()):
                    continue  # a key like "../x" must never write outside the working folder
                known = self._manifest.get(rel)
                if known and known["etag"] == obj["ETag"] and dest.exists():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                self._s3.download_file(self.bucket, obj["Key"], str(dest))
                self._manifest[rel] = {"etag": obj["ETag"], "md5": _md5(dest)}
        self._save_manifest()

    def push(self) -> list[str]:
        pushed: list[str] = []
        for path in sorted(self.local_dir.rglob("*")):
            if not path.is_file() or path.name == MANIFEST or path.name.endswith(SKIPPED_SUFFIXES):
                continue
            rel = path.relative_to(self.local_dir).as_posix()
            md5 = _md5(path)
            known = self._manifest.get(rel)
            if known and known["md5"] == md5:
                continue
            key = self._key(rel)
            self._s3.upload_file(str(path), self.bucket, key)
            etag = self._s3.head_object(Bucket=self.bucket, Key=key)["ETag"]
            self._manifest[rel] = {"etag": etag, "md5": md5}
            pushed.append(key)
        for rel in [r for r in self._manifest if not (self.local_dir / r).exists()]:
            self._s3.delete_object(Bucket=self.bucket, Key=self._key(rel))
            del self._manifest[rel]
        self._save_manifest()
        return pushed

    def presign(self, relative_key: str, expires: int = 900) -> str:
        return self._s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": self._key(relative_key)}, ExpiresIn=expires
        )
