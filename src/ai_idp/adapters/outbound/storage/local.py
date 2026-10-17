from __future__ import annotations

import tempfile
from pathlib import Path

from ai_idp.domain.errors import DomainError


class LocalDocumentBlobStore:
    """Filesystem-backed DocumentBlobStore with path traversal protection."""

    def __init__(self, root_dir: Path) -> None:
        self._root = root_dir.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, key: str) -> Path:
        clean_key = key.lstrip("/\\").replace("\\", "/")
        if not clean_key or ".." in clean_key.split("/"):
            raise DomainError(f"Invalid storage key: '{key}'.", code="invalid_storage_key")
        target = (self._root / clean_key).resolve()
        if not target.is_relative_to(self._root):
            raise DomainError(
                f"Storage key escapes root directory: '{key}'.", code="invalid_storage_key"
            )
        return target

    def put_bytes(self, key: str, content: bytes) -> str:
        target = self._resolve_safe_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            temporary.replace(target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return key

    def get_size(self, key: str) -> int:
        return self._resolve_safe_path(key).stat().st_size

    def get_bytes(self, key: str) -> bytes:
        target = self._resolve_safe_path(key)
        if not target.exists():
            raise DomainError(
                f"Blob not found for key '{key}'.", code="blob_not_found", http_status=404
            )
        return target.read_bytes()

    def put_text(self, key: str, text: str) -> str:
        return self.put_bytes(key, text.encode("utf-8"))

    def get_text(self, key: str) -> str:
        return self.get_bytes(key).decode("utf-8", errors="replace")

    def exists(self, key: str) -> bool:
        try:
            target = self._resolve_safe_path(key)
            return target.is_file()
        except DomainError:
            return False

    def delete(self, key: str) -> None:
        target = self._resolve_safe_path(key)
        if target.is_file():
            target.unlink()

    def check_health(self) -> bool:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            probe = self._root / ".health_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False
