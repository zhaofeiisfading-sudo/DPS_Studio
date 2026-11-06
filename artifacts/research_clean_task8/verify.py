"""Executable acceptance of actual files, counts, tests and immutable boundaries."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from PIL import Image

from .audit import OUT, ROOT, sha, snapshot
from .catalog import METHODS, run_folder
from .runner import write_json

NOTE = Path("D:/Research/Notes/05项目/dps/2026-11-04_TASK-008_PDV算法开放探索.md")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def gates() -> None:
    before = (OUT/"checks/pytest_before.log").read_text(encoding="utf-8")
    final = (OUT/"checks/pytest_final.log").read_text(encoding="utf-8")
    new = (OUT/"checks/pytest_new.log").read_text(encoding="utf-8")
    failures_before = re.findall(r"^FAILED (\S+)", before, re.M)
    failures_final = re.findall(r"^FAILED (\S+)", final, re.M)
    assert failures_before == failures_final and len(failures_final) == 6
    summary = re.findall(r"(\d+) failed, (\d+) passed", final)[-1]
    fresh_tests = re.findall(r"(\d+) passed", new)[-1]
    assert int(summary[1]) == 913 and int(fresh_tests) == 30
    quality = read_json(OUT/"checks/quality_checks_final.json")
    assert all(row["exit_code"] == 0 for row in quality)
    replay = read_json(OUT/"checks/reproduction_smoke/replay_comparison.json")
    assert len(replay) == 14*12 and all(r["trajectory_reproduced"] for r in replay)
    original_frozen = read_json(OUT/"source_freeze.json")
    assert all(sha(ROOT/p) == digest for p, digest in original_frozen.items())
    baseline_frozen = read_json(OUT/"baseline_audit_registration.json")["sources"]
    assert all(sha(ROOT/p) == digest for p, digest in baseline_frozen.items())
    for stage, count in (("fresh", 96), ("phase_stress", 50), ("real", 17)):
        data = pd.read_csv(OUT/"tables"/f"all_{stage}_metrics.csv")
        assert len(data) == len(METHODS)*count and (data.status == "OK").all()
        assert all(len(data[data.method == name]) == count for name in METHODS)
        # New controls must use exactly the original voltage/time values.
        original = data[data.method == "varpro"].set_index("case_id")
        for name in ("legacy_m0_512", "legacy_m0_768"):
            extra = data[data.method == name].set_index("case_id").reindex(original.index)
            assert (extra.source_voltage_sha256 == original.source_voltage_sha256).all()
            assert (extra.source_time_sha256 == original.source_time_sha256).all()
    validation = dict(new_pytest=dict(passed=30, failed=0, log="pytest_new.log"),
        full_pytest=dict(passed=913, failed=6, preexisting_failures_unchanged=True,
                         failed_tests=failures_final, log="pytest_final.log"),
        quality_checks=quality, original_source_freeze_unchanged=True,
        baseline_amendment_unchanged=True, smoke_replayed_method_cases=len(replay),
        formal_streams=2282, method_execution_failures=0,
        baseline_wrapper_first_attempt="exclusive invariance-log filename collision; retried in separate stage; original retained")
    write_json(OUT/"checks/validation.json", validation)
    for name in METHODS:
        write_json(OUT/name/"tests_results.json", dict(
            package_new_tests_passed=30, related_full_suite_passed=913,
            preexisting_full_suite_failures=6, source="../checks/validation.json",
            baseline_boundary_fallback_contract=name.startswith("legacy_m0"),
            in_memory_input_invariance=True, raw_real_streams=17,
            reproducibility_cases=12, identity_is_unvalidated=True))
    print("Gates verified: 30 new tests; 913 passed / six identical existing failures", flush=True)


def notes() -> None:
    before = read_json(OUT/"boundary_before.json")
    source_files = sorted(p.relative_to(ROOT).as_posix() for p in OUT.rglob("*.py")
        if "checks" not in p.relative_to(OUT).parts and "development_sources00" not in p.parts)
    modified = ["README.md", "COMPARISON.md", "tests/unit/test_research_task008.py",
                "tests/unit/test_research_task008_baseline_audit.py", *source_files]
    write_json(OUT/"checks/modified_source_files.json", modified)
    text = f"""# 2026-11-04 TASK-008｜PDV 算法开放探索

状态：研究实验、完整比较与研究结论完成。停止于 Research；没有进入 Production、promotion 或下一 TASK。

工作区：`{ROOT}`。分支 `{before['research']['branch']}`，HEAD `{before['research']['head']}`，无新提交。

范围：14 方法/对照，全部 13 原始波形文件、17 电压通道；96 新种子主合成＋50 随机初相低速压力。正式方法流 2282，执行异常 0。350 张初版图保留可追溯来源，最终图清单 408 PNG（238 真实＋168 固定合成＋2 总图），旧12方法两张总图另存。

核心量化：相干杂散预测＋VarPro 支持后失败率 8.70%，完整历史 M0 768 为 13.64%，去DC＋截断512为17.79%；相对完整M0宏失败差 -4.93 个百分点，配对95%区间 [-11.51,+1.68]，不能声称全面胜出。收益主要来自持续相干杂散族：RMSE 1.364 m/s、覆盖99.8%。强加速 Dechirp 3.360 m/s，对照截断256为6.438。VarPro 单独整体不占优，15 m/s 候选RMSE641.908；短窗矩阵束双分量仅5/632帧满足双频±50MHz诊断。保留失败，不以平滑判断成功。

起跳：共享检测已检出中位绝对误差0.189ns，但普通检测漏13/88，杂散组合漏5/88；不能宣称普适亚纳秒精度。零速和信号消失均未伪造实测零值。80k点 VarPro/组合耗时中位约3.18/3.20s，优先考虑局部研究。

真实记录没有GT；速度图仅为1550nm假设的等效表观速度，波长/参考频移/AC参数未重新标定；corrected velocity 全NaN。谱支持、覆盖和R2不是物理正确率。

测试：新增30项通过；全仓913通过、6失败，与任务前同一六项（历史启动器、冻结记录/缺失旧artifact）。Ruff、严格mypy通过。14方法×12固定合成例在新目录重放，168条轨迹与冻结结果一致。

修改：根 `README.md`（原文已备份）、新增 `COMPARISON.md`、两个 `tests/unit/test_research_task008*.py`，以及 `artifacts/research_clean_task8/` 独立实现/协议/运行/图表/失败/检查。准确源文件表：`{OUT / 'checks/modified_source_files.json'}`。

Git/raw/Production边界：保留任务前12375条tracked删除与既有untracked；未stage、commit、push、merge。全部24个raw及辅助文件SHA-256前后一致，Research既有源文件除授权README外未改，Production代码、配置、HEAD/index/status未改。证据：`{OUT / 'checks/final_boundary_check.json'}`。

报告：`{ROOT / 'COMPARISON.md'}`。入口：`{ROOT / 'README.md'}`。artifact：`{OUT}`。逐数据表：`tables/real_diagnostics.csv`；完整新种子指标：`tables/all_fresh_metrics.csv`；源码冻结和补充M0契约分别见`source_freeze.json`与`BASELINE_AUDIT.md`。

下一步建议（未执行）：相干nuisance模型的漂移/前缀含目标反例；强连续加速局部Dechirp；带多极值与条件数诊断的局部VarPro；有已知前端和相干边界的分段时域反演。保留原strongest及廉价短窗门槛；不自动推进。
"""
    NOTE.parent.mkdir(parents=True, exist_ok=True)
    with NOTE.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"Created requested research note: {NOTE}", flush=True)


def boundaries() -> None:
    snapshot("after")
    before, after = read_json(OUT/"boundary_before.json"), read_json(OUT/"boundary_after.json")
    raw_unchanged = before["raw"] == after["raw"]
    production_unchanged = (before["production"] == after["production"]
                            and before["production_code"] == after["production_code"])
    research_changes = [p for p, digest in before["research_code"].items()
                        if after["research_code"].get(p) != digest]
    assert research_changes == ["README.md"], research_changes
    git_unchanged = all(before["research"][key] == after["research"][key]
                        for key in ("head", "branch", "index"))
    preserved_status = set(before["research"]["status"]).issubset(after["research"]["status"])
    assert raw_unchanged and production_unchanged and git_unchanged and preserved_status
    write_json(OUT/"checks/final_boundary_check.json", dict(
        raw_unchanged=raw_unchanged, raw_and_auxiliary_files=len(before["raw"]),
        production_unchanged=production_unchanged, research_existing_source_changes=research_changes,
        authorized_root_readme_backup_sha256=sha(OUT/"README_before.md"),
        original_root_readme_sha256=before["research_code"]["README.md"],
        git_head_branch_index_unchanged=git_unchanged, preexisting_status_preserved=preserved_status,
        new_status_entries=sorted(set(after["research"]["status"])-set(before["research"]["status"])),
        no_commit_push_promotion=True))
    assert sha(OUT/"README_before.md") == before["research_code"]["README.md"]
    print("Raw x24, Production and Git/index boundaries verified unchanged", flush=True)


def delivery() -> None:
    manifest = pd.read_csv(OUT/"figure_manifest.csv")
    assert len(manifest) == 408
    assert sum(manifest.domain == "REAL_NO_GT") == 238
    images = []
    for row in manifest.itertuples():
        path = OUT/row.path
        with Image.open(path) as im:
            width, height = im.size
            im.verify()
        assert width >= 1000 and height >= 600
        images.append(dict(path=row.path, width=width, height=height))
    real = pd.read_csv(OUT/"tables/all_real_metrics.csv")
    for row in real.itertuples():
        folder = run_folder(OUT, row.method, "real", row.case_id)
        result = np.load(folder/"trajectory.npz")
        csv = pd.read_csv(folder/"trajectory.csv")
        assert len(csv) == len(result["time_s"])
        assert np.isnan(result["corrected_velocity_m_s"]).all()
        for col in ("frequency_hz", "accepted_hz", "equivalent_apparent_velocity_m_s"):
            np.testing.assert_allclose(csv[col].to_numpy(), result[col], rtol=1e-12,
                                       atol=1e-6, equal_nan=True)
    docs = [ROOT/"README.md", ROOT/"COMPARISON.md", OUT/"README.md"]
    docs += [OUT/name/"README.md" for name in METHODS]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert len(re.findall(r"^# ", text, re.M)) == 1
        for href in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if href.startswith(("http:", "https:", "#")):
                continue
            assert (path.parent/href).resolve().exists(), (str(path), href)
    assert NOTE.is_file()
    write_json(OUT/"checks/delivery_verification.json", dict(
        active_png_figures=408, real_csv_trajectories=238,
        all_local_report_links_resolve=True, all_corrected_velocity_nan=True,
        note_path=str(NOTE), note_sha256=sha(NOTE), image_dimensions=images))
    source_files = [p for p in OUT.rglob("*.py") if "checks" not in p.relative_to(OUT).parts]
    source_files += [ROOT/"README.md", ROOT/"COMPARISON.md", NOTE,
                    ROOT/"tests/unit/test_research_task008.py",
                    ROOT/"tests/unit/test_research_task008_baseline_audit.py"]
    write_json(OUT/"checks/final_source_manifest.json", {str(p): sha(p) for p in source_files})
    print("Delivery verified: 408 figures, 238 numeric real trajectories, links and note", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("gates", "notes", "boundaries", "delivery"))
    args = parser.parse_args()
    {"gates": gates, "notes": notes, "boundaries": boundaries, "delivery": delivery}[args.stage]()
