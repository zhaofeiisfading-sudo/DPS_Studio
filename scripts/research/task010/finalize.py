"""Final support-span inventory, source fingerprints, validation, and requested note."""
from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import subprocess
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task010.audit import OUT, ROOT, sha, write_json


def supplement() -> None:
    synthetic=pd.read_csv(OUT/"runs/v01/tables/synthetic_metrics.csv")
    real=pd.read_csv(OUT/"runs/v01/tables/real_metrics.csv")
    streams=pd.read_csv(OUT/"runs/v01/tables/raw_streams.csv").set_index("case_id")
    rows=[]
    for data,domain in ((synthetic,"SYNTHETIC_GT"),(real,"REAL_NO_GT")):
        for r in data.to_dict("records"):
            n=12800 if domain=="SYNTHETIC_GT" else int(streams.loc[r["case_id"],"samples"])
            first=int(r["window"])//2
            last=first+(int(r["frames"])-1)*int(r["hop"])
            fs=r["sample_rate_hz"]
            rows.append(dict(domain=domain,stage=r["stage"],case_id=r["case_id"],name=r["name"],
                samples=n,window=r["window"],hop=r["hop"],native_frames=r["frames"],
                first_center_index=first,last_center_index=last,
                center_span_fraction_of_record=(last-first)/(n-1),
                left_center_margin_s=first/fs,right_center_margin_s=(n-1-last)/fs,
                window_duration_s=r["window_duration_s"],frame_interval_s=r["frame_interval_s"],
                nominal_frames_per_second=fs/r["hop"]))
    pd.DataFrame(rows).to_csv(OUT/"tables/temporal_support.csv",index=False,mode="x",encoding="utf-8-sig")
    before=(OUT/"runs/v01/source_snapshot/run.py").read_text(encoding="utf-8")
    after=(OUT/"run.py").read_text(encoding="utf-8")
    unchanged_ast=ast.dump(ast.parse(before))==ast.dump(ast.parse(after))
    assert unchanged_ast
    write_json(OUT/"checks/entrypoint_ast_comparison.json",dict(
        ast_unchanged=unchanged_ast,explanation="Only a SciPy import typing comment was added after the experiment; executable syntax tree unchanged.",
        kernel_sha_unchanged=sha(OUT/"experiment.py")==sha(OUT/"runs/v01/source_snapshot/experiment.py")))
    sources=sorted(OUT.glob("*.py"))+[OUT/"config.json",OUT/"PROTOCOL.md",
        ROOT/"tests/unit/test_research_task010.py",ROOT/"src/dps_studio/core/time_frequency/stft.py",
        ROOT/"src/dps_studio/core/ridge/refinement.py"]
    write_json(OUT/"checks/source_freeze.json",{p.relative_to(ROOT).as_posix():sha(p) for p in sources})
    write_json(OUT/"checks/hardware.json",dict(platform=platform.platform(),
        cpu=platform.processor(),processor_identifier=os.environ.get("PROCESSOR_IDENTIFIER"),
        logical_cpu_count=os.cpu_count(),benchmark_threads=1,
        note="One Windows desktop workstation; frequency scaling and unrelated OS services not controlled. Three-repeat ranges are retained."))


def documents() -> None:
    release=json.loads((OUT/"checks/release_verification.json").read_text(encoding="utf-8"))
    boundary=json.loads((OUT/"checks/boundary_verification.json").read_text(encoding="utf-8"))
    assert release["all_passed"] and boundary["all_passed"]
    pytest=(OUT/"checks/pytest_final.log").read_text(encoding="utf-8-sig")
    ruff=(OUT/"checks/ruff_final.log").read_text(encoding="utf-8-sig")
    mypy=(OUT/"checks/mypy_final_v02.log").read_text(encoding="utf-8-sig")
    assert "141 passed" in pytest and "All checks passed" in ruff and "Success:" in mypy
    validation="""# TASK-010 验证记录

2026-11-05。最终检查通过；没有遗留失败项目。检查范围为本任务Research代码、相关基准和STFT测试，不将此表述为全仓回归通过。

| 项目 | 实际结果 | 证据 |
| --- | --- | --- |
| 新增测试 | 18项：core一致、步长独立、缺失分母、验证支撑、边界NaN、直接双尺度选择、云端版本保护 | tests/unit/test_research_task010.py |
| 相关pytest | 141 passed | checks/pytest_final.log |
| Ruff | All checks passed | checks/ruff_final.log |
| mypy | Success，严格项目配置，显式namespace bases；冻结依赖静默跟随 | checks/mypy_final_v02.log |
| 逐点冻结基准核验 | 292条，NaN位置相同，最大频差2.0266×10⁻⁵ Hz | runs/v01/checks/frozen_strict_equivalence.json |
| 全矩阵归因 | 730个波形×窗口组合，6种步长的所有共同评分严格相同 | summary/v02/hop_invariance.csv |
| 输入与分母 | 6714合成、170实测结果；340条代表轨迹核验校正速度NaN分离 | checks/release_verification.json |
| 成本 | 189次独立计时，30个研究参数×2长度×3次，另3个core配置×3次 | cost/v01/measurements.csv |
| PDF | 9张单页，字体全嵌入、0栅格image对象、0页面外文字 | checks/pdf_qa_v01/qa_summary.json |
| 视觉复核 | 主图和Origin伴随图已查看；低速保留全幅异常并加局部放大 | checks/visual_review.json |
| Git/raw/Production | 全部保护检查通过 | checks/boundary_verification.json |

最终pytest通过TASK-009入口启用本地原始数据索引，范围为test_stft、test_ridge_refinement、test_peak_ridge、TASK-008、TASK-008 baseline audit、TASK-009 migration/figures以及TASK-010；缓存与临时目录均在TASK-010检查目录。使用现有dps-studio Python3.12环境、PowerShell7，无依赖安装。

Ruff检查整个TASK-010目录及新增测试；mypy使用`--explicit-package-bases --follow-imports=silent`，逐一检查本任务顶层Python脚本和新增测试。早期检查遇到namespace重复与SciPy无类型存根，采用显式包根和与现有项目一致的import-untyped注释修复，没有安装存根或降低项目strict配置。其他本任务静态检查错误已修正，最终日志为准。

文档生成曾因相对路径校验失败而中止，修正为解析绝对路径，保留已写且相同的关键表，随后成功生成完整报告；未重跑或修改实验结果。图件v01保留，v02增加低速局部放大并调整图例和图注，未改变任何轨迹数值。Origin COM数据逐点读回核验，PDF嵌字前版本保留，最终使用_embedded.pdf。

run.py实验后只增加SciPy类型注释，AST与运行快照一致；experiment.py与运行快照SHA完全一致，证据见checks/entrypoint_ast_comparison.json。最终脚本、协议、配置、测试和所调用core入口SHA见checks/source_freeze.json。

data/raw包括占位文件在内11个文件前后SHA相同；全部10个真正原始输入均被运行；补充3个同SHA文件仍在TASK-009归档。TASK-008的11121个文件和整个TASK-009目录前后哈希一致。Production的代码、raw、分支、HEAD、index、Git状态均保持；目标已有代码字节不变，仅新增Research成果和一个测试，未commit/push/promotion。
"""
    with (OUT/"VALIDATION.md").open("x",encoding="utf-8") as stream:
        stream.write(validation)
    head=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    note=f"""# TASK-010｜长窗口高重叠STFT研究

- 日期：2026-11-05；状态：已完成，Research only。
- 分支：codex/research_2/global-path-ridge-v2；HEAD：{head}。
- 任务：5种窗长×6种步长的受控STFT研究；170条GT波形、6714条合成配置，13真实文件/17电压流/170条实测配置，保留原14方法2044条轨迹重评分。
- 结论：高重叠只增加密度与相关性，共同中心指标完全相同；中等长窗有条件收益，2048+H1不适合作通用默认。建议可选768/1024点+H64/H32；快变用512，平稳低速探索1536/2048配H128/H64，显式处理频带/DC并保留质量标志。
- 核心量化：原频带支持含缺失失败512/H128为27.83%，1024/H32为13.18%，2048/H32为14.85%（新启发式门控）；1024差值−14.65 pp，配对波形95%CI[−21.21,−8.58] pp。候选RMSE1024反而更高，不能据支持后数字称全面精度提升。匹配宽带去均值长窗/自适应相对短窗失败+3.22/+0.91 pp。
- H1起跳MAE未改善；W512：3.512→4.042 ns；W2048：10.317→11.319 ns，成功检测者统计，漏检另列。H1双频混合宽度W512/W2048为3.416/13.572 ns（GT外部诊断）。80,000点W2048：H128/H32/H1耗时约34.34/131.61/6678.09 ms，三次中位数。
- Artifact：D:/Code/Python_Projects/DPS_Studio_RESEARCH_CLEAN/artifacts/TASK-010；README.md、COMPARISON.md、FIGURE_INDEX.md、runs/v01、summary/v02、cost/v01；7主图PDF/SVG/600dpi PNG，2个Origin OPJU伴随工程。
- 修改文件：仅新增artifacts/TASK-010下Research脚本、配置、协议、报告、数值及图件；新增tests/unit/test_research_task010.py；无既有源码改动。
- 测试：18项新增；相关pytest 141 passed，Ruff/mypy通过；9个PDF嵌字/纯矢量/页边界检查通过；292条原严格候选对照最大频差2.027e-5 Hz，NaN一致。
- Git/raw/Production：目标HEAD/index/既有代码不变；raw含占位11文件SHA相同，10真正原始输入全覆盖；TASK-008/009哈希不变；Production代码/raw/Git状态不变；无promotion、commit、push。
- 云端：G:/我的云端硬盘/codex/pdv_studio_research/research_clean_task10；手机成果包复制回执见本地checks/cloud_sync.json，完整NPZ和源码以本地artifact为准。
- 下一步：只考虑Research可选参数界面；用独立带真值实测及光学/AC链路标定验证，不将H1或本轮双尺度选择作为Production默认。
"""
    path=Path("D:/Research/Notes/05项目/dps/2026-11-05_TASK-010_长窗口高重叠STFT研究.md")
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as stream:
        stream.write(note)
    write_json(OUT/"checks/research_note.json",dict(path=str(path),sha256=sha(path),created=True))


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("supplement","documents"))
    args=parser.parse_args()
    if args.phase=="supplement":
        supplement()
    else:
        documents()


if __name__=="__main__":
    main()
