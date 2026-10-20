"""S3-compatible object storage (AWS S3, Cloudflare R2, Hetzner, MinIO) for documents.

The bucket is the source of truth. A local store serves as a read-through cache so
document decoding and on-demand PDF rendering keep working on local files; any API or
worker node can serve any document after fetching it from the bucket.
"""

from __future__ import annotations

import json
from typing import Any

from ai_idp.adapters.outbound.storage.local import LocalDocumentBlobStore
from ai_idp.domain.errors import DomainError

RENDER_SUFFIX = ".render.json"


class S3DocumentBlobStore:
    """DocumentBlobStore that writes through to a bucket and reads through a local cache.

    Rendered PDF page images are produced into the cache on demand and never uploaded.
    """

    def __init__(
        self,
        cache: LocalDocumentBlobStore,
        bucket: str,
        *,
        prefix: str = "",
        client: Any | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("S3 storage requires a bucket name.")
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - depends on the installed extra
                raise RuntimeError("S3 storage requires the 'ai-idp[s3]' extra.") from exc
            client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region)
        self._cache = cache
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self.supports_lazy_pdf = bool(getattr(cache, "supports_lazy_pdf", False))

    def _object_key(self, key: str) -> str:
        clean = key.lstrip("/\\").replace("\\", "/")
        if not clean or ".." in clean.split("/"):
            raise DomainError(f"Invalid storage key: '{key}'.", code="invalid_storage_key")
        return self._prefix + clean

    def _download(self, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._object_key(key))
        except self._client.exceptions.NoSuchKey:
            return None
        return response["Body"].read()

    def _cached(self, key: str) -> bool:
        # The plain file check: a cache that renders PDFs also reports descriptors.
        return LocalDocumentBlobStore.exists(self._cache, key)

    def _hydrate(self, key: str) -> None:
        """Copy a blob, or the render descriptor and original behind it, into the cache."""
        if self._cached(key) or self._cached(key + RENDER_SUFFIX):
            return
        content = self._download(key)
        if content is not None:
            LocalDocumentBlobStore.put_bytes(self._cache, key, content)
            return
        descriptor = self._download(key + RENDER_SUFFIX)
        if descriptor is None:
            return
        original = json.loads(descriptor).get("original")
        if isinstance(original, str) and original:
            self._hydrate(original)
        LocalDocumentBlobStore.put_bytes(self._cache, key + RENDER_SUFFIX, descriptor)

    def put_bytes(self, key: str, content: bytes) -> str:
        self._client.put_object(Bucket=self._bucket, Key=self._object_key(key), Body=content)
        LocalDocumentBlobStore.put_bytes(self._cache, key, content)
        return key

    def put_text(self, key: str, text: str) -> str:
        return self.put_bytes(key, text.encode("utf-8"))

    def get_bytes(self, key: str) -> bytes:
        self._hydrate(key)
        return self._cache.get_bytes(key)

    def get_text(self, key: str) -> str:
        return self.get_bytes(key).decode("utf-8", errors="replace")

    def get_size(self, key: str) -> int:
        self._hydrate(key)
        return self._cache.get_size(key)

    def exists(self, key: str) -> bool:
        if self._cache.exists(key):
            return True
        try:
            object_key = self._object_key(key)
        except DomainError:
            return False
        for candidate in (object_key, object_key + RENDER_SUFFIX):
            try:
                self._client.head_object(Bucket=self._bucket, Key=candidate)
                return True
            except self._client.exceptions.ClientError:
                continue
        return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._object_key(key))
        self._cache.delete(key)

    def check_health(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            return False
        return self._cache.check_health()
