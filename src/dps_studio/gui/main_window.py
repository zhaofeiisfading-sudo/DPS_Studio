"""Resizable PDV Studio workstation using public core workflow adapters."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QFileDialog,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
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

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.workflow import WorkflowConfiguration, load_workflow_config
from dps_studio.gui.analysis_adapter import (
    AnalysisRequest,
    AnalysisRunResult,
    AutomaticAnalysisAdapter,
)
from dps_studio.gui.analysis_range import AnalysisRangePanel
from dps_studio.gui.analysis_session import AnalysisRange, AnalysisSession
from dps_studio.gui.data_controller import DataImportController
from dps_studio.gui.i18n import (
    LANGUAGE_EN,
    LANGUAGE_ZH_CN,
    TranslationManager,
)
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.native_icons import native_directory_icon
from dps_studio.gui.raw_signal_view import RawSignalView
from dps_studio.gui.result_views import (
    ComparisonView,
    QualitySummaryWidget,
    RidgeView,
    SpectrogramView,
    VelocityView,
)
from dps_studio.gui.state import WorkflowState, state_reaches


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
        self._session = AnalysisSession()
        self._analysis_adapter = AutomaticAnalysisAdapter(self)
        self._workflow_state = WorkflowState.EMPTY
        self._unsaved_changes = False
        self._wavelength_confirmed = False

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

    @property
    def analysis_session(self) -> AnalysisSession:
        """Return the current in-memory analysis session."""
        return self._session

    def set_loaded_result(self, result: DelimitedSignalLoadResult) -> None:
        """Present a public core load result and enter ``DATA_LOADED``."""
        if not isinstance(result, DelimitedSignalLoadResult):
            raise TypeError("result must be a DelimitedSignalLoadResult.")
        self._load_result = result
        self._session.load_records(
            source_path=result.source_path,
            records=result.records,
        )
        confirm_blocker = QSignalBlocker(self.wavelength_confirm_check)
        self.wavelength_confirm_check.setChecked(False)
        del confirm_blocker
        self._wavelength_confirmed = False
        self.raw_signal_view.set_records(result.records)
        range_start, range_end = self._session.data_bounds_s()
        self.analysis_range_panel.set_data_bounds(range_start, range_end)
        self._populate_data_summary(result)
        self._workflow_state = WorkflowState.DATA_LOADED
        self._unsaved_changes = False
        self._clear_result_presentation(
            self.tr("数据已重新加载；请确认分析范围并重新分析。")
        )
        self._apply_state()
        self._append_log(
            self.tr("已加载 {rows} 行、{channels} 个独立电压通道：{path}").format(
                rows=result.row_count,
                channels=len(result.channel_names),
                path=result.source_path,
            )
        )

    def set_analysis_configuration(
        self,
        configuration: WorkflowConfiguration,
    ) -> None:
        """Install one explicit public workflow configuration for current records."""
        if not isinstance(configuration, WorkflowConfiguration):
            raise TypeError("configuration must be a WorkflowConfiguration.")
        profiles = configuration.analysis.profiles
        if not profiles:
            raise ValueError("The workflow configuration contains no profiles.")
        combo_blocker = QSignalBlocker(self.profile_combo)
        self.profile_combo.clear()
        for profile in profiles:
            self.profile_combo.addItem(profile.display_name, profile)
        self.profile_combo.setCurrentIndex(0)
        self.profile_combo.setEnabled(True)
        del combo_blocker
        self._session.set_workflow_configuration(
            configuration,
            profile=profiles[0],
        )
        wavelength_blocker = QSignalBlocker(self.vacuum_wavelength_spin)
        self.vacuum_wavelength_spin.setValue(
            configuration.analysis.vacuum_wavelength_m * 1e9
        )
        self.vacuum_wavelength_spin.setEnabled(True)
        del wavelength_blocker
        confirm_blocker = QSignalBlocker(self.wavelength_confirm_check)
        self.wavelength_confirm_check.setChecked(False)
        self.wavelength_confirm_check.setEnabled(True)
        del confirm_blocker
        self._wavelength_confirmed = False
        self.config_path_label.setText(str(configuration.config_path))
        self.quality_source_label.setText(str(configuration.config_path))
        self._update_profile_labels(profiles[0])
        self._clear_result_presentation(
            self.tr("分析配置已变化；旧结果已失效。")
        )
        self._sync_workflow_state_after_invalidation()
        self._append_log(
            self.tr("已加载正式 workflow 配置：{path}").format(
                path=configuration.config_path
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
        self.action_open_data = QAction(
            native_directory_icon(),
            self.tr("打开数据…"),
            self,
        )
        self.action_open_data.setObjectName("actionOpenData")
        self.action_open_data.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open_data.setToolTip(self.tr("选择文件并显式配置列与单位"))

        self.action_exit = QAction(self.tr("退出"), self)
        self.action_exit.setObjectName("actionExit")
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)

        planned_tooltip = self.tr("请先加载配置、确认范围和真空波长。")
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
        self.main_toolbar.setIconSize(QSize(20, 20))
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
        self.spectrogram_view = SpectrogramView()
        self.science_tabs.addTab(self.spectrogram_view, self.tr("时频图"))
        self.ridge_view = RidgeView()
        self.science_tabs.addTab(self.ridge_view, self.tr("频谱脊线"))
        self.velocity_view = VelocityView()
        self.science_tabs.addTab(self.velocity_view, self.tr("速度曲线"))
        self.comparison_view = ComparisonView()
        self.science_tabs.addTab(self.comparison_view, self.tr("结果比较"))

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

        self.analysis_range_panel = AnalysisRangePanel()
        self.parameter_stack.addWidget(self.analysis_range_panel)

        stft_page = QWidget()
        stft_layout = QVBoxLayout(stft_page)
        stft_layout.addWidget(self._section_title(self.tr("STFT 与正式配置")))
        config_row = QHBoxLayout()
        self.load_config_button = QPushButton(self.tr("加载 workflow 配置…"))
        self.load_config_button.setObjectName("loadWorkflowConfigButton")
        self.config_path_label = QLabel(self.tr("未加载"))
        self.config_path_label.setWordWrap(True)
        config_row.addWidget(self.load_config_button)
        config_row.addWidget(self.config_path_label, 1)
        stft_layout.addLayout(config_row)
        stft_form = QFormLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("analysisProfileCombo")
        self.profile_combo.setEnabled(False)
        self.window_name_label = QLabel("—")
        self.window_length_label = QLabel("—")
        self.overlap_label = QLabel("—")
        self.hop_label = QLabel("—")
        self.nfft_label = QLabel("—")
        self.search_band_label = QLabel("—")
        self.analysis_range_label = QLabel("—")
        self.quality_source_label = QLabel("—")
        self.quality_source_label.setWordWrap(True)
        stft_form.addRow(self.tr("分析配置"), self.profile_combo)
        stft_form.addRow(self.tr("窗函数"), self.window_name_label)
        stft_form.addRow(self.tr("窗长"), self.window_length_label)
        stft_form.addRow(self.tr("重叠长度"), self.overlap_label)
        stft_form.addRow(self.tr("步长"), self.hop_label)
        stft_form.addRow(self.tr("FFT 长度"), self.nfft_label)
        stft_form.addRow(self.tr("搜索频段"), self.search_band_label)
        stft_form.addRow(self.tr("分析时间范围"), self.analysis_range_label)
        stft_form.addRow(self.tr("质量配置来源"), self.quality_source_label)
        stft_layout.addLayout(stft_form)
        self.run_analysis_button = QPushButton(self.tr("运行完整自动分析"))
        self.run_analysis_button.setObjectName("runAutomaticAnalysisButton")
        self.run_analysis_button.setDefault(True)
        self.run_analysis_button.setEnabled(False)
        stft_layout.addWidget(self.run_analysis_button)
        self.cancel_analysis_button = QPushButton(self.tr("取消分析（不可用）"))
        self.cancel_analysis_button.setObjectName("cancelAnalysisButton")
        self.cancel_analysis_button.setEnabled(False)
        self.cancel_analysis_button.setToolTip(
            self.tr(
                "当前 core 没有协作取消 API；参数变化只会使迟到结果失效，"
                "不会立即中断 NumPy/SciPy 计算。"
            )
        )
        stft_layout.addWidget(self.cancel_analysis_button)
        self.analysis_progress = QProgressBar()
        self.analysis_progress.setObjectName("analysisProgress")
        self.analysis_progress.setRange(0, 0)
        self.analysis_progress.setVisible(False)
        stft_layout.addWidget(self.analysis_progress)
        self.analysis_status_label = self._notice(
            self.tr("加载配置、确认范围和真空波长后可运行。")
        )
        stft_layout.addWidget(self.analysis_status_label)
        stft_layout.addStretch(1)
        self.parameter_stack.addWidget(stft_page)

        self.parameter_stack.addWidget(
            self._planned_parameters(
                self.tr("脊线参数"),
                self.tr(
                    "自动分析使用 public core 的候选峰、亚频点精修、质量门和"
                    "连续性诊断。引导分析与多边形 ROI 尚未接入。"
                ),
            )
        )

        velocity_page = QWidget()
        velocity_layout = QVBoxLayout(velocity_page)
        velocity_layout.addWidget(self._section_title(self.tr("速度参数")))
        velocity_form = QFormLayout()
        self.vacuum_wavelength_spin = QDoubleSpinBox()
        self.vacuum_wavelength_spin.setObjectName("vacuumWavelengthNm")
        self.vacuum_wavelength_spin.setRange(0.001, 100000.0)
        self.vacuum_wavelength_spin.setDecimals(6)
        self.vacuum_wavelength_spin.setSuffix(" nm")
        self.vacuum_wavelength_spin.setEnabled(False)
        velocity_form.addRow(
            self.tr("真空波长"),
            self.vacuum_wavelength_spin,
        )
        velocity_layout.addLayout(velocity_form)
        self.wavelength_confirm_check = QCheckBox(
            self.tr("我已核对当前实验的真空波长")
        )
        self.wavelength_confirm_check.setObjectName("confirmVacuumWavelength")
        self.wavelength_confirm_check.setEnabled(False)
        velocity_layout.addWidget(self.wavelength_confirm_check)
        velocity_layout.addWidget(
            self._notice(
                self.tr(
                    "配置中的波长不会被静默采用；必须由用户明确核对。"
                    "当前仅计算表观速度，窗口修正和 corrected velocity 尚未接入。"
                )
            )
        )
        self.corrected_velocity_parameter = QPushButton(
            self.tr("窗口修正尚未接入")
        )
        self.corrected_velocity_parameter.setEnabled(False)
        velocity_layout.addWidget(self.corrected_velocity_parameter)
        velocity_layout.addStretch(1)
        self.parameter_stack.addWidget(velocity_page)

        self.parameter_stack.addWidget(
            self._planned_parameters(
                self.tr("复核与导出"),
                self.tr(
                    "当前提供双通道正式表观速度比较和质量复核。正式导出保持"
                    "禁用，production 脚本未作为 GUI 运行依赖。"
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

        self.quality_summary = QualitySummaryWidget()
        self.quality_label = self.quality_summary.notice
        self.diagnostics_tabs.addTab(self.quality_summary, self.tr("质量"))

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
        self.action_automatic.triggered.connect(self.run_automatic_analysis)
        self.action_run_stft.triggered.connect(self.run_automatic_analysis)
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
        self.raw_signal_view.analysis_region_changed.connect(
            self.analysis_range_panel.set_draft_range_s
        )
        self.analysis_range_panel.draft_range_changed.connect(
            self.raw_signal_view.set_analysis_region_s
        )
        self.analysis_range_panel.range_confirmed.connect(
            self._analysis_range_confirmed
        )
        self.analysis_range_panel.current_view_requested.connect(
            self._use_current_view_range
        )
        self.load_config_button.clicked.connect(self._choose_analysis_config)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.vacuum_wavelength_spin.valueChanged.connect(
            self._vacuum_wavelength_changed
        )
        self.wavelength_confirm_check.toggled.connect(
            self._wavelength_confirmation_changed
        )
        self.run_analysis_button.clicked.connect(self.run_automatic_analysis)
        self._analysis_adapter.started.connect(self._analysis_started)
        self._analysis_adapter.finished.connect(self._analysis_finished)
        self._analysis_adapter.failed.connect(self._analysis_failed)
        self._analysis_adapter.busy_changed.connect(self._busy_changed)

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

    def _choose_analysis_config(self) -> None:
        selected_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("选择 workflow TOML 配置"),
            str(Path(__file__).resolve().parents[3] / "configs"),
            self.tr("TOML 配置 (*.toml);;所有文件 (*)"),
        )
        if not selected_path:
            return
        try:
            configuration = load_workflow_config(
                Path(selected_path),
                repository_root=Path(__file__).resolve().parents[3],
            )
            self.set_analysis_configuration(configuration)
        except Exception as exc:
            self._append_log(
                self.tr("配置加载失败：{error_type}: {message}").format(
                    error_type=type(exc).__name__,
                    message=exc,
                )
            )
            QMessageBox.critical(
                self,
                self.tr("配置加载失败"),
                self.tr("无法加载所选 workflow 配置。\n\n{message}").format(
                    message=exc
                ),
            )

    def _analysis_range_confirmed(
        self,
        start_time_s: float,
        end_time_s: float,
    ) -> None:
        try:
            self._session.set_analysis_range(
                AnalysisRange(start_time_s, end_time_s)
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            self.analysis_status_label.setText(str(exc))
            return
        self.analysis_range_label.setText(
            f"{start_time_s * 1e6:.9f} – {end_time_s * 1e6:.9f} μs"
        )
        self._workflow_state = WorkflowState.RANGE_DEFINED
        self._clear_result_presentation(
            self.tr("分析范围已变化；请重新运行自动分析。")
        )
        self._apply_state()
        self._append_log(
            self.tr("分析范围已确认：{start:.9f} – {end:.9f} μs").format(
                start=start_time_s * 1e6,
                end=end_time_s * 1e6,
            )
        )

    def _use_current_view_range(self) -> None:
        try:
            visible_range = self.raw_signal_view.current_view_range_s()
        except RuntimeError:
            return
        self.analysis_range_panel.confirm_range_s(*visible_range)

    def _profile_changed(self, index: int) -> None:
        profile = self.profile_combo.itemData(index)
        if not isinstance(profile, AnalysisProfile):
            return
        try:
            self._session.set_profile(profile)
        except ValueError as exc:
            self.analysis_status_label.setText(str(exc))
            return
        self._update_profile_labels(profile)
        self._clear_result_presentation(
            self.tr("分析 profile 已变化；请重新运行自动分析。")
        )
        self._sync_workflow_state_after_invalidation()

    def _vacuum_wavelength_changed(self, value_nm: float) -> None:
        try:
            self._session.set_vacuum_wavelength_m(value_nm * 1e-9)
        except ValueError as exc:
            self.analysis_status_label.setText(str(exc))
            return
        confirm_blocker = QSignalBlocker(self.wavelength_confirm_check)
        self.wavelength_confirm_check.setChecked(False)
        del confirm_blocker
        self._wavelength_confirmed = False
        self._clear_result_presentation(
            self.tr("真空波长已变化；请核对并重新运行自动分析。")
        )
        self._sync_workflow_state_after_invalidation()

    def _wavelength_confirmation_changed(self, checked: bool) -> None:
        self._wavelength_confirmed = bool(checked)
        self._apply_state()

    def run_automatic_analysis(self) -> bool:
        """Capture the current generation and start the public workflow off-thread."""
        configuration = self._session.run_configuration
        analysis_range = self._session.analysis_range
        if (
            not self._session.records
            or configuration is None
            or analysis_range is None
            or not self._wavelength_confirmed
        ):
            self.analysis_status_label.setText(
                self.tr("缺少数据、确认范围、正式配置或已核对的真空波长。")
            )
            self._apply_state()
            return False
        request = AnalysisRequest(
            generation_id=self._session.generation_id,
            records=self._session.records,
            analysis_range=analysis_range,
            configuration=configuration,
        )
        started = self._analysis_adapter.start(request)
        if not started:
            self.analysis_status_label.setText(self.tr("自动分析已在运行。"))
        return started

    def _analysis_started(self, generation_id: int) -> None:
        self.analysis_status_label.setText(self.tr("正在分析…"))
        self._append_log(
            self.tr("后台自动分析已开始（请求 {generation}）。").format(
                generation=generation_id
            )
        )

    def _analysis_finished(self, value: object) -> None:
        if not isinstance(value, AnalysisRunResult):
            self._analysis_failed(
                self._session.generation_id,
                "TypeError",
                "Background adapter returned an unexpected result type.",
                "",
            )
            return
        accepted = self._session.accept_results(
            generation_id=value.generation_id,
            analyses=value.channel_analyses,
        )
        if not accepted:
            self.analysis_status_label.setText(
                self.tr("分析期间参数已变化；已忽略迟到结果。")
            )
            self._append_log(
                self.tr("请求 {generation} 的迟到结果已忽略。").format(
                    generation=value.generation_id
                )
            )
            self._sync_workflow_state_after_invalidation()
            return
        run_configuration = self._session.run_configuration
        if run_configuration is None:
            return
        analyses = self._session.channel_analyses
        self._workflow_state = WorkflowState.STFT_READY
        self._apply_state()
        self.spectrogram_view.set_analyses(
            analyses,
            relative_db_floor=run_configuration.relative_db_floor,
        )
        self._workflow_state = WorkflowState.RIDGE_READY
        self._apply_state()
        self.ridge_view.set_analyses(
            analyses,
            relative_db_floor=run_configuration.relative_db_floor,
        )
        self.velocity_view.set_analyses(
            analyses,
            relative_db_floor=run_configuration.relative_db_floor,
        )
        self.comparison_view.set_analyses(analyses)
        self.quality_summary.set_analyses(analyses)
        self._workflow_state = WorkflowState.RESULT_READY
        self._apply_state()
        self.analysis_status_label.setText(self.tr("自动分析完成；结果为当前有效。"))
        self.diagnostics_tabs.setCurrentWidget(self.quality_summary)
        self._append_log(
            self.tr("自动分析完成：{channels} 个独立通道。").format(
                channels=len(analyses)
            )
        )

    def _analysis_failed(
        self,
        generation_id: int,
        error_type: str,
        message: str,
        traceback_text: str,
    ) -> None:
        if generation_id != self._session.generation_id:
            self._append_log(
                self.tr("已忽略失效请求 {generation} 的异常。").format(
                    generation=generation_id
                )
            )
            return
        summary = f"{error_type}: {message}"
        self.analysis_status_label.setText(
            self.tr("自动分析失败：{summary}").format(summary=summary)
        )
        self.quality_summary.clear_results(
            self.tr("自动分析失败：{summary}").format(summary=summary)
        )
        self._append_log(
            self.tr("自动分析失败：{summary}").format(summary=summary)
        )
        if traceback_text:
            self._append_log(traceback_text.rstrip())
        self._sync_workflow_state_after_invalidation()

    def _busy_changed(self, busy: bool) -> None:
        self.analysis_progress.setVisible(busy)
        self.profile_combo.setEnabled(
            not busy and self._session.workflow_configuration is not None
        )
        self.load_config_button.setEnabled(not busy)
        self.vacuum_wavelength_spin.setEnabled(
            not busy and self._session.run_configuration is not None
        )
        self.wavelength_confirm_check.setEnabled(
            not busy and self._session.run_configuration is not None
        )
        self._apply_state()

    def _update_profile_labels(self, profile: AnalysisProfile) -> None:
        self.window_name_label.setText(profile.window_name)
        self.window_length_label.setText(
            self.tr("{value} samples").format(value=profile.window_length_samples)
        )
        self.overlap_label.setText(
            self.tr("{value} samples").format(value=profile.overlap_samples)
        )
        self.hop_label.setText(
            self.tr("{value} samples").format(value=profile.hop_samples)
        )
        self.nfft_label.setText(str(profile.nfft))
        self.search_band_label.setText(
            f"{profile.minimum_frequency_hz * 1e-9:.3f} – "
            f"{profile.maximum_frequency_hz * 1e-9:.3f} GHz"
        )

    def _clear_result_presentation(self, reason: str) -> None:
        self.spectrogram_view.clear_results()
        self.ridge_view.clear_results()
        self.velocity_view.clear_results()
        self.comparison_view.clear_results()
        self.quality_summary.clear_results(reason)
        self.action_export.setEnabled(False)
        self.analysis_status_label.setText(reason)

    def _sync_workflow_state_after_invalidation(self) -> None:
        if not self._session.records:
            self._workflow_state = WorkflowState.EMPTY
        elif self._session.analysis_range is None:
            self._workflow_state = WorkflowState.DATA_LOADED
        else:
            self._workflow_state = WorkflowState.RANGE_DEFINED
        self._apply_state()

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
        range_defined = state_reaches(
            self._workflow_state,
            WorkflowState.RANGE_DEFINED,
        )
        availability = (
            True,
            loaded,
            range_defined,
            state_reaches(self._workflow_state, WorkflowState.STFT_READY),
            state_reaches(self._workflow_state, WorkflowState.RIDGE_READY),
            state_reaches(self._workflow_state, WorkflowState.RESULT_READY),
        )
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
        tab_requirements = (
            WorkflowState.STFT_READY,
            WorkflowState.RIDGE_READY,
            WorkflowState.RESULT_READY,
            WorkflowState.RESULT_READY,
        )
        for tab_index, required_state in enumerate(tab_requirements, start=1):
            enabled = state_reaches(self._workflow_state, required_state)
            self.science_tabs.setTabEnabled(tab_index, enabled)
            self.science_tabs.setTabToolTip(
                tab_index,
                "" if enabled else unavailable_tooltip,
            )
        can_run = (
            range_defined
            and self._session.run_configuration is not None
            and self._wavelength_confirmed
            and not self._analysis_adapter.busy
        )
        run_tooltip = (
            self.tr("运行 public core 完整自动分析。")
            if can_run
            else self.tr("请先加载配置、确认范围和真空波长。")
        )
        self.action_automatic.setEnabled(can_run)
        self.action_automatic.setToolTip(run_tooltip)
        self.action_run_stft.setEnabled(can_run)
        self.action_run_stft.setToolTip(run_tooltip)
        self.run_analysis_button.setEnabled(can_run)
        self.run_analysis_button.setToolTip(run_tooltip)
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
                "TASK-015A 接入只读范围与 public core 后台自动分析。"
            ),
        )

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Close without claiming to interrupt an active numerical worker."""
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
