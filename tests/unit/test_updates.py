from __future__ import annotations

import hashlib
import io
import json
import ssl
from collections.abc import Iterator
from pathlib import Path
from threading import Event
from urllib.request import HTTPSHandler, Request

import pytest

from dps_studio import __version__, updates
from dps_studio.runtime_paths import USERDATA_ENV_VAR, userdata_paths


INSTALLER_URL = f"https://github.com/{updates.REPOSITORY}/releases/download/v0.2.1/{updates.INSTALLER_NAME}"
CHECKSUM_URL = f"{INSTALLER_URL}.sha256"
INSTALLER_BYTES = b"test installer payload"
SHA256 = hashlib.sha256(INSTALLER_BYTES).hexdigest()


class Response(io.BytesIO):
    def __init__(self, body: bytes, *, include_length: bool = True) -> None:
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))} if include_length else {}


def release(*, digest: str | None = f"sha256:{SHA256}", checksum: str | None = None) -> updates.Release:
    return updates.Release("0.2.1", "Release notes", INSTALLER_URL, checksum, digest)


@pytest.fixture
def installer_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv(USERDATA_ENV_VAR, str(tmp_path / "installation" / "userdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    path = userdata_paths().cache_dir / "updates" / "0.2.1" / updates.INSTALLER_NAME
    yield path
    path.unlink(missing_ok=True)
    path.with_suffix(".exe.part").unlink(missing_ok=True)


@pytest.mark.parametrize(("tag", "version"), [
    ("v0.2.0", (0, 2, 0)),
    ("V0.2.1", (0, 2, 1)),
    ("0.3.0", (0, 3, 0)),
    ("1.0.0", (1, 0, 0)),
    ("v1.0.0-alpha", None),
    ("v1.0.0-beta", None),
    ("v1.0.0-rc", None),
    ("v1.0.0+build", None),
    ("nightly", None),
    ("1.0", None),
    ("v1.0.0\n", None),
])
def test_parse_version(tag: str, version: updates.Version | None) -> None:
    assert updates.parse_version(tag) == version


@pytest.mark.parametrize(("tag", "available"), [
    ("0.2.0", False), ("0.2.1", True), ("0.3.0", True), ("1.0.0", True), ("0.10.0", True),
    ("0.1.99", False),
])
def test_compare_with_installed_version(tag: str, available: bool) -> None:
    latest = updates.Release(tag, "", None, None, None)
    assert updates.UpdateCheck("0.2.0", latest).update_available is available


def test_check_uses_only_releases_api_and_filters_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    formal = {
        "target_commitish": "main", "draft": False, "prerelease": False,
        "tag_name": "v0.2.1", "body": "Changes", "assets": [
            {"name": "unrelated.exe", "browser_download_url": "https://github.com/unrelated"},
            {"name": updates.INSTALLER_NAME, "browser_download_url": INSTALLER_URL,
             "digest": f"sha256:{SHA256}"},
            {"name": updates.CHECKSUM_NAME, "browser_download_url": CHECKSUM_URL},
        ],
    }
    entries = [
        formal, {**formal, "tag_name": "9.0.0", "draft": True},
        {**formal, "tag_name": "9.0.0", "prerelease": True},
        {**formal, "tag_name": "9.0.0", "target_commitish": "dev"},
        {**formal, "tag_name": "9.0.0", "target_commitish": "a" * 40},
        {**formal, "tag_name": "9.0.0-rc.1"},
        {**formal, "tag_name": "latest"},
        {**formal, "tag_name": "V0.10.0", "body": "Newer"},
        {**formal, "tag_name": "v0.3.0"},
    ]
    requests = []

    def open_url(url: str, *, api: bool = False) -> Response:
        requests.append((url, api))
        return Response(json.dumps(entries).encode())

    monkeypatch.setattr(updates, "_open_url", open_url)
    result = updates.check_for_updates(current_version="0.2.0")
    assert requests == [
        ("https://api.github.com/repos/zhaofeiisfading-sudo/DPS_Studio/releases?per_page=30", True)
    ]
    assert result.update_available
    assert result.latest == updates.Release(
        "0.10.0", "Newer", INSTALLER_URL, CHECKSUM_URL, f"sha256:{SHA256}"
    )


@pytest.mark.parametrize("body", [b"[]", b"[\"not an object\", {\"tag_name\": \"v9.0.0\"}]"])
def test_no_formal_releases(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    monkeypatch.setattr(updates, "_open_url", lambda *_args, **_kwargs: Response(body))
    result = updates.check_for_updates()
    assert result.current_version == __version__
    assert result.latest is None
    assert not result.update_available


@pytest.mark.parametrize("body", [b"{", b"{}", b"null"])
def test_malformed_api_response(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    monkeypatch.setattr(updates, "_open_url", lambda *_args, **_kwargs: Response(body))
    with pytest.raises(updates.UpdateError, match="invalid release data"):
        updates.check_for_updates()


def test_http_uses_verified_context_headers_and_restricted_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Opener:
        def open(self, request: Request, *, timeout: float) -> Response:
            assert request.full_url == updates.RELEASES_URL
            headers = {key.lower(): value for key, value in request.header_items()}
            assert headers == {
                "accept": "application/vnd.github+json",
                "x-github-api-version": "2022-11-28",
                "user-agent": f"PDV-Studio/{__version__}",
            }
            assert 0 < timeout <= 10
            return Response(b"[]")

    def build(https: HTTPSHandler, redirects: updates.GitHubRedirectHandler) -> Opener:
        assert https._context.verify_mode == ssl.CERT_REQUIRED
        assert https._context.check_hostname
        assert isinstance(redirects, updates.GitHubRedirectHandler)
        return Opener()

    monkeypatch.setattr(updates, "build_opener", build)
    assert updates.check_for_updates().latest is None


@pytest.mark.parametrize("url", [
    "http://github.com/download",
    "https://github.com.example.net/download",
    "https://evilgithubusercontent.com/download",
    "https://githubusercontent.com/download",
    "https://release-assets.githubusercontent.com.example.net",
    "https://github.com@outside.example",
    "https://outside.example@github.com",
    "https://outside.example%2F.a.githubusercontent.com",
    "https://github.com:9999",
    "file:///installer.exe",
])
def test_rejects_unapproved_initial_and_redirect_urls(url: str) -> None:
    redirect = updates.GitHubRedirectHandler()
    with pytest.raises(updates.UpdateError, match="HTTPS"):
        updates._open_url(url)
    with pytest.raises(updates.UpdateError, match="HTTPS"):
        redirect.redirect_request(Request(INSTALLER_URL), None, 302, "Found", {}, url)


@pytest.mark.parametrize("host", [
    "github.com", "api.github.com", "uploads.github.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com", "some.cdn.githubusercontent.com",
])
def test_approved_redirect_hosts(host: str) -> None:
    target = f"https://{host}/downloads/installer.exe"
    request = updates.GitHubRedirectHandler().redirect_request(
        Request(INSTALLER_URL), None, 302, "Found", {}, target
    )
    assert request is not None and request.full_url == target


def test_resolves_api_digest_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates, "_open_url", lambda *_args: pytest.fail("Unexpected network call"))
    assert updates.resolve_installer_sha256(release(digest=f"sha256:{SHA256.upper()}")) == SHA256


def test_resolves_exact_installer_checksum_from_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    def open_url(url: str, *, api: bool = False) -> Response:
        assert url == CHECKSUM_URL
        assert not api
        return Response(
            f"\ufeff{'0' * 64}  different.exe\r\n{SHA256.upper()}  {updates.INSTALLER_NAME}\r\n".encode()
        )

    monkeypatch.setattr(updates, "_open_url", open_url)
    assert updates.resolve_installer_sha256(release(digest=None, checksum=CHECKSUM_URL)) == SHA256


@pytest.mark.parametrize("content", [
    "",
    f"{SHA256}  other.exe",
    f"garbage  {updates.INSTALLER_NAME}",
    f"{SHA256}\n",
    f"{SHA256}  {updates.INSTALLER_NAME}\n{'0' * 64}  {updates.INSTALLER_NAME}",
])
def test_rejects_missing_invalid_or_ambiguous_checksum(
    monkeypatch: pytest.MonkeyPatch, content: str,
) -> None:
    monkeypatch.setattr(updates, "_open_url", lambda *_args, **_kwargs: Response(content.encode()))
    with pytest.raises(updates.InstallerUnavailable, match="authoritative"):
        updates.resolve_installer_sha256(release(digest="sha256:1234", checksum=CHECKSUM_URL))
    with pytest.raises(updates.InstallerUnavailable, match="authoritative"):
        updates.resolve_installer_sha256(release(digest=None))
    with pytest.raises(updates.InstallerUnavailable, match="no Windows"):
        updates.resolve_installer_sha256(updates.Release("0.2.1", "", None, None, None))


@pytest.mark.parametrize("known_size", [True, False])
def test_download_streams_progress_and_commits_verified_file(
    monkeypatch: pytest.MonkeyPatch, installer_path: Path, known_size: bool,
) -> None:
    monkeypatch.setattr(updates, "_CHUNK_SIZE", 5)
    monkeypatch.setattr(
        updates, "_open_url", lambda _url: Response(INSTALLER_BYTES, include_length=known_size)
    )
    progress = []

    def report(done: int, total: int | None) -> None:
        assert installer_path.with_suffix(".exe.part").is_file()
        assert not installer_path.exists()
        progress.append((done, total))

    result = updates.download_installer(release(), progress=report)
    assert result == updates.DownloadedInstaller(installer_path, SHA256)
    assert installer_path.read_bytes() == INSTALLER_BYTES
    assert not installer_path.with_suffix(".exe.part").exists()
    total = len(INSTALLER_BYTES) if known_size else None
    assert progress == [(value, total) for value in [0, 5, 10, 15, 20, len(INSTALLER_BYTES)]]
    assert not (installer_path.parents[5] / "appdata").exists()
    assert not (installer_path.parents[5] / "temp").exists()


def test_cancel_mid_download_removes_partial(monkeypatch: pytest.MonkeyPatch, installer_path: Path) -> None:
    monkeypatch.setattr(updates, "_CHUNK_SIZE", 5)
    monkeypatch.setattr(updates, "_open_url", lambda _url: Response(INSTALLER_BYTES))
    cancel = Event()

    def report(done: int, _total: int | None) -> None:
        if done:
            cancel.set()

    with pytest.raises(updates.UpdateCancelled):
        updates.download_installer(release(), progress=report, cancel_event=cancel)
    assert not installer_path.with_suffix(".exe.part").exists()
    assert not installer_path.exists()


def test_download_mismatch_deletes_partial_and_is_not_launchable(
    monkeypatch: pytest.MonkeyPatch, installer_path: Path,
) -> None:
    monkeypatch.setattr(updates, "_open_url", lambda _url: Response(b"wrong executable"))
    monkeypatch.setattr(updates.subprocess, "Popen", lambda _args: pytest.fail("Unexpected launch"))
    with pytest.raises(updates.UpdateIntegrityError, match="SHA-256"):
        updates.download_installer(release())
    assert not installer_path.with_suffix(".exe.part").exists()
    assert not installer_path.exists()
    with pytest.raises(updates.UpdateError):
        updates.launch_installer(updates.DownloadedInstaller(installer_path, SHA256))


def test_download_read_failure_removes_partial(monkeypatch: pytest.MonkeyPatch, installer_path: Path) -> None:
    class InterruptedResponse(Response):
        def read1(self, _size: int) -> bytes:
            raise TimeoutError("Read interrupted.")

    monkeypatch.setattr(updates, "_open_url", lambda _url: InterruptedResponse(INSTALLER_BYTES))
    with pytest.raises(updates.UpdateError, match="download"):
        updates.download_installer(release())
    assert not installer_path.with_suffix(".exe.part").exists()
    assert not installer_path.exists()


def test_cache_reuse_and_corruption_recovery(monkeypatch: pytest.MonkeyPatch, installer_path: Path) -> None:
    installer_path.parent.mkdir(parents=True)
    installer_path.write_bytes(INSTALLER_BYTES)
    requests = []

    def open_url(url: str) -> Response:
        assert not installer_path.exists()
        requests.append(url)
        return Response(INSTALLER_BYTES)

    monkeypatch.setattr(updates, "_open_url", open_url)
    first = updates.download_installer(release())
    assert requests == []
    installer_path.write_bytes(b"corrupt")
    assert updates.download_installer(release()) == first
    assert requests == [INSTALLER_URL]
    assert installer_path.read_bytes() == INSTALLER_BYTES


def test_rejects_invalid_version_path(monkeypatch: pytest.MonkeyPatch, installer_path: Path) -> None:
    monkeypatch.setattr(updates, "_open_url", lambda _url: pytest.fail("Unexpected download"))
    invalid = updates.Release("../other", "", INSTALLER_URL, None, f"sha256:{SHA256}")
    with pytest.raises(updates.UpdateError, match="version"):
        updates.download_installer(invalid)
    assert not installer_path.parent.exists()


def test_competing_download_preserves_owned_partial(monkeypatch: pytest.MonkeyPatch, installer_path: Path) -> None:
    installer_path.parent.mkdir(parents=True)
    partial = installer_path.with_suffix(".exe.part")
    partial.write_bytes(b"another transfer")
    monkeypatch.setattr(updates, "_open_url", lambda _url: pytest.fail("Unexpected download"))
    with updates._download_lock(installer_path.with_suffix(".lock")):
        with pytest.raises(updates.UpdateError, match="Another instance"):
            updates.download_installer(release())
        assert partial.read_bytes() == b"another transfer"


def test_stale_partial_can_be_retried(monkeypatch: pytest.MonkeyPatch, installer_path: Path) -> None:
    installer_path.parent.mkdir(parents=True)
    partial = installer_path.with_suffix(".exe.part")
    partial.write_bytes(b"interrupted transfer")
    monkeypatch.setattr(updates, "_open_url", lambda _url: Response(INSTALLER_BYTES))
    assert updates.download_installer(release()).path == installer_path
    assert installer_path.read_bytes() == INSTALLER_BYTES
    assert not partial.exists()


@pytest.mark.parametrize("mode", ["runtime", "explicit_frozen", "explicit_directory", "source"])
def test_launch_is_normal_and_targets_current_installation(
    monkeypatch: pytest.MonkeyPatch, installer_path: Path, mode: str,
) -> None:
    installer_path.parent.mkdir(parents=True)
    installer_path.write_bytes(INSTALLER_BYTES)
    install_dir = installer_path.parents[3] / "PDV Studio"
    monkeypatch.setattr(updates.sys, "frozen", mode == "runtime", raising=False)
    monkeypatch.setattr(updates, "installation_root", lambda: install_dir)
    invocations = []
    monkeypatch.setattr(updates.subprocess, "Popen", invocations.append)
    installer = updates.DownloadedInstaller(installer_path, SHA256)
    if mode == "explicit_frozen":
        updates.launch_installer(installer, frozen=True)
    elif mode == "explicit_directory":
        updates.launch_installer(installer, install_dir=install_dir)
    else:
        updates.launch_installer(installer)
    flags = ["/CURRENTUSER", f"/DIR={install_dir}"] if mode != "source" else []
    assert invocations == [[str(installer_path), *flags]]


def test_launch_rechecks_cached_bytes(monkeypatch: pytest.MonkeyPatch, installer_path: Path) -> None:
    installer_path.parent.mkdir(parents=True)
    installer_path.write_bytes(b"tampered")
    monkeypatch.setattr(updates.subprocess, "Popen", lambda _args: pytest.fail("Unexpected launch"))
    with pytest.raises(updates.UpdateIntegrityError, match="SHA-256"):
        updates.launch_installer(updates.DownloadedInstaller(installer_path, SHA256))
