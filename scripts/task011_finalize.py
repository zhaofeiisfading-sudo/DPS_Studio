"""Assemble the reviewed delivery only after every TASK-011 acceptance gate passes."""
from __future__ import annotations

import hashlib
import argparse
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/research_clean_task11"
BUNDLE = ARTIFACT / "portable_v4/PDV_Studio_Research_TASK011"
CHECKS = ARTIFACT / "checks"
NOTE = Path("D:/Research/Notes/05项目/dps/2026-11-05_TASK-011_人工分段与算法池集成.md")


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_json(path: Path, value: Any) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(ROOT), *args])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-pending-boundary", action="store_true",
                        help="Deliver verified software while explicitly retaining a pending boundary exception")
    args = parser.parse_args()
    matrix = [read(CHECKS / "runtime_matrix_v3/matrix.json")[0],
              *read(CHECKS / "runtime_gui_final_v5/matrix.json")]
    assert matrix and all(row["exit_code"] == 0 for row in matrix)
    counts = {"tests": 0, "failures": 0, "errors": 0}
    xml_paths = [CHECKS / "runtime_matrix_v3/core_research.xml",
                 *(CHECKS / "runtime_gui_final_v5").glob("*.xml")]
    for xml in xml_paths:
        for suite in ET.parse(xml).getroot().iter("testsuite"):
            for key in counts:
                counts[key] += int(suite.attrib.get(key, "0"))
    assert counts["tests"] >= 1250 and counts["failures"] == counts["errors"] == 0
    frozen = read(CHECKS / "frozen_gui_v4/verification.json")
    assert {row["case"] for row in frozen} == {"normal", "ch1", "ch2", "ch3", "ch4"}
    assert all(row["passed"] and row["all_application_modules_inside_bundle"] for row in frozen)
    native = read(CHECKS / "native_interaction.json")
    assert native["passed"] and native["roi_native_drag_validated"]
    assert Path(native["packaged_executable"]).resolve() == (BUNDLE / "PDV Studio Research TASK011.exe").resolve()
    boundary = read(ARTIFACT / "boundary_verification_final.json")
    detail = read(ARTIFACT / "boundary_detail.json")
    delivery_recheck = read(CHECKS / "delivery_boundary_recheck.json")
    assert delivery_recheck["checks"] and all(delivery_recheck["checks"].values())
    strict_boundary = bool(boundary) and all(boundary.values())
    acceptance_path = ARTIFACT / "boundary_exception_acceptance.json"
    exception_accepted = acceptance_path.exists() and read(acceptance_path).get("user_accepted") is True
    if not strict_boundary:
        assert all(detail[key] for key in (
            "production_files_outside_git_unchanged", "production_git_branch_head_status_unchanged",
            "production_main_index_unchanged", "research_head_unchanged", "research_branch_unchanged",
            "research_raw_unchanged", "frozen_task8_unchanged", "frozen_task9_unchanged",
            "frozen_task10_unchanged", "drift_confined_to_codex_refs_and_git_objects"))
        assert exception_accepted or args.allow_pending_boundary, "Client Git metadata exception is pending"
    delivery_state = ("COMPLETE" if strict_boundary else "COMPLETE_WITH_ACCEPTED_CLIENT_GIT_EXCEPTION"
                      if exception_accepted else "SOFTWARE_VERIFIED_BOUNDARY_EXCEPTION_PENDING")
    boundary_text = ("Production 全目录含 .git、两边 raw 及 TASK-008～010 校验保持" if strict_boundary else
                     "Production 非 .git 内容、main/HEAD/index、两边 raw 及 TASK-008～010 保持；"
                     "严格 .git 不变检查未通过，变化限于 Codex turn-diff 元数据及对象")
    status_text = ("软件功能与验证完成；客户端 Git 元数据例外已获确认" if exception_accepted else
                   "已完成并验证" if strict_boundary else
                   "软件功能与验证完成；严格 .git 边界例外等待用户确认，目标尚未标记完成")
    parity = read(CHECKS / "classic_parity/report.json")
    assert parity["passed"] and parity["raw_files"] == 13 and parity["streams"] == 17
    manual = read(CHECKS / "real_manual/report.json")
    assert manual["raw_files"] == 13 and manual["streams"] == 17
    assert all(row["export_roundtrip"] and not any(part["error"] for part in row["algorithms"])
               for row in manual["results"])
    assert "Success: no issues" in (CHECKS / "mypy_delivery_v4.log").read_text(encoding="utf-8")
    assert "All checks passed" in (CHECKS / "ruff_delivery_v4.log").read_text(encoding="utf-8")
    assert not NOTE.exists() and not (ARTIFACT / "README.md").exists()

    # Initial Research status was clean. Recover any ancillary test preimages
    # absent from the pre-copy migration backups, without modifying the Git index.
    modified = [part.decode("utf-8") for part in git("diff", "--name-only", "-z").split(b"\0") if part]
    recovered = []
    for relative in modified:
        backup = ARTIFACT / "pre_migration" / relative
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            with backup.open("xb") as handle:
                handle.write(git("show", f"HEAD:{relative}"))
            recovered.append({"path": relative, "origin": "initial clean HEAD Git blob",
                              "note": "Git-normalized line endings may differ from checkout"})
    write_json(ARTIFACT / "ancillary_backup_manifest.json", recovered)

    screenshots = ARTIFACT / "screenshots"
    screenshots.mkdir(exist_ok=False)
    for case, name in (("normal", "01_classic_stft.png"), ("normal", "02_manual_gates.png"),
                       ("normal", "03_segmented_velocity.png"), ("normal", "04_segmented_frequency.png"),
                       ("ch3", "03_segmented_velocity.png"), ("ch4", "03_segmented_velocity.png")):
        shutil.copyfile(CHECKS / "frozen_gui_v4" / case / name, screenshots / f"{case}_{name}")

    branch = git("branch", "--show-current").decode().strip()
    head = git("rev-parse", "HEAD").decode().strip()
    acceptance = {
        "status": delivery_state, "task": "TASK-011", "task_date": "2026-11-05",
        "completion_date": "2026-11-06", "branch": branch, "head": head,
        "production_reference": "677a22df0566f8403786a0b4d8eac11ff55bcf4f",
        "pytest": counts, "archived_checks_deselected": 7,
        "frozen_gui_cases": frozen, "native_interaction": native,
        "classic_parity_raw_files": 13, "classic_parity_streams": 17,
        "manual_raw_files": 13, "manual_streams": 17,
        "boundaries": boundary, "commit_push_merge_promotion": "NONE",
        "delivery_boundary_recheck": delivery_recheck,
        "strict_git_invariance_passed": strict_boundary,
        "client_git_metadata_exception_user_accepted": exception_accepted,
    }
    write_json(ARTIFACT / "acceptance.json", acceptance)
    source_files = [p for directory in (ROOT / "src", ROOT / "packaging")
                    for p in directory.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    source_files += list((ROOT / "scripts").glob("task011*.py"))
    source_files += [ROOT / "scripts/build_task011.ps1", ROOT / "configs/pdv_studio_defaults.toml",
                     ROOT / "tests/unit/test_task011_segmentation.py",
                     ROOT / "tests/unit/gui/test_task011_manual_segments.py"]
    write_json(ARTIFACT / "source_freeze.json", {
        p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(source_files))})
    write_json(ARTIFACT / "changed_files.json", {
        "modified_tracked": modified,
        "new_untracked": [p.decode("utf-8") for p in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p]})

    readme = f"""# PDV Studio Research / Test · TASK-011

任务日期 2026-11-05；2026-11-06 交付。状态：{status_text}。基础 GUI/处理链来自 Production v0.1.6，开发分支 `{branch}`，未提交分支变更。

## 打开测试版

本机可直接双击 [PDV Studio Research TASK011.exe](portable_v4/PDV_Studio_Research_TASK011/PDV%20Studio%20Research%20TASK011.exe)，也可使用本目录的 `Open_PDV_Research_TASK011.cmd`。
移至其他电脑时，完整解压 `PDV_Studio_Research_TASK011_Windows_x64.zip`，保留 EXE 旁的 `_internal` 文件夹。无需 Python 或 Conda。已在本机 Windows 桌面验证，尚未在另一台物理电脑验证；包未签名。

## 使用

1. 沿用原有“打开数据”流程，明确时间/电压单位和列。原有时频图中框选的时间与频带 ROI 会传入分段页；也可在分段页点击“ROI 范围”，拖动蓝色两端并松开确认时间范围。直接调整时间范围后使用当前全局频带参数；需要限定拍频时，在原有时频图中重新框选时间与频带。
2. 使用经典 STFT 时，原有快速分析、时频图、人工频率范围、速度修正和导出流程照常使用。
3. 切换“人工分段”，选通道，点击“新增分割线”；拖动竖线或使用数值框调节，选择分割线后可删除。逐段设置阶段和算法。
4. 点击“分析当前通道”，切换校正速度/表观速度/拍频复核；悬停可查看质量。各通道独立分析，可显式将方案应用到全部通道。编辑或参数变化后重新分析。
5. “导出结果”在所选位置新建目录，保留 CSV 与 metadata；“保存分段/载入分段”支持复用方案，不覆盖已有文件。分段导出使用实验绝对时间，不填事件前零平台。

算法池提供 STFT、Dechirp、VarPro、Clutter VarPro 和“不估计（NaN）”。阶段与建议不自动决定算法。STFT 参数来自原有面板；研究算法保留冻结窗口、128 点步长与事件/前缀假设，详见 metadata。跨段不插值、不平滑、不连接不同区段；边界窗口保留原始上下文并标记 `BOUNDARY_CONTEXT`。

## 验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| pytest | {counts['tests']} passed；7 项历史检查明确排除 | `checks/runtime_matrix_v3/core_research.xml`、`checks/runtime_gui_final_v5/` |
| Ruff | core、GUI、算法副本及本任务脚本/测试通过 | `checks/ruff_delivery_v4.log` |
| mypy | 严格项目配置，本任务类型边界通过；冻结依赖静默跟随 | `checks/mypy_delivery_v4.log` |
| 经典数值回归 | 13 文件、17 路；9 类数组逐点相同，质量/来源相同 | `checks/classic_parity/report.json` |
| 实测分段与导出 | 13 文件、17 路、四算法，无算法异常；CSV 回读相同 | `checks/real_manual/report.json` |
| 打包程序 | 正常数据及 ch1–ch4：经典、四算法分段、ROI 编辑失效/重算、方案往返、导出通过 | `checks/frozen_gui_v4/verification.json` |
| 桌面操作 | 独立 EXE 的原生交互复核通过 | `checks/native_interaction.json` |
| 安全边界 | {boundary_text} | `boundary_verification_final.json`、`boundary_detail.json` |

7 项排除项的名称、原因见 `checks/runtime_matrix_v3/archived_exclusions.json`：两项旧 Production 启动器假设、四项过期源码/配置冻结假设、一项缺失的历史 TASK-025 轨迹。未修改旧归档以伪造通过；不把这些检查表述为已通过。较早验证中的迁入、长路径与 DLL 失败日志均保留，以本表列出的最终记录为准。

## 科学与运行边界

真实数据无物理真值，验证的是软件一致性、状态、质量和导出，不能据此宣称速度更准确或支路已确认。研究算法的安静前缀、可检测事件、杂波持续性与目标身份假设仍需实验员判断。Clutter VarPro 可能移除前缀中已存在的目标信号。候选点不等于通过质量门槛的结果；缺失保留 NaN。极短区段可无估计中心，metadata 记录 0 frames。

表观速度与校正速度分列；角度后接既有 LiF 修正。非负拍频不自动判断运动方向。研究算法可能耗时，分析中需等待完成；当前未实现取消任务。其他 Windows 版本、另一台电脑和特殊显卡/显示缩放尚未逐一实测。

配置命名空间独立为 `DPS Studio Research / PDV Studio TASK011 Test`。运行入口保护 Production 与 data/raw 写入；测试包不读取 Production 实时源码。未执行 commit、push、merge、promotion 或其他 Git 写命令。

恢复聊天后检测到共享 `.git/refs/codex/turn-diffs` 检查点及配套对象变化，路径与时间指向 Codex 客户端自动元数据。未清理或恢复这些文件，未把严格 `.git` 校验报告为通过；逐文件差异保留在 `boundary_detail.json`。例外确认状态以 `acceptance.json` 为准。
交付前再次逐文件核对 Production、两侧 raw 和 TASK-008～010，相对上述快照无新增变化，见 `checks/delivery_boundary_recheck.json`；该复核不消除先前的客户端元数据例外。

## 复现与来源

- [架构与适用边界](DESIGN.md)、`migration_manifest.json`、`test_migration_manifest.json`、`pre_migration/`。
- `scripts/build_task011.ps1`：PowerShell 7、本地既有 dps-studio 环境构建，拒绝覆盖既有构建目录。
- `scripts/task011_test_matrix.py`：pytest 分批隔离 Qt，使用短临时路径，不修改系统长路径设置。
- `scripts/task011_real_regression.py`、`scripts/task011_verify_package.py` 与 `scripts/task011_boundaries.py`：回归、独立 EXE 与全边界验证。
- `source_freeze.json`、`delivery_manifest.json` 与 ZIP SHA-256：源码、交付文件及包完整性。

`portable/` 是首次 DLL 依赖冲突的失败包，仅保留诊断；`portable_v2/`、`portable_v3/` 为中间验证版本。请使用 `portable_v4/` 或最终 ZIP。冲突与修复证据见 `checks/dll_resolution_fix.json`、`checks/dll_audit_v2.json`。中断留下的 `frozen_gui_v2/` 和较早版本 `frozen_gui_v3/` 不是最终验收记录。
"""
    write(ARTIFACT / "README.md", readme)
    quick = """PDV Studio Research / Test - TASK-011

Run PDV Studio Research TASK011.exe. Keep the entire _internal folder beside it.
No Python/Conda installation is required. This is a Research/Test build.
Classic STFT and manual segmented analysis are available in the analysis-mode selector.
Import data with explicit units, confirm the ROI, then add/move/delete time boundaries
and select each segment's stage and algorithm. Analyze the active channel and export.
NaN gaps and per-segment provenance are preserved. Research algorithms require review
of their prefix/event/branch assumptions. Windows 11 on the build machine was tested;
another physical machine was not tested. Unsigned internal test build.
"""
    write(BUNDLE / "README_TASK011.txt", quick)
    write(ARTIFACT / "Open_PDV_Research_TASK011.cmd",
          '@echo off\nstart "" "%~dp0portable_v4\\PDV_Studio_Research_TASK011\\PDV Studio Research TASK011.exe"\n')
    archive = ARTIFACT / "PDV_Studio_Research_TASK011_Windows_x64.zip"
    with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=6) as zipper:
        for path in sorted(BUNDLE.rglob("*")):
            if path.is_file():
                zipper.write(path, path.relative_to(BUNDLE.parent).as_posix())
    with ZipFile(archive) as zipper:
        assert zipper.testzip() is None
    archive_sha = sha(archive)
    write(ARTIFACT / f"{archive.name}.sha256", f"{archive_sha}  {archive.name}\n")
    write_json(ARTIFACT / "delivery_manifest.json", {
        "zip": {"name": archive.name, "sha256": archive_sha, "bytes": archive.stat().st_size},
        "bundle": {path.relative_to(BUNDLE).as_posix(): {"sha256": sha(path), "bytes": path.stat().st_size}
                   for path in sorted(BUNDLE.rglob("*")) if path.is_file()},
        "acceptance": "acceptance.json", "tests": counts})
    NOTE.parent.mkdir(parents=True, exist_ok=True)
    write(NOTE, f"""# TASK-011｜人工分段与统一算法池集成

- 日期：任务 2026-11-05；完成 2026-11-06。
- 分支：`{branch}`；HEAD `{head}`；状态：{status_text}，Research/Test，未提交分支变更。
- 结论：基于 Production v0.1.6 成熟 GUI/处理链，独立集成人工分段编辑与 STFT/Dechirp/VarPro/Clutter VarPro 算法池；可绘图复核、保存分段和导出 CSV/metadata。
- 修改：选择性迁入共享 core/GUI/config；新增 `core/segmentation`、`algorithms/task008`、`gui/segment_workspace.py`、`gui/research_window.py`、安全入口、打包/回归脚本及测试。完整清单见 artifact 的 `changed_files.json`，前像见 `pre_migration/`。
- Artifact：`{ARTIFACT}`；直接程序：`{BUNDLE / 'PDV Studio Research TASK011.exe'}`；最终 ZIP：`{archive.name}`；SHA-256：`{archive_sha}`。
- 测试：pytest {counts['tests']} passed，7 项历史检查明确排除；Ruff/mypy 通过。13 个真实原始文件、17 路经典数组逐点一致；同数据四算法分段及导出通过；独立 EXE 正常及 ch1–ch4 全部 GUI 回归通过，另有原生桌面操作复核。
- 边界：{boundary_text}。测试程序不依赖 Production 实时源码，使用独立配置。未执行 Git 写命令。客户端检查点差异未清理、未伪装通过；确认状态见 acceptance.json。
- 遗留与限制：实测无物理真值，研究算法的前缀/事件/目标身份假设需判断；极短段可无中心，保留 NaN。运行中暂不支持取消；未在第二台物理电脑逐一验证，程序未签名。过期历史冻结与缺失 TASK-025 产物未伪造修复。初次 DLL 冲突包仅作诊断，使用 portable_v4 或最终 ZIP。
""")
    print(json.dumps({"status": delivery_state, "tests": counts, "archive": str(archive),
                      "archive_sha256": archive_sha, "note": str(NOTE)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
