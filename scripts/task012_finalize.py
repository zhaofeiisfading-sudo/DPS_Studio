"""Produce the reviewable TASK-012 handoff only from successful final evidence."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/research_clean_task12"
BUNDLE = ROOT / "release/PDV_Studio_Research_TASK012"
EXE = BUNDLE / "PDV Studio Research TASK012.exe"
ZIP = ROOT / "release/PDV_Studio_Research_TASK012_Windows_x64.zip"
NOTE = Path("D:/Research/Notes/05项目/dps/2026-11-06_TASK-012_GUI重构与交互修复.md")


def read(name: str) -> Any:
    return json.loads((ARTIFACT / name).read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def junit(name: str) -> int:
    suites = ET.parse(ARTIFACT / name).getroot().findall(".//testsuite")
    assert suites
    assert sum(int(suite.get("failures", "0")) + int(suite.get("errors", "0")) for suite in suites) == 0
    return sum(int(suite.get("tests", "0")) for suite in suites)


def main() -> None:
    exe_sha = sha(EXE)
    reports = [row for group in ("release_acceptance_normal", "release_acceptance_real", "release_acceptance_layout")
               for row in read(f"{group}/verification.json")]
    assert len(reports) == 8 and all(row["passed"] and row["executable_sha256"] == exe_sha for row in reports)
    code_parity = read("bundle_code_parity_acceptance.json")
    assert code_parity["passed"] and code_parity["executable_sha256"] == exe_sha
    assert read("numerical_parity.json")["passed"]
    native = read("native_interaction_final.json")
    assert native["passed"] and native["executable_sha256"] == exe_sha
    assert all(read("boundary_final_check.json")["checks"].values())
    assert "All checks passed!" in (ARTIFACT / "ruff_final.log").read_text(encoding="utf-8")
    assert "Success: no issues found" in (ARTIFACT / "mypy_final.log").read_text(encoding="utf-8")
    full = junit("pytest_delivery_full.xml")
    cases = ET.parse(ARTIFACT / "pytest_delivery_full.xml").getroot().findall(".//testcase")
    gui = sum(".gui." in case.get("classname", "") for case in cases)
    contract = sum(case.get("classname", "").endswith("test_task012_workspaces") for case in cases)
    assert gui > 150 and contract >= 26
    assert "fatal exception" not in (ARTIFACT / "pytest_delivery_full.log").read_text(encoding="utf-8").lower()
    branch = subprocess.check_output(["git", "--no-optional-locks", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    maintained = ("src/", "tests/", "scripts/", "packaging/")
    changed = subprocess.check_output(["git", "--no-optional-locks", "diff", "--name-only"], cwd=ROOT, text=True).splitlines()
    added = subprocess.check_output(["git", "--no-optional-locks", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    changed = sorted(set(changed + [name for name in added if name.startswith(maintained)]))
    (ARTIFACT / "changed_files.json").write_text(json.dumps(changed, ensure_ascii=False, indent=2), encoding="utf-8")
    source_files = [path for path in (ROOT / "src").rglob("*") if path.is_file() and path.suffix in (".py", ".svg", ".ico", ".qm")]
    source_files += [ROOT / "configs/pdv_studio_defaults.toml", ROOT / "packaging/pdv_research_task012.spec"]
    (ARTIFACT / "source_freeze.json").write_text(json.dumps({path.relative_to(ROOT).as_posix(): sha(path)
        for path in sorted(source_files)}, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = """# PDV Studio Research · TASK-012

2026-11-06，Windows x64 免安装测试版。双击 `PDV Studio Research TASK012.exe`；从压缩包使用时请完整解压整个文件夹。

1. 打开数据，确认时间列、电压列和单位。
2. 顶部“工作区”选择经典 STFT 或人工分段。经典分析保留四步流程；人工分段使用独立图页和区间属性栏。
3. 分段时可切换原始信号、STFT 参考、经典速度、分段结果。新增分割线后，在右栏选择区间、阶段和算法；分析／导出按钮固定可见。
4. 经典速度页的低频设置位于“实验参数”。底部“诊断与数据”默认紧凑，可点击展开或拖动调整。

分段参考图使用实验绝对时间，与分割线和区间起止值一致；经典页及导出仍可选择起跳零点。研究算法使用冻结原生参数，经典 STFT 参数不等于这些方法的可调参数。

阶段默认推荐：加速→Dechirp；噪声→不估计（NaN）；其余阶段→STFT。推荐有研究适用条件，悬停查看原因。人工选择会保留；“采用推荐算法”才恢复自动选择。删除分割线保留左区间，可撤销当前通道编辑。

经典与分段共享导入数据和实验参数；切换工作区保留结果与视图。更改共享科学参数或范围会明确使依赖结果失效。候选编号仅为界面显示，CSV/metadata 保留真实通道标识。

这是 Research / Test 构建，不需要 Python/Conda，也不覆盖 Production 或其配置。验证细节及已知限制见 `VALIDATION.md`，改动见 `CHANGELOG.md`。
"""
    changelog = """# TASK-012 改动

- 经典分析与人工分段改为独立工作区，分别使用参数面板；普通绘图标签不再触发模式切换。
- 自动候选检测及采用候选保持当前速度图、缩放和页面；分析范围／全部结果／完整频谱及手动缩放状态跨重绘保留。
- 分段支持原始、STFT、已有经典速度和分段结果四种视图；分割线同步编辑，区间编号、阶段和算法单独显示，标签跟随缩放。
- 分割线不跨越相邻边界，区间连续且无重叠；数值编辑、鼠标拖动、删除和撤销保留稳定身份与设置。
- 计算分段 STFT 参考图保留已编辑的 ROI、分段设置及有效结果；“调整范围”明确打开原始参考图。
- 保守的阶段算法推荐；人工覆盖的来源随通道、拆分、复制和 JSON 保存／载入保留。
- 实验参数折叠，诊断面板默认低高度，分段分析／导出固定在侧栏底部；统一控件、颜色、间距及下拉图标。
- 候选名称简化但身份、数据映射与导出元数据保持；状态栏跟随当前工作区和通道。
- 速度／加速度切换保留自定义时间范围，按新物理量适配纵轴；分段速度参考固定绝对时间，避免事件零点造成分割线错位。
- 串行化两类异步分析，防止重复启动；迟到结果仍按修订号丢弃。
- 频率 ROI 和时间分割线在信号回调中重建时采用 Qt 所有权及延迟销毁；关闭窗口清理所有新增图形回调。
- 计算算法、速度公式、LiF/角度修正及正式导出数值流程未改动；不平滑、不插值、不填补实验数据。
"""
    validation = f"""# TASK-012 验证

日期：2026-11-06；分支：`{branch}`。测试主机为 Windows 11 x64，build 26200。

完整日志、逐例报告及截图位于开发工作树 `artifacts/research_clean_task12/`；随包的此文件是验收摘要。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 最终全量回归 | {full} passed；7 个既有历史检查单独排除 | `pytest_delivery_full.log/.xml`、`historical_exclusions.json` |
| GUI 子集 | {gui} passed，0 failures/errors；无原生访问异常 | 同一最终全量 JUnit 中的 GUI 用例 |
| TASK-012 交互合同 | {contract} passed，含真正鼠标拖动、24 次 ROI 重建、10 次窗口重建、参考图 ROI/结果保留 | 同一最终全量 JUnit 中的 test_task012_workspaces 用例 |
| Ruff | 维护源码零错误；范围 src/tests/scripts/packaging | `ruff_final.log` |
| mypy | 150 个源码文件通过 | `mypy_final.log` |
| 数值回归 | 13 文件、17 流、每流 9 类数组及质量标志与 TASK-011 逐点一致 | `numerical_parity.json` |
| 包内源码核对 | 101 个应用模块代码对象与交付源码一致 | `bundle_code_parity_acceptance.json` |
| 独立 Windows EXE | 8/8 验收运行通过；Conda/Python 源路径从环境移除 | `release_acceptance_*/verification.json` |
| 原生鼠标键盘 | 工作区、增线、阶段推荐、撤销、参考图、自动候选及正常关闭通过 | `native_interaction_final.json`、`native_*.jpg` |
| 数据与 Git 边界 | 全部通过；无 commit/push/merge/promotion | `boundary_verification.json`、`boundary_final_check.json` |

最终 EXE 的 SHA-256：`{exe_sha}`。八次打包验证均记录同一 EXE 哈希。

实测覆盖 `20260607.csv` 两路及 ch1–ch4，经典 STFT、分段分析、通道切换、候选、模式往返、四种参考图分割线编辑、阶段与算法来源、速度/加速度、LiF/角度修正、CSV/metadata 逐点读回、过期结果与后台互锁。ch1/ch2/ch4 在本工作树 data/raw 中缺失，使用 TASK-009 的同 SHA 原样归档副本；映射位于其 data_index.json。

布局覆盖 1024×640、1280×800、1600×1000。Windows 原生 DPR=2；通过进程级 Qt 缩放得到有效 DPR=1/1.25/1.5/2（100/125/150/200%），不改系统设置。实际窗口、可见图形、侧栏尺寸均记录在逐例 report.json；超过当前屏幕可用面积的请求按 Qt 实际尺寸记录。分析和导出按钮始终位于可见固定区域。

## 遗留问题与边界

- 7 项旧检查涉及历史启动器合同、旧冻结哈希和缺失的 T25 归档 NPZ。完整首轮测试也保留了这些失败；本任务未改写历史证据以制造通过。排除清单沿用 TASK-011 记录。
- 开发中一次长进程 GUI 回归触发原生 ROI 访问异常。随后补充 Qt 延迟销毁与关闭清理，最终连续 GUI 与窗口/ROI 压力测试通过。失败日志保留为 `pytest_gui_release.log`。
- Dechirp/VarPro/Clutter VarPro 仍沿用冻结研究假设，真实实验无 GT；质量通过不等于支路物理身份已确认。没有宣称算法普遍胜出。
- 未验证多显示器混合 DPI 热切换、低于 1024×640 的窗口或其他 Windows 版本。测试包未签名。

Production 的 26598 个文件（含 .git）进行完整 SHA-256/大小/mtime 前后核对；raw 的全部 11 个文件再次核对 SHA-256；13 个索引原始输入也逐项匹配。收尾再次检查 Production 完整路径/大小/mtime、Git 与全量哈希后快照一致。算法、core 与 configs 不在改动列表中。

独立打包文件位于 `../../release/`，只保留一个程序文件夹和一个 ZIP。最终截图位于 `release_acceptance_normal/20260607_native/` 与 `release_acceptance_layout/`；其他 staging、source_smoke、frozen、final、acceptance 目录均为保留的开发过程，不是交付入口。
"""
    for name, content in (("README.md", readme), ("CHANGELOG.md", changelog), ("VALIDATION.md", validation)):
        with (ARTIFACT / name).open("x", encoding="utf-8") as handle:
            handle.write(content)
        shutil.copyfile(ARTIFACT / name, BUNDLE / name)
    (ARTIFACT / "implementation/README.md").write_text(
        "此处仅保存 TASK-011 到 TASK-012 的一次性改写过程，不应再次执行。正式构建使用 scripts/build_task012.ps1，验收使用 task012_checks.py、task012_verify_package.py。\n", encoding="utf-8")
    screenshots = ARTIFACT / "screenshots"
    screenshots.mkdir(exist_ok=False)
    for source_name in ("01_classic_velocity.png", "02_acceleration.png", "03_reference_raw.png", "03_reference_stft.png", "04_segmented_result.png", "05_manual_1024x640.png"):
        shutil.copyfile(ARTIFACT / "release_acceptance_normal/20260607_native" / source_name, screenshots / source_name)
    with zipfile.ZipFile(ZIP, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(BUNDLE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT / "release"))
    with zipfile.ZipFile(ZIP) as archive:
        assert archive.testzip() is None
        for entry in archive.infolist():
            assert hashlib.sha256(archive.read(entry)).hexdigest() == sha(ROOT / "release" / entry.filename)
    assert len(list((ROOT / "release").iterdir())) == 2
    manifest = {"status": "complete", "date": "2026-11-06", "branch": branch,
        "executable_sha256": exe_sha, "zip_sha256": sha(ZIP), "bundle": str(BUNDLE), "zip": str(ZIP),
        "bundle_bytes": sum(path.stat().st_size for path in BUNDLE.rglob("*") if path.is_file()),
        "zip_bytes": ZIP.stat().st_size, "source_freeze_sha256": sha(ARTIFACT / "source_freeze.json"),
        "gui_tests": gui, "full_regression_tests": full, "frozen_cases": reports,
        "package_equals_verified_folder": True, "release_top_level_items": 2}
    (ARTIFACT / "delivery_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    note = f"""# 2026-11-06 · TASK-012 GUI 重构与交互修复

- 完成状态：已交付 Research / Test 测试版；分支 `{branch}`，HEAD 未改变，修改未提交。
- 核心成果：独立经典/分段工作区、持久视图、四图分割线、稳定区间身份、保守算法推荐及人工覆盖来源、紧凑参数/诊断布局、异步互锁、Qt ROI/分割线生命周期修复。
- Artifact：`{ARTIFACT}`；交付：`{BUNDLE}`、`{ZIP}`。
- 测试：最终全量 {full} passed（7 项既有历史排除）；GUI 子集 {gui} passed；交互合同 {contract} passed；Ruff/mypy 通过；8 次独立 EXE 验收通过；13 文件/17 流与 TASK-011 数组/标志逐点一致。
- 边界：Production 全量哈希/Git 不变；raw 全部哈希不变；TASK-008～010 归档不变；未 commit、push、merge 或 promotion；验收配置位于本任务目录。
- 遗留：7 项历史归档检查；混合 DPI 热切换及其他 Windows 版本未测；真实支路物理身份与研究算法适用条件仍需实验判断。
- 下一步：实验员用自己的常用数据试用；如需推广，单独安排其他 Windows/混合 DPI 验证。

修改文件：
""" + "\n".join(f"- `{name}`" for name in changed) + "\n"
    NOTE.parent.mkdir(parents=True, exist_ok=True)
    with NOTE.open("x", encoding="utf-8") as handle:
        handle.write(note)
    print(json.dumps({"bundle": str(BUNDLE), "zip": str(ZIP), "zip_bytes": ZIP.stat().st_size, "gui_passed": gui}, ensure_ascii=False))


if __name__ == "__main__":
    main()
