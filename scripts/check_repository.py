"""Offline publication checks against the exact Git index, including binary metadata."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

import yaml
from pypdf import PdfReader

LOCAL_PATH = re.compile(r"""(?:[A-Za-z]:[/\\]Users[/\\]|/(?:Users|home)/)[^/\\\r\n"'<>]+[/\\]""")
FORBIDDEN_ROOTS = {
    "eval/downloads",
    "eval/cache",
    "eval/results",
    "data",
    "uploads",
    "artifacts",
    "telemetry",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
PRIVATE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".sqlite3",
    ".exe",
    ".dll",
    ".whl",
    ".parquet",
    ".zip",
    ".tar",
    ".gz",
}
FIXTURE_IDENTITIES = {"", "anonymous", "AI-IDP", "AI-IDP synthetic fixture generator"}


def document_metadata(path: str, data: bytes) -> dict[str, str]:
    if path.endswith(".pdf"):
        return {str(k): str(v) for k, v in (PdfReader(io.BytesIO(data)).metadata or {}).items()}
    if path.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            core = ElementTree.fromstring(archive.read("docProps/core.xml"))
        return {element.tag.rsplit("}", 1)[-1]: element.text or "" for element in core}
    return {}


def check_blob(path: str, data: bytes) -> list[str]:
    """Return category-only diagnostics; never echo potentially sensitive content."""
    errors = []
    file = PurePosixPath(path)
    if any(path == root or path.startswith(root + "/") for root in FORBIDDEN_ROOTS):
        errors.append("local artifacts must not be tracked")
    if "__pycache__" in file.parts or file.suffix in PRIVATE_SUFFIXES:
        errors.append("private, generated or downloaded binary file")
    if file.name.startswith(".env") and file.name != ".env.example":
        errors.append("local environment configuration")
    if file.suffix == ".jsonl" and path != "eval/manifest.jsonl":
        errors.append("generated JSONL output")
    if file.suffix.lower() in DOCUMENT_SUFFIXES and not path.startswith("eval/fixtures/synthetic/"):
        errors.append("only project-owned synthetic document fixtures may be tracked")
    if file.suffix.lower() not in DOCUMENT_SUFFIXES:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return errors + ["unexpected binary or non-UTF-8 text file"]
        if LOCAL_PATH.search(text):
            errors.append("personal local filesystem path")
        try:
            if file.suffix == ".json":
                json.loads(text)
            elif file.suffix == ".jsonl":
                for line in text.splitlines():
                    if line.strip():
                        json.loads(line)
            elif file.suffix in {".toml", ".lock"}:
                tomllib.loads(text)
            elif file.suffix in {".yaml", ".yml"}:
                yaml.safe_load(text)
        except (ValueError, yaml.YAMLError):
            errors.append("invalid JSON, TOML or YAML")
    try:
        metadata = document_metadata(path, data)
        if any(LOCAL_PATH.search(value) for value in metadata.values()):
            errors.append("personal path in document metadata")
        for key in ("/Author", "/Creator", "creator", "lastModifiedBy"):
            if key in metadata and metadata[key] not in FIXTURE_IDENTITIES:
                errors.append("document author/creator metadata needs review")
    except Exception:
        errors.append("unreadable document metadata")
    return errors


def read_index() -> dict[str, bytes]:
    records = subprocess.check_output(["git", "ls-files", "--stage", "-z"]).split(b"\0")
    entries = []
    for record in records:
        if not record:
            continue
        info, path = record.split(b"\t", 1)
        mode, oid, stage = info.split()
        if stage != b"0" or mode not in (b"100644", b"100755"):
            raise ValueError("Unmerged entries, symlinks and submodules require review.")
        entries.append((path.decode("utf-8"), oid))
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        input=b"".join(oid + b"\n" for _, oid in entries),
        capture_output=True,
        check=True,
    )
    stream = io.BytesIO(result.stdout)
    blobs = {}
    for path, _ in entries:
        _, kind, size = stream.readline().split()
        if kind != b"blob":
            raise ValueError("Expected a staged file blob.")
        blobs[path] = stream.read(int(size))
        if stream.read(1) != b"\n":
            raise ValueError("Invalid Git batch response.")
    return blobs


def check_fixtures(blobs: dict[str, bytes]) -> list[str]:
    errors = []
    manifest = blobs.get("eval/manifest.jsonl")
    if manifest is None:
        return ["missing corpus manifest"]
    cases = [json.loads(line) for line in manifest.splitlines() if line.strip()]
    if len(cases) != 120 or len({c["case_id"] for c in cases}) != 120:
        errors.append("corpus must retain 120 unique candidate identities")
    groups = {}
    for case in cases:
        splits = groups.setdefault(case["group_id"], set())
        splits.add(case["split"])
        fixture = case.get("repository_fixture")
        if fixture:
            content = blobs.get(fixture)
            if content is None or hashlib.sha256(content).hexdigest() != case["sha256"]:
                errors.append(f"{case['case_id']}: synthetic fixture missing or hash mismatch")
    if any(len(splits) > 1 for splits in groups.values()):
        errors.append("corpus group crosses data splits")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args()
    if args.worktree:
        names = (
            subprocess.check_output(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
            )
            .decode("utf-8")
            .split("\0")
        )
        blobs = {name: Path(name).read_bytes() for name in names if name and Path(name).is_file()}
    else:
        blobs = read_index()
    errors = []
    for path, data in blobs.items():
        errors.extend(f"{path}: {error}" for error in check_blob(path, data))
    if not any("invalid JSON" in error for error in errors):
        errors.extend(check_fixtures(blobs))
    if errors:
        print("Repository checks failed:\n" + "\n".join(errors))
        return 1
    scope = "worktree" if args.worktree else "staged"
    print(f"Checked {len(blobs)} {scope} files, document metadata and synthetic fixture hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
