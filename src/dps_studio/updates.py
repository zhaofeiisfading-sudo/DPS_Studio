"""Discover and verify official PDV Studio Windows installer releases."""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.client import HTTPException, HTTPResponse
from pathlib import Path
from threading import Event
from typing import Any, cast
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from dps_studio import __version__
from dps_studio.runtime_paths import installation_root, userdata_paths


REPOSITORY = "zhaofeiisfading-sudo/DPS_Studio"
RELEASE_BRANCH = "main"
RELEASES_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
INSTALLER_NAME = "PDV-Studio-Setup-x64.exe"
CHECKSUM_NAME = f"{INSTALLER_NAME}.sha256"
USER_AGENT = f"PDV-Studio/{__version__}"
_GITHUB_HOSTS = {"github.com", "api.github.com", "uploads.github.com"}
_GITHUB_CONTENT_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+githubusercontent\.com")
_VERSION = re.compile(r"[vV]?([0-9]+)\.([0-9]+)\.([0-9]+)")
_SHA256 = r"[0-9a-fA-F]{64}"
_CHUNK_SIZE = 256 * 1024
_NETWORK_TIMEOUT = 5

type Version = tuple[int, int, int]
type ProgressCallback = Callable[[int, int | None], None]


class UpdateError(RuntimeError):
    """An update operation could not complete."""


class UpdateCancelled(UpdateError):
    """The current operation was cancelled."""


class InstallerUnavailable(UpdateError):
    """The release lacks an installer or an authoritative checksum."""


class UpdateIntegrityError(UpdateError):
    """An installer's contents do not match the authoritative checksum."""


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    notes: str
    installer_url: str | None
    checksum_url: str | None
    api_digest: str | None


@dataclass(frozen=True, slots=True)
class UpdateCheck:
    current_version: str
    latest: Release | None

    @property
    def update_available(self) -> bool:
        if self.latest is None:
            return False
        current = parse_version(self.current_version)
        latest = parse_version(self.latest.version)
        return current is not None and latest is not None and latest > current


@dataclass(frozen=True, slots=True)
class DownloadedInstaller:
    path: Path
    sha256: str


def parse_version(tag: str) -> Version | None:
    """Return the numeric version of a formal release tag."""
    match = _VERSION.fullmatch(tag)
    if match is None:
        return None
    try:
        return int(match[1]), int(match[2]), int(match[3])
    except ValueError:  # Python limits conversion of unusually long integers.
        return None


def validate_github_url(url: str) -> None:
    """Require HTTPS without credentials and with a GitHub host."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        valid = (
            parts.scheme == "https"
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and (host in _GITHUB_HOSTS or _GITHUB_CONTENT_HOST.fullmatch(host) is not None)
        )
    except ValueError:
        valid = False
    if not valid:
        raise UpdateError("Update URLs must use HTTPS on an approved GitHub host.")


class GitHubRedirectHandler(HTTPRedirectHandler):
    """Apply the same host policy to every redirect before it is followed."""

    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Request | None:
        validate_github_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_url(url: str, *, api: bool = False) -> HTTPResponse:
    validate_github_url(url)
    headers = {"User-Agent": USER_AGENT}
    if api:
        headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), GitHubRedirectHandler())
    return cast("HTTPResponse", opener.open(Request(url, headers=headers), timeout=_NETWORK_TIMEOUT))


def _check_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelled("The update operation was cancelled.")


def _read_metadata(url: str, limit: int, cancel_event: Event | None, *, api: bool = False) -> bytes:
    _check_cancelled(cancel_event)
    data = bytearray()
    try:
        with _open_url(url, api=api) as response:
            while len(data) <= limit:
                _check_cancelled(cancel_event)
                chunk = response.read1(min(_CHUNK_SIZE, limit + 1 - len(data)))
                if not chunk:
                    _check_cancelled(cancel_event)
                    return bytes(data)
                data.extend(chunk)
    except (OSError, HTTPException) as exc:
        raise UpdateError("Could not retrieve update information from GitHub.") from exc
    raise UpdateError("GitHub update metadata exceeds the supported size.")


def _asset(assets: object, filename: str) -> dict[str, object]:
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, dict) and asset.get("name") == filename:
                return cast("dict[str, object]", asset)
    return {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def check_for_updates(
    *, current_version: str = __version__, cancel_event: Event | None = None
) -> UpdateCheck:
    """Find the highest formal release in the GitHub Releases response."""
    if parse_version(current_version) is None:
        raise UpdateError("The installed version is not a formal version.")
    payload = _read_metadata(RELEASES_URL, 8 * 1024 * 1024, cancel_event, api=True)
    try:
        entries = json.loads(payload)
    except (ValueError, RecursionError) as exc:
        raise UpdateError("GitHub returned invalid release data.") from exc
    if not isinstance(entries, list):
        raise UpdateError("GitHub returned invalid release data.")

    best_version: Version | None = None
    latest: Release | None = None
    for entry in entries:
        _check_cancelled(cancel_event)
        if not isinstance(entry, dict) or entry.get("draft") or entry.get("prerelease"):
            continue
        if entry.get("target_commitish") != RELEASE_BRANCH:
            continue
        version = parse_version(_text(entry.get("tag_name")) or "")
        if version is None or (best_version is not None and version <= best_version):
            continue
        best_version = version
        installer = _asset(entry.get("assets"), INSTALLER_NAME)
        checksum = _asset(entry.get("assets"), CHECKSUM_NAME)
        latest = Release(
            ".".join(map(str, version)),
            _text(entry.get("body")) or "",
            _text(installer.get("browser_download_url")),
            _text(checksum.get("browser_download_url")),
            _text(installer.get("digest")),
        )
    return UpdateCheck(current_version, latest)


def resolve_installer_sha256(release: Release, cancel_event: Event | None = None) -> str:
    """Resolve the installer digest from the Releases API or its checksum asset."""
    _check_cancelled(cancel_event)
    if not release.installer_url:
        raise InstallerUnavailable("The release has no Windows x64 installer.")
    validate_github_url(release.installer_url)
    digest = re.fullmatch(f"sha256:({_SHA256})", release.api_digest or "")
    if digest:
        return digest[1].lower()
    if release.checksum_url:
        payload = _read_metadata(release.checksum_url, 16 * 1024, cancel_event)
        digests = {
            match[1].lower()
            for line in payload.decode("utf-8-sig", errors="replace").splitlines()
            if (match := re.fullmatch(
                rf"({_SHA256})[ \t]+\*?{re.escape(INSTALLER_NAME)}", line.strip()
            ))
        }
        if len(digests) == 1:
            return digests.pop()
    raise InstallerUnavailable("The release has no authoritative installer SHA-256.")


def _installer_path(version: str) -> Path:
    if parse_version(version) is None:
        raise UpdateError("Invalid installer version.")
    cache = userdata_paths().cache_dir.resolve()
    path = cache / "updates" / version / INSTALLER_NAME
    if path.resolve() != path:
        raise UpdateError("The installer cache contains a redirected path.")
    return path


def _sha256_file(path: Path, cancel_event: Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_SIZE):
            _check_cancelled(cancel_event)
            digest.update(chunk)
    _check_cancelled(cancel_event)
    return digest.hexdigest()


def _cached_installer_matches(path: Path, expected: str, cancel_event: Event | None) -> bool:
    try:
        return _sha256_file(path, cancel_event) == expected
    except FileNotFoundError:
        return False


@contextmanager
def _download_lock(path: Path) -> Iterator[None]:
    """Use an OS lock so a crashed process cannot leave the cache permanently busy."""
    if path.resolve() != path:
        raise UpdateError("The installer cache contains a redirected lock path.")
    # Keep the lock file so all processes use the same file identity across retries.
    with path.open("a+b") as lock:
        lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise UpdateError("Another instance is downloading this installer.") from exc
        yield


def download_installer(
    release: Release,
    *,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> DownloadedInstaller:
    """Reuse a verified cache entry or stream the installer into an owned partial file."""
    expected = resolve_installer_sha256(release, cancel_event)
    assert release.installer_url is not None
    try:
        path = _installer_path(release.version)
        if _cached_installer_matches(path, expected, cancel_event):
            return DownloadedInstaller(path, expected)
        _check_cancelled(cancel_event)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".exe.part")
        with _download_lock(path.with_suffix(".lock")):
            _check_cancelled(cancel_event)
            if _cached_installer_matches(path, expected, cancel_event):
                return DownloadedInstaller(path, expected)
            path.unlink(missing_ok=True)
            partial.unlink(missing_ok=True)
            try:
                _download_to_partial(release.installer_url, partial, expected, progress, cancel_event)
                _check_cancelled(cancel_event)
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
    except (OSError, HTTPException) as exc:
        raise UpdateError("Could not download or cache the installer.") from exc
    return DownloadedInstaller(path, expected)


def _download_to_partial(
    url: str, partial: Path, expected: str, progress: ProgressCallback | None,
    cancel_event: Event | None,
) -> None:
    digest = hashlib.sha256()
    downloaded = 0
    with partial.open("xb") as stream, _open_url(url) as response:
        length = response.headers.get("Content-Length", "")
        total = int(length) if re.fullmatch(r"[0-9]{1,19}", length) else None
        if total is not None and total >= 2**63:
            total = None
        if progress is not None:
            progress(downloaded, total)
        while True:
            _check_cancelled(cancel_event)
            chunk = response.read1(_CHUNK_SIZE)
            if not chunk:
                break
            stream.write(chunk)
            digest.update(chunk)
            downloaded += len(chunk)
            if progress is not None:
                progress(downloaded, total)
    _check_cancelled(cancel_event)
    if digest.hexdigest() != expected:
        raise UpdateIntegrityError("The installer failed SHA-256 verification.")


def launch_installer(
    installer: DownloadedInstaller,
    *,
    frozen: bool | None = None,
    install_dir: Path | None = None,
) -> None:
    """Reverify the cached installer immediately before launching the normal setup wizard."""
    try:
        if installer.path.name != INSTALLER_NAME or _sha256_file(installer.path) != installer.sha256:
            raise UpdateIntegrityError("The cached installer failed SHA-256 verification.")
        arguments = [str(installer.path)]
        if install_dir is not None or (getattr(sys, "frozen", False) if frozen is None else frozen):
            root = installation_root() if install_dir is None else install_dir.resolve()
            arguments.extend(["/CURRENTUSER", f"/DIR={root}"])
        subprocess.Popen(arguments)
    except OSError as exc:
        raise UpdateError("Could not read or launch the verified installer.") from exc
