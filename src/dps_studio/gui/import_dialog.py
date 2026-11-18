"""Explicit column and unit mapping for delimited signal import."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dps_studio.core.io import (
    WHITESPACE_DELIMITER,
    DelimitedFilePreview,
    DelimitedPreviewError,
    preview_delimited_file,
)
from dps_studio.gui.data_controller import ChannelImportSpec, SignalLoadRequest
from dps_studio.gui.icons import chevron_icon, vector_icon
from dps_studio.gui.inspector_widgets import InspectorCard, StatusBanner


_SIGNAL_SLOT_COUNT = 3
_FALLBACK_COLUMN_COUNT = 3
_CUSTOM_DELIMITER = "custom"


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
        self._mapping_initialized = False
        self._column_count = _FALLBACK_COLUMN_COUNT
        self._slots: list[_SignalSlot] = []
        self.setWindowTitle(self.tr("导入数据"))
        self.setModal(True)
        self._resize_for_available_screen()

        root_layout = QVBoxLayout(self)
        path_label = QLabel(source_path.name)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        header = QHBoxLayout()
        emblem = QLabel()
        emblem.setPixmap(vector_icon("open_data", "#0f5c8a").pixmap(24, 24))
        header.addWidget(emblem)
        path_label.setTextFormat(Qt.TextFormat.PlainText)
        path_label.setToolTip(str(source_path.absolute()))
        path_label.setProperty("role", "cardTitle")
        header.addWidget(path_label)
        if source_path.is_file():
            size = source_path.stat().st_size
            size_badge = QLabel(f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.1f} kB")
            size_badge.setProperty("role", "badge")
            header.addWidget(size_badge)
        header.addStretch()
        root_layout.addLayout(header)

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

        file_group = InspectorCard(self.tr("文件结构与时间单位"))
        file_form = QGridLayout()
        file_group.body_layout.addLayout(file_form)
        self.time_column_spin = self._column_spin_box(0)
        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItem(self.tr("自动检测"), None)
        self.delimiter_combo.addItem(self.tr("逗号 (,)"), ",")
        self.delimiter_combo.addItem(self.tr("制表符 (Tab)"), "\t")
        self.delimiter_combo.addItem(
            self.tr("空白字符（空格 / Tab）"), WHITESPACE_DELIMITER
        )
        self.delimiter_combo.addItem(self.tr("分号 (;)"), ";")
        self.delimiter_combo.addItem(self.tr("自定义"), _CUSTOM_DELIMITER)
        self.delimiter_custom_edit = QLineEdit("|")
        self.delimiter_custom_edit.setMaxLength(1)
        self.delimiter_custom_edit.hide()
        delimiter_control = QWidget()
        delimiter_layout = QHBoxLayout(delimiter_control)
        delimiter_layout.setContentsMargins(0, 0, 0, 0)
        delimiter_layout.addWidget(self.delimiter_combo, 1)
        delimiter_layout.addWidget(self.delimiter_custom_edit)
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
        for grid_row, col, caption, control in (
            (0, 0, self.tr("时间列（从 0 开始）"), self.time_column_spin),
            (0, 2, self.tr("分隔符"), delimiter_control),
            (1, 0, self.tr("文本编码"), self.encoding_combo),
            (1, 2, self.tr("源时间单位"), self.time_unit_combo),
        ):
            label = QLabel(caption)
            label.setBuddy(control)
            file_form.addWidget(label, grid_row, col)
            file_form.addWidget(control, grid_row, col + 1)
        file_form.setColumnStretch(1, 1)
        file_form.setColumnStretch(3, 1)
        file_form.addWidget(self.header_check, 2, 0, 1, 4)
        body_layout.addWidget(file_group)

        preview_group = InspectorCard(self.tr("列预览"))
        preview_layout = preview_group.body_layout
        self.structure_status_label = QLabel()
        self.structure_status_label.setObjectName("importStructureStatus")
        self.structure_status_label.setWordWrap(True)
        preview_layout.addWidget(self.structure_status_label)
        self.preview_table = QTableWidget()
        self.preview_table.setObjectName("importPreviewTable")
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setShowGrid(False)
        self.preview_table.verticalHeader().hide()
        self.preview_table.verticalHeader().setDefaultSectionSize(22)
        self.preview_table.horizontalHeader().setMinimumSectionSize(76)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.preview_table.setFixedHeight(132)
        preview_layout.addWidget(self.preview_table)
        self.summary_toggle = QToolButton()
        self.summary_toggle.setText(self.tr("列摘要"))
        self.summary_toggle.setAccessibleName(self.summary_toggle.text())
        self.summary_toggle.setProperty("accordionToggle", True)
        self.summary_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.summary_toggle.setIcon(chevron_icon(False))
        self.summary_toggle.setCheckable(True)
        preview_layout.addWidget(self.summary_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.column_preview_label = QLabel()
        self.column_preview_label.setTextFormat(Qt.TextFormat.PlainText)
        self.column_preview_label.hide()
        self.summary_toggle.toggled.connect(self._show_column_summary)
        self.column_preview_label.setObjectName("importColumnPreview")
        self.column_preview_label.setWordWrap(True)
        self.column_preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        preview_layout.addWidget(self.column_preview_label)

        channel_group = InspectorCard(self.tr("信号列（最多选择 3 个）"))
        channel_layout = channel_group.body_layout
        channel_layout.setSpacing(6)
        headings = QHBoxLayout()
        enabled_heading = QLabel(self.tr("导入"))
        enabled_heading.setMinimumWidth(110)
        headings.addWidget(enabled_heading)
        headings.addWidget(QLabel(self.tr("名称")), 1)
        column_heading = QLabel(self.tr("电压列"))
        column_heading.setMinimumWidth(76)
        headings.addWidget(column_heading)
        unit_heading = QLabel(self.tr("源单位"))
        unit_heading.setMinimumWidth(98)
        headings.addWidget(unit_heading)
        channel_layout.addLayout(headings)
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
            row = QHBoxLayout()
            enabled.setMinimumWidth(110)
            row.addWidget(enabled)
            row.addWidget(editor, 1)
            channel_layout.addLayout(row)
            self._slots.append(_SignalSlot(enabled, editor, name, column, unit))
        body_layout.addWidget(preview_group)
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

        self.validation_banner = StatusBanner("error")
        self.validation_error_label = self.validation_banner.label
        self.validation_error_label.setObjectName("importValidationError")
        self.validation_banner.hide()
        root_layout.addWidget(self.validation_banner)
        body_layout.addStretch(1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        import_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        import_button.setText(self.tr("导入"))
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(self.tr("取消"))
        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        root_layout.addWidget(self.button_box)

        self.delimiter_combo.currentIndexChanged.connect(
            self._delimiter_selection_changed
        )
        self.delimiter_custom_edit.editingFinished.connect(self._refresh_preview)
        self.encoding_combo.currentTextChanged.connect(self._refresh_preview)
        self.header_check.toggled.connect(self._header_selection_changed)
        self._refresh_preview(initialize_slots=True, detect_delimiter=True)
        self.time_column_spin.valueChanged.connect(self._mapping_changed)
        for slot in self._slots:
            slot.enabled.toggled.connect(self._mapping_changed)
            slot.name.textChanged.connect(self._mapping_changed)
            slot.column.valueChanged.connect(self._mapping_changed)
        self._mapping_changed()

    def _show_column_summary(self, expanded: bool) -> None:
        self.column_preview_label.setVisible(expanded)
        self.summary_toggle.setIcon(chevron_icon(expanded))

    def _resize_for_available_screen(self) -> None:
        """Keep the initial dialog inside the active desktop work area."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:  # pragma: no cover - a GUI application normally has one.
            self.resize(740, 640)
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
        width = min(740, max(480, int(available_width * 0.82)))
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
                original_voltage_unit=("V", "mV")[slot.unit.currentIndex()],
            )
            for slot in self._slots
            if slot.enabled.isChecked()
        )
        return SignalLoadRequest(
            path=self._source_path,
            time_column=self.time_column_spin.value(),
            channels=channels,
            delimiter=self._required_delimiter(),
            has_header=self.header_check.isChecked(),
            encoding=self.encoding_combo.currentText(),
            time_scale=float(self.time_unit_combo.currentData()),
            original_time_unit=("s", "ms", "us", "ns")[self.time_unit_combo.currentIndex()],
        )

    def validation_error(self) -> str | None:
        """Return a user-readable validation error, or ``None`` when valid."""
        delimiter = self._selected_delimiter()
        if delimiter is None:
            return self.tr("请先完成分隔符检测。")
        if delimiter != WHITESPACE_DELIMITER and len(delimiter) != 1:
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
            self.validation_banner.hide()
            self.accept()
            return
        self._show_validation_error(error)

    def _show_validation_error(self, notice: str) -> None:
        self.validation_error_label.setText(notice)
        self.validation_banner.show()

    def _mapping_changed(self) -> None:
        active = [slot for slot in self._slots if slot.enabled.isChecked()]
        columns = [slot.column.value() for slot in active]
        names = [slot.name.text().strip() for slot in active]
        time = self.time_column_spin.value()
        self._mark_conflict(self.time_column_spin, time in columns or time >= self._column_count)
        for slot in self._slots:
            column = slot.column.value()
            name = slot.name.text().strip()
            enabled = slot.enabled.isChecked()
            self._mark_conflict(slot.column, enabled and (
                column == time or columns.count(column) > 1 or column >= self._column_count
            ))
            self._mark_conflict(slot.name, enabled and (not name or names.count(name) > 1))
        error = self.validation_error()
        self.validation_error_label.setText(error or "")
        self.validation_banner.setVisible(error is not None)
        for index in range(self.preview_table.columnCount()):
            roles = [self.tr("时间")] if index == time else []
            roles.extend(slot.name.text().strip() for slot in active if slot.column.value() == index)
            title = self.tr("列 {index}").format(index=index)
            if roles:
                title += " · " + " / ".join(roles)
            item = QTableWidgetItem(title)
            item.setToolTip(title)
            if roles:
                item.setForeground(QColor("#0f5c8a" if len(roles) == 1 else "#c62828"))
            self.preview_table.setHorizontalHeaderItem(index, item)

    @staticmethod
    def _mark_conflict(control: QSpinBox | QLineEdit, conflict: bool) -> None:
        selector = "QSpinBox" if isinstance(control, QSpinBox) else "QLineEdit"
        control.setStyleSheet(f"{selector} {{ border: 1px solid #c62828; }}" if conflict else "")

    def _refresh_preview(
        self,
        _text: str | None = None,
        *,
        initialize_slots: bool = False,
        detect_delimiter: bool = False,
    ) -> None:
        delimiter = None if detect_delimiter else self._selected_delimiter()
        try:
            preview = preview_delimited_file(
                self._source_path,
                delimiter=delimiter,
                encoding=self.encoding_combo.currentText(),
            )
        except DelimitedPreviewError as exc:
            self._preview = None
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            self.column_preview_label.clear()
            if self._source_path.exists():
                self.structure_status_label.setText(
                    self.tr("文件结构预览失败：{message}").format(message=exc)
                )
            else:
                self.structure_status_label.setText(
                    self.tr("文件尚不可读取；将在确认时由严格读取器校验。")
                )
                if self._selected_delimiter() is None:
                    self._set_delimiter_control(",")
            self._set_column_count(self._column_count, initialize_slots)
            self._mapping_changed()
            return

        initialize_slots = initialize_slots or not self._mapping_initialized
        self._mapping_initialized = True
        self._preview = preview
        self._set_delimiter_control(preview.delimiter)
        if initialize_slots:
            header_blocker = QSignalBlocker(self.header_check)
            self.header_check.setChecked(preview.has_header)
            del header_blocker
        self._set_column_count(preview.column_count, initialize_slots)
        self._render_preview(preview)

    def _set_column_count(self, column_count: int, initialize_slots: bool) -> None:
        self._column_count = max(1, column_count)
        maximum = self._column_count - 1
        time_max = maximum if initialize_slots else max(maximum, self.time_column_spin.value())
        self.time_column_spin.setRange(0, time_max)
        if initialize_slots:
            self.time_column_spin.setValue(0)
        for slot_index, slot in enumerate(self._slots):
            slot_max = maximum if initialize_slots else max(maximum, slot.column.value())
            slot.column.setRange(0, slot_max)
            if initialize_slots:
                slot.enabled.setChecked(slot_index + 1 < self._column_count)
                slot.column.setValue(min(slot_index + 1, maximum))
            slot.editor.setEnabled(slot.enabled.isChecked())

    def _header_selection_changed(self, _checked: bool) -> None:
        if self._preview is not None:
            self._render_preview(self._preview)

    def _render_preview(self, preview: DelimitedFilePreview) -> None:
        rows = (preview.header, *preview.rows) if preview.has_header else preview.rows
        has_header = self.header_check.isChecked()
        selected_header = rows[0] if has_header and rows else ()
        table_rows = rows[1:5] if has_header else rows[:4]
        self.preview_table.setColumnCount(preview.column_count)
        self.preview_table.setRowCount(len(table_rows))
        for row_index, row in enumerate(table_rows):
            for col_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.preview_table.setItem(row_index, col_index, item)
        self._mapping_changed()
        sample_rows = table_rows[:3]
        self.structure_status_label.setText(
            self.tr(
                "{count} 列（0–{maximum}） · {delimiter} · {encoding}"
            ).format(
                count=preview.column_count,
                maximum=preview.column_count - 1,
                delimiter=self._delimiter_label(preview.delimiter),
                encoding=preview.encoding,
            )
        )
        lines: list[str] = []
        for column_index in range(preview.column_count):
            header = (
                selected_header[column_index]
                if column_index < len(selected_header)
                and selected_header[column_index]
                else self.tr("无表头")
            )
            values = [
                row[column_index]
                for row in sample_rows
                if column_index < len(row)
            ]
            sample = ", ".join(self._short_preview(value) for value in values)
            lines.append(
                self.tr("列 {index} · {header}：{sample}").format(
                    index=column_index,
                    header=header,
                    sample=sample or self.tr("无数据行"),
                )
            )
        self.column_preview_label.setText("\n".join(lines))

    def _delimiter_selection_changed(self, _index: int) -> None:
        is_custom = self.delimiter_combo.currentData() == _CUSTOM_DELIMITER
        self.delimiter_custom_edit.setVisible(is_custom)
        self._refresh_preview(detect_delimiter=self._selected_delimiter() is None)

    def _selected_delimiter(self) -> str | None:
        selection = self.delimiter_combo.currentData()
        if selection == _CUSTOM_DELIMITER:
            return self.delimiter_custom_edit.text()
        if selection is None:
            return None
        if not isinstance(selection, str):  # pragma: no cover - fixed combo data.
            raise TypeError("delimiter combo data must be a string or None")
        return selection

    def _required_delimiter(self) -> str:
        delimiter = self._selected_delimiter()
        if delimiter is None:
            raise ValueError("delimiter detection has not completed")
        return delimiter

    def _set_delimiter_control(self, delimiter: str) -> None:
        index = self.delimiter_combo.findData(delimiter)
        if index < 0:
            index = self.delimiter_combo.findData(_CUSTOM_DELIMITER)
            custom_blocker = QSignalBlocker(self.delimiter_custom_edit)
            self.delimiter_custom_edit.setText(delimiter)
            del custom_blocker
        combo_blocker = QSignalBlocker(self.delimiter_combo)
        self.delimiter_combo.setCurrentIndex(index)
        del combo_blocker
        self.delimiter_custom_edit.setVisible(
            self.delimiter_combo.currentData() == _CUSTOM_DELIMITER
        )

    def _delimiter_label(self, delimiter: str) -> str:
        if delimiter == WHITESPACE_DELIMITER:
            return self.tr("空白字符（空格 / Tab）")
        if delimiter == "\t":
            return self.tr("制表符 (Tab)")
        return repr(delimiter)

    def _channel_editor(
        self,
        name_edit: QLineEdit,
        column_spin: QSpinBox,
        unit_combo: QComboBox,
    ) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        name_edit.setPlaceholderText(self.tr("通道名"))
        column_spin.setToolTip(self.tr("源文件列索引（从 0 开始）"))
        unit_combo.setToolTip(
            self.tr("源文件数值单位；不是 V/div 或示波器硬件量程。")
        )
        name_edit.setAccessibleName(self.tr("名称"))
        column_spin.setAccessibleName(self.tr("电压列（从 0 开始）"))
        unit_combo.setAccessibleName(self.tr("源文件中该列的单位"))
        column_spin.setFixedWidth(76)
        unit_combo.setFixedWidth(98)
        layout.addWidget(name_edit, 1)
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
