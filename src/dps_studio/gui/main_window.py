"""Resizable PDV Studio workstation using public core workflow adapters."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, QSignalBlocker, QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDockWidget,
    QFileDialog,
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
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from dps_studio.core.analysis_profiles import (
    AnalysisParameterOverrides,
    AnalysisProfile,
    AnalysisProfileId,
    AnalysisRunParameters,
)
from dps_studio.core.export import (
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultExportError,
    ResultExportOptions,
    export_formal_results,
)
from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.physics import (
    LIF_RIGG_2014_1550NM,
    LiFWindowCorrectionModel,
    VelocityCorrectionConfig,
    WindowMaterial,
)
from dps_studio.core.ridge import (
    AutomaticRidgeExtractionMode,
    ManualFrequencyRegion,
    RidgeConfigurationError,
    RidgeCorridorConstraint,
    validate_manual_frequency_region_for_stft,
    validate_ridge_corridor_for_stft,
)
from dps_studio.core.time_frequency import STFTWindowName
from dps_studio.core.workflow import (
    ChannelAnalysis,
    WorkflowConfiguration,
    load_workflow_config,
)
from dps_studio.gui.analysis_adapter import (
    AnalysisRequest,
    AnalysisResultSource,
    AnalysisRunResult,
    AutomaticAnalysisAdapter,
)
from dps_studio.gui.analysis_range import AnalysisRangePanel
from dps_studio.gui.analysis_session import (
    AnalysisRange,
    AnalysisRunConfiguration,
    AnalysisSession,
    EventTimeSource,
    RidgeExtractionMode,
    RidgeSearchRegion,
)
from dps_studio.gui.advanced_parameters_dialog import AdvancedParametersDialog
from dps_studio.gui.data_controller import DataImportController
from dps_studio.gui.display_preferences import DisplayPreferences
from dps_studio.gui.i18n import (
    LANGUAGE_EN,
    LANGUAGE_ZH_CN,
    TranslationManager,
)
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.native_icons import native_directory_icon
from dps_studio.gui.preset_repository import (
    CUSTOM_PRESET_ID,
    PresetRepository,
)
from dps_studio.gui.raw_signal_view import RawSignalView
from dps_studio.gui.result_views import (
    ComparisonView,
    QualitySummaryWidget,
    RidgeView,
    SpectrogramView,
    VelocityView,
)
from dps_studio.gui.state import WorkflowState, state_reaches
from dps_studio.gui.styles import configure_action_button_cursors
from dps_studio.runtime_paths import application_resource_root


_LAYOUT_STATE_VERSION = 1
_GEOMETRY_SETTINGS_KEY = "layout/main_window_geometry"
_WINDOW_STATE_SETTINGS_KEY = "layout/main_window_state"
_SPLITTER_STATE_SETTINGS_KEY = "layout/workspace_splitter_state"
_DIAGNOSTICS_HEIGHT_SETTINGS_KEY = "layout/diagnostics_dock_height"
_DEFAULT_WORKSPACE_SIZES = (220, 830, 340)
_DEFAULT_DIAGNOSTICS_HEIGHT = 210
_AUTOMATIC_MODE_BUTTON_ID = 101
_GUIDED_MODE_BUTTON_ID = 102
_STFT_WINDOW_OPTIONS = (
    (STFTWindowName.HANN.value, "Hann"),
    (STFTWindowName.HAMMING.value, "Hamming"),
    (STFTWindowName.BLACKMAN.value, "Blackman"),
    (STFTWindowName.BLACKMAN_HARRIS.value, "Blackman-Harris"),
    (STFTWindowName.BOXCAR.value, "矩形窗（Boxcar）"),
)
_AUTOMATIC_RIDGE_OPTIONS = (
    (AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED.value, "连续性辅助"),
    (AutomaticRidgeExtractionMode.LEGACY_STRONGEST_PEAK.value, "传统最强峰"),
)


class _CompactDoubleSpinBox(QDoubleSpinBox):
    """Preserve numeric precision while avoiding padded display zeroes."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        minimum_decimals: int = 0,
    ) -> None:
        super().__init__(parent)
        self._minimum_decimals = minimum_decimals

    def textFromValue(self, value: float) -> str:  # noqa: N802 - Qt virtual API
        text = f"{value:.{self.decimals()}f}"
        whole, separator, fraction = text.partition(".")
        if not separator:
            return whole
        fraction = fraction.rstrip("0")
        if len(fraction) < self._minimum_decimals:
            fraction += "0" * (self._minimum_decimals - len(fraction))
        return f"{whole}.{fraction}" if fraction else whole


class MainWindow(QMainWindow):
    """Compose the first runnable workstation and its explicit UI states."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        translation_manager: TranslationManager | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self._translation_manager = translation_manager
        self._settings = settings if settings is not None else QSettings()
        self._display_preferences = DisplayPreferences(self._settings)
        self._data_controller = DataImportController()
        self._load_result: DelimitedSignalLoadResult | None = None
        self._repository_root = application_resource_root()
        self._preset_repository: PresetRepository | None = None
        self._session = AnalysisSession()
        self._analysis_adapter = AutomaticAnalysisAdapter(self)
        self._pending_analysis_source = AnalysisResultSource.AUTOMATIC
        self._pending_navigation_tab: int | None = None
        self._pending_candidate_detection = False
        self._quick_analysis_waiting = False
        self._continue_to_velocity_after_analysis = False
        self._current_guided_channel: str | None = None
        self._export_output_directory: Path | None = None
        self._workflow_state = WorkflowState.EMPTY
        self._unsaved_changes = False
        self._parameters_valid = False
        self._parameter_error = self.tr("默认科学参数尚未加载。")
        self._updating_parameter_controls = False

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
        configure_action_button_cursors(self)
        self._default_geometry = QByteArray(self.saveGeometry())
        self._default_window_state = QByteArray(
            self.saveState(_LAYOUT_STATE_VERSION)
        )
        self._connect_signals()
        self._set_spectrogram_colormap(
            self._display_preferences.spectrogram_colormap(),
            persist=False,
        )
        self._restore_layout_settings()
        self._restore_default_parameters(initial=True)
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

    @property
    def ridge_extraction_mode(self) -> RidgeExtractionMode:
        """Return the explicit model value selected by the Ridge controls."""
        return self._session.ridge_extraction_mode

    def set_loaded_result(self, result: DelimitedSignalLoadResult) -> None:
        """Present a public core load result and enter ``DATA_LOADED``."""
        if not isinstance(result, DelimitedSignalLoadResult):
            raise TypeError("result must be a DelimitedSignalLoadResult.")
        self._load_result = result
        self._current_guided_channel = None
        self._session.load_records(
            source_path=result.source_path,
            records=result.records,
        )
        self._constrain_search_band_to_records()
        run_configuration = self._session.run_configuration
        if run_configuration is not None:
            self._set_parameter_controls(
                run_configuration.parameters,
                editable=True,
            )
        self._sync_export_time_origin_controls()
        self.raw_signal_view.set_records(result.records)
        self.raw_signal_view.analysis_region.setVisible(False)
        range_start, range_end = self._session.data_bounds_s()
        self.analysis_range_panel.set_data_bounds(range_start, range_end)
        self._populate_data_summary(result)
        self._workflow_state = WorkflowState.DATA_LOADED
        self._unsaved_changes = False
        self._clear_result_presentation(
            self.tr("数据已重新加载；正在建立默认分析范围。")
        )
        self._validate_current_parameters()
        default_range = self._default_analysis_range(range_start, range_end)
        self.analysis_range_panel.confirm_range_s(*default_range)
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
        """Install a traceable preset repository without changing loaded records."""
        if not isinstance(configuration, WorkflowConfiguration):
            raise TypeError("configuration must be a WorkflowConfiguration.")
        repository = PresetRepository(configuration)
        self._preset_repository = repository
        combo_blocker = QSignalBlocker(self.profile_combo)
        self.profile_combo.clear()
        for profile in repository.profiles:
            self.profile_combo.addItem(self._profile_display_name(profile), profile)
            self.profile_combo.setItemData(
                self.profile_combo.count() - 1,
                self._profile_tooltip(profile),
                Qt.ItemDataRole.ToolTipRole,
            )
        default_index = next(
            index
            for index, profile in enumerate(repository.profiles)
            if profile is repository.default_profile
        )
        self.profile_combo.setCurrentIndex(default_index)
        self.profile_combo.setEnabled(True)
        del combo_blocker
        self._session.set_workflow_configuration(
            configuration,
            profile=repository.default_profile,
        )
        self._constrain_search_band_to_records()
        self._sync_event_reference_panel()
        self._updating_parameter_controls = True
        wavelength_blocker = QSignalBlocker(self.vacuum_wavelength_spin)
        window_material_blocker = QSignalBlocker(self.window_material_combo)
        measurement_angle_blocker = QSignalBlocker(self.measurement_angle_spin)
        lif_b1_blocker = QSignalBlocker(self.lif_b1_spin)
        lif_b2_blocker = QSignalBlocker(self.lif_b2_spin)
        lif_reference_blocker = QSignalBlocker(
            self.lif_reference_wavelength_spin
        )
        display_velocity_blocker = QSignalBlocker(
            self.pre_event_display_velocity_spin
        )
        display_check_blocker = QSignalBlocker(self.pre_event_display_check)
        self.vacuum_wavelength_spin.setValue(
            configuration.analysis.vacuum_wavelength_m * 1e9
        )
        window_index = self.window_material_combo.findData(
            configuration.velocity_correction.window_material.value
        )
        if window_index < 0:
            raise ValueError("Unsupported configured window material.")
        self.window_material_combo.setCurrentIndex(window_index)
        self.measurement_angle_spin.setValue(
            math.degrees(configuration.velocity_correction.measurement_angle_rad)
        )
        self.lif_b1_spin.setValue(configuration.velocity_correction.lif_model.b1)
        self.lif_b2_spin.setValue(configuration.velocity_correction.lif_model.b2)
        self.lif_reference_wavelength_spin.setValue(
            configuration.velocity_correction.lif_model.reference_wavelength_m
            * 1e9
        )
        self.pre_event_display_velocity_spin.setValue(
            configuration.plot.pre_event_display_velocity_m_s
        )
        self.pre_event_display_check.setChecked(
            configuration.plot.assume_pre_event_zero_for_display
        )
        self.display_velocity_status_label.setText(
            self.tr("开启")
            if configuration.plot.assume_pre_event_zero_for_display
            else self.tr("关闭")
        )
        self.vacuum_wavelength_spin.setEnabled(True)
        del wavelength_blocker
        del window_material_blocker
        del measurement_angle_blocker
        del lif_b1_blocker
        del lif_b2_blocker
        del lif_reference_blocker
        del display_velocity_blocker
        del display_check_blocker
        run_configuration = self._session.run_configuration
        if run_configuration is None:
            raise RuntimeError("Session did not retain the workflow configuration.")
        self._set_parameter_controls(
            run_configuration.parameters,
            editable=True,
        )
        self._updating_parameter_controls = False
        self._validate_current_parameters()
        self._sync_velocity_correction_controls()
        self._sync_export_time_origin_controls()
        self._sync_velocity_correction_warning()
        presentation_reason = (
            self.tr("分析配置已变化；旧结果已失效。")
            if self._session.records
            else self.tr("默认科学参数已就绪；请导入实验数据。")
        )
        self._clear_result_presentation(presentation_reason)
        self._sync_workflow_state_after_invalidation()
        self._append_log(
            self.tr("已加载分析参数源：{path}").format(
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

    def _profile_display_name(self, profile: AnalysisProfile) -> str:
        labels = {
            AnalysisProfileId.BALANCED: self.tr("平衡"),
            AnalysisProfileId.HIGH_TIME_RESOLUTION: self.tr("高时间分辨率"),
            AnalysisProfileId.HIGH_FREQUENCY_RESOLUTION: self.tr("高频率分辨率"),
            AnalysisProfileId.VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL: self.tr(
                "极高时间分辨率（实验）"
            ),
            AnalysisProfileId.VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL: self.tr(
                "极高频率分辨率（实验）"
            ),
        }
        return labels[profile.profile_id]

    def _profile_tooltip(self, profile: AnalysisProfile) -> str:
        """Describe the physical time--frequency trade-off of each profile."""
        tooltips = {
            AnalysisProfileId.VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL: self.tr(
                "使用更短时间窗，提高局部时间响应能力，但有限窗频率分辨能力更弱。"
            ),
            AnalysisProfileId.VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL: self.tr(
                "使用更长时间窗，提高有限窗频率分辨能力，但会牺牲快速瞬态的时间定位能力。"
            ),
        }
        return tooltips.get(
            profile.profile_id,
            self.tr("不同预设代表不同时间—频率分辨率取舍。结果仍需结合频谱和质量状态复核。"),
        )

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
        self.action_quick_analysis = QAction(self.tr("快速分析"), self)
        self.action_quick_analysis.setObjectName("actionQuickAnalysis")
        self.action_quick_analysis.setEnabled(False)
        self.action_quick_analysis.setToolTip(planned_tooltip)
        # Hidden compatibility hook for older automation. Production menus and
        # toolbar expose Quick Analysis and Full Automatic Analysis explicitly.
        self.action_automatic = QAction(self.tr("一键分析"), self)
        self.action_automatic.setObjectName("actionAutomaticAnalysis")
        self.action_automatic.setEnabled(False)
        self.action_automatic.setToolTip(planned_tooltip)
        self.action_full_automatic = QAction(self.tr("全自动分析"), self)
        self.action_full_automatic.setObjectName("actionFullAutomaticAnalysis")
        self.action_full_automatic.setEnabled(False)
        self.action_full_automatic.setToolTip(planned_tooltip)
        self.action_guided = QAction(self.tr("人工范围分析"), self)
        self.action_guided.setObjectName("actionGuidedAnalysis")
        self.action_guided.setEnabled(False)
        self.action_guided.setToolTip(self.tr("请先计算当前 STFT。"))
        self.action_undo_corridor = QAction(self.tr("撤销上一点"), self)
        self.action_undo_corridor.setShortcut(QKeySequence("Ctrl+Z"))
        self.action_backspace_corridor = QAction(self.tr("撤销上一点"), self)
        self.action_backspace_corridor.setShortcut(QKeySequence("Backspace"))
        self.action_cancel_corridor_drawing = QAction(
            self.tr("退出人工边界编辑"), self
        )
        self.action_cancel_corridor_drawing.setShortcut(QKeySequence("Escape"))
        self.action_finish_corridor_drawing = QAction(
            self.tr("完成人工边界编辑"), self
        )
        self.action_finish_corridor_drawing.setShortcut(QKeySequence("Return"))
        for corridor_action in (
            self.action_undo_corridor,
            self.action_backspace_corridor,
            self.action_cancel_corridor_drawing,
            self.action_finish_corridor_drawing,
        ):
            self.addAction(corridor_action)
        self.action_run_stft = QAction(self.tr("计算时频图"), self)
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
        self.action_export = QAction(self.tr("复核与导出"), self)
        self.action_export.setObjectName("actionExport")
        self.action_export.setEnabled(False)
        self.action_export.setToolTip(
            self.tr("查看当前有效结果并设置导出参数。")
        )

        self.action_import_analysis_config = QAction(
            self.tr("导入配置…"),
            self,
        )
        self.action_import_analysis_config.setObjectName(
            "actionImportAnalysisConfiguration"
        )
        self.action_restore_default_parameters = QAction(
            self.tr("恢复默认参数"),
            self,
        )
        self.action_restore_default_parameters.setObjectName(
            "actionRestoreDefaultAnalysisParameters"
        )

        self.action_restore_default_layout = QAction(
            self.tr("恢复默认布局"),
            self,
        )
        self.action_restore_default_layout.setObjectName(
            "actionRestoreDefaultLayout"
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
        self.file_menu.addAction(self.action_export)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_exit)

        self.analysis_menu = self.menuBar().addMenu(self.tr("分析"))
        self.analysis_menu.setObjectName("analysisMenu")
        self.analysis_menu.addAction(self.action_quick_analysis)
        self.analysis_menu.addAction(self.action_full_automatic)

        self.view_menu = self.menuBar().addMenu(self.tr("视图"))
        self.view_menu.setObjectName("viewMenu")
        self.view_menu.addAction(self.action_restore_default_layout)

        self.settings_menu = self.menuBar().addMenu(self.tr("设置"))
        self.settings_menu.setObjectName("settingsMenu")
        self.analysis_parameters_menu = QMenu(self.tr("分析参数"), self)
        self.analysis_parameters_menu.setObjectName("analysisParametersMenu")
        self.analysis_parameters_menu.addAction(
            self.action_import_analysis_config
        )
        self.analysis_parameters_menu.addAction(
            self.action_restore_default_parameters
        )
        self.settings_menu.addMenu(self.analysis_parameters_menu)
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
        self.main_toolbar.addAction(self.action_quick_analysis)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.action_export)
        self.addToolBar(self.main_toolbar)

    def _create_workspace(self) -> None:
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(7)

        self.navigation_panel = QWidget()
        self.navigation_panel.setObjectName("workflowNavigationPanel")
        navigation_layout = QVBoxLayout(self.navigation_panel)
        navigation_layout.addWidget(self._section_title(self.tr("处理流程")))
        self.workflow_navigation = QListWidget()
        self.workflow_navigation.setObjectName("workflowNavigation")
        self._workflow_labels = (
            self.tr("1  数据与时频"),
            self.tr("2  脊线提取"),
            self.tr("3  速度结果"),
            self.tr("4  复核与导出"),
        )
        for label in self._workflow_labels:
            self.workflow_navigation.addItem(QListWidgetItem(label))
        self.workflow_navigation.setCurrentRow(0)
        navigation_layout.addWidget(self.workflow_navigation, 1)
        self.navigation_panel.setMinimumWidth(150)
        navigation_policy = self.navigation_panel.sizePolicy()
        navigation_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        navigation_policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        self.navigation_panel.setSizePolicy(navigation_policy)

        self.science_tabs = QTabWidget()
        self.science_tabs.setObjectName("scienceTabs")
        self.science_tabs.setDocumentMode(True)
        self.science_tabs.setMinimumWidth(360)
        science_policy = self.science_tabs.sizePolicy()
        science_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        science_policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        self.science_tabs.setSizePolicy(science_policy)
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

        self.parameter_panel = QWidget()
        self.parameter_panel.setObjectName("analysisParameterPanel")
        parameter_layout = QVBoxLayout(self.parameter_panel)
        parameter_layout.addWidget(self._section_title(self.tr("当前参数")))
        self.common_analysis_panel = self._build_common_analysis_panel()
        self.parameter_stack = QStackedWidget()
        self.parameter_stack.setObjectName("parameterStack")
        self._build_parameter_pages()
        parameter_layout.addWidget(self.parameter_stack, 1)
        self.parameter_panel.setMinimumWidth(240)
        parameter_policy = self.parameter_panel.sizePolicy()
        parameter_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        parameter_policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        self.parameter_panel.setSizePolicy(parameter_policy)

        splitter_policy = self.workspace_splitter.sizePolicy()
        splitter_policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        self.workspace_splitter.setSizePolicy(splitter_policy)
        self.workspace_splitter.addWidget(self.navigation_panel)
        self.workspace_splitter.addWidget(self.science_tabs)
        self.workspace_splitter.addWidget(self.parameter_panel)
        for index in range(3):
            self.workspace_splitter.setCollapsible(index, False)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes(list(_DEFAULT_WORKSPACE_SIZES))
        self.setCentralWidget(self.workspace_splitter)

    def _build_common_analysis_panel(self) -> QWidget:
        panel = QGroupBox(self.tr("分析配置"))
        layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("analysisProfileCombo")
        self.profile_combo.setEnabled(False)
        self.vacuum_wavelength_spin = _CompactDoubleSpinBox()
        self.vacuum_wavelength_spin.setObjectName("vacuumWavelengthNm")
        self.vacuum_wavelength_spin.setRange(0.001, 100000.0)
        self.vacuum_wavelength_spin.setDecimals(6)
        self.vacuum_wavelength_spin.setSuffix(" nm")
        self.vacuum_wavelength_spin.setToolTip(
            self.tr(
                "当前默认值为实验室 PDV 系统的 1550 nm 真空波长；"
                "实验条件变化时请直接修改。"
            )
        )
        self.vacuum_wavelength_spin.setEnabled(False)
        self.window_name_combo = QComboBox()
        self.window_name_combo.setObjectName("stftWindowFunctionCombo")
        for window_name, display_name in _STFT_WINDOW_OPTIONS:
            translated_name = (
                self.tr("矩形窗（Boxcar）")
                if window_name == STFTWindowName.BOXCAR.value
                else display_name
            )
            self.window_name_combo.addItem(translated_name, window_name)
        self.window_name_combo.setToolTip(
            self.tr(
                "窗口函数只改变 STFT 的数学 window；不会联动窗长、重叠、"
                "FFT 长度、搜索频带或质量门槛。矩形窗可作为无加权基线比较；"
                "其频谱泄漏特性与其他加窗方式不同，不作为默认选择。"
            )
        )
        self.automatic_ridge_extraction_combo = QComboBox()
        self.automatic_ridge_extraction_combo.setObjectName(
            "automaticRidgeExtractionCombo"
        )
        for mode, _display_name in _AUTOMATIC_RIDGE_OPTIONS:
            translated_name = (
                self.tr("连续性辅助")
                if mode == AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED.value
                else self.tr("传统最强峰")
            )
            self.automatic_ridge_extraction_combo.addItem(
                translated_name,
                mode,
            )
        self.automatic_ridge_extraction_combo.setToolTip(
            self.tr(
                "连续性辅助：在最强峰出现孤立跳变时，可在可信局部候选峰中"
                "选择与前后时间帧更连续的谱峰。\n传统最强峰：每个时间帧始终"
                "使用搜索频带内的最强谱峰。"
            )
        )
        self.window_length_spin = self._sample_spin("windowLengthSamples")
        self.overlap_spin = self._sample_spin("overlapSamples", minimum=0)
        self.hop_label = QLabel("—")
        self.nfft_spin = self._sample_spin("nfftSamples")
        self.minimum_frequency_spin = self._frequency_spin("minimumFrequencyGhz")
        self.maximum_frequency_spin = self._frequency_spin("maximumFrequencyGhz")
        form.addRow(self.tr("分析配置"), self.profile_combo)
        form.addRow(self.tr("窗口函数"), self.window_name_combo)
        form.addRow(self.tr("窗长"), self.window_length_spin)
        form.addRow(self.tr("重叠长度"), self.overlap_spin)
        form.addRow(self.tr("步长"), self.hop_label)
        form.addRow(self.tr("FFT 长度"), self.nfft_spin)
        layout.addLayout(form)
        self.parameter_error_label = QLabel()
        self.parameter_error_label.setObjectName("analysisParameterError")
        self.parameter_error_label.setWordWrap(True)
        self.parameter_error_label.setStyleSheet("color: #c62828;")
        self.parameter_error_label.setVisible(False)
        layout.addWidget(self.parameter_error_label)
        self.restore_preset_button = QPushButton(self.tr("恢复预设值"))
        self.restore_preset_button.setObjectName("restoreAnalysisPresetButton")
        self.restore_preset_button.setEnabled(False)
        layout.addWidget(self.restore_preset_button)
        self.advanced_parameters_button = QPushButton(self.tr("高级参数…"))
        self.advanced_parameters_button.setObjectName("advancedParametersButton")
        self.advanced_parameters_button.setEnabled(False)
        layout.addWidget(self.advanced_parameters_button)
        self.compute_stft_button = QPushButton(self.tr("计算时频图"))
        self.compute_stft_button.setObjectName("computeSpectrogramButton")
        self.compute_stft_button.setDefault(True)
        self.compute_stft_button.setEnabled(False)
        layout.addWidget(self.compute_stft_button)
        self.run_analysis_button = self.compute_stft_button
        self.analysis_progress = QProgressBar()
        self.analysis_progress.setObjectName("analysisProgress")
        self.analysis_progress.setRange(0, 0)
        self.analysis_progress.setVisible(False)
        layout.addWidget(self.analysis_progress)
        self.analysis_status_label = self._notice(
            self.tr("请先导入实验数据。")
        )
        layout.addWidget(self.analysis_status_label)
        return panel

    def _build_parameter_pages(self) -> None:
        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
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
        self.analysis_range_panel = AnalysisRangePanel()
        self.analysis_range_panel.set_analysis_range_controls_visible(False)
        data_layout.addStretch(1)
        self.analysis_range_scroll = QScrollArea()
        self.analysis_range_scroll.setObjectName("analysisRangeScrollArea")
        self.analysis_range_scroll.setWidgetResizable(True)
        self.analysis_range_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.analysis_range_scroll.setWidget(data_page)
        self.parameter_stack.addWidget(self.analysis_range_scroll)

        stft_page = QWidget()
        stft_layout = QVBoxLayout(stft_page)
        stft_layout.addWidget(self.common_analysis_panel)
        stft_layout.addWidget(self._section_title(self.tr("STFT 状态")))
        stft_status_widget = QWidget()
        stft_form = QFormLayout(stft_status_widget)
        self.analysis_range_label = QLabel("—")
        self.quality_source_label = QLabel(self.tr("内置默认质量配置"))
        self.quality_source_label.setToolTip(
            self.tr("完整配置来源可在“高级参数…”中查看。")
        )
        stft_form.addRow(self.tr("分析时间范围"), self.analysis_range_label)
        stft_form.addRow(self.tr("质量配置来源"), self.quality_source_label)
        stft_layout.addWidget(stft_status_widget)
        self.stft_ready_label = self._notice(self.tr("尚未计算时频图。"))
        self.stft_ready_label.setObjectName("stftReadyStatus")
        stft_layout.addWidget(self.stft_ready_label)
        self.cancel_analysis_button = QPushButton(
            self.tr("取消分析（不可用）"),
            stft_page,
        )
        self.cancel_analysis_button.setObjectName("cancelAnalysisButton")
        self.cancel_analysis_button.setEnabled(False)
        self.cancel_analysis_button.setToolTip(
            self.tr(
                "当前 core 没有协作取消 API；参数变化只会使迟到结果失效，"
                "不会立即中断 NumPy/SciPy 计算。"
            )
        )
        self.cancel_analysis_button.hide()
        stft_layout.addStretch(1)
        self.stft_parameter_scroll = QScrollArea()
        self.stft_parameter_scroll.setObjectName("stftParameterScrollArea")
        self.stft_parameter_scroll.setWidgetResizable(True)
        self.stft_parameter_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        stft_page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.stft_parameter_scroll.setWidget(stft_page)
        # Data import and STFT are one user-facing stage. Keep the legacy
        # scroll object for source compatibility, but place its controls on the
        # first page and do not add a fifth workflow page.
        data_layout.insertWidget(data_layout.count() - 1, self.common_analysis_panel)
        data_layout.insertWidget(data_layout.count() - 1, stft_status_widget)
        data_layout.insertWidget(data_layout.count() - 1, self.cancel_analysis_button)

        guided_page = QWidget()
        guided_layout = QVBoxLayout(guided_page)
        guided_layout.addWidget(self._section_title(self.tr("脊线提取")))
        ridge_mode_group = QGroupBox(self.tr("提取方式"))
        ridge_mode_layout = QHBoxLayout(ridge_mode_group)
        self.automatic_mode_radio = QRadioButton(self.tr("自动"))
        self.automatic_mode_radio.setChecked(True)
        self.guided_mode_radio = QRadioButton(self.tr("人工范围"))
        self.guided_mode_radio.setEnabled(False)
        self.guided_mode_radio.setToolTip(self.tr("请先计算当前 STFT。"))
        self.ridge_mode_button_group = QButtonGroup(ridge_mode_group)
        self.ridge_mode_button_group.setExclusive(True)
        self.ridge_mode_button_group.addButton(
            self.automatic_mode_radio,
            _AUTOMATIC_MODE_BUTTON_ID,
        )
        self.ridge_mode_button_group.addButton(
            self.guided_mode_radio,
            _GUIDED_MODE_BUTTON_ID,
        )
        ridge_mode_layout.addWidget(self.automatic_mode_radio)
        ridge_mode_layout.addWidget(self.guided_mode_radio)
        guided_layout.addWidget(ridge_mode_group)
        self.automatic_ridge_panel = QGroupBox(self.tr("脊线搜索区域"))
        automatic_layout = QVBoxLayout(self.automatic_ridge_panel)
        automatic_form = QFormLayout()
        self.ridge_time_start_spin = _CompactDoubleSpinBox(minimum_decimals=3)
        self.ridge_time_start_spin.setObjectName("ridgeSearchTimeStartUs")
        self.ridge_time_start_spin.setDecimals(9)
        self.ridge_time_start_spin.setRange(-1.0e12, 1.0e12)
        self.ridge_time_start_spin.setSuffix(" μs")
        self.ridge_time_end_spin = _CompactDoubleSpinBox(minimum_decimals=3)
        self.ridge_time_end_spin.setObjectName("ridgeSearchTimeEndUs")
        self.ridge_time_end_spin.setDecimals(9)
        self.ridge_time_end_spin.setRange(-1.0e12, 1.0e12)
        self.ridge_time_end_spin.setSuffix(" μs")
        automatic_form.addRow(
            self.tr("自动脊线提取"),
            self.automatic_ridge_extraction_combo,
        )
        automatic_form.addRow(self.tr("时间起点"), self.ridge_time_start_spin)
        automatic_form.addRow(self.tr("时间终点"), self.ridge_time_end_spin)
        automatic_form.addRow(
            self.tr("搜索频率下限"), self.minimum_frequency_spin
        )
        automatic_form.addRow(
            self.tr("搜索频率上限"), self.maximum_frequency_spin
        )
        automatic_layout.addLayout(automatic_form)
        self.automatic_ridge_status_label = self._notice(
            self.tr("当前 STFT 尚未就绪。")
        )
        automatic_layout.addWidget(self.automatic_ridge_status_label)
        self.extract_automatic_ridge_button = QPushButton(
            self.tr("确认区域并继续分析")
        )
        self.extract_automatic_ridge_button.setObjectName(
            "extractAutomaticRidgeButton"
        )
        automatic_layout.addWidget(self.extract_automatic_ridge_button)
        self.confirm_search_region_button = self.extract_automatic_ridge_button
        guided_layout.addWidget(self.automatic_ridge_panel)
        self.guided_ridge_panel = QGroupBox(self.tr("人工频率范围"))
        guided_panel_layout = QVBoxLayout(self.guided_ridge_panel)
        guided_layout.addWidget(
            self.guided_ridge_panel
        )
        guided_panel_layout.addWidget(
            self._notice(
                self.tr(
                    "默认使用完整搜索频带。可绘制上边界或下边界限制候选谱峰"
                    "搜索区域。人工边界在控制点之间线性连接，并以首末点高度"
                    "延伸至当前分析范围两端。"
                )
            )
        )
        guided_form = QFormLayout()
        self.guided_channel_label = QLabel("—")
        self.guided_channel_label.setObjectName("guidedCurrentChannel")
        self.corridor_state_label = QLabel(self.tr("未设置"))
        self.corridor_state_label.setObjectName("ridgeCorridorState")
        self.upper_boundary_point_count_label = QLabel("0")
        self.upper_boundary_point_count_label.setObjectName(
            "upperBoundaryPointCount"
        )
        self.lower_boundary_point_count_label = QLabel("0")
        self.lower_boundary_point_count_label.setObjectName(
            "lowerBoundaryPointCount"
        )
        # Compatibility alias: this is now the total of independent boundaries.
        self.corridor_point_count_label = QLabel("0")
        self.corridor_point_count_label.setObjectName("ridgeCorridorPointCount")
        self.corridor_point_count_label.hide()
        self.guided_range_label = QLabel("—")
        self.guided_range_label.setObjectName("guidedRange")
        self.guided_range_label.setWordWrap(True)
        self.guided_range_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        guided_form.addRow(self.tr("当前通道"), self.guided_channel_label)
        guided_form.addRow(self.tr("人工范围"), self.corridor_state_label)
        guided_form.addRow(
            self.tr("上边界点"), self.upper_boundary_point_count_label
        )
        guided_form.addRow(
            self.tr("下边界点"), self.lower_boundary_point_count_label
        )
        guided_form.addRow(self.tr("边界控制点范围"), self.guided_range_label)
        guided_panel_layout.addLayout(guided_form)
        self.edit_upper_boundary_button = QPushButton(self.tr("编辑上边界"))
        self.edit_upper_boundary_button.setObjectName("editUpperBoundaryButton")
        self.edit_upper_boundary_button.setToolTip(
            self.tr(
                "从左到右点击控制点；再次点击本按钮、Enter 或运行时完成编辑。"
            )
        )
        guided_panel_layout.addWidget(self.edit_upper_boundary_button)
        self.edit_lower_boundary_button = QPushButton(self.tr("编辑下边界"))
        self.edit_lower_boundary_button.setObjectName("editLowerBoundaryButton")
        self.edit_lower_boundary_button.setToolTip(
            self.edit_upper_boundary_button.toolTip()
        )
        guided_panel_layout.addWidget(self.edit_lower_boundary_button)
        self.draw_corridor_button = self.edit_upper_boundary_button
        edit_buttons = QHBoxLayout()
        self.undo_corridor_button = QPushButton(self.tr("撤销上一点"))
        self.undo_corridor_button.setObjectName("undoLastCorridorPointButton")
        edit_buttons.addWidget(self.undo_corridor_button)
        self.clear_corridor_button = QPushButton(self.tr("清除人工范围"))
        self.clear_corridor_button.setObjectName("clearRidgeCorridorButton")
        edit_buttons.addWidget(self.clear_corridor_button)
        guided_panel_layout.addLayout(edit_buttons)
        self.run_guided_button = QPushButton(self.tr("运行人工范围分析"))
        self.run_guided_button.setObjectName("runGuidedAnalysisButton")
        guided_panel_layout.addWidget(self.run_guided_button)
        self.guided_status_label = self._notice(
            self.tr("人工范围未设置；当前使用完整搜索频带。")
        )
        self.guided_status_label.setObjectName("guidedAnalysisStatus")
        guided_panel_layout.addWidget(self.guided_status_label)
        guided_layout.addStretch(1)
        self.ridge_parameter_scroll = QScrollArea()
        self.ridge_parameter_scroll.setObjectName("ridgeParameterScrollArea")
        self.ridge_parameter_scroll.setWidgetResizable(True)
        self.ridge_parameter_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        guided_page.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.ridge_parameter_scroll.setWidget(guided_page)
        self.parameter_stack.addWidget(self.ridge_parameter_scroll)
        self.guided_ridge_panel.setVisible(False)

        velocity_page = QWidget()
        velocity_layout = QVBoxLayout(velocity_page)
        velocity_layout.addWidget(self._section_title(self.tr("速度参数")))
        velocity_layout.addWidget(
            self._notice(
                self.tr(
                    "当前速度曲线已应用所选修正；详细诊断和中间速度保存在分析记录中。"
                )
            )
        )
        velocity_layout.addWidget(self.analysis_range_panel)
        velocity_form = QFormLayout()
        self.formal_velocity_status_label = QLabel(self.tr("尚无速度结果"))
        self.display_velocity_status_label = QLabel(self.tr("关闭"))
        velocity_form.addRow(
            self.tr("最终速度"), self.formal_velocity_status_label
        )
        self.pre_event_display_check = QCheckBox(self.tr("启用"))
        self.pre_event_display_check.setObjectName("preEventDisplayCheck")
        self.pre_event_display_check.setToolTip(
            self.tr("仅在已设置事件参考时，用指定速度显示事件前平台。")
        )
        velocity_form.addRow(
            self.tr("事件前平台"), self.pre_event_display_check
        )
        velocity_form.addRow(self.tr("真空波长"), self.vacuum_wavelength_spin)
        self.pre_event_display_velocity_spin = QDoubleSpinBox()
        self.pre_event_display_velocity_spin.setObjectName(
            "preEventDisplayVelocityMetersPerSecond"
        )
        self.pre_event_display_velocity_spin.setRange(-1.0e9, 1.0e9)
        self.pre_event_display_velocity_spin.setDecimals(6)
        self.pre_event_display_velocity_spin.setSingleStep(1.0)
        self.pre_event_display_velocity_spin.setSuffix(" m/s")
        self.pre_event_display_velocity_spin.setMaximumWidth(160)
        self.pre_event_display_velocity_spin.setToolTip(
            self.tr(
                "仅用于事件前显示/可选导出平台，不代表正式测得速度。"
            )
        )
        velocity_form.addRow(
            self.tr("事件前平台速度"),
            self.pre_event_display_velocity_spin,
        )
        self.window_material_combo = QComboBox()
        self.window_material_combo.setObjectName("windowMaterialCombo")
        self.window_material_combo.addItem(
            self.tr("LiF"), WindowMaterial.LIF.value
        )
        self.window_material_combo.addItem(
            self.tr("无窗口修正"),
            WindowMaterial.NONE.value,
        )
        self.window_material_combo.setToolTip(
            self.tr(
                "LiF 使用 Rigg 等（2014）针对 [100] LiF、1550 nm PDV 标定的"
                " Eq. (16)。超出标定加载条件的适用性需由实验评估；不会额外乘除"
                "常温折射率。"
            )
        )
        velocity_form.addRow(self.tr("窗口材料"), self.window_material_combo)
        self.measurement_angle_spin = QDoubleSpinBox()
        self.measurement_angle_spin.setObjectName("measurementAngleDegrees")
        self.measurement_angle_spin.setRange(0.0, 89.999999)
        self.measurement_angle_spin.setDecimals(6)
        self.measurement_angle_spin.setSingleStep(0.1)
        self.measurement_angle_spin.setSuffix("°")
        self.measurement_angle_spin.setMaximumWidth(160)
        self.measurement_angle_spin.setToolTip(
            self.tr(
                "PDV 测量视线与被测界面运动法线之间的夹角；0° 表示法向观测。"
                "经过透明窗口时，窗口外部安装角不一定等于界面处实际光线角；"
                "当前软件不会按 Snell 定律静默推断动态窗口内部角度。"
            )
        )
        velocity_form.addRow(self.tr("观测角度"), self.measurement_angle_spin)
        self.lif_parameter_toggle = QPushButton(self.tr("材料参数…"))
        self.lif_parameter_toggle.setObjectName("toggleLifMaterialParameters")
        self.lif_parameter_toggle.setCheckable(True)
        velocity_form.addRow("", self.lif_parameter_toggle)
        self.lif_parameter_panel = QWidget()
        self.lif_parameter_panel.setObjectName("lifMaterialParametersPanel")
        lif_form = QFormLayout(self.lif_parameter_panel)
        lif_form.setContentsMargins(0, 0, 0, 0)
        self.lif_b1_spin = _CompactDoubleSpinBox(minimum_decimals=4)
        self.lif_b1_spin.setObjectName("lifCorrectionB1")
        self.lif_b1_spin.setRange(1.0e-9, 1.0e6)
        self.lif_b1_spin.setDecimals(9)
        self.lif_b1_spin.setSingleStep(0.001)
        self.lif_b1_spin.setToolTip(
            self.tr("Rigg 2014 Eq. (16) 中的无量纲幂律系数 b1。")
        )
        self.lif_b2_spin = _CompactDoubleSpinBox(minimum_decimals=4)
        self.lif_b2_spin.setObjectName("lifCorrectionB2")
        self.lif_b2_spin.setRange(1.0e-9, 1.0e6)
        self.lif_b2_spin.setDecimals(9)
        self.lif_b2_spin.setSingleStep(0.001)
        self.lif_b2_spin.setToolTip(
            self.tr("Rigg 2014 Eq. (16) 中的无量纲幂律指数 b2。")
        )
        self.lif_reference_wavelength_spin = _CompactDoubleSpinBox()
        self.lif_reference_wavelength_spin.setObjectName(
            "lifCorrectionReferenceWavelengthNm"
        )
        self.lif_reference_wavelength_spin.setRange(0.001, 100000.0)
        self.lif_reference_wavelength_spin.setDecimals(6)
        self.lif_reference_wavelength_spin.setSingleStep(1.0)
        self.lif_reference_wavelength_spin.setSuffix(" nm")
        self.lif_reference_wavelength_spin.setToolTip(
            self.tr("该经验模型参数的标定参考真空波长；不替代当前 PDV 真空波长。")
        )
        self.lif_provenance_label = QLabel()
        self.lif_provenance_label.setObjectName("lifCorrectionProvenance")
        self.lif_provenance_label.setWordWrap(True)
        self.restore_lif_defaults_button = QPushButton(self.tr("恢复 LiF 默认值"))
        self.restore_lif_defaults_button.setObjectName("restoreLifDefaultsButton")
        lif_form.addRow(self.tr("系数 b1"), self.lif_b1_spin)
        lif_form.addRow(self.tr("指数 b2"), self.lif_b2_spin)
        lif_form.addRow(
            self.tr("标定参考波长"), self.lif_reference_wavelength_spin
        )
        lif_form.addRow(self.tr("来源"), self.lif_provenance_label)
        lif_form.addRow("", self.restore_lif_defaults_button)
        self.lif_parameter_panel.setVisible(False)
        velocity_layout.addLayout(velocity_form)
        velocity_layout.addWidget(self.lif_parameter_panel)
        self.velocity_correction_warning_label = self._notice("")
        self.velocity_correction_warning_label.setObjectName(
            "velocityCorrectionWarning"
        )
        velocity_layout.addWidget(self.velocity_correction_warning_label)
        velocity_layout.addStretch(1)
        self.velocity_parameter_scroll = QScrollArea()
        self.velocity_parameter_scroll.setObjectName("velocityParameterScrollArea")
        self.velocity_parameter_scroll.setWidgetResizable(True)
        self.velocity_parameter_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        velocity_page.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.velocity_parameter_scroll.setWidget(velocity_page)
        self.parameter_stack.addWidget(self.velocity_parameter_scroll)

        self.parameter_stack.addWidget(self._build_export_parameters_page())

    def _build_export_parameters_page(self) -> QWidget:
        """Build controls for one current, independently analyzed result."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._section_title(self.tr("复核与导出")))
        self.export_availability_label = self._notice(
            self.tr("当前没有可导出的有效正式结果。")
        )
        self.export_availability_label.setObjectName("exportAvailabilityStatus")
        layout.addWidget(self.export_availability_label)
        form = QFormLayout()
        self.export_mode_combo = QComboBox()
        self.export_mode_combo.setObjectName("exportAnalysisModeCombo")
        self.export_mode_combo.setEnabled(False)
        self.export_channel_combo = QComboBox()
        self.export_channel_combo.setObjectName("exportChannelCombo")
        self.export_channel_combo.setEnabled(False)
        form.addRow(self.tr("分析结果"), self.export_mode_combo)
        form.addRow(self.tr("导出通道"), self.export_channel_combo)
        layout.addLayout(form)

        velocity_group = QGroupBox(self.tr("导出速度设置"))
        velocity_form = QFormLayout(velocity_group)
        # Compatibility aliases keep integrations source-compatible while the
        # Review page presents a single read-only summary instead of a second
        # correction editor.
        self.export_window_material_combo = self.window_material_combo
        self.export_measurement_angle_spin = self.measurement_angle_spin

        time_origin_widget = QWidget()
        time_origin_layout = QVBoxLayout(time_origin_widget)
        time_origin_layout.setContentsMargins(0, 0, 0, 0)
        self.export_event_time_origin_radio = QRadioButton(
            self.tr("起跳点设为 0")
        )
        self.export_event_time_origin_radio.setObjectName(
            "exportEventTimeOriginRadio"
        )
        self.export_event_time_origin_radio.setToolTip(
            self.tr(
                "简表使用 time_from_event_s；详细表仍同时保留绝对 time_s。"
            )
        )
        self.export_absolute_time_origin_radio = QRadioButton(
            self.tr("保留实验绝对时间")
        )
        self.export_absolute_time_origin_radio.setObjectName(
            "exportAbsoluteTimeOriginRadio"
        )
        self.export_absolute_time_origin_radio.setToolTip(
            self.tr(
                "简表使用实验绝对 time_s；详细表仍包含 time_from_event_s。"
            )
        )
        self.export_time_origin_group = QButtonGroup(self)
        self.export_time_origin_group.addButton(
            self.export_event_time_origin_radio
        )
        self.export_time_origin_group.addButton(
            self.export_absolute_time_origin_radio
        )
        self.export_event_time_origin_radio.setChecked(True)
        time_origin_layout.addWidget(self.export_event_time_origin_radio)
        time_origin_layout.addWidget(self.export_absolute_time_origin_radio)
        velocity_form.addRow(self.tr("时间零点"), time_origin_widget)

        self.export_velocity_summary_label = QLabel()
        self.export_velocity_summary_label.setObjectName(
            "exportVelocitySummary"
        )
        self.export_velocity_summary_label.setWordWrap(True)
        velocity_form.addRow(
            self.tr("最终导出速度"),
            self.export_velocity_summary_label,
        )
        layout.addWidget(velocity_group)

        self.export_directory_button = QPushButton(self.tr("选择导出目录…"))
        self.export_directory_button.setObjectName("chooseExportDirectoryButton")
        self.export_directory_button.setEnabled(False)
        layout.addWidget(self.export_directory_button)
        self.export_directory_label = self._notice(self.tr("尚未选择导出目录。"))
        self.export_directory_label.setObjectName("exportDirectoryStatus")
        layout.addWidget(self.export_directory_label)
        self.export_include_pre_event_check = QCheckBox(
            self.tr("包含事件前 display-only 平台")
        )
        self.export_include_pre_event_check.setObjectName("includePreEventDisplayRows")
        self.export_include_pre_event_check.setChecked(True)
        self.export_include_pre_event_check.setToolTip(
            self.tr(
                "仅控制 CSV 行范围；不会把显示平台写入正式表观速度，"
                "也不会修改内存中的分析结果。"
            )
        )
        self.export_include_pre_event_check.setEnabled(False)
        layout.addWidget(self.export_include_pre_event_check)
        self.export_description_label = self._notice(
            self.tr("将导出时间—速度数据、详细诊断数据和分析参数记录。")
        )
        self.export_description_label.setObjectName("exportDescription")
        layout.addWidget(self.export_description_label)
        self.export_button = QPushButton(self.tr("导出结果"))
        self.export_button.setObjectName("exportFormalResultsButton")
        self.export_button.setDefault(True)
        self.export_button.setEnabled(False)
        layout.addWidget(self.export_button)
        layout.addStretch(1)
        return page

    def _create_diagnostics_dock(self) -> None:
        self.diagnostics_dock = QDockWidget(self.tr("诊断与数据"), self)
        self.diagnostics_dock.setObjectName("diagnosticsDock")
        self.diagnostics_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.diagnostics_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.diagnostics_tabs = QTabWidget()
        self.diagnostics_tabs.setObjectName("diagnosticsTabs")
        diagnostics_policy = self.diagnostics_tabs.sizePolicy()
        diagnostics_policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        self.diagnostics_tabs.setSizePolicy(diagnostics_policy)

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
        self.resizeDocks(
            [self.diagnostics_dock],
            [_DEFAULT_DIAGNOSTICS_HEIGHT],
            Qt.Orientation.Vertical,
        )

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
        self.action_export.triggered.connect(self._show_review_and_export)
        self.action_quick_analysis.triggered.connect(self.run_quick_analysis)
        self.action_full_automatic.triggered.connect(self.run_automatic_analysis)
        self.action_automatic.triggered.connect(self.run_automatic_analysis)
        self.action_guided.triggered.connect(self._activate_guided_analysis)
        self.action_run_stft.triggered.connect(self.run_stft_analysis)
        self.action_run_ridge.triggered.connect(self.run_staged_automatic_analysis)
        self.action_import_analysis_config.triggered.connect(
            self._choose_analysis_config
        )
        self.action_restore_default_parameters.triggered.connect(
            lambda: self._restore_default_parameters()
        )
        self.action_restore_default_layout.triggered.connect(
            self._reset_default_layout
        )
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
        self.workflow_navigation.itemClicked.connect(self._workflow_item_clicked)
        self.raw_signal_view.channel_selection_changed.connect(
            self._channel_changed
        )
        self.raw_signal_view.cursor_position_changed.connect(
            self._cursor_changed
        )
        self.raw_signal_view.analysis_region_changed.connect(
            self.analysis_range_panel.set_draft_range_s
        )
        self.raw_signal_view.analysis_region_committed.connect(
            self.analysis_range_panel.confirm_range_s
        )
        self.raw_signal_view.analysis_boundary_hovered.connect(
            self._analysis_boundary_hovered
        )
        self.analysis_range_panel.draft_range_changed.connect(
            self.raw_signal_view.set_analysis_region_s
        )
        self.analysis_range_panel.range_confirmed.connect(
            self._analysis_range_confirmed
        )
        self.analysis_range_panel.candidate_detection_requested.connect(
            self.run_event_candidate_detection
        )
        self.analysis_range_panel.event_reference_confirmed.connect(
            self._event_reference_confirmed
        )
        self.analysis_range_panel.event_reference_cleared.connect(
            self._event_reference_cleared
        )
        self.analysis_range_panel.event_time_source_changed.connect(
            self._event_time_source_changed
        )
        self.analysis_range_panel.candidate_adopt_requested.connect(
            self._adopt_event_candidate
        )
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.window_name_combo.currentIndexChanged.connect(
            self._scientific_parameter_changed
        )
        self.automatic_ridge_extraction_combo.currentIndexChanged.connect(
            self._automatic_ridge_extraction_changed
        )
        self.vacuum_wavelength_spin.valueChanged.connect(
            self._scientific_parameter_changed
        )
        self.window_material_combo.currentIndexChanged.connect(
            self._velocity_correction_changed
        )
        self.measurement_angle_spin.valueChanged.connect(
            self._velocity_correction_changed
        )
        self.lif_b1_spin.valueChanged.connect(self._velocity_correction_changed)
        self.lif_b2_spin.valueChanged.connect(self._velocity_correction_changed)
        self.lif_reference_wavelength_spin.valueChanged.connect(
            self._velocity_correction_changed
        )
        self.lif_parameter_toggle.toggled.connect(
            self.lif_parameter_panel.setVisible
        )
        self.restore_lif_defaults_button.clicked.connect(
            self._restore_lif_defaults
        )
        self.export_event_time_origin_radio.toggled.connect(
            self._export_time_origin_changed
        )
        self.export_absolute_time_origin_radio.toggled.connect(
            self._export_time_origin_changed
        )
        self.pre_event_display_velocity_spin.valueChanged.connect(
            self._pre_event_display_velocity_changed
        )
        self.pre_event_display_check.toggled.connect(
            self._display_velocity_toggled
        )
        self.spectrogram_view.colormap_changed.connect(
            self._spectrogram_colormap_changed
        )
        self.spectrogram_view.channel_selection_changed.connect(
            self._guided_channel_changed
        )
        self.spectrogram_view.search_region_changed.connect(
            self._ridge_search_region_graphically_changed
        )
        self.science_tabs.currentChanged.connect(self._science_tab_changed)
        self.ridge_view.search_region_changed.connect(
            self._ridge_search_region_graphically_changed
        )
        corridor_controller = self.spectrogram_view.corridor_controller
        corridor_controller.constraint_changed.connect(
            self._ridge_constraint_changed
        )
        corridor_controller.constraint_cleared.connect(
            self._ridge_constraint_cleared
        )
        corridor_controller.drawing_state_changed.connect(
            self._corridor_drawing_state_changed
        )
        corridor_controller.message.connect(self.guided_status_label.setText)
        self.ridge_mode_button_group.idToggled.connect(
            self._ridge_mode_button_toggled
        )
        self.automatic_mode_radio.clicked.connect(
            lambda _checked=False: self._ridge_mode_clicked(
                RidgeExtractionMode.AUTOMATIC
            )
        )
        self.guided_mode_radio.clicked.connect(
            lambda _checked=False: self._ridge_mode_clicked(
                RidgeExtractionMode.GUIDED
            )
        )
        self.edit_upper_boundary_button.clicked.connect(
            self._edit_upper_boundary
        )
        self.edit_lower_boundary_button.clicked.connect(
            self._edit_lower_boundary
        )
        self.undo_corridor_button.clicked.connect(self._undo_corridor_point)
        self.clear_corridor_button.clicked.connect(self._clear_current_corridor)
        self.run_guided_button.clicked.connect(self.run_guided_analysis)
        self.extract_automatic_ridge_button.clicked.connect(
            self.confirm_search_region_and_continue
        )
        self.action_undo_corridor.triggered.connect(self._undo_corridor_point)
        self.action_backspace_corridor.triggered.connect(
            self._undo_corridor_point
        )
        self.action_cancel_corridor_drawing.triggered.connect(
            self._cancel_corridor_drawing
        )
        self.action_finish_corridor_drawing.triggered.connect(
            self._finish_corridor_drawing
        )
        for control in (
            self.window_length_spin,
            self.overlap_spin,
            self.nfft_spin,
        ):
            control.valueChanged.connect(self._scientific_parameter_changed)
        for region_control in (
            self.ridge_time_start_spin,
            self.ridge_time_end_spin,
            self.minimum_frequency_spin,
            self.maximum_frequency_spin,
        ):
            region_control.valueChanged.connect(
                self._ridge_search_region_numeric_changed
            )
        self.restore_preset_button.clicked.connect(self._restore_selected_preset)
        self.advanced_parameters_button.clicked.connect(
            self._show_advanced_parameters
        )
        self.compute_stft_button.clicked.connect(self.run_stft_analysis)
        self.export_mode_combo.currentIndexChanged.connect(
            self._export_mode_changed
        )
        self.export_channel_combo.currentIndexChanged.connect(
            self._export_channel_changed
        )
        self.export_directory_button.clicked.connect(self._choose_export_directory)
        self.export_button.clicked.connect(self._export_current_result)
        self._analysis_adapter.started.connect(self._analysis_started)
        self._analysis_adapter.finished.connect(self._analysis_finished)
        self._analysis_adapter.failed.connect(self._analysis_failed)
        self._analysis_adapter.busy_changed.connect(self._busy_changed)

    def _spectrogram_colormap_changed(self, name: str) -> None:
        self._set_spectrogram_colormap(name, persist=True)

    def _science_tab_changed(self, _index: int) -> None:
        controller = self.spectrogram_view.corridor_controller
        if controller.drawing and self.science_tabs.currentWidget() is not (
            self.spectrogram_view
        ):
            controller.cancel_drawing()
            self._sync_guided_panel()

    def _set_spectrogram_colormap(
        self,
        name: str,
        *,
        persist: bool,
    ) -> None:
        normalized = (
            self._display_preferences.set_spectrogram_colormap(name)
            if persist
            else name
        )
        self.spectrogram_view.set_colormap(normalized)
        self.ridge_view.set_colormap(normalized)

    def _analysis_boundary_hovered(self, hovered: bool) -> None:
        message = self.tr("拖动以调整分析范围")
        if hovered:
            self.statusBar().showMessage(message)
        elif self.statusBar().currentMessage() == message:
            self.statusBar().clearMessage()

    @staticmethod
    def _as_byte_array(value: object) -> QByteArray | None:
        if isinstance(value, QByteArray):
            return value
        if isinstance(value, bytes):
            return QByteArray(value)
        return None

    def _restore_layout_settings(self) -> None:
        """Restore stable layout keys, falling back on each invalid value."""
        geometry = self._as_byte_array(
            self._settings.value(_GEOMETRY_SETTINGS_KEY)
        )
        if geometry is not None and not self.restoreGeometry(geometry):
            self.restoreGeometry(self._default_geometry)

        window_state = self._as_byte_array(
            self._settings.value(_WINDOW_STATE_SETTINGS_KEY)
        )
        if window_state is not None and not self.restoreState(
            window_state,
            _LAYOUT_STATE_VERSION,
        ):
            self.restoreState(
                self._default_window_state,
                _LAYOUT_STATE_VERSION,
            )

        splitter_state = self._as_byte_array(
            self._settings.value(_SPLITTER_STATE_SETTINGS_KEY)
        )
        if splitter_state is not None and not self.workspace_splitter.restoreState(
            splitter_state
        ):
            self.workspace_splitter.setSizes(list(_DEFAULT_WORKSPACE_SIZES))

        dock_height = self._settings.value(_DIAGNOSTICS_HEIGHT_SETTINGS_KEY)
        if isinstance(dock_height, int) and dock_height > 0:
            self.resizeDocks(
                [self.diagnostics_dock],
                [dock_height],
                Qt.Orientation.Vertical,
            )

    def _save_layout_settings(self) -> None:
        self._settings.setValue(_GEOMETRY_SETTINGS_KEY, self.saveGeometry())
        self._settings.setValue(
            _WINDOW_STATE_SETTINGS_KEY,
            self.saveState(_LAYOUT_STATE_VERSION),
        )
        self._settings.setValue(
            _SPLITTER_STATE_SETTINGS_KEY,
            self.workspace_splitter.saveState(),
        )
        self._settings.setValue(
            _DIAGNOSTICS_HEIGHT_SETTINGS_KEY,
            self.diagnostics_dock.height(),
        )
        self._settings.sync()

    def _reset_default_layout(self) -> None:
        """Restore the initial geometry, dock placement, and splitter sizes."""
        self.restoreGeometry(self._default_geometry)
        self.restoreState(
            self._default_window_state,
            _LAYOUT_STATE_VERSION,
        )
        self.diagnostics_dock.setFloating(False)
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea,
            self.diagnostics_dock,
        )
        self.diagnostics_dock.show()
        self.workspace_splitter.setSizes(list(_DEFAULT_WORKSPACE_SIZES))
        self.resizeDocks(
            [self.diagnostics_dock],
            [_DEFAULT_DIAGNOSTICS_HEIGHT],
            Qt.Orientation.Vertical,
        )
        self._save_layout_settings()
        self.statusBar().showMessage(self.tr("已恢复默认布局。"), 3000)

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
            str(self._repository_root / "configs"),
            self.tr("TOML 配置 (*.toml);;所有文件 (*)"),
        )
        if not selected_path:
            return
        try:
            configuration = load_workflow_config(
                Path(selected_path),
                repository_root=self._repository_root,
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

    def _restore_default_parameters(self, *, initial: bool = False) -> None:
        try:
            repository = PresetRepository.load_default(
                repository_root=self._repository_root
            )
            self.set_analysis_configuration(repository.configuration)
        except Exception as exc:
            self._parameters_valid = False
            self._parameter_error = self.tr(
                "无法加载内置默认科学参数：{message}"
            ).format(message=exc)
            self.analysis_status_label.setText(self._parameter_error)
            self._append_log(
                self.tr("默认参数加载失败：{error_type}: {message}").format(
                    error_type=type(exc).__name__,
                    message=exc,
                )
            )
            if not initial:
                QMessageBox.critical(
                    self,
                    self.tr("默认参数加载失败"),
                    self._parameter_error,
                )
            return
        if not initial:
            self._append_log(self.tr("已恢复内置默认分析参数。"))

    def _default_analysis_range(
        self,
        data_start_s: float,
        data_end_s: float,
    ) -> tuple[float, float]:
        """Production STFT always starts from the complete imported record."""
        return data_start_s, data_end_s

    def _set_parameter_controls(
        self,
        parameters: AnalysisRunParameters,
        *,
        editable: bool,
    ) -> None:
        previous_update_state = self._updating_parameter_controls
        self._updating_parameter_controls = True
        blockers = [
            QSignalBlocker(control)
            for control in (
                self.vacuum_wavelength_spin,
                self.window_name_combo,
                self.automatic_ridge_extraction_combo,
                self.window_length_spin,
                self.overlap_spin,
                self.nfft_spin,
                self.minimum_frequency_spin,
                self.maximum_frequency_spin,
            )
        ]
        self.vacuum_wavelength_spin.setValue(
            parameters.vacuum_wavelength_m * 1e9
        )
        window_index = self.window_name_combo.findData(parameters.window_name)
        if window_index < 0:
            raise ValueError(
                f"Unsupported GUI STFT window: {parameters.window_name!r}."
            )
        self.window_name_combo.setCurrentIndex(window_index)
        run_configuration = self._session.run_configuration
        if run_configuration is not None:
            extraction_index = self.automatic_ridge_extraction_combo.findData(
                run_configuration.automatic_ridge_selection_config.mode.value
            )
            if extraction_index >= 0:
                self.automatic_ridge_extraction_combo.setCurrentIndex(
                    extraction_index
                )
        self.window_length_spin.setValue(parameters.window_length_samples)
        self.overlap_spin.setValue(parameters.overlap_samples)
        self.nfft_spin.setValue(parameters.nfft)
        self._set_search_spin_limits()
        self.minimum_frequency_spin.setValue(
            parameters.minimum_frequency_hz * 1e-9
        )
        self.maximum_frequency_spin.setValue(
            parameters.maximum_frequency_hz * 1e-9
        )
        self.hop_label.setText(
            self.tr("{value} 点").format(value=parameters.hop_samples)
        )
        self._set_parameter_editability(editable)
        del blockers
        self._updating_parameter_controls = previous_update_state

    def _set_parameter_editability(self, editable: bool) -> None:
        for control in (
            self.vacuum_wavelength_spin,
            self.window_length_spin,
            self.overlap_spin,
            self.nfft_spin,
            self.ridge_time_start_spin,
            self.ridge_time_end_spin,
            self.minimum_frequency_spin,
            self.maximum_frequency_spin,
            self.pre_event_display_velocity_spin,
        ):
            control.setReadOnly(not editable)
        self.pre_event_display_check.setEnabled(editable)
        self.window_name_combo.setEnabled(editable)
        self.automatic_ridge_extraction_combo.setEnabled(editable)
        self.window_material_combo.setEnabled(editable)
        self.measurement_angle_spin.setEnabled(editable)
        self.lif_b1_spin.setReadOnly(not editable)
        self.lif_b2_spin.setReadOnly(not editable)
        self.lif_reference_wavelength_spin.setReadOnly(not editable)
        self.restore_lif_defaults_button.setEnabled(editable)
        self.export_event_time_origin_radio.setEnabled(editable)
        self.export_absolute_time_origin_radio.setEnabled(editable)

    def _scientific_parameter_changed(self, _value: float | int) -> None:
        """Resolve the visible draft as per-session overrides of its base preset."""
        if self._updating_parameter_controls:
            return
        self._set_search_spin_limits()
        self.hop_label.setText(
            self.tr("{value} 点").format(
                value=self.window_length_spin.value() - self.overlap_spin.value()
            )
        )
        configuration = self._session.run_configuration
        if configuration is None:
            return
        overrides = AnalysisParameterOverrides(
            vacuum_wavelength_m=self.vacuum_wavelength_spin.value() * 1e-9,
            window_name=self.window_name_combo.currentData(),
            window_length_samples=self.window_length_spin.value(),
            overlap_samples=self.overlap_spin.value(),
            nfft=self.nfft_spin.value(),
            minimum_frequency_hz=configuration.parameters.minimum_frequency_hz,
            maximum_frequency_hz=configuration.parameters.maximum_frequency_hz,
        )
        stft_was_valid = self._session.stft_valid
        try:
            changed = self._session.set_analysis_overrides(overrides)
        except (TypeError, ValueError) as exc:
            self._session.invalidate_results()
            self._parameters_valid = False
            self._parameter_error = self.tr("参数无效：{message}").format(
                message=exc
            )
            self._show_custom_profile_state(configuration.base_profile)
            self._set_parameter_validation_state(False, self._parameter_error)
            changed = True
        else:
            self._constrain_search_band_to_records()
            updated = self._session.run_configuration
            if updated is None:
                return
            self._sync_profile_combo_for_parameters(updated.parameters)
            self._validate_current_parameters()
            self._sync_velocity_correction_warning()
        if not changed:
            self._apply_state()
            return
        if stft_was_valid and self._session.stft_valid:
            self._clear_downstream_presentation(
                self.tr("脊线参数已变化；STFT 保持有效，请重新提取脊线。")
            )
        else:
            self._clear_result_presentation(
                self.tr("STFT 参数已变化；请重新计算时频图。")
            )
        self._sync_workflow_state_after_invalidation()

    def _usable_stft_frequency_max_hz(self, nfft: int | None = None) -> float | None:
        """Return a mHz GUI limit no greater than the common upper rFFT bin."""
        if not self._session.records:
            return None
        active_nfft = self.nfft_spin.value() if nfft is None else nfft
        if active_nfft <= 0:
            return None
        return float(
            math.floor(
                min(
                    record.sample_rate_hz * (active_nfft // 2) / active_nfft
                    for record in self._session.records.values()
                )
                * 1.0e3
            )
            / 1.0e3
        )

    def _set_search_spin_limits(self) -> None:
        usable_hz = self._usable_stft_frequency_max_hz()
        maximum_ghz = 1_000_000.0 if usable_hz is None else usable_hz * 1e-9
        blockers = [
            QSignalBlocker(self.minimum_frequency_spin),
            QSignalBlocker(self.maximum_frequency_spin),
        ]
        self.minimum_frequency_spin.setMaximum(maximum_ghz)
        self.maximum_frequency_spin.setMaximum(maximum_ghz)
        del blockers

    def _constrain_search_band_to_records(self) -> None:
        """Clamp a preset band to the common valid frequency grid, in SI Hz."""
        configuration = self._session.run_configuration
        if configuration is None:
            self._set_search_spin_limits()
            return
        parameters = configuration.parameters
        usable_hz = self._usable_stft_frequency_max_hz(parameters.nfft)
        if usable_hz is None:
            self._set_search_spin_limits()
            return
        upper_hz = min(parameters.maximum_frequency_hz, usable_hz)
        lower_hz = parameters.minimum_frequency_hz
        if lower_hz >= upper_hz:
            grid_step_hz = max(
                1.0e-3,
                min(
                    record.sample_rate_hz / parameters.nfft
                    for record in self._session.records.values()
                ),
            )
            lower_hz = max(0.0, upper_hz - grid_step_hz)
        if (
            lower_hz != parameters.minimum_frequency_hz
            or upper_hz != parameters.maximum_frequency_hz
        ):
            self._session.set_analysis_overrides(
                replace(
                    parameters.overrides,
                    minimum_frequency_hz=lower_hz,
                    maximum_frequency_hz=upper_hz,
                )
            )
        self._set_search_spin_limits()

    def _search_band_dragged(self, minimum_hz: float, maximum_hz: float) -> None:
        """Compatibility entry for frequency-only drag integrations."""
        region = self._session.ridge_search_region
        if region is None:
            return
        self._apply_ridge_search_region(
            RidgeSearchRegion(
                region.time_start_s,
                region.time_end_s,
                minimum_hz,
                maximum_hz,
            )
        )

    def _ridge_search_region_graphically_changed(
        self,
        time_start_s: float,
        time_end_s: float,
        frequency_min_hz: float,
        frequency_max_hz: float,
    ) -> None:
        """Commit one grid-snapped ROI edit in physical coordinates."""
        try:
            region = RidgeSearchRegion(
                time_start_s,
                time_end_s,
                frequency_min_hz,
                frequency_max_hz,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            self._sync_ridge_search_region_controls()
            return
        self._apply_ridge_search_region(region)

    def _ridge_search_region_numeric_changed(self, _value: float) -> None:
        if self._updating_parameter_controls or self._session.ridge_search_region is None:
            return
        try:
            region = RidgeSearchRegion(
                self.ridge_time_start_spin.value() * 1.0e-6,
                self.ridge_time_end_spin.value() * 1.0e-6,
                self.minimum_frequency_spin.value() * 1.0e9,
                self.maximum_frequency_spin.value() * 1.0e9,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            self._sync_ridge_search_region_controls()
            return
        self._apply_ridge_search_region(region)

    def _apply_ridge_search_region(self, region: RidgeSearchRegion) -> None:
        try:
            changed = self._session.set_ridge_search_region(region)
        except (RuntimeError, ValueError) as exc:
            self.statusBar().showMessage(str(exc), 5000)
            self._sync_ridge_search_region_controls()
            return
        self._sync_ridge_search_region_controls()
        if not changed:
            return
        self._quick_analysis_waiting = True
        self._clear_downstream_presentation(
            self.tr("脊线搜索区域已变化；STFT 保持有效，请确认区域后继续。")
        )
        self._sync_workflow_state_after_invalidation()

    def _sync_ridge_search_region_controls(self) -> None:
        region = self._session.ridge_search_region
        if region is None:
            return
        blockers = [
            QSignalBlocker(self.ridge_time_start_spin),
            QSignalBlocker(self.ridge_time_end_spin),
            QSignalBlocker(self.minimum_frequency_spin),
            QSignalBlocker(self.maximum_frequency_spin),
        ]
        self.ridge_time_start_spin.setValue(region.time_start_s * 1.0e6)
        self.ridge_time_end_spin.setValue(region.time_end_s * 1.0e6)
        self.minimum_frequency_spin.setValue(region.frequency_min_hz * 1.0e-9)
        self.maximum_frequency_spin.setValue(region.frequency_max_hz * 1.0e-9)
        del blockers
        self._sync_scientific_view_configuration()

    def _velocity_correction_changed(self, _value: float | int) -> None:
        """Apply the velocity-step correction controls to stored apparent velocity."""
        self._apply_velocity_correction_controls(
            self.window_material_combo,
            self.measurement_angle_spin,
        )

    def _restore_lif_defaults(self) -> None:
        blockers = [
            QSignalBlocker(self.lif_b1_spin),
            QSignalBlocker(self.lif_b2_spin),
            QSignalBlocker(self.lif_reference_wavelength_spin),
        ]
        self.lif_b1_spin.setValue(LIF_RIGG_2014_1550NM.b1)
        self.lif_b2_spin.setValue(LIF_RIGG_2014_1550NM.b2)
        self.lif_reference_wavelength_spin.setValue(
            LIF_RIGG_2014_1550NM.reference_wavelength_m * 1e9
        )
        del blockers
        self._velocity_correction_changed(0)

    def _apply_velocity_correction_controls(
        self,
        material_combo: QComboBox,
        angle_spin: QDoubleSpinBox,
    ) -> None:
        """Synchronize both pages and refresh correction-only result fields."""
        if self._updating_parameter_controls:
            return
        material_value = material_combo.currentData()
        if not isinstance(material_value, str):
            return
        try:
            material = WindowMaterial(material_value)
            lif_model = LiFWindowCorrectionModel(
                b1=self.lif_b1_spin.value(),
                b2=self.lif_b2_spin.value(),
                reference_wavelength_m=(
                    self.lif_reference_wavelength_spin.value() * 1e-9
                ),
            )
            if (
                lif_model.b1 == LIF_RIGG_2014_1550NM.b1
                and lif_model.b2 == LIF_RIGG_2014_1550NM.b2
                and math.isclose(
                    lif_model.reference_wavelength_m,
                    LIF_RIGG_2014_1550NM.reference_wavelength_m,
                    rel_tol=0.0,
                    abs_tol=1.0e-18,
                )
            ):
                lif_model = LIF_RIGG_2014_1550NM
            correction = VelocityCorrectionConfig(
                window_material=material,
                measurement_angle_rad=math.radians(angle_spin.value()),
                lif_model=lif_model,
            )
            changed = self._session.set_velocity_correction_config(correction)
        except (TypeError, ValueError) as exc:
            self.analysis_status_label.setText(str(exc))
            return
        self._sync_velocity_correction_controls()
        self._sync_velocity_correction_warning()
        if not changed:
            return
        if self._session.any_formal_results_available:
            self._refresh_result_source_views(preserve_view=True)
            self.formal_velocity_status_label.setText(
                self.tr("当前正式结果有效（仅后处理已刷新）")
            )
        message = self.tr(
            "速度修正参数已更新；STFT、脊线、事件检测与质量判定保持不变。"
        )
        self.analysis_status_label.setText(message)
        self._append_log(message)
        self._refresh_export_controls()

    def _sync_velocity_correction_controls(self) -> None:
        """Mirror the one session correction config into its single editor."""
        configuration = self._session.run_configuration
        if configuration is None:
            self.export_velocity_summary_label.clear()
            return
        correction = configuration.velocity_correction_config
        blockers = [
            QSignalBlocker(self.window_material_combo),
            QSignalBlocker(self.measurement_angle_spin),
            QSignalBlocker(self.lif_b1_spin),
            QSignalBlocker(self.lif_b2_spin),
            QSignalBlocker(self.lif_reference_wavelength_spin),
        ]
        index = self.window_material_combo.findData(correction.window_material.value)
        if index < 0:
            raise ValueError("Unsupported configured window material.")
        self.window_material_combo.setCurrentIndex(index)
        angle_degrees = math.degrees(correction.measurement_angle_rad)
        self.measurement_angle_spin.setValue(angle_degrees)
        self.lif_b1_spin.setValue(correction.lif_model.b1)
        self.lif_b2_spin.setValue(correction.lif_model.b2)
        self.lif_reference_wavelength_spin.setValue(
            correction.lif_model.reference_wavelength_m * 1e9
        )
        del blockers
        self.lif_provenance_label.setText(
            self.tr("Custom LiF · 用户参数")
            if correction.lif_model != LIF_RIGG_2014_1550NM
            else self.tr(
                "Rigg et al. (2014), Eq. (16) · DOI 10.1063/1.4890714"
            )
        )
        self._sync_export_velocity_summary()

    def _sync_export_velocity_summary(self) -> None:
        configuration = self._session.run_configuration
        if configuration is None:
            self.export_velocity_summary_label.clear()
            return
        correction = configuration.velocity_correction_config
        angle_degrees = math.degrees(correction.measurement_angle_rad)
        if correction.window_material is WindowMaterial.LIF:
            summary = self.tr(
                "{material} · {angle:.6g}°；最终导出连续绘图速度。"
            ).format(
                material=(
                    self.tr("Custom LiF")
                    if correction.lif_model != LIF_RIGG_2014_1550NM
                    else self.tr("LiF")
                ),
                angle=angle_degrees,
            )
        elif correction.measurement_angle_rad > 0.0:
            summary = self.tr(
                "最终绘图速度；连续 working 结果已应用角度修正"
                "（无窗口修正，观测角 {angle:.6g}°）。"
            ).format(angle=angle_degrees)
        else:
            summary = self.tr(
                "最终绘图速度；连续 working 结果未应用窗口或角度修正。"
            )
        self.export_velocity_summary_label.setText(summary)

    def _sync_export_time_origin_controls(self) -> None:
        if (
            self._session.event_reference_time_s is None
            and self._session.export_time_origin is ExportTimeOrigin.EVENT
        ):
            self._session.set_export_time_origin(ExportTimeOrigin.ABSOLUTE)
        blockers = [
            QSignalBlocker(self.export_event_time_origin_radio),
            QSignalBlocker(self.export_absolute_time_origin_radio),
        ]
        is_event = self._session.export_time_origin is ExportTimeOrigin.EVENT
        self.export_event_time_origin_radio.setChecked(is_event)
        self.export_absolute_time_origin_radio.setChecked(not is_event)
        del blockers
        self.export_event_time_origin_radio.setEnabled(
            self._session.event_reference_time_s is not None
        )
        self.export_event_time_origin_radio.setToolTip(
            self.tr("需要先设置事件参考。")
            if self._session.event_reference_time_s is None
            else self.tr(
                "简表使用 time_from_event_s；详细表仍同时保留绝对 time_s。"
            )
        )
        self.velocity_view.set_time_origin(self._session.export_time_origin)

    def _export_time_origin_changed(self, checked: bool) -> None:
        if not checked or self._updating_parameter_controls:
            return
        time_origin = (
            ExportTimeOrigin.EVENT
            if self.export_event_time_origin_radio.isChecked()
            else ExportTimeOrigin.ABSOLUTE
        )
        if (
            time_origin is ExportTimeOrigin.EVENT
            and self._session.event_reference_time_s is None
        ):
            time_origin = ExportTimeOrigin.ABSOLUTE
        self._session.set_export_time_origin(time_origin)
        self._sync_export_time_origin_controls()
        self._refresh_export_controls()

    def _sync_velocity_correction_warning(self) -> None:
        """Expose exact-wavelength and oblique-window applicability limits."""
        configuration = self._session.run_configuration
        if configuration is None:
            self.velocity_correction_warning_label.clear()
            return
        correction = configuration.velocity_correction_config
        if correction.window_material is WindowMaterial.NONE:
            self.velocity_correction_warning_label.setText(
                self.tr("窗口修正已关闭；角度投影修正仍按当前角度执行。")
            )
            return
        wavelength_nm = configuration.vacuum_wavelength_m * 1e9
        reference_wavelength_nm = correction.lif_model.reference_wavelength_m * 1e9
        if not math.isclose(
            configuration.vacuum_wavelength_m,
            correction.lif_model.reference_wavelength_m,
            rel_tol=0.0,
            abs_tol=1.0e-18,
        ):
            self.velocity_correction_warning_label.setText(
                self.tr(
                    "警告：当前 LiF 参数参考 {reference:.12g} nm；当前 PDV 波长为 "
                    "{wavelength:.12g} nm。"
                ).format(
                    reference=reference_wavelength_nm,
                    wavelength=wavelength_nm,
                )
            )
            return
        if correction.measurement_angle_rad > 0.0:
            self.velocity_correction_warning_label.setText(
                self.tr(
                    "非零角度与 LiF 修正按可分离工程近似组合，不代表完整斜入射"
                    "动态折射模型。"
                )
            )
            return
        self.velocity_correction_warning_label.setText(
            self.tr("LiF [100] / {reference:.12g} nm；观测角 0°。").format(
                reference=reference_wavelength_nm
            )
        )

    def _automatic_ridge_extraction_changed(self, index: int) -> None:
        """Invalidate ridge and downstream products when selection mode changes."""
        if self._updating_parameter_controls:
            return
        mode_value = self.automatic_ridge_extraction_combo.itemData(index)
        if not isinstance(mode_value, str):
            return
        try:
            mode = AutomaticRidgeExtractionMode(mode_value)
        except ValueError:
            return
        if not self._session.set_automatic_ridge_extraction_mode(mode):
            return
        self._clear_downstream_presentation(
            self.tr("自动脊线提取方式已变化；请重新提取脊线。")
        )
        self._sync_workflow_state_after_invalidation()

    def _validate_current_parameters(self) -> bool:
        configuration = self._session.run_configuration
        if configuration is None:
            self._parameters_valid = False
            self._parameter_error = self.tr("科学参数尚未加载。")
            self._set_parameter_validation_state(False, self._parameter_error)
            return False
        try:
            if self._session.records:
                configuration.parameters.validate_for_records(
                    self._session.records
                )
        except (TypeError, ValueError) as exc:
            self._parameters_valid = False
            self._parameter_error = self.tr("参数无效：{message}").format(
                message=exc
            )
            self._set_parameter_validation_state(False, self._parameter_error)
            return False
        self._parameters_valid = True
        self._parameter_error = ""
        self._set_parameter_validation_state(True, "")
        return True

    def _set_parameter_validation_state(self, valid: bool, message: str) -> None:
        self.parameter_error_label.setText(message)
        self.parameter_error_label.setVisible(not valid)
        style = "" if valid else "border: 1px solid #c62828;"
        for control in (
            self.vacuum_wavelength_spin,
            self.window_name_combo,
            self.automatic_ridge_extraction_combo,
            self.window_length_spin,
            self.overlap_spin,
            self.nfft_spin,
            self.minimum_frequency_spin,
            self.maximum_frequency_spin,
        ):
            control.setStyleSheet(style)

    def _show_custom_profile_state(self, base_profile: AnalysisProfile) -> None:
        blocker = QSignalBlocker(self.profile_combo)
        custom_index = self.profile_combo.findData(CUSTOM_PRESET_ID)
        label = self.tr("自定义（基于 {name}）").format(
            name=self._profile_display_name(base_profile)
        )
        if custom_index < 0:
            self.profile_combo.addItem(label, CUSTOM_PRESET_ID)
            custom_index = self.profile_combo.count() - 1
        else:
            self.profile_combo.setItemText(custom_index, label)
        self.profile_combo.setCurrentIndex(custom_index)
        del blocker

    def _sync_profile_combo_for_parameters(
        self,
        parameters: AnalysisRunParameters,
    ) -> None:
        if parameters.is_custom:
            self._show_custom_profile_state(parameters.base_profile)
            return
        blocker = QSignalBlocker(self.profile_combo)
        custom_index = self.profile_combo.findData(CUSTOM_PRESET_ID)
        if custom_index >= 0:
            self.profile_combo.removeItem(custom_index)
        profile_index = self.profile_combo.findData(parameters.base_profile)
        if profile_index >= 0:
            self.profile_combo.setCurrentIndex(profile_index)
        del blocker

    def _restore_selected_preset(self) -> None:
        configuration = self._session.run_configuration
        if configuration is None:
            return
        previous_generation = self._session.generation_id
        self._session.set_profile(configuration.base_profile)
        self._constrain_search_band_to_records()
        restored = self._session.run_configuration
        if restored is None:
            return
        self._sync_profile_combo_for_parameters(restored.parameters)
        self._set_parameter_controls(restored.parameters, editable=True)
        self._validate_current_parameters()
        if self._session.generation_id == previous_generation:
            self._apply_state()
            return
        self._clear_result_presentation(
            self.tr("已恢复预设值；请重新运行自动分析。")
        )
        self._sync_workflow_state_after_invalidation()

    def _show_advanced_parameters(self) -> None:
        run_configuration = self._session.run_configuration
        workflow_configuration = self._session.workflow_configuration
        if run_configuration is None or workflow_configuration is None:
            return
        dialog = AdvancedParametersDialog(
            run_configuration,
            workflow_configuration,
            self,
        )
        dialog.exec()

    def _analysis_range_confirmed(
        self,
        start_time_s: float,
        end_time_s: float,
    ) -> None:
        previous_range = self._session.analysis_range
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
        if self._session.analysis_range == previous_range:
            return
        self._workflow_state = WorkflowState.RANGE_DEFINED
        self._clear_result_presentation(
            self.tr("分析范围已变化；请重新运行自动分析。")
        )
        self._sync_event_reference_panel()
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

    def _event_reference_confirmed(self, value_s: float) -> None:
        self._set_event_reference(
            value_s,
            source="manual",
            source_text=self.tr("用户确认"),
        )

    def _event_reference_cleared(self) -> None:
        if self._session.clear_event_reference():
            self._refresh_event_reference_results()
            self._append_log(self.tr("事件参考已清除；使用实验绝对时间。"))
        self._sync_event_reference_panel()

    def _event_time_source_changed(self, source: str) -> None:
        if source == EventTimeSource.UNSET.value:
            self._event_reference_cleared()
            return
        if source != EventTimeSource.AUTOMATIC.value:
            return
        candidate = next(
            (
                (channel_name, value)
                for channel_name, value in (
                    self._session.automatic_event_reference_times_s.items()
                )
                if value is not None
            ),
            None,
        )
        if candidate is None:
            self._event_reference_cleared()
            self.analysis_range_panel.show_event_reference_unset(
                self.tr("尚无可采用的自动候选；可保持不使用或改为手动。")
            )
            return
        self._adopt_event_candidate(candidate[0], candidate[1])

    def _adopt_event_candidate(self, channel_name: str, value_s: float) -> None:
        self._set_event_reference(
            value_s,
            source=f"user_adopted:automatic_primary:{channel_name}",
            source_text=self.tr("检测候选（用户显式采用）"),
        )

    def _set_event_reference(
        self,
        value_s: float,
        *,
        source: str,
        source_text: str,
    ) -> None:
        try:
            changed = self._session.set_event_reference_time_s(
                value_s,
                source=source,
            )
        except (RuntimeError, ValueError) as exc:
            cleared = self._session.clear_event_reference()
            if cleared:
                self._refresh_event_reference_results()
            self.analysis_range_panel.show_event_reference_unset(str(exc))
            self.analysis_status_label.setText(str(exc))
            return
        self.analysis_range_panel.show_event_reference(
            value_s,
            source_text=source_text,
        )
        self.analysis_range_panel.set_event_time_source(
            self._session.event_time_source.value
        )
        if changed:
            self._refresh_event_reference_results()
        self._append_log(
            self.tr(
                "事件参考时刻已确认：{value:.9f} μs；仅更新显示/复核语义。"
            ).format(value=value_s * 1e6)
        )

    def _refresh_event_reference_results(self) -> None:
        if self._session.any_formal_results_available:
            self._refresh_result_source_views(preserve_view=True)
            self.analysis_status_label.setText(
                self.tr("事件参考已刷新；正式表观速度与 STFT 保持不变。")
            )
        self._refresh_export_controls()

    def _sync_event_reference_panel(self) -> None:
        if self.analysis_range_panel.bounds_s is None:
            return
        self.analysis_range_panel.set_event_time_source(
            self._session.event_time_source.value
        )
        reference = self._session.event_reference_time_s
        if reference is None:
            rejected = self._session.rejected_event_reference_time_s
            if rejected is None:
                reason = self.tr(
                    "事件参考未设置；速度使用实验绝对时间，自动候选仅供选择。"
                )
            else:
                reason = self.tr(
                    "原事件参考 {value:.9f} μs 不在当前数据或分析范围内，"
                    "已设为未设置；不会生成显示平台。"
                ).format(value=rejected * 1e6)
            self.analysis_range_panel.show_event_reference_unset(reason)
            return
        source = self._session.event_reference_source
        if self._session.event_time_source is EventTimeSource.AUTOMATIC:
            channel_name = next(iter(self._session.records), "pdv_channel_1")
            automatic_source = self._session.resolved_event_source(channel_name)
            source_text = (
                self.tr("自动检测（低可信候选回退）")
                if automatic_source is not None
                and "low_confidence_fallback" in automatic_source
                else self.tr("自动检测（CH1 共享）")
            )
        elif source == "configuration":
            source_text = self.tr("当前配置")
        elif source is not None and source.startswith(
            ("detected_candidate:", "user_adopted:")
        ):
            source_text = self.tr("检测候选（用户显式采用）")
        else:
            source_text = self.tr("用户确认")
        self.analysis_range_panel.show_event_reference(
            reference,
            source_text=source_text,
        )

    def _profile_changed(self, index: int) -> None:
        selected = self.profile_combo.itemData(index)
        if isinstance(selected, AnalysisProfile):
            previous_generation = self._session.generation_id
            try:
                self._session.set_profile(selected)
                self._constrain_search_band_to_records()
            except ValueError as exc:
                self.analysis_status_label.setText(str(exc))
                return
            configuration = self._session.run_configuration
            if configuration is None:
                return
            self._sync_profile_combo_for_parameters(configuration.parameters)
            self._set_parameter_controls(configuration.parameters, editable=True)
            self._validate_current_parameters()
            if self._session.generation_id == previous_generation:
                self._apply_state()
                return
        elif selected == CUSTOM_PRESET_ID:
            return
        else:
            return
        self._clear_result_presentation(
            self.tr("分析参数预设已变化；请重新运行自动分析。")
        )
        self._sync_workflow_state_after_invalidation()

    def _pre_event_display_velocity_changed(self, value_m_s: float) -> None:
        self._refresh_display_velocity_configuration(
            enabled=self.pre_event_display_check.isChecked(),
            value_m_s=value_m_s,
        )

    def _display_velocity_toggled(self, enabled: bool) -> None:
        self.display_velocity_status_label.setText(
            self.tr("开启") if enabled else self.tr("关闭")
        )
        self._refresh_display_velocity_configuration(
            enabled=enabled,
            value_m_s=self.pre_event_display_velocity_spin.value(),
        )

    def _refresh_display_velocity_configuration(
        self,
        *,
        enabled: bool,
        value_m_s: float,
    ) -> None:
        try:
            changed = self._session.set_display_velocity_configuration(
                enabled=enabled,
                pre_event_display_velocity_m_s=value_m_s,
            )
        except (TypeError, ValueError) as exc:
            self.analysis_status_label.setText(str(exc))
            return
        if not changed:
            return
        if self._session.results_valid:
            self._refresh_result_source_views(preserve_view=True)
            self.analysis_status_label.setText(
                self.tr("显示速度已刷新；正式表观速度与 STFT 保持不变。")
            )
        self._append_log(
            self.tr(
                "事件前显示速度已设为 {value:g} m/s；仅刷新 display velocity。"
            ).format(value=value_m_s)
        )

    def _activate_guided_analysis(self) -> None:
        """Open the guided controls without running science on the GUI thread."""
        if not self._session.stft_valid:
            self.guided_status_label.setText(
                self.tr("请先计算当前 STFT。")
            )
            return
        self._set_ridge_extraction_mode(
            RidgeExtractionMode.GUIDED,
            user_initiated=True,
        )

    def _ridge_mode_button_toggled(self, button_id: int, checked: bool) -> None:
        """Map explicit stable button ids to the only Ridge mode model."""
        if not checked:
            return
        mode_by_id = {
            _AUTOMATIC_MODE_BUTTON_ID: RidgeExtractionMode.AUTOMATIC,
            _GUIDED_MODE_BUTTON_ID: RidgeExtractionMode.GUIDED,
        }
        mode = mode_by_id.get(button_id)
        if mode is not None:
            self._set_ridge_extraction_mode(mode, sync_button=False)

    def _ridge_mode_clicked(self, mode: RidgeExtractionMode) -> None:
        """Apply the one-shot view action associated with an explicit click."""
        self._set_ridge_extraction_mode(
            mode,
            sync_button=False,
            user_initiated=True,
        )

    def _set_ridge_extraction_mode(
        self,
        mode: RidgeExtractionMode,
        *,
        sync_button: bool = True,
        user_initiated: bool = False,
    ) -> None:
        """Synchronize mode buttons, session model, and visible parameter group."""
        if sync_button:
            button_id = (
                _GUIDED_MODE_BUTTON_ID
                if mode is RidgeExtractionMode.GUIDED
                else _AUTOMATIC_MODE_BUTTON_ID
            )
            button = self.ridge_mode_button_group.button(button_id)
            if button is not None and not button.isChecked():
                blocker = QSignalBlocker(self.ridge_mode_button_group)
                button.setChecked(True)
                del blocker
        self._session.set_ridge_extraction_mode(mode)
        guided = mode is RidgeExtractionMode.GUIDED
        self.automatic_ridge_panel.setVisible(not guided)
        self.guided_ridge_panel.setVisible(guided)
        controller = self.spectrogram_view.corridor_controller
        controller.set_manual_region_visible(guided)
        if guided:
            self._show_guided_controls()
        else:
            controller.cancel_drawing()
            self._sync_guided_panel()
        if user_initiated and self._session.stft_valid:
            self.select_workflow_step(1)
            self.science_tabs.setCurrentWidget(self.spectrogram_view)
            self.spectrogram_view.fit_search_region()

    def _show_guided_controls(self) -> None:
        """Present the current displayed channel's Guided controls."""
        self.automatic_ridge_panel.setVisible(False)
        self.guided_ridge_panel.setVisible(True)
        self.select_workflow_step(1)
        self.science_tabs.setCurrentWidget(self.spectrogram_view)
        self._sync_guided_panel()

    def _undo_corridor_point(self) -> None:
        if self.spectrogram_view.corridor_controller.undo_last_point():
            self._sync_guided_panel()
            self._apply_state()

    def _cancel_corridor_drawing(self) -> None:
        self.spectrogram_view.corridor_controller.cancel_drawing()
        self._sync_guided_panel()

    def _finish_corridor_drawing(self) -> None:
        self.spectrogram_view.corridor_controller.finish_drawing()
        self._sync_guided_panel()

    def _guided_channel_changed(self, channel_name: str) -> None:
        self._current_guided_channel = channel_name
        self._sync_guided_panel()

    def _current_guided_channel_name(self) -> str | None:
        """Use the Spectrogram selector as the single current Guided channel."""
        displayed = self.spectrogram_view.channel_combo.currentData()
        if (
            isinstance(displayed, str)
            and displayed in self._session.stft_results
        ):
            self._current_guided_channel = displayed
            return displayed
        return self._current_guided_channel

    def _edit_upper_boundary(self) -> None:
        self._edit_manual_boundary("upper")

    def _edit_lower_boundary(self) -> None:
        self._edit_manual_boundary("lower")

    def _edit_manual_boundary(self, boundary: str) -> None:
        controller = self.spectrogram_view.corridor_controller
        if controller.drawing and controller.active_boundary == boundary:
            controller.finish_drawing()
            self._sync_guided_panel()
            return
        self.science_tabs.setCurrentWidget(self.spectrogram_view)
        if boundary == "upper":
            controller.begin_boundary("upper")
        else:
            controller.begin_boundary("lower")
        self._sync_guided_panel()

    def _clear_current_corridor(self) -> None:
        channel_name = self._current_guided_channel_name()
        if channel_name is None:
            return
        controller = self.spectrogram_view.corridor_controller
        if controller.channel_name == channel_name and controller.constraint is not None:
            controller.clear_constraint(emit_change=True)
        else:
            self._ridge_constraint_cleared(channel_name)

    def _ridge_constraint_changed(
        self,
        channel_name: str,
        value: object,
    ) -> None:
        if not isinstance(
            value,
            (ManualFrequencyRegion, RidgeCorridorConstraint),
        ):
            self.guided_status_label.setText(
                self.tr("人工频率范围返回了无效的 core 数据模型。")
            )
            return
        self._session.set_ridge_constraint(channel_name, value)
        controller = self.spectrogram_view.corridor_controller
        self.spectrogram_view.set_corridors(
            self._session.ridge_constraints,
            refresh=not (
                controller.channel_name == channel_name
                and controller.constraint is value
            ),
        )
        self._refresh_result_source_views(preserve_view=True)
        self._sync_guided_panel()
        self._apply_state()
        if isinstance(value, ManualFrequencyRegion):
            upper_count = (
                0
                if value.upper_boundary is None
                else value.upper_boundary.control_point_count
            )
            lower_count = (
                0
                if value.lower_boundary is None
                else value.lower_boundary.control_point_count
            )
            detail = self.tr("上边界 {upper} 点，下边界 {lower} 点").format(
                upper=upper_count,
                lower=lower_count,
            )
        else:
            detail = self.tr("旧版走廊 {count} 点").format(
                count=value.control_point_count
            )
        self._append_log(
            self.tr("{channel} 的人工频率范围已更新：{detail}。").format(
                channel=channel_name,
                detail=detail,
            )
        )

    def _ridge_constraint_cleared(self, channel_name: str) -> None:
        self._session.clear_ridge_constraint(channel_name)
        controller = self.spectrogram_view.corridor_controller
        self.spectrogram_view.set_corridors(
            self._session.ridge_constraints,
            refresh=not (
                controller.channel_name == channel_name
                and controller.constraint is None
            ),
        )
        self._refresh_result_source_views(preserve_view=True)
        self._sync_guided_panel()
        self._apply_state()
        self._append_log(
            self.tr("{channel} 的人工频率范围已清除。").format(
                channel=channel_name
            )
        )

    def _corridor_drawing_state_changed(self, drawing: bool) -> None:
        self.spectrogram_view.set_search_band_handles_enabled(not drawing)
        active = self.spectrogram_view.corridor_controller.active_boundary
        self.edit_upper_boundary_button.setText(
            self.tr("完成上边界编辑")
            if drawing and active == "upper"
            else self.tr("编辑上边界")
        )
        self.edit_lower_boundary_button.setText(
            self.tr("完成下边界编辑")
            if drawing and active == "lower"
            else self.tr("编辑下边界")
        )
        self._sync_guided_panel()
        self._apply_state()

    def _sync_guided_panel(self) -> None:
        self.spectrogram_view.corridor_controller.set_manual_region_visible(
            self._session.ridge_extraction_mode is RidgeExtractionMode.GUIDED
        )
        channel_name = self._current_guided_channel_name()
        if channel_name is None and self._session.stft_results:
            channel_name = next(iter(self._session.stft_results))
            self._current_guided_channel = channel_name
        self.guided_channel_label.setText(channel_name or "—")
        constraint = (
            self._session.ridge_constraints.get(channel_name)
            if channel_name is not None
            else None
        )
        if isinstance(constraint, ManualFrequencyRegion):
            upper_count = (
                0
                if constraint.upper_boundary is None
                else constraint.upper_boundary.control_point_count
            )
            lower_count = (
                0
                if constraint.lower_boundary is None
                else constraint.lower_boundary.control_point_count
            )
            if upper_count and lower_count:
                state = self.tr("已设置（上下边界）")
            elif upper_count:
                state = self.tr("已设置（仅上边界）")
            elif lower_count:
                state = self.tr("已设置（仅下边界）")
            else:
                state = self.tr("未设置")
            constrained_range = constraint.constrained_time_range_s
        elif isinstance(constraint, RidgeCorridorConstraint):
            upper_count = constraint.control_point_count
            lower_count = constraint.control_point_count
            state = self.tr("旧版走廊（已兼容显示）")
            constrained_range = (
                constraint.start_time_s,
                constraint.end_time_s,
            )
        else:
            upper_count = 0
            lower_count = 0
            state = self.tr("未设置")
            constrained_range = None
        controller = self.spectrogram_view.corridor_controller
        if controller.drawing:
            if controller.active_boundary == "upper":
                upper_count = controller.upper_point_count
            elif controller.active_boundary == "lower":
                lower_count = controller.lower_point_count
        self.corridor_state_label.setText(state)
        self.upper_boundary_point_count_label.setText(str(upper_count))
        self.lower_boundary_point_count_label.setText(str(lower_count))
        self.corridor_point_count_label.setText(str(upper_count + lower_count))
        self.guided_range_label.setText(
            (
                self.tr("{start:.6f} – {end:.6f} μs").format(
                    start=constrained_range[0] * 1.0e6,
                    end=constrained_range[1] * 1.0e6,
                )
                if constrained_range is not None
                else "—"
            )
        )
        if not self._session.stft_valid:
            status = self.tr("请先计算当前 STFT。")
        elif controller.invalid_draft:
            status = self.tr("人工上下边界发生交叉，请调整后重新分析。")
        elif controller.drawing:
            status = self.tr("正在编辑人工边界；控制点需从左到右添加。")
        elif channel_name is not None and self._session.guided_result_is_stale(
            channel_name
        ):
            status = self.tr("当前人工范围已修改，请重新运行人工范围分析。")
        elif channel_name is not None and self._session.guided_result_is_valid(
            channel_name
        ):
            status = self.tr("当前人工范围结果有效。")
        elif constraint is not None:
            status = self.tr("人工范围已设置；请运行人工范围分析。")
        else:
            status = self.tr("人工范围未设置；当前使用完整搜索频带。")
        self.guided_status_label.setText(status)

    def _refresh_result_source_views(self, *, preserve_view: bool = False) -> None:
        configuration = self._session.run_configuration
        if configuration is None:
            return
        self.velocity_view.set_time_origin(self._session.export_time_origin)
        guided = (
            self._session.valid_guided_channel_analyses
        )
        self.ridge_view.set_result_sets(
            self._session.channel_analyses,
            guided,
            corridors=self._session.ridge_constraints,
            relative_db_floor=configuration.relative_db_floor,
            fit_view=not preserve_view,
        )
        self.velocity_view.set_result_sets(
            self._session.channel_analyses,
            guided,
            relative_db_floor=configuration.relative_db_floor,
            fit_view=not preserve_view,
            available_channel_names=tuple(self._session.records),
        )
        self.comparison_view.set_result_sets(
            self._session.channel_analyses,
            guided,
        )

    def _guided_validation_error(self, channel_name: str | None = None) -> str | None:
        configuration = self._session.run_configuration
        region = self._session.ridge_search_region
        if configuration is None or region is None:
            return self.tr("分析配置或分析范围尚未就绪。")
        target = channel_name or self._current_guided_channel_name()
        if target is None:
            return self.tr("请先选择当前 STFT 通道。")
        constraint = self._session.ridge_constraints.get(target)
        stft_result = self._session.stft_results.get(target)
        if stft_result is None:
            return self.tr("通道 {channel} 没有当前有效 STFT。").format(
                channel=target
            )
        controller = self.spectrogram_view.corridor_controller
        if controller.channel_name == target and controller.invalid_draft:
            return self.tr("人工上下边界发生交叉，请调整后重新分析。")
        if constraint is None:
            return None
        try:
            if isinstance(constraint, ManualFrequencyRegion):
                validate_manual_frequency_region_for_stft(
                    constraint,
                    stft_result,
                    minimum_frequency_hz=(
                        region.frequency_min_hz
                    ),
                    maximum_frequency_hz=(
                        region.frequency_max_hz
                    ),
                    analysis_start_time_s=region.time_start_s,
                    analysis_end_time_s=region.time_end_s,
                )
            else:
                validate_ridge_corridor_for_stft(
                    constraint,
                    stft_result,
                    minimum_frequency_hz=(
                        region.frequency_min_hz
                    ),
                    maximum_frequency_hz=(
                        region.frequency_max_hz
                    ),
                    analysis_start_time_s=region.time_start_s,
                    analysis_end_time_s=region.time_end_s,
                )
        except RidgeConfigurationError as exc:
            return self.tr("通道 {channel} 的约束无效：{reason}").format(
                channel=target,
                reason=exc,
            )
        return None

    def run_guided_analysis(self) -> bool:
        """Run the formal workflow with one channel's manual region off-thread."""
        self._pending_candidate_detection = False
        controller = self.spectrogram_view.corridor_controller
        if controller.drawing and not controller.finish_drawing():
            self.guided_status_label.setText(
                self.tr("人工上下边界发生交叉，请调整后重新分析。")
            )
            return False
        configuration = self._session.run_configuration
        analysis_range = self._session.analysis_range
        channel_name = self._current_guided_channel_name()
        error = self._guided_validation_error(channel_name)
        if channel_name is None:
            self.guided_status_label.setText(
                error or self.tr("请先选择当前 STFT 通道。")
            )
            self._apply_state()
            return False
        if (
            not self._session.stft_valid
            or configuration is None
            or analysis_range is None
            or error is not None
        ):
            self.guided_status_label.setText(
                error or self.tr("请先计算当前 STFT。")
            )
            self._apply_state()
            return False
        request = AnalysisRequest(
            generation_id=self._session.guided_generation_id,
            analysis_range=analysis_range,
            configuration=configuration,
            result_source=AnalysisResultSource.GUIDED,
            ridge_constraints={
                channel_name: self._session.ridge_constraints[channel_name]
            }
            if channel_name is not None
            and channel_name in self._session.ridge_constraints
            else {},
            stft_results={
                channel_name: self._session.stft_results[channel_name]
            },
            records={channel_name: self._session.records[channel_name]},
            event_reference_time_s=self._session.resolved_event_time_s(
                channel_name
            ),
            ridge_search_region=self._session.ridge_search_region,
        )
        self._pending_analysis_source = AnalysisResultSource.GUIDED
        self._pending_navigation_tab = 2
        started = self._analysis_adapter.start(request)
        if not started:
            self._pending_navigation_tab = None
            self.guided_status_label.setText(self.tr("分析任务已在运行。"))
        return started

    def _analysis_request_ready(self) -> tuple[
        AnalysisRunConfiguration,
        AnalysisRange,
    ] | None:
        configuration = self._session.run_configuration
        analysis_range = self._session.analysis_range
        if (
            not self._session.records
            or configuration is None
            or analysis_range is None
            or not self._parameters_valid
        ):
            self.analysis_status_label.setText(self._parameter_error)
            self._apply_state()
            return None
        return configuration, analysis_range

    def run_stft_analysis(self) -> bool:
        """Compute and cache only the formal STFT intermediate results."""
        self._pending_candidate_detection = False
        ready = self._analysis_request_ready()
        if ready is None:
            return False
        configuration, analysis_range = ready
        request = AnalysisRequest(
            generation_id=self._session.generation_id,
            records=self._session.records,
            analysis_range=analysis_range,
            configuration=configuration,
            result_source=AnalysisResultSource.SPECTROGRAM,
        )
        self._pending_analysis_source = AnalysisResultSource.SPECTROGRAM
        self._pending_navigation_tab = 1
        started = self._analysis_adapter.start(request)
        if not started:
            self._pending_navigation_tab = None
            self.analysis_status_label.setText(self.tr("分析任务已在运行。"))
        return started

    def run_quick_analysis(self) -> bool:
        """Compute STFT if needed, then stop at the region checkpoint."""
        if not self._session.records:
            self._open_data()
            if not self._session.records:
                return False
        self._pending_candidate_detection = False
        self._continue_to_velocity_after_analysis = False
        self._quick_analysis_waiting = True
        if self._session.stft_valid and self._session.stft_results:
            self._sync_ridge_search_region_controls()
            self.select_workflow_step(1)
            self.science_tabs.setCurrentWidget(self.spectrogram_view)
            self.spectrogram_view.set_search_region_interaction(
                visible=True,
                editable=True,
            )
            self.analysis_status_label.setText(
                self.tr("请调整脊线搜索区域，然后确认并继续分析。")
            )
            return True
        started = self.run_stft_analysis()
        if not started:
            self._quick_analysis_waiting = False
        return started

    def confirm_search_region_and_continue(self) -> bool:
        """Run the shared automatic post-STFT workflow after human confirmation."""
        if self._session.ridge_search_region is None:
            self.automatic_ridge_status_label.setText(
                self.tr("请先计算时频图并建立脊线搜索区域。")
            )
            return False
        self._quick_analysis_waiting = False
        self._continue_to_velocity_after_analysis = True
        started = self.run_staged_automatic_analysis()
        if not started:
            self._continue_to_velocity_after_analysis = False
        return started

    def run_staged_automatic_analysis(self) -> bool:
        """Extract automatic ridge and velocity from the cached current STFT."""
        self._pending_candidate_detection = False
        ready = self._analysis_request_ready()
        if (
            ready is None
            or not self._session.stft_valid
            or self._session.ridge_search_region is None
        ):
            self.automatic_ridge_status_label.setText(
                self.tr("请先计算当前 STFT。")
            )
            return False
        configuration, analysis_range = ready
        request = AnalysisRequest(
            generation_id=self._session.generation_id,
            records=self._session.records,
            analysis_range=analysis_range,
            configuration=configuration,
            result_source=AnalysisResultSource.AUTOMATIC,
            stft_results=self._session.stft_results,
            ridge_search_region=self._session.ridge_search_region,
        )
        self._pending_analysis_source = AnalysisResultSource.AUTOMATIC
        self._pending_navigation_tab = 2
        started = self._analysis_adapter.start(request)
        if not started:
            self._pending_navigation_tab = None
        return started

    def run_automatic_analysis(self) -> bool:
        """Capture the current generation and start the public workflow off-thread."""
        self._pending_candidate_detection = False
        ready = self._analysis_request_ready()
        if ready is None:
            return False
        configuration, analysis_range = ready
        request = AnalysisRequest(
            generation_id=self._session.generation_id,
            records=self._session.records,
            analysis_range=analysis_range,
            configuration=configuration,
            stft_results=(
                self._session.stft_results if self._session.stft_valid else {}
            ),
            ridge_search_region=self._session.ridge_search_region,
        )
        self._quick_analysis_waiting = False
        self._continue_to_velocity_after_analysis = True
        self._set_ridge_extraction_mode(RidgeExtractionMode.AUTOMATIC)
        self._pending_analysis_source = AnalysisResultSource.AUTOMATIC
        self._pending_navigation_tab = 3
        started = self._analysis_adapter.start(request)
        if not started:
            self._pending_navigation_tab = None
            self.analysis_status_label.setText(self.tr("自动分析已在运行。"))
        return started

    def run_event_candidate_detection(self) -> bool:
        """Run the existing automatic chain but keep candidate adoption explicit."""
        ready = self._analysis_request_ready()
        if ready is None:
            return False
        configuration, analysis_range = ready
        request = AnalysisRequest(
            generation_id=self._session.generation_id,
            records=self._session.records,
            analysis_range=analysis_range,
            configuration=configuration,
        )
        self._set_ridge_extraction_mode(RidgeExtractionMode.AUTOMATIC)
        self._pending_analysis_source = AnalysisResultSource.AUTOMATIC
        self._pending_navigation_tab = 0
        self._pending_candidate_detection = True
        started = self._analysis_adapter.start(request)
        if not started:
            self._pending_navigation_tab = None
            self._pending_candidate_detection = False
            self.analysis_status_label.setText(self.tr("候选检测任务已在运行。"))
        return started

    def _analysis_started(self, generation_id: int) -> None:
        if self._pending_candidate_detection:
            self.analysis_status_label.setText(self.tr("正在检测事件候选…"))
            message = self.tr("后台事件候选检测已开始（请求 {generation}）。")
        elif self._pending_analysis_source is AnalysisResultSource.SPECTROGRAM:
            self.analysis_status_label.setText(self.tr("正在计算时频图…"))
            message = self.tr("后台 STFT 计算已开始（请求 {generation}）。")
        elif self._pending_analysis_source is AnalysisResultSource.GUIDED:
            self.analysis_status_label.setText(self.tr("正在运行人工范围分析…"))
            self.guided_status_label.setText(self.tr("正在运行人工范围分析…"))
            message = self.tr("后台人工范围分析已开始（请求 {generation}）。")
        else:
            self.analysis_status_label.setText(self.tr("正在分析…"))
            message = self.tr("后台自动分析已开始（请求 {generation}）。")
        self._append_log(message.format(generation=generation_id))

    def _analysis_finished(self, value: object) -> None:
        candidate_detection = self._pending_candidate_detection
        self._pending_candidate_detection = False
        if not isinstance(value, AnalysisRunResult):
            generation_id = (
                self._session.guided_generation_id
                if self._pending_analysis_source is AnalysisResultSource.GUIDED
                else self._session.generation_id
            )
            self._analysis_failed(
                generation_id,
                "TypeError",
                "Background adapter returned an unexpected result type.",
                "",
            )
            return
        if candidate_detection:
            if value.generation_id != self._session.generation_id:
                self._pending_navigation_tab = None
                self.analysis_status_label.setText(
                    self.tr("候选检测期间参数已变化；已忽略迟到候选。")
                )
                self._apply_state()
                return
            analyses = value.channel_analyses
            self.analysis_range_panel.set_detected_candidates(
                {
                    channel_name: analysis.stream_event_candidates.primary_candidate_time_s
                    for channel_name, analysis in analyses.items()
                },
                {
                    channel_name: analysis.signal_detection_result.detected_event_candidate_time_s
                    for channel_name, analysis in analyses.items()
                },
            )
            self.analysis_status_label.setText(
                self.tr("候选检测完成；正式事件参考仍未设置，请显式采用候选。")
            )
            self._append_log(
                self.tr(
                    "事件候选检测完成：{channels} 个独立通道；临时分析结果未写入 session，"
                    "未自动确认参考时刻。"
                ).format(channels=len(analyses))
            )
            self._apply_state()
            self._complete_pending_navigation()
            return
        if value.result_source is AnalysisResultSource.SPECTROGRAM:
            accepted = self._session.accept_stft_results(
                generation_id=value.generation_id,
                stft_results=value.stft_results,
            )
        elif value.result_source is AnalysisResultSource.GUIDED:
            accepted = self._session.accept_guided_results(
                generation_id=value.generation_id,
                analyses=value.channel_analyses,
            )
        else:
            accepted = self._session.accept_results(
                generation_id=value.generation_id,
                analyses=value.channel_analyses,
                ridge_search_region=value.ridge_search_region,
            )
        if not accepted:
            self._pending_navigation_tab = None
            self.analysis_status_label.setText(
                self.tr("分析期间参数已变化；已忽略迟到结果。")
            )
            self._append_log(
                self.tr("请求 {generation} 的迟到结果已忽略。").format(
                    generation=value.generation_id
                )
            )
            if value.result_source is AnalysisResultSource.GUIDED:
                self._apply_state()
            else:
                self._sync_workflow_state_after_invalidation()
            return
        if value.result_source is AnalysisResultSource.SPECTROGRAM:
            self._finish_stft_presentation()
            self._complete_pending_navigation()
            return
        if value.result_source is AnalysisResultSource.GUIDED:
            self._finish_guided_presentation(value.channel_analyses)
            self._complete_pending_navigation()
            return
        run_configuration = self._session.run_configuration
        if run_configuration is None:
            return
        analyses = self._session.channel_analyses
        self._workflow_state = WorkflowState.STFT_READY
        self._sync_ridge_search_region_controls()
        self._sync_scientific_view_configuration()
        self._apply_state()
        self.spectrogram_view.set_analyses(
            analyses,
            relative_db_floor=run_configuration.relative_db_floor,
        )
        self.spectrogram_view.set_corridors(self._session.ridge_constraints)
        self._workflow_state = WorkflowState.RIDGE_READY
        self._apply_state()
        self._refresh_result_source_views()
        self.quality_summary.set_analyses(analyses)
        self.analysis_range_panel.set_detected_candidates(
            {
                channel_name: analysis.stream_event_candidates.primary_candidate_time_s
                for channel_name, analysis in analyses.items()
            },
            {
                channel_name: analysis.signal_detection_result.detected_event_candidate_time_s
                for channel_name, analysis in analyses.items()
            },
        )
        self._sync_event_reference_panel()
        self._workflow_state = WorkflowState.RESULT_READY
        self._apply_state()
        self.analysis_status_label.setText(self.tr("自动分析完成；结果为当前有效。"))
        self.formal_velocity_status_label.setText(self.tr("当前正式结果有效"))
        self.stft_ready_label.setText(self.tr("当前 STFT 有效。"))
        self.automatic_ridge_status_label.setText(self.tr("自动脊线结果有效。"))
        self._append_log(
            self.tr("自动分析完成：{channels} 个独立通道。").format(
                channels=len(analyses)
            )
        )
        self._sync_guided_panel()
        self._complete_pending_navigation()
        if self._continue_to_velocity_after_analysis:
            self._continue_to_velocity_after_analysis = False
            self.select_workflow_step(2)

    def _finish_stft_presentation(self) -> None:
        configuration = self._session.run_configuration
        if configuration is None:
            return
        self._workflow_state = WorkflowState.STFT_READY
        self._sync_ridge_search_region_controls()
        self._sync_scientific_view_configuration()
        self.spectrogram_view.set_stft_results(
            self._session.stft_results,
            relative_db_floor=configuration.relative_db_floor,
        )
        self.spectrogram_view.set_corridors(self._session.ridge_constraints)
        self.stft_ready_label.setText(self.tr("当前 STFT 有效，可进入脊线提取。"))
        self.analysis_status_label.setText(self.tr("时频图计算完成。"))
        self.automatic_ridge_status_label.setText(self.tr("当前 STFT 已就绪。"))
        self._apply_state()
        self._sync_guided_panel()
        self._append_log(
            self.tr("STFT 计算完成：{channels} 个独立通道。").format(
                channels=len(self._session.stft_results)
            )
        )
        if self._quick_analysis_waiting:
            self.select_workflow_step(1)
            self.science_tabs.setCurrentWidget(self.spectrogram_view)
            self.spectrogram_view.set_search_region_interaction(
                visible=True,
                editable=True,
            )
            self.analysis_status_label.setText(
                self.tr("请调整脊线搜索区域，然后确认并继续分析。")
            )
        else:
            self.spectrogram_view.set_search_region_interaction(
                visible=False,
                editable=False,
            )

    def _finish_guided_presentation(
        self,
        analyses: Mapping[str, ChannelAnalysis],
    ) -> None:
        valid_guided = self._session.valid_guided_channel_analyses
        self._sync_workflow_state_from_capabilities()
        self._refresh_result_source_views()
        ridge_guided_index = self.ridge_view.result_source_combo.findData("guided")
        velocity_guided_index = self.velocity_view.result_source_combo.findData(
            "guided"
        )
        if ridge_guided_index >= 0:
            self.ridge_view.result_source_combo.setCurrentIndex(ridge_guided_index)
        if velocity_guided_index >= 0:
            self.velocity_view.result_source_combo.setCurrentIndex(
                velocity_guided_index
            )
        self.quality_summary.set_analyses(valid_guided)
        self.analysis_status_label.setText(
            (
                self.tr("人工范围分析完成；自动结果仍保持有效。")
                if self._session.automatic_results_available
                else self.tr("人工范围分析完成；当前已获得正式结果。")
            )
        )
        self.guided_status_label.setText(self.tr("当前人工范围结果有效。"))
        self.formal_velocity_status_label.setText(self.tr("当前正式结果有效"))
        self.diagnostics_tabs.setCurrentWidget(self.quality_summary)
        self._sync_guided_panel()
        self._apply_state()
        self._append_log(
            self.tr(
                "人工范围分析完成：{channels} 个当前有效通道；自动结果未覆盖。"
            ).format(
                channels=len(valid_guided)
            )
        )

    def _analysis_failed(
        self,
        generation_id: int,
        error_type: str,
        message: str,
        traceback_text: str,
    ) -> None:
        candidate_detection = self._pending_candidate_detection
        self._pending_candidate_detection = False
        self._continue_to_velocity_after_analysis = False
        if self._pending_analysis_source is AnalysisResultSource.SPECTROGRAM:
            self._quick_analysis_waiting = False
        expected_generation = (
            self._session.guided_generation_id
            if self._pending_analysis_source is AnalysisResultSource.GUIDED
            else self._session.generation_id
        )
        if generation_id != expected_generation:
            self._pending_navigation_tab = None
            self._append_log(
                self.tr("已忽略失效请求 {generation} 的异常。").format(
                    generation=generation_id
                )
            )
            return
        self._pending_navigation_tab = None
        summary = f"{error_type}: {message}"
        if self._pending_analysis_source is AnalysisResultSource.GUIDED:
            failure_text = self.tr("人工范围分析失败：{summary}").format(
                summary=summary
            )
            self.guided_status_label.setText(failure_text)
        elif self._pending_analysis_source is AnalysisResultSource.SPECTROGRAM:
            failure_text = self.tr("时频图计算失败：{summary}").format(
                summary=summary
            )
            self.stft_ready_label.setText(failure_text)
            self.quality_summary.clear_results(failure_text)
        elif candidate_detection:
            failure_text = self.tr("事件候选检测失败：{summary}").format(
                summary=summary
            )
            self.quality_summary.clear_results(failure_text)
        else:
            failure_text = self.tr("自动分析失败：{summary}").format(
                summary=summary
            )
            self.quality_summary.clear_results(failure_text)
        self.analysis_status_label.setText(failure_text)
        self._append_log(failure_text)
        if traceback_text:
            self._append_log(traceback_text.rstrip())
        if self._pending_analysis_source is AnalysisResultSource.GUIDED:
            self._apply_state()
        else:
            self._sync_workflow_state_after_invalidation()

    def _busy_changed(self, busy: bool) -> None:
        self.analysis_progress.setVisible(busy)
        self.profile_combo.setEnabled(
            not busy and self._session.workflow_configuration is not None
        )
        self.action_import_analysis_config.setEnabled(not busy)
        self.action_restore_default_parameters.setEnabled(not busy)
        self.vacuum_wavelength_spin.setEnabled(
            not busy and self._session.run_configuration is not None
        )
        self._set_parameter_editability(
            not busy and self._session.run_configuration is not None
        )
        self.restore_preset_button.setEnabled(
            not busy and self._session.run_configuration is not None
        )
        self.advanced_parameters_button.setEnabled(
            not busy and self._session.run_configuration is not None
        )
        self._apply_state()

    def _exportable_result_sets(self) -> dict[
        ResultAnalysisMode,
        Mapping[str, ChannelAnalysis],
    ]:
        """Return only results that remain valid in the current session."""
        available: dict[ResultAnalysisMode, Mapping[str, ChannelAnalysis]] = {}
        if self._session.automatic_results_available:
            available[ResultAnalysisMode.AUTOMATIC] = (
                self._session.automatic_channel_analyses
            )
        if self._session.guided_results_available:
            available[ResultAnalysisMode.GUIDED] = (
                self._session.valid_guided_channel_analyses
            )
        return available

    def _refresh_export_controls(self) -> None:
        """Reflect only the current valid Automatic/Guided result sets."""
        available = self._exportable_result_sets()
        selected_mode = self._selected_export_mode()
        mode_blocker = QSignalBlocker(self.export_mode_combo)
        self.export_mode_combo.clear()
        labels = {
            ResultAnalysisMode.AUTOMATIC: self.tr("自动分析"),
            ResultAnalysisMode.GUIDED: self.tr("人工范围分析"),
        }
        for mode in (ResultAnalysisMode.AUTOMATIC, ResultAnalysisMode.GUIDED):
            if mode in available:
                self.export_mode_combo.addItem(labels[mode], mode.value)
        if selected_mode in available:
            index = self.export_mode_combo.findData(selected_mode.value)
            self.export_mode_combo.setCurrentIndex(index)
        elif self.export_mode_combo.count():
            self.export_mode_combo.setCurrentIndex(0)
        del mode_blocker
        self._refresh_export_channels()

        result_available = bool(available)
        busy = self._analysis_adapter.busy
        directory_selected = self._export_output_directory is not None
        current_mode = self._selected_export_mode()
        current_channel = self.export_channel_combo.currentData()
        selection_valid = (
            isinstance(current_mode, ResultAnalysisMode)
            and isinstance(current_channel, str)
            and current_channel in available.get(current_mode, {})
        )
        event_origin_ready = (
            self._session.export_time_origin is ExportTimeOrigin.ABSOLUTE
            or self._session.event_reference_time_s is not None
        )
        if not result_available:
            availability_text = self.tr("当前没有可导出的有效正式结果。")
            action_tooltip = self.tr("请先获得当前有效的 Automatic 或 Guided 结果。")
        else:
            modes = " / ".join(labels[mode] for mode in available)
            availability_text = self.tr("可导出的当前有效结果：{modes}。").format(
                modes=modes
            ) + self.tr("Automatic 与 Guided 将保持独立导出。")
            action_tooltip = self.tr("打开复核与导出页面，检查当前结果和导出参数。")
            if not event_origin_ready:
                availability_text += self.tr(
                    " 当前选择起跳点为 0；请先正式采用事件参考，或改用实验绝对时间。"
                )
            if not selection_valid:
                availability_text += self.tr(
                    " 当前通道尚无所选分析模式的结果，预览已清空且不可导出。"
                )
        self.export_availability_label.setText(availability_text)
        self.export_mode_combo.setEnabled(result_available and not busy)
        self.export_channel_combo.setEnabled(result_available and not busy)
        self.export_directory_button.setEnabled(result_available and not busy)
        self.export_include_pre_event_check.setEnabled(result_available and not busy)
        self.export_button.setEnabled(
            selection_valid
            and directory_selected
            and event_origin_ready
            and not busy
        )
        self.action_export.setEnabled(result_available and not busy)
        self.action_export.setToolTip(action_tooltip)
        if self.workflow_navigation.currentRow() == 3:
            self._sync_review_preview()

    def _refresh_export_channels(self) -> None:
        """Populate the channel selector from the selected, independent mode."""
        selected_channel = self.export_channel_combo.currentData()
        channel_names = tuple(self._session.records)
        channel_blocker = QSignalBlocker(self.export_channel_combo)
        self.export_channel_combo.clear()
        for channel_name in channel_names:
            self.export_channel_combo.addItem(channel_name, channel_name)
        if isinstance(selected_channel, str) and selected_channel in channel_names:
            self.export_channel_combo.setCurrentIndex(
                self.export_channel_combo.findData(selected_channel)
            )
        elif self.export_channel_combo.count():
            self.export_channel_combo.setCurrentIndex(0)
        del channel_blocker

    def _export_mode_changed(self, _index: int) -> None:
        self._refresh_export_controls()

    def _export_channel_changed(self, _index: int) -> None:
        self._refresh_export_controls()

    def _sync_review_preview(self) -> None:
        """Make the review step's velocity view match its exact export target."""
        self.velocity_view.set_export_preview_mode(True)
        mode = self._selected_export_mode()
        channel_name = self.export_channel_combo.currentData()
        if mode is None or not isinstance(channel_name, str):
            self.velocity_view.clear_results()
            return
        self.science_tabs.setCurrentWidget(self.velocity_view)
        self.velocity_view.select_result_target(mode.value, channel_name)

    def _selected_export_mode(self) -> ResultAnalysisMode | None:
        """Normalize Qt's QVariant string back to the public export enum."""
        value = self.export_mode_combo.currentData()
        try:
            return ResultAnalysisMode(value)
        except (TypeError, ValueError):
            return None

    def _choose_export_directory(self) -> bool:
        selected_path = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择正式结果导出目录"),
            str(self._export_output_directory or self._repository_root),
        )
        if not selected_path:
            return False
        self._set_export_output_directory(Path(selected_path))
        return True

    def _set_export_output_directory(self, directory: Path) -> None:
        """Store a user-selected output parent without creating any files."""
        self._export_output_directory = Path(directory)
        self.export_directory_label.setText(
            self.tr("导出目录：{path}").format(path=self._export_output_directory)
        )
        self._refresh_export_controls()

    def _show_review_and_export(self) -> None:
        """Navigate to the review step without writing files or changing state."""
        self._refresh_export_controls()
        review_index = 3
        review_item = self.workflow_navigation.item(review_index)
        if review_item is None or not bool(
            review_item.flags() & Qt.ItemFlag.ItemIsEnabled
        ):
            message = self.tr("当前没有可复核与导出的有效正式结果。")
            self.statusBar().showMessage(message, 5000)
            return
        self.workflow_navigation.setCurrentRow(review_index)
        self.parameter_stack.setCurrentIndex(review_index)

    def _export_current_result(self) -> bool:
        """Select a directory if needed, then call the public core export API."""
        available = self._exportable_result_sets()
        mode = self._selected_export_mode()
        channel_name = self.export_channel_combo.currentData()
        if (
            mode is None
            or not isinstance(channel_name, str)
            or channel_name not in available.get(mode, {})
        ):
            message = self.tr("当前没有可导出的有效正式结果。")
            self.analysis_status_label.setText(message)
            self._append_log(message)
            self._refresh_export_controls()
            return False
        if self._export_output_directory is None and not self._choose_export_directory():
            self._append_log(self.tr("用户已取消选择导出目录。"))
            return False
        configuration = self._session.run_configuration
        if configuration is None or self._export_output_directory is None:
            return False
        selected_analysis = available[mode][channel_name]
        has_event_reference = (
            selected_analysis.signal_detection_result.manual_event_reference_time_s
            is not None
        )
        event_reference_source = (
            self._session.resolved_event_source(channel_name)
            if has_event_reference
            else None
        )
        try:
            report = export_formal_results(
                ResultExportOptions(
                    output_directory=self._export_output_directory,
                    analysis_mode=mode,
                    channel_analyses={channel_name: available[mode][channel_name]},
                    time_origin=self._session.export_time_origin,
                    include_pre_event_display_rows=(
                        self.export_include_pre_event_check.isChecked()
                    ),
                    source_path=self._session.source_path,
                    analysis_profile_name=configuration.parameters.provenance_name,
                    pre_event_display_enabled=(
                        configuration.enable_pre_event_display
                    ),
                    pre_event_display_velocity_m_s=(
                        configuration.pre_event_display_velocity_m_s
                    ),
                    event_reference_source=event_reference_source,
                    event_time_source=self._session.event_time_source.value,
                    ridge_constraints=(
                        {
                            channel_name: self._session.ridge_constraints[
                                channel_name
                            ]
                        }
                        if mode is ResultAnalysisMode.GUIDED
                        and channel_name in self._session.ridge_constraints
                        else {}
                    ),
                    protected_output_directories=(
                        self._repository_root / "data" / "raw",
                    ),
                )
            )
        except ResultExportError as exc:
            message = self.tr("结果导出失败：{message}").format(message=exc)
            self.analysis_status_label.setText(message)
            self._append_log(message)
            QMessageBox.critical(self, self.tr("结果导出失败"), message)
            return False
        exported = report.exported_channels[0]
        message = self.tr("结果导出完成：{path}").format(
            path=report.output_directory
        )
        self.analysis_status_label.setText(message)
        self.statusBar().showMessage(message, 8000)
        self._append_log(
            self.tr(
                "{mode} / {channel} 已导出至 {directory}：{csv}；{detail}；{metadata}"
            ).format(
                mode=mode.value,
                channel=channel_name,
                directory=report.output_directory,
                csv=exported.csv_path.name,
                detail=exported.detail_csv_path.name,
                metadata=exported.metadata_path.name,
            )
        )
        QMessageBox.information(
            self,
            self.tr("导出完成"),
            self.tr(
                "已生成：\n{csv}\n{detail}\n{metadata}\n\n输出位置：\n{directory}"
            ).format(
                csv=exported.csv_path.name,
                detail=exported.detail_csv_path.name,
                metadata=exported.metadata_path.name,
                directory=report.output_directory,
            ),
        )
        return True

    def _clear_result_presentation(self, reason: str) -> None:
        self.spectrogram_view.clear_results()
        self.ridge_view.clear_results()
        self.velocity_view.clear_results()
        self.comparison_view.clear_results()
        self.analysis_range_panel.clear_detected_candidates()
        self.quality_summary.clear_results(reason)
        self.action_export.setEnabled(False)
        self._refresh_export_controls()
        self.analysis_status_label.setText(reason)
        self.formal_velocity_status_label.setText(self.tr("尚无正式结果"))
        self.stft_ready_label.setText(self.tr("尚未计算时频图。"))
        self.automatic_ridge_status_label.setText(self.tr("当前 STFT 尚未就绪。"))
        self._sync_guided_panel()

    def _clear_downstream_presentation(self, reason: str) -> None:
        """Clear ridge/velocity views while retaining the cached STFT display."""
        self.ridge_view.clear_results()
        self.velocity_view.clear_results()
        self.comparison_view.clear_results()
        self.analysis_range_panel.clear_detected_candidates()
        self.quality_summary.clear_results(reason)
        self.analysis_status_label.setText(reason)
        self.formal_velocity_status_label.setText(self.tr("尚无正式结果"))
        self.automatic_ridge_status_label.setText(self.tr("请重新提取脊线。"))
        self._sync_scientific_view_configuration()
        configuration = self._session.run_configuration
        if configuration is not None and self._session.stft_valid:
            self.spectrogram_view.set_stft_results(
                self._session.stft_results,
                relative_db_floor=configuration.relative_db_floor,
            )
            self.spectrogram_view.set_corridors(self._session.ridge_constraints)
        self._sync_guided_panel()

    def _sync_scientific_view_configuration(self) -> None:
        configuration = self._session.run_configuration
        region = self._session.ridge_search_region
        if configuration is None or region is None:
            return
        for view in (self.spectrogram_view, self.ridge_view):
            view.set_view_configuration(
                analysis_start_time_s=region.time_start_s,
                analysis_end_time_s=region.time_end_s,
                minimum_frequency_hz=region.frequency_min_hz,
                maximum_frequency_hz=region.frequency_max_hz,
            )

    def _sync_workflow_state_after_invalidation(self) -> None:
        self._sync_workflow_state_from_capabilities()

    def _sync_workflow_state_from_capabilities(self) -> None:
        """Derive availability from independent STFT/Automatic/Guided capabilities."""
        if not self._session.records:
            self._workflow_state = WorkflowState.EMPTY
        elif self._session.analysis_range is None:
            self._workflow_state = WorkflowState.DATA_LOADED
        elif self._session.any_formal_results_available:
            self._workflow_state = WorkflowState.RESULT_READY
        elif (
            self._session.automatic_results_available
            or self._session.guided_results_available
        ):
            self._workflow_state = WorkflowState.RIDGE_READY
        elif self._session.stft_valid:
            self._workflow_state = WorkflowState.STFT_READY
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
        stft_ready = self._session.stft_valid and bool(self._session.stft_results)
        result_ready = self._session.any_formal_results_available
        availability = (True, stft_ready, result_ready, result_ready)
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
        tab_availability = (loaded, result_ready, result_ready, result_ready)
        for tab_index, enabled in enumerate(tab_availability, start=1):
            self.science_tabs.setTabEnabled(tab_index, enabled)
            self.science_tabs.setTabToolTip(
                tab_index,
                "" if enabled else unavailable_tooltip,
            )
        can_run = (
            range_defined
            and self._session.run_configuration is not None
            and self._parameters_valid
            and not self._analysis_adapter.busy
        )
        if can_run:
            run_tooltip = self.tr("运行 public core 完整自动分析。")
        elif self._analysis_adapter.busy:
            run_tooltip = self.tr("自动分析正在运行。")
        elif not self._session.records:
            run_tooltip = self.tr("请先导入实验数据。")
        elif not range_defined:
            run_tooltip = self.tr("请先建立合法分析范围。")
        else:
            run_tooltip = self._parameter_error
        self.action_automatic.setEnabled(can_run)
        self.action_automatic.setToolTip(run_tooltip)
        self.action_quick_analysis.setEnabled(not self._analysis_adapter.busy)
        self.action_quick_analysis.setToolTip(
            run_tooltip
            if loaded
            else self.tr("打开数据后计算 STFT，并停在脊线搜索区域确认。")
        )
        self.action_full_automatic.setEnabled(can_run)
        self.action_full_automatic.setToolTip(run_tooltip)
        self.action_run_stft.setEnabled(can_run)
        self.action_run_stft.setToolTip(run_tooltip)
        self.run_analysis_button.setEnabled(can_run)
        self.run_analysis_button.setToolTip(run_tooltip)
        self.analysis_range_panel.detect_candidates_button.setEnabled(can_run)
        can_use_guided = (
            self._session.stft_valid
            and bool(self._session.stft_results)
            and not self._analysis_adapter.busy
        )
        guided_tooltip = (
            self.tr("在当前 STFT 上创建或编辑人工频率范围。")
            if can_use_guided
            else self.tr("请先计算当前 STFT。")
        )
        self.action_guided.setEnabled(can_use_guided)
        self.action_guided.setToolTip(guided_tooltip)
        self.guided_mode_radio.setEnabled(can_use_guided)
        self.guided_mode_radio.setToolTip(guided_tooltip)
        self.edit_upper_boundary_button.setEnabled(can_use_guided)
        self.edit_lower_boundary_button.setEnabled(can_use_guided)
        self.undo_corridor_button.setEnabled(
            can_use_guided
            and (
                self.spectrogram_view.corridor_controller.constraint is not None
                or self.spectrogram_view.corridor_controller.drawing
            )
        )
        self.clear_corridor_button.setEnabled(
            can_use_guided
            and self._current_guided_channel_name()
            in self._session.ridge_constraints
        )
        self.run_guided_button.setEnabled(
            can_use_guided
            and self._guided_validation_error() is None
        )
        self.extract_automatic_ridge_button.setEnabled(can_use_guided)
        self.action_run_ridge.setEnabled(can_use_guided)
        has_configuration = self._session.run_configuration is not None
        self.advanced_parameters_button.setEnabled(
            has_configuration and not self._analysis_adapter.busy
        )
        self.profile_combo.setEnabled(
            has_configuration and not self._analysis_adapter.busy
        )
        self.vacuum_wavelength_spin.setEnabled(
            has_configuration and not self._analysis_adapter.busy
        )
        self.restore_preset_button.setEnabled(
            has_configuration and not self._analysis_adapter.busy
        )
        self._set_parameter_editability(
            has_configuration and not self._analysis_adapter.busy
        )
        region_editable = (
            has_configuration and stft_ready and not self._analysis_adapter.busy
        )
        for region_control in (
            self.ridge_time_start_spin,
            self.ridge_time_end_spin,
            self.minimum_frequency_spin,
            self.maximum_frequency_spin,
        ):
            region_control.setReadOnly(not region_editable)
        self.confirm_search_region_button.setEnabled(region_editable)
        self._refresh_export_controls()
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
        self.velocity_view.set_export_preview_mode(row == 3)
        if row == 0:
            self.science_tabs.setCurrentWidget(self.raw_signal_view)
        elif row == 1:
            self.spectrogram_view.set_search_region_interaction(
                visible=True,
                editable=True,
            )
            if (
                self._session.automatic_results_available
                or self._session.guided_results_available
            ):
                self.science_tabs.setCurrentWidget(self.ridge_view)
                self.ridge_view.set_search_region_interaction(
                    visible=True,
                    editable=True,
                )
            else:
                self.science_tabs.setCurrentWidget(self.spectrogram_view)
        elif row == 2:
            self.science_tabs.setCurrentWidget(self.velocity_view)
        elif row == 3:
            self._sync_review_preview()

    def _workflow_item_clicked(self, item: QListWidgetItem) -> None:
        """Open the existing import flow when the empty first step is clicked."""
        if self.workflow_navigation.row(item) == 0 and not self._session.records:
            self._open_data()

    def _complete_pending_navigation(self) -> None:
        """Perform one focus change after the requested scientific operation."""
        if self._pending_navigation_tab is not None:
            self.science_tabs.setCurrentIndex(self._pending_navigation_tab)
        self._pending_navigation_tab = None

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
        self._save_layout_settings()
        self.spectrogram_view.dispose_search_region_interactions()
        self.spectrogram_view.corridor_controller.detach_context()
        self.ridge_view.dispose_search_region_interactions()
        event.accept()

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

    def _sample_spin(self, object_name: str, *, minimum: int = 1) -> QSpinBox:
        spin = QSpinBox()
        spin.setObjectName(object_name)
        spin.setRange(minimum, 10_000_000)
        spin.setSuffix(self.tr(" 点"))
        spin.setReadOnly(True)
        return spin

    @staticmethod
    def _frequency_spin(object_name: str) -> QDoubleSpinBox:
        spin = _CompactDoubleSpinBox(minimum_decimals=2)
        spin.setObjectName(object_name)
        spin.setRange(0.0, 1_000_000.0)
        spin.setDecimals(12)
        spin.setSingleStep(1.0)
        spin.setSuffix(" GHz")
        spin.setReadOnly(True)
        return spin


__all__ = ["MainWindow"]
