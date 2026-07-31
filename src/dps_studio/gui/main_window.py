"""Resizable PDV Studio workstation shell without scientific algorithms."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.gui.data_controller import DataImportController
from dps_studio.gui.i18n import (
    LANGUAGE_EN,
    LANGUAGE_ZH_CN,
    TranslationManager,
)
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.raw_signal_view import RawSignalView
from dps_studio.gui.state import WorkflowState


class MainWindow(QMainWindow):
    """Compose the first runnable workstation and its explicit UI states."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        translation_manager: TranslationManager | None = None,
    ) -> None:
        super().__init__(parent)
        self._translation_manager = translation_manager
        self._data_controller = DataImportController()
        self._load_result: DelimitedSignalLoadResult | None = None
        self._workflow_state = WorkflowState.EMPTY
        self._unsaved_changes = False

        self.setObjectName("mainWindow")
        self.setWindowTitle(self.tr("PDV Studio"))
        self.resize(1440, 900)
        self.setMinimumSize(1024, 640)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_workspace()
        self._create_diagnostics_dock()
        self._create_status_bar()
        self._connect_signals()
        self._apply_state()
        self._append_log(self.tr("工作台已启动；当前未加载数据。"))

    @property
    def workflow_state(self) -> WorkflowState:
        """Return the current user-interface workflow state."""
        return self._workflow_state

    @property
    def load_result(self) -> DelimitedSignalLoadResult | None:
        """Return the immutable result currently presented by the window."""
        return self._load_result

    def set_loaded_result(self, result: DelimitedSignalLoadResult) -> None:
        """Present a public core load result and enter ``DATA_LOADED``."""
        if not isinstance(result, DelimitedSignalLoadResult):
            raise TypeError("result must be a DelimitedSignalLoadResult.")
        self._load_result = result
        self.raw_signal_view.set_records(result.records)
        self._populate_data_summary(result)
        self._workflow_state = WorkflowState.DATA_LOADED
        self._unsaved_changes = False
        self._apply_state()
        self._append_log(
            self.tr("已加载 {rows} 行、{channels} 个独立电压通道：{path}").format(
                rows=result.row_count,
                channels=len(result.channel_names),
                path=result.source_path,
            )
        )

    def select_workflow_step(self, row: int) -> bool:
        """Select an enabled workflow page and return whether it was available."""
        item = self.workflow_navigation.item(row)
        if item is None or not bool(item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return False
        self.workflow_navigation.setCurrentRow(row)
        return True

    def _create_actions(self) -> None:
        style = QApplication.style()
        self.action_open_data = QAction(
            style.standardIcon(style.StandardPixmap.SP_DialogOpenButton),
            self.tr("打开数据…"),
            self,
        )
        self.action_open_data.setObjectName("actionOpenData")
        self.action_open_data.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open_data.setToolTip(self.tr("选择文件并显式配置列与单位"))

        self.action_exit = QAction(self.tr("退出"), self)
        self.action_exit.setObjectName("actionExit")
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)

        planned_tooltip = self.tr("计划功能：完整分析尚未接入 GUI。")
        self.action_automatic = QAction(self.tr("自动分析"), self)
        self.action_automatic.setObjectName("actionAutomaticAnalysis")
        self.action_automatic.setEnabled(False)
        self.action_automatic.setToolTip(planned_tooltip)
        self.action_guided = QAction(self.tr("引导分析"), self)
        self.action_guided.setObjectName("actionGuidedAnalysis")
        self.action_guided.setEnabled(False)
        self.action_guided.setToolTip(self.tr("计划功能：人工约束接口尚未接入。"))
        self.action_run_stft = QAction(self.tr("运行 STFT"), self)
        self.action_run_stft.setObjectName("actionRunStft")
        self.action_run_stft.setEnabled(False)
        self.action_run_stft.setToolTip(planned_tooltip)
        self.action_run_ridge = QAction(self.tr("提取脊线"), self)
        self.action_run_ridge.setObjectName("actionRunRidge")
        self.action_run_ridge.setEnabled(False)
        self.action_run_ridge.setToolTip(planned_tooltip)
        self.action_velocity = QAction(self.tr("计算速度"), self)
        self.action_velocity.setObjectName("actionVelocity")
        self.action_velocity.setEnabled(False)
        self.action_velocity.setToolTip(planned_tooltip)
        self.action_export = QAction(self.tr("导出结果"), self)
        self.action_export.setObjectName("actionExport")
        self.action_export.setEnabled(False)
        self.action_export.setToolTip(
            self.tr("尚未接入：当前没有可供 GUI 使用的 public core 导出接口。")
        )

        self.action_language_zh = QAction(self.tr("简体中文"), self)
        self.action_language_zh.setCheckable(True)
        self.action_language_zh.setObjectName("actionLanguageZh")
        self.action_language_en = QAction(self.tr("English"), self)
        self.action_language_en.setCheckable(True)
        self.action_language_en.setObjectName("actionLanguageEn")
        configured_language = (
            self._translation_manager.current_language
            if self._translation_manager is not None
            else LANGUAGE_ZH_CN
        )
        self.action_language_zh.setChecked(configured_language == LANGUAGE_ZH_CN)
        self.action_language_en.setChecked(configured_language == LANGUAGE_EN)

        self.action_about = QAction(self.tr("关于 PDV Studio"), self)
        self.action_about.setObjectName("actionAbout")

    def _create_menus(self) -> None:
        self.file_menu = self.menuBar().addMenu(self.tr("文件"))
        self.file_menu.setObjectName("fileMenu")
        self.file_menu.addAction(self.action_open_data)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_exit)

        self.analysis_menu = self.menuBar().addMenu(self.tr("分析"))
        self.analysis_menu.setObjectName("analysisMenu")
        self.analysis_menu.addAction(self.action_automatic)
        self.analysis_menu.addAction(self.action_guided)

        self.settings_menu = self.menuBar().addMenu(self.tr("设置"))
        self.settings_menu.setObjectName("settingsMenu")
        self.language_menu = QMenu(self.tr("语言"), self)
        self.language_menu.setObjectName("languageMenu")
        self.language_menu.addAction(self.action_language_zh)
        self.language_menu.addAction(self.action_language_en)
        self.settings_menu.addMenu(self.language_menu)

        self.help_menu = self.menuBar().addMenu(self.tr("帮助"))
        self.help_menu.setObjectName("helpMenu")
        self.help_menu.addAction(self.action_about)

    def _create_toolbar(self) -> None:
        self.main_toolbar = QToolBar(self.tr("常用工具"), self)
        self.main_toolbar.setObjectName("mainToolbar")
        self.main_toolbar.setMovable(True)
        self.main_toolbar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.main_toolbar.addAction(self.action_open_data)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.action_automatic)
        self.main_toolbar.addAction(self.action_guided)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.action_export)
        self.addToolBar(self.main_toolbar)

    def _create_workspace(self) -> None:
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)

        navigation_panel = QWidget()
        navigation_layout = QVBoxLayout(navigation_panel)
        navigation_layout.addWidget(self._section_title(self.tr("处理流程")))
        self.workflow_navigation = QListWidget()
        self.workflow_navigation.setObjectName("workflowNavigation")
        self._workflow_labels = (
            self.tr("1  数据导入"),
            self.tr("2  分析范围"),
            self.tr("3  时频分析"),
            self.tr("4  脊线提取"),
            self.tr("5  速度结果"),
            self.tr("6  复核与导出"),
        )
        for label in self._workflow_labels:
            self.workflow_navigation.addItem(QListWidgetItem(label))
        self.workflow_navigation.setCurrentRow(0)
        navigation_layout.addWidget(self.workflow_navigation, 1)
        navigation_panel.setMinimumWidth(210)

        self.science_tabs = QTabWidget()
        self.science_tabs.setObjectName("scienceTabs")
        self.science_tabs.setDocumentMode(True)
        self.raw_signal_view = RawSignalView()
        self.science_tabs.addTab(self.raw_signal_view, self.tr("原始信号"))
        self.science_tabs.addTab(
            self._planned_view(self.tr("时频结果尚未接入。")),
            self.tr("时频图"),
        )
        self.science_tabs.addTab(
            self._planned_view(self.tr("脊线结果尚未接入。")),
            self.tr("频谱脊线"),
        )
        self.science_tabs.addTab(
            self._planned_view(self.tr("速度结果尚未接入。")),
            self.tr("速度曲线"),
        )
        self.science_tabs.addTab(
            self._planned_view(self.tr("比较视图尚未接入。")),
            self.tr("结果比较"),
        )

        parameter_panel = QWidget()
        parameter_layout = QVBoxLayout(parameter_panel)
        parameter_layout.addWidget(self._section_title(self.tr("当前参数")))
        self.parameter_stack = QStackedWidget()
        self.parameter_stack.setObjectName("parameterStack")
        self._build_parameter_pages()
        parameter_layout.addWidget(self.parameter_stack, 1)
        parameter_panel.setMinimumWidth(230)

        self.workspace_splitter.addWidget(navigation_panel)
        self.workspace_splitter.addWidget(self.science_tabs)
        self.workspace_splitter.addWidget(parameter_panel)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes([230, 860, 300])
        self.setCentralWidget(self.workspace_splitter)

    def _build_parameter_pages(self) -> None:
        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
        mode_group = QGroupBox(self.tr("分析方式"))
        mode_layout = QVBoxLayout(mode_group)
        automatic = QRadioButton(self.tr("自动分析"))
        automatic.setChecked(True)
        guided = QRadioButton(self.tr("引导分析（计划功能）"))
        guided.setEnabled(False)
        guided.setToolTip(self.tr("尚未接入人工约束和多边形 ROI。"))
        mode_layout.addWidget(automatic)
        mode_layout.addWidget(guided)
        data_layout.addWidget(mode_group)
        open_button = QPushButton(self.tr("选择并导入数据…"))
        open_button.setDefault(True)
        open_button.clicked.connect(self.action_open_data.trigger)
        data_layout.addWidget(open_button)
        data_layout.addWidget(
            self._notice(
                self.tr(
                    "时间、电压和列映射必须在导入对话框中明确指定。"
                    "内部数据保持 s 和 V。"
                )
            )
        )
        data_layout.addStretch(1)
        self.parameter_stack.addWidget(data_page)

        range_page = QWidget()
        range_layout = QFormLayout(range_page)
        range_layout.addRow(
            self.tr("状态"),
            self._notice(self.tr("可配置界面已预留；范围写入尚未接入。")),
        )
        range_layout.addRow(
            self.tr("ROI 坐标"),
            QLabel("time_s / frequency_hz"),
        )
        self.parameter_stack.addWidget(range_page)

        self.parameter_stack.addWidget(
            self._planned_parameters(
                self.tr("STFT 参数"),
                self.tr(
                    "计划显示窗函数、窗长、重叠、hop、nfft 与搜索频段。"
                    "当前未调用 compute_stft。"
                ),
            )
        )
        self.parameter_stack.addWidget(
            self._planned_parameters(
                self.tr("脊线参数"),
                self.tr(
                    "计划显示自动/引导分析、候选峰、亚频点精修和质量门。"
                    "当前未调用脊线算法。"
                ),
            )
        )
        self.parameter_stack.addWidget(
            self._planned_parameters(
                self.tr("速度参数"),
                self.tr(
                    "计划分别展示表观速度、显示速度和未来经验证的修正速度。"
                    "当前未执行速度转换。"
                ),
            )
        )
        self.parameter_stack.addWidget(
            self._planned_parameters(
                self.tr("复核与导出"),
                self.tr(
                    "计划提供双通道比较、质量复核和导出。"
                    "production 脚本未作为 GUI 运行依赖。"
                ),
            )
        )

    def _create_diagnostics_dock(self) -> None:
        self.diagnostics_dock = QDockWidget(self.tr("诊断与数据"), self)
        self.diagnostics_dock.setObjectName("diagnosticsDock")
        self.diagnostics_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.diagnostics_tabs = QTabWidget()
        self.diagnostics_tabs.setObjectName("diagnosticsTabs")

        quality_page = QWidget()
        quality_layout = QVBoxLayout(quality_page)
        self.quality_label = self._notice(
            self.tr("尚未运行分析；当前没有正式质量结果。")
        )
        quality_layout.addWidget(self.quality_label)
        quality_layout.addStretch(1)
        self.diagnostics_tabs.addTab(quality_page, self.tr("质量"))

        self.data_summary_table = QTableWidget(0, 2)
        self.data_summary_table.setObjectName("dataSummaryTable")
        self.data_summary_table.setHorizontalHeaderLabels(
            [self.tr("字段"), self.tr("值")]
        )
        self.data_summary_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.data_summary_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.data_summary_table.horizontalHeader().setStretchLastSection(True)
        self.diagnostics_tabs.addTab(self.data_summary_table, self.tr("数据"))

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.diagnostics_tabs.addTab(self.log_view, self.tr("日志"))
        self.diagnostics_dock.setWidget(self.diagnostics_tabs)
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea,
            self.diagnostics_dock,
        )
        self.resizeDocks([self.diagnostics_dock], [210], Qt.Orientation.Vertical)

    def _create_status_bar(self) -> None:
        status_bar = QStatusBar()
        status_bar.setObjectName("mainStatusBar")
        self.setStatusBar(status_bar)
        self.status_file = QLabel(self.tr("文件：未加载"))
        self.status_file.setObjectName("statusFile")
        self.status_channel = QLabel(self.tr("通道：—"))
        self.status_channel.setObjectName("statusChannel")
        self.status_state = QLabel(self.tr("状态：EMPTY"))
        self.status_state.setObjectName("statusState")
        self.status_time = QLabel(self.tr("时间：—"))
        self.status_time.setObjectName("statusTime")
        self.status_value = QLabel(self.tr("数值：—"))
        self.status_value.setObjectName("statusValue")
        self.status_unsaved = QLabel(self.tr("未保存修改：否"))
        self.status_unsaved.setObjectName("statusUnsaved")
        for label in (
            self.status_file,
            self.status_channel,
            self.status_state,
            self.status_time,
            self.status_value,
            self.status_unsaved,
        ):
            status_bar.addPermanentWidget(label)

    def _connect_signals(self) -> None:
        self.action_open_data.triggered.connect(self._open_data)
        self.action_exit.triggered.connect(self.close)
        self.action_about.triggered.connect(self._show_about)
        self.action_language_zh.triggered.connect(
            lambda: self._save_language(LANGUAGE_ZH_CN)
        )
        self.action_language_en.triggered.connect(
            lambda: self._save_language(LANGUAGE_EN)
        )
        self.workflow_navigation.currentRowChanged.connect(
            self._workflow_page_changed
        )
        self.raw_signal_view.channel_selection_changed.connect(
            self._channel_changed
        )
        self.raw_signal_view.cursor_position_changed.connect(
            self._cursor_changed
        )

    def _open_data(self) -> None:
        selected_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("选择时间—电压数据文件"),
            "",
            self.tr("分隔文本文件 (*.csv *.txt *.dat);;所有文件 (*)"),
        )
        if not selected_path:
            return
        dialog = ImportSettingsDialog(Path(selected_path), self)
        if dialog.exec() != int(dialog.DialogCode.Accepted):
            return
        try:
            result = self._data_controller.load(dialog.load_request())
        except Exception as exc:
            self._append_log(
                self.tr("数据加载失败：{error_type}: {message}").format(
                    error_type=type(exc).__name__,
                    message=exc,
                )
            )
            QMessageBox.critical(
                self,
                self.tr("数据加载失败"),
                self.tr("无法按当前列和单位设置读取文件。\n\n{message}").format(
                    message=exc
                ),
            )
            return
        self.set_loaded_result(result)

    def _populate_data_summary(self, result: DelimitedSignalLoadResult) -> None:
        first_record = result.records[result.channel_names[0]]
        unselected = (
            ", ".join(str(index) for index in result.unselected_column_indices)
            if result.unselected_column_indices
            else self.tr("无")
        )
        rows = (
            (self.tr("源文件"), str(result.source_path)),
            (self.tr("数据行数"), str(result.row_count)),
            (self.tr("源列数"), str(result.column_count)),
            (self.tr("独立通道"), ", ".join(result.channel_names)),
            (self.tr("未选择列索引"), unselected),
            (self.tr("样本数/通道"), str(first_record.sample_count)),
            (
                self.tr("时间范围 (s)"),
                f"{first_record.start_time_s:.9e} – {first_record.end_time_s:.9e}",
            ),
            (
                self.tr("代表采样间隔 (s)"),
                f"{first_record.representative_sample_interval_s:.9e}",
            ),
            (
                self.tr("代表采样率 (Hz)"),
                f"{first_record.sample_rate_hz:.9e}",
            ),
            (
                self.tr("均匀采样"),
                self.tr("是") if first_record.is_uniformly_sampled else self.tr("否"),
            ),
            (self.tr("内部单位"), "s / V"),
            (self.tr("源数据写入"), self.tr("无（只读）")),
        )
        self.data_summary_table.setRowCount(len(rows))
        for row_index, (field, value) in enumerate(rows):
            self.data_summary_table.setItem(
                row_index,
                0,
                QTableWidgetItem(field),
            )
            self.data_summary_table.setItem(
                row_index,
                1,
                QTableWidgetItem(value),
            )
        self.data_summary_table.resizeColumnsToContents()
        self.diagnostics_tabs.setCurrentWidget(self.data_summary_table)

    def _apply_state(self) -> None:
        loaded = self._workflow_state is not WorkflowState.EMPTY
        availability = (True, loaded, False, False, False, False)
        unavailable_tooltip = self.tr(
            "当前状态不可用，或该功能尚未接入本版 GUI。"
        )
        for index, enabled in enumerate(availability):
            item = self.workflow_navigation.item(index)
            if item is None:
                continue
            flags = item.flags()
            if enabled:
                item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip("")
            else:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(unavailable_tooltip)
        for tab_index in range(1, self.science_tabs.count()):
            self.science_tabs.setTabEnabled(tab_index, False)
            self.science_tabs.setTabToolTip(tab_index, unavailable_tooltip)
        if not loaded:
            self.workflow_navigation.setCurrentRow(0)
            self.parameter_stack.setCurrentIndex(0)
        self.status_state.setText(
            self.tr("状态：{state}").format(state=self._workflow_state.name)
        )
        self.status_unsaved.setText(
            self.tr("未保存修改：{value}").format(
                value=self.tr("是") if self._unsaved_changes else self.tr("否")
            )
        )
        if self._load_result is None:
            self.status_file.setText(self.tr("文件：未加载"))
        else:
            self.status_file.setText(
                self.tr("文件：{name}").format(
                    name=self._load_result.source_path.name
                )
            )

    def _workflow_page_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.workflow_navigation.item(row)
        if item is None or not bool(item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        self.parameter_stack.setCurrentIndex(row)

    def _channel_changed(self, channel_name: str) -> None:
        self.status_channel.setText(
            self.tr("通道：{channel}").format(channel=channel_name)
        )

    def _cursor_changed(
        self,
        time_s: float,
        voltage_v: float,
        channel_name: str,
    ) -> None:
        self.status_time.setText(
            self.tr("时间：{time_us:.6f} μs").format(time_us=time_s * 1e6)
        )
        self.status_value.setText(
            self.tr("电压：{voltage_mv:.6f} mV ({channel})").format(
                voltage_mv=voltage_v * 1e3,
                channel=channel_name,
            )
        )

    def _save_language(self, language_code: str) -> None:
        if self._translation_manager is None:
            return
        saved = self._translation_manager.save_preference(language_code)
        self.action_language_zh.setChecked(saved == LANGUAGE_ZH_CN)
        self.action_language_en.setChecked(saved == LANGUAGE_EN)
        self.statusBar().showMessage(
            self.tr("语言设置已保存，重启 PDV Studio 后生效。"),
            5000,
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self.tr("关于 PDV Studio"),
            self.tr(
                "PDV Studio\n\n"
                "用于 PDV 时间—电压数据的可追溯桌面工作台。\n"
                "TASK-014 版本仅接入只读数据导入与原始信号显示。"
            ),
        )

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Close normally; TASK-014 does not hold background analysis jobs."""
        event.accept()

    def _planned_view(self, text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = self._notice(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label, 1)
        return page

    def _planned_parameters(self, title: str, text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._section_title(title))
        layout.addWidget(self._notice(text))
        planned_button = QPushButton(self.tr("尚未接入"))
        planned_button.setEnabled(False)
        planned_button.setToolTip(
            self.tr("该功能已列入后续开发计划，当前版本尚未接入。")
        )
        layout.addWidget(planned_button)
        layout.addStretch(1)
        return page

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _notice(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("plannedNotice")
        label.setWordWrap(True)
        return label


__all__ = ["MainWindow"]
