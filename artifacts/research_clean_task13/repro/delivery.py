"""Reviewable local-only delivery records. Never pushes or changes Production."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from scripts.check_git_hygiene import violations
from .experiment import OUT, ROOT, write_json
from .git_governance import BASE, BRANCH, ORIGINAL, git, sha

NOTE = Path("D:/Research/Notes/05项目/dps/2026-11-06_TASK-013_分阶段算法与Git治理.md")


def write_text(name: str, text: str) -> None:
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text.strip() + "\n")


def prepare() -> None:
    boundary = json.loads((OUT / "checks/boundary_verification_final.json").read_text(encoding="utf-8"))
    if not all(value for key, value in boundary.items() if key.endswith("_unchanged")):
        raise RuntimeError("Boundary acceptance is incomplete")
    before = json.loads((OUT / "checks/boundary_before.json").read_text(encoding="utf-8"))
    released = before["release"]
    package_bytes = sum(item.get("bytes", 0) for item in released.values())
    package_count = sum("bytes" in item for item in released.values())
    bundle = OUT / "git_backup/unpushed_task012.bundle"
    git("bundle", "verify", str(bundle))
    baseline_data = ["docs/原始数据.csv", "docs/旧软件速度时间数据.csv", "docs/旧软件新参数.dat",
                     "data/reference/legacy(旧软件参考速度)/legacy_velocity_time.csv"]
    preservation = []
    for name in baseline_data:
        old = git("rev-parse", f"{BASE}:{name}").decode().strip()
        current = git("hash-object", "--path", name, "--", name).decode().strip()
        if old != current:
            raise RuntimeError(f"Untracked local data changed: {name}")
        preservation.append({"path": name, "base_blob_equals_local_filtered_blob": True,
                             "local_sha256": sha(ROOT / name), "bytes": (ROOT / name).stat().st_size})
    write_json(OUT / "checks/untracked_data_preservation.json", preservation)
    write_text("GIT_CLEANUP.md", f"""
# TASK-013 Git 清理报告

**已完成；没有push、force push、远端分支删除、硬重置或破坏性清理。**

- 开始：Research分支`{BRANCH}`，HEAD`{ORIGINAL}`，工作区干净；远端研究分支实际为`{BASE}`。误提交仅在本地，未进入该远端分支；证据为`checks/git_before.json`中的实时ls-remote与提交关系。
- 原Research是Production的linked worktree，公用元数据位于Production/.git。为遵守绝对只读边界，在Research内建立独立.git，使用本地只读file传输导入远端基点的浅历史，没有复制6 GiB旧对象库，也没有改Production登记、refs、index或对象。旧worktree登记保留在原处，本任务未运行prune/repair/remove。
- 可恢复备份：原.git指针、原.gitignore、原未推送提交的已验证bundle（{bundle.stat().st_size:,}字节；SHA-256 `{sha(bundle)}`），均保存在`git_backup/`。bundle以26066704为前提，基点在独立仓库中；原共享仓库的b8faed27引用仍保持原样。备份大对象不属于新仓库待推送历史。
- TASK-012的27个源码/测试/构建文件以本地提交`ea50506`完整保存，源码实际字节未变；发布包完全保留。release共{package_count}个文件、{package_bytes / 1024**2:.2f} MiB，前后逐文件SHA-256一致。四份历史采集/生成表只解除跟踪，物理文件保留，见`checks/untracked_data_preservation.json`。
- `.gitignore`精确排除release/dist/build、EXE/DLL/打包ZIP、缓存、数值文件与生成图件；保留.spec、构建脚本、配置、TASK-008～013的选定轻量源码/报告和必要输入索引。审计文本清单与确定性测试CSV有明确例外，没有笼统忽略所有配置或所有artifacts。
- `.githooks/pre-commit`已通过本仓库的`core.hooksPath=.githooks`启用。标准库脚本检查实际暂存对象，拦截构建目录、二进制、数值数据和>2 MiB文件；强制add后的拦截也有真实临时Git测试。新克隆需自行运行`git config --local core.hooksPath .githooks`启用hook，ignore规则随代码生效。

后续正常提交不会重新纳入本地发布包或大型研究输出；不要使用`git add -f`或绕过hook来纳入生成物。Git仍保留远端26066704的既有祖先语义；不声称删除了远端旧历史中的数据。本地最终提交/对象审计、远端复核和clean状态见`checks/git_final.json`。

Production源码、配置、发布包、raw及完整.git逐文件SHA-256一致；其大型生成目录与TASK-008～012已有成果使用名称/大小/mtime清单核对一致。Research原src与configs未修改。恢复时先在新的研究恢复目录中读取bundle和基点，避免覆盖当前工作区。
""")
    write_text("VALIDATION.md", r"""
# 验证与复现

2026-11-06，Research only。正式结果：`runs/evaluation_v02`、`runs/real_v02`、`runs/sensitivity_v02`、`runs/cost_v03`、`statistics/final_v02`和`figures/final_v02`。开发轮不混入正式统计；首轮种子重用的evaluation_v01及早期图表完整保留为探索记录。

| 检查 | 结果与权威记录 |
| --- | --- |
| 相关pytest | 135通过；`checks/pytest_release.xml`与同名log。包含真实临时Git索引拦截、算法梯度、DC/低周期拒绝、整数中心、基准一致、缺失分母、边界隔离、全场景开发/测试种子不重用、输入字节保护及TASK-008～011相关回归。不是全仓GUI测试声明。 |
| Ruff | 本任务源码/测试`checks/ruff_release.log`；54份新纳入版本管理的既有研究Python源码`checks/ruff_existing_sources.log`。 |
| mypy | 严格项目配置，`--explicit-package-bases --follow-imports=silent`；本任务17个Python文件，冻结依赖静默跟随；`checks/mypy_release.log`。 |
| 合成正式实验 | 290波形×13方法/控制/映射＝3770配置，0异常；`runs/evaluation_v02/completion.json`，完整分阶段/候选/支持统计。 |
| 独立新种子 | 144条、16族；36条开发波形另存，不计入正式结果；146条旧波形明确标为旧分布。 |
| 全场景随机流独立性 | `checks/independence_audit_v02.json`确认开发/新测试及旧样本/新测试种子交集均为空。首轮12个跨场景重用已在v01审计披露，正式重跑全部290条，不剔除案例。 |
| STFT整数中心修复 | 580条方法×案例的候选/支持逐值完全相同，最大差0 Hz；`checks/integer_grid_parity.json`。 |
| 缺失与分母 | NaN、消光不剔除；`statistics/final_v02/checks.json`核对全案例/全方法、无遗漏异常与缺失控制。 |
| 实测观测 | 13份indexed raw、17路完整记录、221条观察结果；`runs/real_v02/completion.json`，不报告真实准确率或支路真值。 |
| 标注敏感性 | 12条独立场景×4标注扰动×3方法/映射；`runs/sensitivity_v02/metrics.csv`，全部负结果保留。 |
| 成本 | 8记录×13方法×3次串行独立测量＝312次，包含初始化；`runs/cost_v03/measurements.csv`。 |
| Git/raw/Production | `checks/boundary_verification_final.json`所有unchanged为true。raw、发布包、src/configs与Production完整.git用SHA-256；旧大型生成结果使用路径/大小/mtime清单，不冒充全部内容哈希。 |
| 科研图 | 六组PNG600dpi＋SVG，逐张视觉核对；`checks/visual_review.json`。 |

早期直接运行旧TASK-008测试时，绕过TASK-009 owning data adapter，只看到10个物理raw，导致1项inventory断言失败；支持的回归入口安装本地索引适配后，完整相关测试通过，未改旧测试来伪造结果。实测首轮浮点中心对齐失败保留在real_v01；整数索引修复不改变任何主实验数值。cost_v01因实验并发被中止，不用于公平成本；新成本在其他任务计算停止后串行完成。

## 复现命令

PowerShell 7；使用既有`D:miniconda3envsdps-studiopython.exe`，未全局安装依赖。下例从仓库根运行，输出名必须是未存在的新目录；原冻结TASK-008数据和TASK-009 index/raw supplement需作为本地研究输入保留。Git只跟踪轻量代码/索引，不含原始或数值数组。

```powershell
$task13Python = 'D:miniconda3envsdps-studiopython.exe'
$env:PYTHONPATH = "$PWD/src;$PWD"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
& $task13Python -B -m artifacts.research_clean_task13.repro.verify tests --tag replay2
& $task13Python -B -m artifacts.research_clean_task13.repro.experiment evaluate --output artifacts/research_clean_task13/runs/replay2 --workers 4
& $task13Python -B -m artifacts.research_clean_task13.repro.observations real --output artifacts/research_clean_task13/runs/real_replay2
& $task13Python -B -m artifacts.research_clean_task13.repro.observations sensitivity --output artifacts/research_clean_task13/runs/sensitivity_replay2
# 成本必须在其他实验计算结束后独立串行运行。
& $task13Python -B -m artifacts.research_clean_task13.repro.experiment benchmark --output artifacts/research_clean_task13/runs/cost_replay2
& $task13Python -B -m artifacts.research_clean_task13.repro.summarize --run artifacts/research_clean_task13/runs/replay2 --cost artifacts/research_clean_task13/runs/cost_replay2 --sensitivity artifacts/research_clean_task13/runs/sensitivity_replay2 --output artifacts/research_clean_task13/statistics/replay2
& $task13Python -B -m artifacts.research_clean_task13.repro.plot --run artifacts/research_clean_task13/runs/replay2 --summary artifacts/research_clean_task13/statistics/replay2 --output artifacts/research_clean_task13/figures/replay2
```

`git_governance.py`是本次一次性Git取证/隔离记录，不是需要重新执行的常规复现步骤。未push、未promotion、未改GUI或正式默认值；GIT_CLEANUP.md提供恢复边界。
""")


def stage() -> None:
    names = set(git("ls-files", "--others", "--exclude-standard", "-z").decode().rstrip("\0").split("\0"))
    names.update(git("diff", "--name-only", "-z").decode().rstrip("\0").split("\0"))
    names.discard("")
    rows = []
    for name in sorted(names):
        path = ROOT / name
        if not path.is_file():
            raise RuntimeError(f"Unexpected missing file: {name}")
        problems = violations(name, path.stat().st_size)
        if problems or path.suffix not in {".py", ".md", ".json"} and name not in {".gitignore", ".gitattributes"}:
            raise RuntimeError(f"Unreviewed output: {name}: {problems}")
        data = path.read_bytes()
        data.decode("utf-8-sig")
        if b"\0" in data:
            raise RuntimeError(f"Binary disguised as text: {name}")
        rows.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    if names:
        git("add", "--", *sorted(names))
    # Data removals were staged explicitly using --cached. No working file removal.
    write_json(OUT / "checks/staged_source_review.json", rows)
    print(f"Reviewed and staged {len(rows)} lightweight UTF-8 source/document/config files")


def final() -> None:
    import pandas as pd  # type: ignore[import-untyped]
    from .final_report import select

    status = git("status", "--porcelain=v1").decode()
    if status.strip():
        raise RuntimeError(f"Final worktree is not clean: {status}")
    history = git("rev-list", "--all").decode().splitlines()
    remote = git("ls-remote", "origin", f"refs/heads/{BRANCH}").decode()
    tracked_release = git("ls-files", "release", "dist", "build").decode().splitlines()
    if ORIGINAL in history or tracked_release:
        raise RuntimeError("Accidental build commit/output is reachable/tracked")
    objects = git("rev-list", "--objects", "HEAD", f"^{BASE}")
    check = subprocess.run(["git", "cat-file", "--batch-check=%(objecttype) %(objectname) %(objectsize) %(rest)"],
                           input=objects, cwd=ROOT, check=True, stdout=subprocess.PIPE).stdout.decode()
    blobs: list[dict[str, Any]] = []
    for line in check.splitlines():
        fields = line.split(" ", 3)
        if fields[0] != "blob":
            continue
        name, size = fields[3], int(fields[2])
        # Three legacy tables may be in the shared ancestor; none is newly added here.
        if violations(name, size):
            raise RuntimeError(f"Disallowed blob in pending history: {name}")
        blobs.append({"path": name, "bytes": size})
    value: dict[str, Any] = {
        "branch": BRANCH, "head": git("rev-parse", "HEAD").decode().strip(),
        "status_porcelain": status, "git_dir": git("rev-parse", "--absolute-git-dir").decode().strip(),
        "is_shallow": git("rev-parse", "--is-shallow-repository").decode().strip(),
        "remote_ref_final": remote, "remote_ref_matches_original_base": remote.startswith(BASE),
        "no_push_performed": True, "accidental_commit_reachable": False, "tracked_build_paths": tracked_release,
        "pending_commits": git("log", "--oneline", f"{BASE}..HEAD").decode().splitlines(),
        "pending_blob_count": len(blobs), "pending_max_blob_bytes": max(b["bytes"] for b in blobs),
        "pending_blob_bytes": sum(b["bytes"] for b in blobs), "pending_blobs": blobs,
        "hook_path": git("config", "--local", "core.hooksPath").decode().strip(),
        "object_database": git("count-objects", "-vH").decode(),
    }
    write_json(OUT / "checks/git_final.json", value)
    metrics = pd.read_csv(OUT / "statistics/final_v02/overall.csv")
    ablation = pd.read_csv(OUT / "statistics/routing_ablation_v02/overall.csv")
    stages = pd.read_csv(OUT / "statistics/final_v02/stage.csv")
    current, proposed = select(metrics, "current_map"), select(metrics, "stage_map")
    simple = select(ablation, "simple_stage_map")
    low_profile = select(stages, "profile2048", region="low_frequency")
    low_stft = select(stages, "clip_stft2048", region="low_frequency")
    old_proposed = select(metrics, "stage_map", split="legacy_fresh")
    old_simple = select(ablation, "simple_stage_map", split="legacy_fresh")
    NOTE.parent.mkdir(parents=True, exist_ok=True)
    with NOTE.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"""# 2026-11-06 TASK-013｜分阶段算法与Git治理

- 日期：2026-11-06（Asia/Shanghai）；状态：研究与Git治理完成，Research only。
- 分支：`{BRANCH}`；最终HEAD：`{value['head']}`。本地提交保留TASK-012源码、Git治理和TASK-013证据；未push、未promotion。
- 核心结论：阶段应拆成运动形态/观测质量/上下文；现有五项算法池可保留，优先合理窗长、下降/回升使用Dechirp、明确杂波才用Clutter VarPro。低频可见与静止先验/无拍频分开，最低频率不等于实测零速度。
- 核心数据：290条GT（146旧＋144全局不重用开发种子的独立测试），13配置/映射共3770，0异常。新分布当前映射失败{current.failure_percent:.2f}%，简单适配{simple.failure_percent:.2f}%，复杂预设{proposed.failure_percent:.2f}%；复杂减简单为{proposed.failure_percent-simple.failure_percent:+.2f} pp，旧主分布为{old_proposed.failure_percent-old_simple.failure_percent:+.2f} pp。低频Profile2048 RMSE{low_profile.rmse_m_s:.3f} m/s、覆盖{low_profile.coverage_percent:.2f}%，匹配长窗STFT为{low_stft.rmse_m_s:.3f} m/s、{low_stft.coverage_percent:.2f}%。
- 负结果：旧主分布当前→预设新映射RMSE8.15→36.59 m/s，起跳MAE7.72→14.25 ns；漂移杂波/交叉支路仍失败，消光NaN。真实13文件17路仅Hz观测，不报告物理支路正确性。
- 修改文件：.gitignore、.gitattributes、.githooks/pre-commit、scripts/check_git_hygiene.py、两份TASK-013测试、artifacts内选定旧轻量源码/报告与TASK-013/repro及文档；原src、GUI、configs未改。
- Artifact：`{OUT}`，入口README.md、STAGE_ALGORITHM_MAP.md、COMPARISON.md、GIT_CLEANUP.md、VALIDATION.md；figures/final_v02有6组600dpi PNG与SVG；正式统计statistics/final_v02，合成数据/完整轨迹runs/evaluation_v02。
- 测试：135相关pytest，Ruff、严格mypy；580条早期合成STFT轨迹整数中心修复逐值一致；312次串行成本。首轮12个跨场景种子重用已披露，evaluation_v01只作探索，全部290条已按不重用的新种子重跑。
- Git：误提交b8faed27未进入远端研究分支；Research转独立浅仓库，原gitlink及161335217字节bundle已保留。所有发布包留本地；4份历史数值表仅解除跟踪；普通提交有ignore和hook双层检查。远端/Production Git未写。
- 边界：Research raw与13 indexed raw、release、src/configs，以及Production源码/配置/发布包/raw和完整.git SHA-256一致；旧生成成果路径/大小/mtime清单一致。既有成果不删除。
- 后续四方向：可观测性驱动窗长/频率剖面；人工边界不确定性；现有Dechirp/VarPro按需计算和残差检查；杂波持续性及多支路身份。
""")
    print(json.dumps({"head": value["head"], "pending_blob_max_bytes": value["pending_max_blob_bytes"],
                      "clean": True, "note": str(NOTE)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "stage", "final"))
    args = parser.parse_args()
    {"prepare": prepare, "stage": stage, "final": final}[args.mode]()


if __name__ == "__main__":
    main()
