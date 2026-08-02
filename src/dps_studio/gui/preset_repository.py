"""Traceable analysis presets backed by the formal workflow configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.workflow import WorkflowConfiguration, load_workflow_config


CUSTOM_PRESET_ID = "custom"
DEFAULT_PRESET_CONFIG_NAME = "pdv_studio_defaults.toml"


@dataclass(frozen=True, slots=True)
class PresetRepository:
    """Expose configured public profiles without profile-specific GUI branches."""

    configuration: WorkflowConfiguration

    @property
    def profiles(self) -> tuple[AnalysisProfile, ...]:
        return self.configuration.analysis.profiles

    @property
    def default_profile(self) -> AnalysisProfile:
        return self.configuration.analysis.default_profile

    @property
    def source_path(self) -> Path:
        return self.configuration.config_path

    @classmethod
    def load(
        cls,
        config_path: str | Path,
        *,
        repository_root: str | Path,
    ) -> PresetRepository:
        """Load one inspectable preset source through the public config loader."""
        return cls(
            load_workflow_config(
                config_path,
                repository_root=repository_root,
            )
        )

    @classmethod
    def load_default(cls, *, repository_root: str | Path) -> PresetRepository:
        """Load the built-in formal desktop defaults."""
        root = Path(repository_root).resolve()
        return cls.load(
            root / "configs" / DEFAULT_PRESET_CONFIG_NAME,
            repository_root=root,
        )


__all__ = [
    "CUSTOM_PRESET_ID",
    "DEFAULT_PRESET_CONFIG_NAME",
    "PresetRepository",
]
