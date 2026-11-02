"""Small named-coefficient editor for the velocity correction panel."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QStandardPaths, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QWidget,
)

from dps_studio.core.physics.models import LIF_RIGG_2014_1550NM, LiFWindowCorrectionModel
from dps_studio.core.physics.exceptions import VelocityConfigurationError
from dps_studio.core.physics.window_presets import (
    WindowPresetError, WindowPresetRepository, is_builtin_window, window_configuration_name,
)


def window_preset_path() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)) / "window_presets.json"


class WindowPresetEditor(QWidget):
    """Explicit save / save-as; changing a name updates provenance immediately."""

    model_selected = Signal(object)

    def __init__(self, repository: WindowPresetRepository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.model = LIF_RIGG_2014_1550NM
        self._original_name: str | None = None
        self._presets: dict[str, LiFWindowCorrectionModel] = {}
        self._read_error: str | None = None
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.preset_combo = QComboBox()
        self.preset_combo.setObjectName("windowPresetSelector")
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("windowPresetName")
        self.save_button = QPushButton(self.tr("保存修改"))
        self.save_as_button = QPushButton(self.tr("另存为新配置…"))
        row = QHBoxLayout()
        row.addWidget(self.save_button)
        row.addWidget(self.save_as_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addRow(self.tr("窗口配置"), self.preset_combo)
        layout.addRow(self.tr("自定义名称"), self.name_edit)
        layout.addRow(row)
        layout.addRow(self.status)
        self.setToolTip(str(repository.path))
        self._reload()
        self.set_model(self.model)
        self.preset_combo.currentIndexChanged.connect(self._selected)
        self.name_edit.editingFinished.connect(self._rename)
        self.save_button.clicked.connect(self.save_current)
        self.save_as_button.clicked.connect(self._save_as)

    def _reload(self) -> None:
        try:
            self._presets = self.repository.load()
            self._read_error = None
        except WindowPresetError as exc:
            self._read_error = str(exc)
        blocker = QSignalBlocker(self.preset_combo)
        self.preset_combo.clear()
        self.preset_combo.addItem(self.tr("LiF · 内置只读预设"), "builtin")
        for name in self._presets:
            self.preset_combo.addItem(self.tr("自定义 · {name}").format(name=name), "user:" + name)
        self.preset_combo.addItem(self.tr("自定义配置 · 未保存修改"), "draft")
        del blocker

    def next_name(self) -> str:
        try:
            return self.repository.next_name()
        except WindowPresetError:
            return "新材料1"  # Saving remains disabled until the file is repaired.

    def reset_save_target(self) -> None:
        """Imported workflows must not overwrite the previously selected entry."""
        self._original_name = None

    def set_model(self, model: LiFWindowCorrectionModel) -> None:
        self.model = model
        builtin = is_builtin_window(model)
        if builtin:
            self._original_name = None
        name = window_configuration_name(model)
        selection = "builtin" if builtin else (
            "user:" + name if self._presets.get(name) == model else "draft"
        )
        blockers = [QSignalBlocker(self.preset_combo), QSignalBlocker(self.name_edit)]
        self.preset_combo.setCurrentIndex(self.preset_combo.findData(selection))
        self.name_edit.setText("" if builtin else model.configuration_name or self.next_name())
        del blockers
        self.name_edit.setEnabled(not builtin)
        self.save_button.setText(self.tr("保存修改") if self._original_name else self.tr("保存自定义配置"))
        self.save_button.setEnabled(not builtin and self._read_error is None)
        self.save_as_button.setEnabled(self._read_error is None)
        self.status.setText(self._read_error or self.tr(
            "仅保存固定幂律形式的用户参数；名称不代表材料标定。"
        ))

    def _selected(self, _index: int) -> None:
        selected = self.preset_combo.currentData()
        if not isinstance(selected, str):
            return
        if selected == "draft":
            return
        previous_target = self._original_name
        self._original_name = None if selected == "builtin" else selected.removeprefix("user:")
        model = (
            LIF_RIGG_2014_1550NM if selected == "builtin" else
            self._presets[selected.removeprefix("user:")]
        )
        self.model_selected.emit(model)
        if self.model != model:
            self._original_name = previous_target

    def _rename(self) -> bool:
        if is_builtin_window(self.model):
            return True
        name = self.name_edit.text().strip()
        try:
            WindowPresetRepository._name(name)
        except WindowPresetError as exc:
            self.status.setText(str(exc))
            return False
        self.model_selected.emit(replace(self.model, configuration_name=name))
        return True

    def save_current(self) -> bool:
        if not self._rename():
            return False
        try:
            self.repository.save(self.model, original_name=self._original_name)
        except WindowPresetError as exc:
            self.status.setText(str(exc))
            return False
        self._original_name = self.model.configuration_name
        self._reload()
        self.set_model(self.model)
        self.status.setText(self.tr("已保存：{path}").format(path=self.repository.path))
        return True

    def _save_as(self) -> None:
        name, accepted = QInputDialog.getText(
            self, self.tr("另存为自定义窗口配置"), self.tr("名称"), text=self.next_name(),
        )
        if not accepted:
            return
        try:
            model = replace(self.model, configuration_name=name.strip())
            self.repository.save(model)
        except (WindowPresetError, VelocityConfigurationError) as exc:
            self.status.setText(str(exc))
            return
        self._original_name = model.configuration_name
        self._reload()
        self.model_selected.emit(model)
        self.status.setText(self.tr("已保存：{path}").format(path=self.repository.path))
