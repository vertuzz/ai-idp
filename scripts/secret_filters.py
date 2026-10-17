"""Narrow secret-scan exception for public corpus checksums and pinned revisions."""

import re


def is_public_corpus_hash(secret: str, filename: str, line: str) -> bool:
    path = filename.replace("\\", "/")
    if not path.startswith("eval/") or not path.endswith((".json", ".jsonl")):
        return False
    hashes = re.finditer(
        r'"(?:[a-z_]*sha256|revision|source_revision)"\s*:\s*"([a-f0-9]{40}|[a-f0-9]{64})"',
        line,
    )
    return any(match.group(1) == secret for match in hashes)
