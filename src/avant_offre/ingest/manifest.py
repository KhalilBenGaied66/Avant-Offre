"""data/manifest.json: source URL, download date and checksum of every snapshot.

Also holds the shared HTTP plumbing (retrying client, resumable conditional download) so every
downloader records provenance the same way.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from avant_offre.runinfo import utc_now
from avant_offre.settings import get_settings

log = logging.getLogger(__name__)

CHUNK = 1 << 20


class ManifestEntry(BaseModel):
    name: str
    source_url: str
    final_url: str = ""
    path: str
    downloaded_at: str
    sha256: str = ""
    bytes: int = 0
    licence: str = ""
    etag: str | None = None
    last_modified: str | None = None
    extra: dict[str, str | int | float | None] = Field(default_factory=dict)


class Manifest(BaseModel):
    entries: dict[str, ManifestEntry] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> Manifest:
        path = path or get_settings().manifest_path
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path | None = None) -> None:
        path = path or get_settings().manifest_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)

    def record(self, entry: ManifestEntry, path: Path | None = None) -> None:
        self.entries[entry.name] = entry
        self.save(path)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    # A proxy refusal is a policy decision, not a transient failure: never retry it.
    return isinstance(exc, httpx.TransportError) and not isinstance(exc, httpx.ProxyError)


def with_retries[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Retry transient HTTP failures (5xx, 429, transport errors) with exponential backoff."""
    s = get_settings()
    decorator = retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(s.http.retries),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    return decorator(fn)


@contextmanager
def http_client(transport: httpx.BaseTransport | None = None) -> Iterator[httpx.Client]:
    s = get_settings()
    with httpx.Client(
        follow_redirects=True,
        timeout=s.http.timeout_s,
        headers={"User-Agent": s.http.user_agent},
        transport=transport,
    ) as client:
        yield client


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


DownloadStatus = Literal["downloaded", "unchanged"]


def download(
    name: str,
    url: str,
    dest: Path,
    *,
    licence: str = "",
    client: httpx.Client | None = None,
    manifest: Manifest | None = None,
) -> tuple[DownloadStatus, ManifestEntry]:
    """Download ``url`` to ``dest`` once; skip when the server says it is unchanged.

    - Conditional request (ETag / Last-Modified from the manifest): 304 => skip.
    - Resumable: a partial ``dest.part`` is continued with a Range request.
    - The manifest records source URL, final URL, date, size and sha256.
    """
    manifest = manifest or Manifest.load()
    previous = manifest.entries.get(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    def _do(c: httpx.Client) -> tuple[DownloadStatus, ManifestEntry]:
        headers: dict[str, str] = {}
        if previous and dest.exists():
            if previous.etag:
                headers["If-None-Match"] = previous.etag
            if previous.last_modified:
                headers["If-Modified-Since"] = previous.last_modified
        offset = part.stat().st_size if part.exists() else 0
        if offset:
            headers["Range"] = f"bytes={offset}-"
        with c.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 304 and previous:
                log.info("%s unchanged (304)", name)
                return "unchanged", previous
            resp.raise_for_status()
            mode = "ab" if resp.status_code == 206 else "wb"
            with part.open(mode) as fh:
                for chunk in resp.iter_bytes(CHUNK):
                    fh.write(chunk)
            etag = resp.headers.get("ETag")
            last_modified = resp.headers.get("Last-Modified")
            final_url = str(resp.url)
        digest = sha256_file(part)
        if previous and previous.sha256 == digest and dest.exists():
            part.unlink()
            log.info("%s unchanged (same sha256)", name)
            return "unchanged", previous
        part.replace(dest)
        entry = ManifestEntry(
            name=name,
            source_url=url,
            final_url=final_url,
            path=str(dest),
            downloaded_at=utc_now(),
            sha256=digest,
            bytes=dest.stat().st_size,
            licence=licence,
            etag=etag,
            last_modified=last_modified,
        )
        manifest.record(entry)
        return "downloaded", entry

    run = with_retries(_do)
    if client is not None:
        return run(client)
    with http_client() as c:
        return run(c)
