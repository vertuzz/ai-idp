"""Render PDF pages on demand in monitored child processes, with a bounded disk cache."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

from ai_idp.adapters.outbound.storage.local import LocalDocumentBlobStore
from ai_idp.domain.errors import DocumentLimitExceededError, MalformedDocumentError

if TYPE_CHECKING:
    from ai_idp.settings import Settings


class PdfArtifactStore(LocalDocumentBlobStore):
    supports_lazy_pdf = True

    def __init__(self, settings: Settings):
        super().__init__(settings.local_storage_root)
        self.settings = settings
        self._render_lock = threading.Lock()

    def exists(self, key: str) -> bool:
        return super().exists(key) or super().exists(key + ".render.json")

    def get_size(self, key: str) -> int:
        with self._render_lock:
            return self._access(key, size_only=True)

    def get_bytes(self, key: str) -> bytes:
        with self._render_lock:
            return self._access(key, size_only=False)

    def _access(self, key, *, size_only):
        # A per-document SQLite write lock also coordinates independent API and
        # worker processes. Cache eviction cannot race an authorized image read.
        if not super().exists(key + ".render.json"):
            return super().get_size(key) if size_only else super().get_bytes(key)
        parent = self._resolve_safe_path(key).parent
        with (
            closing(
                sqlite3.connect(
                    parent / ".cache-lock.sqlite3", timeout=self.settings.document_timeout_seconds
                )
            ) as connection,
            connection,
        ):
            connection.execute("BEGIN IMMEDIATE")
            self._ensure(key)
            return super().get_size(key) if size_only else super().get_bytes(key)

    def _ensure(self, key: str) -> None:
        if super().exists(key) or not super().exists(key + ".render.json"):
            return
        descriptor = json.loads(super().get_bytes(key + ".render.json"))
        original = self._resolve_safe_path(descriptor["original"])
        target = self._resolve_safe_path(key)
        with tempfile.TemporaryDirectory(prefix="ai-idp-page-") as temporary:
            root = Path(temporary)
            request = {**descriptor, "original": str(original), "output": str(root / "page.png")}
            (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
            started = time.monotonic()
            with subprocess.Popen(
                [sys.executable, "-m", __name__, str(root / "request.json")],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ) as child:
                process = psutil.Process(child.pid)
                try:
                    while child.poll() is None:
                        if time.monotonic() - started > self.settings.document_timeout_seconds:
                            raise DocumentLimitExceededError(
                                "PDF page rendering time limit exceeded."
                            )
                        try:
                            if (
                                process.memory_info().rss
                                > self.settings.document_memory_mib * 1024**2
                            ):
                                raise DocumentLimitExceededError(
                                    "PDF page rendering memory limit exceeded."
                                )
                        except psutil.NoSuchProcess:
                            break
                        try:
                            child.wait(timeout=0.05)
                        except subprocess.TimeoutExpired:
                            pass
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait()
            output = root / "page.png"
            if child.returncode or not output.exists():
                raise MalformedDocumentError("PDF page rendering failed.")
            size = output.stat().st_size
            cache_limit = min(self.settings.max_expanded_bytes, 64 * 1024**2)
            if size > cache_limit:
                raise DocumentLimitExceededError("Rendered PDF page exceeds its cache budget.")
            target.parent.mkdir(parents=True, exist_ok=True)
            # This cache contains only generated page images, never originals.
            cached = sorted(target.parent.glob("*.png"), key=lambda p: p.stat().st_mtime)
            total = sum(p.stat().st_size for p in cached)
            for path in cached:
                if total + size <= cache_limit:
                    break
                total -= path.stat().st_size
                path.unlink(missing_ok=True)
            self.put_bytes(key, output.read_bytes())


def _main():
    import pymupdf

    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    with pymupdf.open(request["original"]) as pdf:
        page = pdf[request["page_index"]]
        picture = page.get_pixmap(
            matrix=pymupdf.Matrix(request["scale"], request["scale"]), alpha=False
        )
        if picture.width * picture.height > request["max_pixels"] + 100_000:
            raise ValueError("Rendered page exceeds the pixel budget.")
        picture.save(request["output"])


if __name__ == "__main__":
    _main()
