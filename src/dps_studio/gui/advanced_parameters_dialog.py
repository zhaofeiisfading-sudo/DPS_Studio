"""Read-only organization of the current formal advanced parameters."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dps_studio.core.workflow import WorkflowConfiguration
from dps_studio.gui.analysis_session import AnalysisRunConfiguration


class AdvancedParametersDialog(QDialog):
    """Show real workflow parameters grouped by scientific responsibility."""

    def __init__(
        self,
        run_configuration: AnalysisRunConfiguration,
        workflow_configuration: WorkflowConfiguration,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("高级分析参数"))
        self.resize(620, 470)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.setObjectName("advancedParameterTabs")
        parameters = run_configuration.parameters
        tabs.addTab(
            self._page(
                (
                    (self.tr("基础预设"), parameters.preset_name),
                    (
                        self.tr("运行状态"),
                        self.tr("自定义覆写")
                        if parameters.is_custom
                        else self.tr("未修改预设"),
                    ),
                    (
                        self.tr("显式覆写"),
                        ", ".join(parameters.custom_overrides)
                        if parameters.custom_overrides
                        else self.tr("无"),
                    ),
                    (self.tr("窗函数"), parameters.window_name),
                    (self.tr("窗长"), f"{parameters.window_length_samples} samples"),
                    (self.tr("重叠长度"), f"{parameters.overlap_samples} samples"),
                    (self.tr("步长"), f"{parameters.hop_samples} samples"),
                    (self.tr("FFT 长度"), str(parameters.nfft)),
                    (
                        self.tr("搜索频段"),
                        f"{parameters.minimum_frequency_hz * 1e-9:.6f} – "
                        f"{parameters.maximum_frequency_hz * 1e-9:.6f} GHz",
                    ),
                )
            ),
            self.tr("STFT"),
        )
        ridge_method = run_configuration.base_profile.ridge_refinement
        tabs.addTab(
            self._page(((self.tr("亚频点精修方法"), ridge_method),)),
            self.tr("脊线"),
        )
        detection = run_configuration.detection_config
        tabs.addTab(
            self._page(
                (
                    (
                        self.tr("峰值/背景阈值"),
                        f"{detection.minimum_peak_to_background_db:g} dB",
                    ),
                    (
                        self.tr("峰值/竞争峰阈值"),
                        f"{detection.minimum_peak_to_competitor_db:g} dB",
                    ),
                    (
                        self.tr("峰排除半宽"),
                        f"{detection.peak_exclusion_half_width_bins} bins",
                    ),
                    (
                        self.tr("最小连续帧"),
                        str(detection.minimum_consecutive_frames),
                    ),
                    (
                        self.tr("窗内最小周期数"),
                        f"{detection.minimum_cycles_in_window:g}",
                    ),
                    (self.tr("检测启用"), str(detection.enabled)),
                )
            ),
            self.tr("信号检测"),
        )
        tabs.addTab(
            self._page(
                (
                    (
                        self.tr("背景保护窗比例"),
                        f"{run_configuration.background_guard_window_scale:g}",
                    ),
                    (
                        self.tr("最小背景频点数"),
                        str(run_configuration.minimum_background_bin_count),
                    ),
                    (
                        self.tr("质量配置"),
                        self.tr("来自当前正式默认配置（只读）"),
                    ),
                )
            ),
            self.tr("质量"),
        )
        tabs.addTab(
            self._page(
                (
                    (
                        self.tr("相对 dB floor"),
                        f"{run_configuration.relative_db_floor:g} dB",
                    ),
                    (
                        self.tr("事件前显示启用"),
                        str(run_configuration.enable_pre_event_display),
                    ),
                    (
                        self.tr("事件前显示速度"),
                        f"{run_configuration.pre_event_display_velocity_m_s:g} m/s",
                    ),
                    (self.tr("配置来源"), str(workflow_configuration.config_path)),
                )
            ),
            self.tr("显示"),
        )
        layout.addWidget(tabs)
        notice = QLabel(
            self.tr(
                "本对话框只显示当前 core 中真实存在的高级参数；质量与检测参数"
                "在本版本保持只读。"
            )
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _page(rows: tuple[tuple[str, str], ...]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        for label, value in rows:
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            form.addRow(label, value_label)
        return page


__all__ = ["AdvancedParametersDialog"]
