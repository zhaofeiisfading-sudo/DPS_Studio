"""Explicit column and unit mapping for delimited signal import."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dps_studio.gui.data_controller import ChannelImportSpec, SignalLoadRequest


class ImportSettingsDialog(QDialog):
    """Collect every reader parameter that cannot be safely inferred."""

    def __init__(self, source_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_path = source_path
        self.setWindowTitle(self.tr("数据导入设置"))
        self.setModal(True)
        self.resize(560, 520)

        root_layout = QVBoxLayout(self)
        path_label = QLabel(str(source_path))
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root_layout.addWidget(self._section_title(self.tr("源文件（只读）")))
        root_layout.addWidget(path_label)

        file_group = QGroupBox(self.tr("文件结构与时间单位"))
        file_form = QFormLayout(file_group)
        self.time_column_spin = self._column_spin_box(0)
        self.delimiter_edit = QLineEdit(",")
        self.delimiter_edit.setMaxLength(1)
        self.header_check = QCheckBox(self.tr("第一行是表头"))
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["utf-8", "utf-8-sig", "gb18030"])
        self.time_unit_combo = self._unit_combo(
            (
                (self.tr("秒 (s)"), 1.0),
                (self.tr("毫秒 (ms)"), 1e-3),
                (self.tr("微秒 (μs)"), 1e-6),
                (self.tr("纳秒 (ns)"), 1e-9),
            )
        )
        file_form.addRow(self.tr("时间列（从 0 开始）"), self.time_column_spin)
        file_form.addRow(self.tr("分隔符"), self.delimiter_edit)
        file_form.addRow(self.tr("表头"), self.header_check)
        file_form.addRow(self.tr("文本编码"), self.encoding_combo)
        file_form.addRow(self.tr("源时间单位"), self.time_unit_combo)
        root_layout.addWidget(file_group)

        channel_group = QGroupBox(self.tr("电压通道映射"))
        channel_layout = QVBoxLayout(channel_group)
        self.channel_1_name = QLineEdit("pdv_channel_1")
        self.channel_1_column = self._column_spin_box(1)
        self.channel_1_unit = self._voltage_unit_combo()
        channel_layout.addWidget(
            self._channel_row(
                self.tr("通道 1"),
                self.channel_1_name,
                self.channel_1_column,
                self.channel_1_unit,
            )
        )
        self.channel_2_enabled = QCheckBox(self.tr("导入第二个独立通道"))
        self.channel_2_enabled.setChecked(True)
        channel_layout.addWidget(self.channel_2_enabled)
        self.channel_2_name = QLineEdit("pdv_channel_2")
        self.channel_2_column = self._column_spin_box(2)
        self.channel_2_unit = self._voltage_unit_combo()
        self.channel_2_row = self._channel_row(
            self.tr("通道 2"),
            self.channel_2_name,
            self.channel_2_column,
            self.channel_2_unit,
        )
        channel_layout.addWidget(self.channel_2_row)
        self.channel_2_enabled.toggled.connect(self.channel_2_row.setEnabled)
        root_layout.addWidget(channel_group)

        notice = QLabel(
            self.tr(
                "必须显式确认列和物理单位。未选择的额外列不会被解释为信号，"
                "但其列索引会出现在加载摘要中；两个电压通道不会被平均。"
            )
        )
        notice.setWordWrap(True)
        notice.setObjectName("plannedNotice")
        root_layout.addWidget(notice)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        root_layout.addWidget(self.button_box)

    def load_request(self) -> SignalLoadRequest:
        """Return the explicit immutable request represented by the controls."""
        channels = [
            ChannelImportSpec(
                name=self.channel_1_name.text().strip(),
                column_index=self.channel_1_column.value(),
                voltage_scale=float(self.channel_1_unit.currentData()),
            )
        ]
        if self.channel_2_enabled.isChecked():
            channels.append(
                ChannelImportSpec(
                    name=self.channel_2_name.text().strip(),
                    column_index=self.channel_2_column.value(),
                    voltage_scale=float(self.channel_2_unit.currentData()),
                )
            )
        return SignalLoadRequest(
            path=self._source_path,
            time_column=self.time_column_spin.value(),
            channels=tuple(channels),
            delimiter=self.delimiter_edit.text(),
            has_header=self.header_check.isChecked(),
            encoding=self.encoding_combo.currentText(),
            time_scale=float(self.time_unit_combo.currentData()),
        )

    def _validate_and_accept(self) -> None:
        names = [self.channel_1_name.text().strip()]
        columns = [self.channel_1_column.value()]
        if self.channel_2_enabled.isChecked():
            names.append(self.channel_2_name.text().strip())
            columns.append(self.channel_2_column.value())
        valid = (
            bool(self.delimiter_edit.text())
            and all(names)
            and len(set(names)) == len(names)
            and len(set(columns)) == len(columns)
            and self.time_column_spin.value() not in columns
        )
        if valid:
            self.accept()
            return
        self._show_validation_error()

    def _show_validation_error(self) -> None:
        notice = self.tr(
            "请检查：分隔符和通道名不能为空；通道名与所选列必须唯一；"
            "时间列不能同时作为电压列。"
        )
        self.button_box.setToolTip(notice)
        self.button_box.setStyleSheet("border: 1px solid #b94040;")

    def _channel_row(
        self,
        label_text: str,
        name_edit: QLineEdit,
        column_spin: QSpinBox,
        unit_combo: QComboBox,
    ) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setMinimumWidth(64)
        name_edit.setPlaceholderText(self.tr("通道名"))
        column_spin.setToolTip(self.tr("源文件列索引（从 0 开始）"))
        layout.addWidget(label)
        layout.addWidget(name_edit, 2)
        layout.addWidget(column_spin)
        layout.addWidget(unit_combo)
        return widget

    def _voltage_unit_combo(self) -> QComboBox:
        return self._unit_combo(
            (
                (self.tr("伏 (V)"), 1.0),
                (self.tr("毫伏 (mV)"), 1e-3),
            )
        )

    @staticmethod
    def _column_spin_box(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 999)
        spin.setValue(value)
        return spin

    @staticmethod
    def _unit_combo(items: tuple[tuple[str, float], ...]) -> QComboBox:
        combo = QComboBox()
        for text, scale in items:
            combo.addItem(text, scale)
        return combo

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label


__all__ = ["ImportSettingsDialog"]
