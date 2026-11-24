from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from dps_studio import __version__, feedback


@pytest.mark.parametrize("frozen", [True, False])
def test_diagnostics_are_allowlisted(monkeypatch: pytest.MonkeyPatch, frozen: bool) -> None:
    private_values = {
        "USERNAME": "private-user",
        "COMPUTERNAME": "private-computer",
        "USERPROFILE": "C:/Users/private-user",
        "PDV_STUDIO_USERDATA_DIR": "D:/private-repo/userdata",
        "RECENT_FILE": "private-pdv-sample.csv",
    }
    for key, value in private_values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(feedback.platform, "system", lambda: "Windows")
    monkeypatch.setattr(feedback.platform, "release", lambda: "11")
    monkeypatch.setattr(feedback.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(feedback.platform, "node", lambda: private_values["COMPUTERNAME"])
    monkeypatch.setattr(feedback.sys, "frozen", frozen, raising=False)

    diagnostics = feedback.collect_safe_diagnostics("en")
    assert diagnostics == {
        "app_version": __version__,
        "os": "Windows 11",
        "architecture": "AMD64",
        "runtime_mode": "frozen" if frozen else "source",
        "ui_language": "en",
    }
    assert all(value not in str(diagnostics) for value in private_values.values())


@pytest.mark.parametrize(("category", "label"), [
    ("bug", "Bug 反馈"), ("enhancement", "功能建议"), ("feedback", "其他意见"),
])
def test_issue_url_and_markdown(category: str, label: str) -> None:
    body = feedback.format_feedback(category, "  复现步骤\n\n- 打开 C++ & 测试 #1\n")
    assert body == f"**Category:** {label}\n\n复现步骤\n\n- 打开 C++ & 测试 #1"
    url, too_long = feedback.build_issue_url(" 反馈 #42 & C++ ", body, category)
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https", "github.com", "/zhaofeiisfading-sudo/DPS_Studio/issues/new"
    )
    assert not too_long
    assert parse_qs(parts.query) == {
        "title": ["反馈 #42 & C++"], "body": [body], "labels": [category]
    }
    public_url, too_long = feedback.build_issue_url(
        " 反馈 #42 & C++ ", body, category, include_label=False,
    )
    assert not too_long
    assert parse_qs(urlsplit(public_url).query) == {"title": ["反馈 #42 & C++"], "body": [body]}


def test_markdown_diagnostics_use_only_expected_fields() -> None:
    diagnostics = {"ui_language": "zh_CN", "app_version": __version__, "cwd": "D:/secret"}
    markdown = feedback.format_feedback("bug", "描述", diagnostics)
    assert markdown == (
        f"**Category:** Bug 反馈\n\n描述\n\n### Environment\n\n"
        f"- app_version: {__version__}\n- ui_language: zh_CN"
    )


def test_long_body_has_title_only_fallback_and_preserves_text() -> None:
    body = feedback.format_feedback("enhancement", "建议" * 600)
    url, too_long = feedback.build_issue_url("标题", body, "enhancement")
    assert too_long
    assert parse_qs(urlsplit(url).query)["body"] == [body]
    assert parse_qs(urlsplit(feedback.build_title_only_url("标题")).query) == {"title": ["标题"]}
    assert feedback.build_title_only_url("标题" * 600) == feedback.ISSUES_URL
