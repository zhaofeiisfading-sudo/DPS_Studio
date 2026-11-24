"""Prepare local feedback text and prefilled GitHub Issues links."""

from __future__ import annotations

import platform
import sys
from collections.abc import Mapping
from urllib.parse import urlencode

from dps_studio import __version__
from dps_studio.updates import REPOSITORY


ISSUES_URL = f"https://github.com/{REPOSITORY}/issues/new"
CATEGORIES = {"bug": "Bug 反馈", "enhancement": "功能建议", "feedback": "其他意见"}
DIAGNOSTIC_FIELDS = ("app_version", "os", "architecture", "runtime_mode", "ui_language")
MAX_BROWSER_URL_LENGTH = 2000


def collect_safe_diagnostics(language_code: str) -> dict[str, str]:
    """Collect version, OS, architecture, runtime mode and the active UI locale."""
    return {
        "app_version": __version__,
        "os": f"{platform.system()} {platform.release()}".strip(),
        "architecture": platform.machine(),
        "runtime_mode": "frozen" if getattr(sys, "frozen", False) else "source",
        "ui_language": language_code,
    }


def format_feedback(
    category: str, description: str, diagnostics: Mapping[str, str] | None = None
) -> str:
    """Format a GitHub-compatible Markdown issue body."""
    sections = [f"**Category:** {CATEGORIES[category]}", description.strip()]
    if diagnostics:
        lines = [f"- {field}: {diagnostics[field]}" for field in DIAGNOSTIC_FIELDS
                 if field in diagnostics]
        if lines:
            sections.append("### Environment\n\n" + "\n".join(lines))
    return "\n\n".join(section for section in sections if section)


def build_issue_url(
    title: str, body: str, category: str, *, include_label: bool = True,
) -> tuple[str, bool]:
    """Encode a GitHub issue draft and flag links that need the clipboard fallback."""
    if category not in CATEGORIES:
        raise ValueError(f"Unsupported feedback category: {category}")
    query = {"title": title.strip(), "body": body}
    if include_label:
        query["labels"] = category
    url = f"{ISSUES_URL}?{urlencode(query)}"
    return url, len(url) > MAX_BROWSER_URL_LENGTH


def build_title_only_url(title: str) -> str:
    """Prefill the title when it fits the browser limit."""
    url = f"{ISSUES_URL}?{urlencode({'title': title.strip()})}"
    return url if len(url) <= MAX_BROWSER_URL_LENGTH else ISSUES_URL
