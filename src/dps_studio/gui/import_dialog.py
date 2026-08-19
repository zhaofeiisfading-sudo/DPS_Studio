"""Explicit column and unit mapping for delimited signal import."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dps_studio.gui.data_controller import ChannelImportSpec, SignalLoadRequest
from dps_studio.gui.delimited_preview import (
    DelimitedFilePreview,
    DelimitedPreviewError,
    preview_delimited_file,
)


_SIGNAL_SLOT_COUNT = 3
_FALLBACK_COLUMN_COUNT = 3


@dataclass(slots=True)
class _SignalSlot:
    enabled: QCheckBox
    editor: QWidget
    name: QLineEdit
    column: QSpinBox
    unit: QComboBox


class ImportSettingsDialog(QDialog):
    """Collect explicit mappings after a bounded structural file preview."""

    def __init__(self, source_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_path = source_path
        self._preview: DelimitedFilePreview | None = None
        self._column_count = _FALLBACK_COLUMN_COUNT
        self._slots: list[_SignalSlot] = []
        self.setWindowTitle(self.tr("数据导入设置"))
        self.setModal(True)
        self._resize_for_available_screen()

        root_layout = QVBoxLayout(self)
        path_label = QLabel(str(source_path))
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root_layout.addWidget(self._section_title(self.tr("源文件（只读）")))
        root_layout.addWidget(path_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("importSettingsScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.scroll_body = QWidget()
        body_layout = QVBoxLayout(self.scroll_body)
        self.scroll_area.setWidget(self.scroll_body)
        root_layout.addWidget(self.scroll_area, 1)

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
        body_layout.addWidget(file_group)

        preview_group = QGroupBox(self.tr("轻量文件预览"))
        preview_layout = QVBoxLayout(preview_group)
        self.structure_status_label = QLabel()
        self.structure_status_label.setObjectName("importStructureStatus")
        self.structure_status_label.setWordWrap(True)
        preview_layout.addWidget(self.structure_status_label)
        self.column_preview_label = QLabel()
        self.column_preview_label.setObjectName("importColumnPreview")
        self.column_preview_label.setWordWrap(True)
        self.column_preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        preview_layout.addWidget(self.column_preview_label)
        body_layout.addWidget(preview_group)

        channel_group = QGroupBox(self.tr("信号列（最多选择 3 个）"))
        channel_layout = QVBoxLayout(channel_group)
        for slot_index in range(_SIGNAL_SLOT_COUNT):
            slot_number = slot_index + 1
            enabled = QCheckBox(
                self.tr("导入信号 {number}").format(number=slot_number)
            )
            enabled.setObjectName(f"importSignal{slot_number}Enabled")
            name = QLineEdit(f"pdv_channel_{slot_number}")
            column = self._column_spin_box(slot_number)
            unit = self._voltage_unit_combo()
            editor = self._channel_editor(name, column, unit)
            enabled.toggled.connect(editor.setEnabled)
            channel_layout.addWidget(enabled)
            channel_layout.addWidget(editor)
            self._slots.append(_SignalSlot(enabled, editor, name, column, unit))
        body_layout.addWidget(channel_group)

        # Keep the established test/plugin attribute names while the UI uses slots.
        self.channel_1_enabled = self._slots[0].enabled
        self.channel_1_name = self._slots[0].name
        self.channel_1_column = self._slots[0].column
        self.channel_1_unit = self._slots[0].unit
        self.channel_1_row = self._slots[0].editor
        self.channel_2_enabled = self._slots[1].enabled
        self.channel_2_name = self._slots[1].name
        self.channel_2_column = self._slots[1].column
        self.channel_2_unit = self._slots[1].unit
        self.channel_2_row = self._slots[1].editor
        self.channel_3_enabled = self._slots[2].enabled
        self.channel_3_name = self._slots[2].name
        self.channel_3_column = self._slots[2].column
        self.channel_3_unit = self._slots[2].unit
        self.channel_3_row = self._slots[2].editor

        notice = QLabel(
            self.tr(
                "V / mV 表示 CSV 中该列数值的单位，只用于转换为内部 SI 单位；"
                "它不是示波器 V/div 或硬件量程。未选择的源列会被忽略。"
            )
        )
        notice.setWordWrap(True)
        notice.setObjectName("plannedNotice")
        body_layout.addWidget(notice)

        self.validation_error_label = QLabel()
        self.validation_error_label.setObjectName("importValidationError")
        self.validation_error_label.setWordWrap(True)
        self.validation_error_label.setStyleSheet("color: #b94040;")
        self.validation_error_label.hide()
        body_layout.addWidget(self.validation_error_label)
        body_layout.addStretch(1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        root_layout.addWidget(self.button_box)

        self.delimiter_edit.editingFinished.connect(self._refresh_preview)
        self.encoding_combo.currentTextChanged.connect(self._refresh_preview)
        self._refresh_preview(initialize_slots=True, detect_delimiter=True)

    def _resize_for_available_screen(self) -> None:
        """Keep the initial dialog inside the active desktop work area."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:  # pragma: no cover - a GUI application normally has one.
            self.resize(680, 640)
            return
        available = screen.availableGeometry()
        width, height = self._bounded_initial_size(
            available.width(),
            available.height(),
        )
        self.resize(width, height)

    @staticmethod
    def _bounded_initial_size(
        available_width: int,
        available_height: int,
    ) -> tuple[int, int]:
        """Return a readable initial size capped at 82% of the work area."""
        width = min(680, max(480, int(available_width * 0.82)))
        height = min(720, max(400, int(available_height * 0.82)))
        return width, height

    @property
    def detected_column_count(self) -> int:
        """Return the preview column count used to constrain selectors."""
        return self._column_count

    def load_request(self) -> SignalLoadRequest:
        """Return the explicit immutable request represented by the controls."""
        channels = tuple(
            ChannelImportSpec(
                name=slot.name.text().strip(),
                column_index=slot.column.value(),
                voltage_scale=float(slot.unit.currentData()),
            )
            for slot in self._slots
            if slot.enabled.isChecked()
        )
        return SignalLoadRequest(
            path=self._source_path,
            time_column=self.time_column_spin.value(),
            channels=channels,
            delimiter=self.delimiter_edit.text(),
            has_header=self.header_check.isChecked(),
            encoding=self.encoding_combo.currentText(),
            time_scale=float(self.time_unit_combo.currentData()),
        )

    def validation_error(self) -> str | None:
        """Return a user-readable validation error, or ``None`` when valid."""
        delimiter = self.delimiter_edit.text()
        if len(delimiter) != 1:
            return self.tr("分隔符必须恰好是一个字符。")
        enabled_slots = [slot for slot in self._slots if slot.enabled.isChecked()]
        if not enabled_slots:
            return self.tr("请至少启用一个信号列。")
        time_column = self.time_column_spin.value()
        if not 0 <= time_column < self._column_count:
            return self.tr("时间列超出实际列范围。")
        names = [slot.name.text().strip() for slot in enabled_slots]
        if not all(names):
            return self.tr("每个启用信号的名称都不能为空。")
        if len(set(names)) != len(names):
            return self.tr("启用信号的名称不能重复。")
        columns = [slot.column.value() for slot in enabled_slots]
        if any(not 0 <= column < self._column_count for column in columns):
            return self.tr("启用信号的电压列超出实际列范围。")
        if time_column in columns:
            return self.tr("时间列不能同时作为电压列。")
        if len(set(columns)) != len(columns):
            return self.tr("启用信号的电压列不能重复。")
        return None

    def _validate_and_accept(self) -> None:
        error = self.validation_error()
        if error is None:
            self.validation_error_label.clear()
            self.validation_error_label.hide()
            self.button_box.setToolTip("")
            self.button_box.setStyleSheet("")
            self.accept()
            return
        self._show_validation_error(error)

    def _show_validation_error(self, notice: str) -> None:
        self.validation_error_label.setText(notice)
        self.validation_error_label.show()
        self.button_box.setToolTip(notice)
        self.button_box.setStyleSheet("border: 1px solid #b94040;")

    def _refresh_preview(
        self,
        _text: str | None = None,
        *,
        initialize_slots: bool = False,
        detect_delimiter: bool = False,
    ) -> None:
        delimiter = None if detect_delimiter else self.delimiter_edit.text()
        try:
            preview = preview_delimited_file(
                self._source_path,
                delimiter=delimiter,
                encoding=self.encoding_combo.currentText(),
            )
        except DelimitedPreviewError as exc:
            if self._source_path.exists():
                self.structure_status_label.setText(
                    self.tr("文件结构预览失败：{message}").format(message=exc)
                )
                self.column_preview_label.clear()
            else:
                self.structure_status_label.setText(
                    self.tr("文件尚不可读取；将在确认时由严格读取器校验。")
                )
            self._set_column_count(self._column_count, initialize_slots)
            return

        initialize_slots = initialize_slots or self._preview is None
        self._preview = preview
        delimiter_blocker = QSignalBlocker(self.delimiter_edit)
        self.delimiter_edit.setText(preview.delimiter)
        del delimiter_blocker
        if initialize_slots:
            header_blocker = QSignalBlocker(self.header_check)
            self.header_check.setChecked(preview.has_header)
            del header_blocker
        self._set_column_count(preview.column_count, initialize_slots)
        self._render_preview(preview)

    def _set_column_count(self, column_count: int, initialize_slots: bool) -> None:
        self._column_count = max(1, column_count)
        maximum = self._column_count - 1
        self.time_column_spin.setRange(0, maximum)
        if initialize_slots:
            self.time_column_spin.setValue(0)
        for slot_index, slot in enumerate(self._slots):
            slot.column.setRange(0, maximum)
            if initialize_slots:
                slot.enabled.setChecked(slot_index + 1 < self._column_count)
                slot.column.setValue(min(slot_index + 1, maximum))
            slot.editor.setEnabled(slot.enabled.isChecked())

    def _render_preview(self, preview: DelimitedFilePreview) -> None:
        self.structure_status_label.setText(
            self.tr(
                "检测到 {count} 列，可用列索引：0–{maximum}；分隔符：{delimiter}；"
                "编码：{encoding}；表头判断为初步检测，可手动修改。"
            ).format(
                count=preview.column_count,
                maximum=preview.column_count - 1,
                delimiter=repr(preview.delimiter),
                encoding=preview.encoding,
            )
        )
        lines: list[str] = []
        for column_index in range(preview.column_count):
            header = (
                preview.header[column_index]
                if column_index < len(preview.header)
                and preview.header[column_index]
                else self.tr("无表头")
            )
            values = [
                row[column_index]
                for row in preview.rows[:3]
                if column_index < len(row)
            ]
            sample = ", ".join(self._short_preview(value) for value in values)
            lines.append(
                self.tr("列 {index}：{header}　示例：{sample}").format(
                    index=column_index,
                    header=header,
                    sample=sample or self.tr("无数据行"),
                )
            )
        self.column_preview_label.setText("\n".join(lines))

    def _channel_editor(
        self,
        name_edit: QLineEdit,
        column_spin: QSpinBox,
        unit_combo: QComboBox,
    ) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(22, 0, 0, 8)
        name_edit.setPlaceholderText(self.tr("通道名"))
        column_spin.setToolTip(self.tr("源文件列索引（从 0 开始）"))
        unit_combo.setToolTip(
            self.tr("CSV 数值单位；不是 V/div 或示波器硬件量程。")
        )
        layout.addRow(self.tr("名称"), name_edit)
        layout.addRow(self.tr("电压列（从 0 开始）"), column_spin)
        layout.addRow(self.tr("CSV 中该列的单位"), unit_combo)
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

    @staticmethod
    def _short_preview(value: str, maximum: int = 24) -> str:
        return value if len(value) <= maximum else f"{value[: maximum - 1]}…"


__all__ = ["ImportSettingsDialog"]
