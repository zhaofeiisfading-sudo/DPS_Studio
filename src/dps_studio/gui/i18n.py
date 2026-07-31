"""Qt translation loading and persistent language selection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QTranslator
from PySide6.QtWidgets import QApplication


LANGUAGE_ZH_CN = "zh_CN"
LANGUAGE_EN = "en"
SUPPORTED_LANGUAGES = (LANGUAGE_ZH_CN, LANGUAGE_EN)
LANGUAGE_SETTINGS_KEY = "ui/language"


class TranslationManager:
    """Install a Qt translator and persist the chosen interface language."""

    def __init__(
        self,
        application: QApplication,
        *,
        settings: QSettings | None = None,
    ) -> None:
        self._application = application
        self._settings = settings if settings is not None else QSettings()
        self._translator = QTranslator(application)
        self._installed = False
        self._current_language = LANGUAGE_ZH_CN

    @property
    def current_language(self) -> str:
        """Return the installed language code."""
        return self._current_language

    def configured_language(self) -> str:
        """Return the normalized persisted language code."""
        value = self._settings.value(LANGUAGE_SETTINGS_KEY, LANGUAGE_ZH_CN)
        return normalize_language(str(value))

    def install(self, language_code: str | None = None) -> str:
        """Install the configured translator before user widgets are built."""
        resolved = normalize_language(
            language_code if language_code is not None else self.configured_language()
        )
        if self._installed:
            self._application.removeTranslator(self._translator)
            self._installed = False
        if resolved == LANGUAGE_EN:
            translation_path = (
                Path(__file__).resolve().parent
                / "translations"
                / "pdv_studio_en.qm"
            )
            if not self._translator.load(str(translation_path)):
                raise RuntimeError(
                    f"Could not load Qt translation resource: {translation_path}"
                )
            self._installed = self._application.installTranslator(self._translator)
            if not self._installed:
                raise RuntimeError("Qt refused to install the English translator.")
        self._current_language = resolved
        return resolved

    def save_preference(self, language_code: str) -> str:
        """Persist a language choice; the next application start applies it."""
        resolved = normalize_language(language_code)
        self._settings.setValue(LANGUAGE_SETTINGS_KEY, resolved)
        self._settings.sync()
        return resolved


def normalize_language(language_code: str) -> str:
    """Normalize supported locale spellings and reject unknown languages."""
    normalized = language_code.strip().replace("-", "_").lower()
    if normalized in {"zh", "zh_cn", "chinese"}:
        return LANGUAGE_ZH_CN
    if normalized in {"en", "en_us", "en_gb", "english"}:
        return LANGUAGE_EN
    raise ValueError(
        f"Unsupported interface language {language_code!r}; "
        f"expected one of {SUPPORTED_LANGUAGES!r}."
    )


__all__ = [
    "LANGUAGE_EN",
    "LANGUAGE_ZH_CN",
    "TranslationManager",
    "normalize_language",
]
