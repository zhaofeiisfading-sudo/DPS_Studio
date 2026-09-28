"""Write the audited results and a concise Obsidian index, exclusively new files."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts import run_task023f_proposal_recovery as r
from scripts.finalize_task023f_recovery import read_csv


def write_text(path: Path, value: str) -> None:
    with path.open('x',encoding='utf-8') as handle:
        handle.write(value)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    output=parser.parse_args().output.resolve()
    gate=json.loads((output/'phase_c_gate.json').read_text())
    counts=json.loads((output/'summary_counts.json').read_text())
    integrity=json.loads((output/'integrity_summary.json').read_text())
    summaries=read_csv(output/'pairwise_separability_by_family.csv')
    def metric(feature: str, tag: str, role: str='FRESH', aggregation: str='WAVEFORM_MACRO') -> dict[str,str]:
        return next(v for v in summaries if v['feature']==feature and v['stratum']==tag
            and v['role']==role and v['aggregation']==aggregation and v['scope']=='STRICT_WHOLE_HISTORY')
    def percentage(value: Any) -> str:
        return f'{float(value)*100:.3f}'
    lines=[
        '# TASK-023H 原始波形域证据与可辨识性审计', '',
        '请求标题 TASK-024；按指定目录/日志命名为 TASK-023H。状态：审计完成，Phase C 后停止 scorer/反事实阶段，等待人工审计。', '',
        '**新 fresh Candidate Recall=100%。E1 在部分既有错误 pair 上有正信号，但总体增益仅 0.203 pp，低 SNR 与 amplitude fading 没有净改善，不支持下一 TASK 直接实现正式 raw-domain scorer。**', '',
        '| 审计项 | Verdict | 适用范围 |','|---|---|---|',
        '| Candidate sufficiency | SUPPORTED | 原 generator、Top-20、200 MHz truth-near 容差；不是任意双分量的独立分辨证明 |',
        '| Raw-domain separability | NOT SUPPORTED | 未达预声明完整启用 gate；保留 E1 小样本局部正信号 |',
        '| Identifiability headroom | LIMITED | 有分量支持信息，缺少仅由观测确定目标身份的依据；总体发生率未知 |',
        '| Potential for future scorer | NOT SUPPORTED | 本轮不支持正式实现；不否定后续重新预登记的局部验证 |',
        '| Potential for informative interval | SUPPORTED | 仅未来研究潜力，未设 threshold、未输出自动 interval；不等于 target identity detector |', '',
        '## 预登记、冻结和事实边界', '',
        '开始时 Research clean，branch=`codex/research_2/global-path-ridge`，HEAD=`2565eb0d8fa71ff3777bc5ec56807812730118e6`。Production clean、main、HEAD=`07a1e0f85f156225518b671a48d687bea94908e9`。已检查当前源码、git status/diff、F/G 最新 artifact 和 2026-09-13 Obsidian 日志；旧日志的 Research HEAD 已过时，不作为当前事实。', '',
        'protocol.md 和 seed_registration.json 先于生成；evidence_code_freeze.json 先于 fresh 评分及真实数据。保留 protocol_clarification_before_observation.md 对单分量参考公式草稿的排版错误更正。只用四个预声明统计量，无 bandwidth/segment/feature 选择、无 AI。F/G 数据始终为 LEGACY_DIAGNOSTIC。', '',
        'STFT、Top-K、sub-bin、Challengeable Core、Diversity B8、旧 E4、acceptance、band、analysis range 和 modification budget 未变。仅新增 Research 审计模块/脚本/测试；不生成新的最终轨迹或 velocity 输出。内部量用 SI，未加入 LiF 公式。', '',
        '## Fresh 样本和 Candidate premise', '',
        f'8 families × 16 instances=128 新波形；seeds=2408000+100×family_index+instance，instance 8…23。调用原 generate_case，只改 seed/ID。两个 profile 属于同一波形。共 256 streams，{gate["truth_frames"]:,} 个有效 GT 帧均有 200 MHz 内候选；{gate["strongest_error_frames"]:,} 个 strongest-error 帧也全部可用。error-frame pooled、waveform-macro 和 all-valid-frame recall 均为 100%。', '',
        'Top-K 对本次 recall 定义足够，没有证据要求扩大 K。此容差并不证明两个接近分量可各自分离，也不保证完整 truth-near proposal 存在。I2 的双分量分离测试是另一问题。', '',
        '40 GHz 合成采样下，Balanced 物理窗长 19.2 ns，High-time 12.8 ns；两者 frame spacing=3.2 ns，FFT bin spacing=9.765625 MHz。1/T 频率尺度分别 52.083、78.125 MHz，不能把 hop 当真实时间分辨率，或把 nfft 当提高真实频率分辨能力。v_app=λ0 f_b/2；1550 nm 只是冻结物理关系背景，本轮不计算新速度结果。', '',
        '## Pair 定义、统计单位和分母限制', '',
        f'共保存 {counts["pairs"]:,} 个 pair：fresh {counts["fresh_pairs"]:,}、legacy {counts["legacy_pairs"]:,}。主 gate 使用 4,863 个 fresh STRICT_WHOLE_HISTORY pair，涉及 113 个波形。其余波形或窗口无合格两支比较，排除原因和 NO_VALID_DESCENDANT 负对照完整保存，未填造 proposal。', '',
        '严格 terminal pair 要求正确成员所有历史 GT knots 有效且误差≤200 MHz；正确 prefix 也要求完整已有前缀都满足此条件。错误成员至少一 knot 超差。每个窗口按预登记选择一对；correct control 使用 E4 原选中的正确成员。LOCAL_SUBPATH 仅检查最后最多4个节点，另列，不冒充完整正确 lineage；其 baseline 仍为全前缀累计 cost，不能直接与完整窗口主结果混用。', '',
        '统计先在波形内合并 profiles/pairs，再做 waveform-macro。另有 pair-pooled 敏感性表和 2,000 次 waveform-cluster bootstrap；NaN 不当成功，平局记0.5准确率，preservation/rescue 只计严格赢。失败条件包括低 phase coverage。', '',
        '**门槛可达性限制：主集合含4,792个原本正确 control，E4 baseline=98.614%，总体理论最大提升仅1.386 pp。因此用户指定的总体+10 pp门槛在本次自然枚举分母下数学上不可达。没有事后重采样、改变权重或降低门槛。NOT SUPPORTED 表示完整 gate 未满足，不能据此说 raw 相干证据完全无信息。下一次若继续审计，应先预登记有可达性的错误/对照采样和主要 estimand。**', '',
        'Identity-swap 的16个观测组另作 I3 控制。其冻结 P3 没有合法搜索窗口/terminal proposal，严格 D terminal pair=0，见 identity_swap_frozen_graph_audit.csv 与空 ambiguity_proposal_pair_manifest.json。未为满足分组人为制造 proposal；I3 另用明确标注的已知双频模板检查相同观测的 evidence 恒等性。', '',
        '## 四类 raw-domain evidence', '',
        r'对完整原始实值电压构造 $z=\mathrm{HilbertAnalytic}(V)$。已有候选频率 knots 之间采用明确声明的分段线性频率模型，在未改动的 raw sample time 上计算 $\phi_n-\phi_{n-1}=\pi(f_n+f_{n-1})(t_n-t_{n-1})$，$d_n=z_n e^{-i\phi_n}$。模型的节点间求值不等于对原始电压插值。无外推、重采样、平滑或删点；NaN 不填补。', '',
        r'- E1：$|\sum d_n|^2/(N\sum|z_n|^2)$，复常数幅度解析最小二乘消元后的归一化投影。',
        r'- E2：解调 FFT 在固定 $|f|\le1/T_{STFT}$ 内的能量占比；矩形分析，不补零、不调带宽。',
        r'- E3：相邻残余相位增量得到 residual IF；只使用相邻幅度均≥0.1×local RMS且相位增量绝对值<0.9π的样本对。有效比例不足50%则NaN；评分为 $1/(1+\mathrm{median}|f_{res}|/(1/T))$。不作 unwrap 插值。',
        r'- E4raw：固定4段，每段独立复幅度，$\sum_j|\sum_{n\in j}d_n|^2/N_j\,/\sum|z_n|^2$，不拟合任何频率修正。E4raw 与旧 E4 score 是不同名称空间。', '',
        '所有量称 evidence/coherence，未推导为概率 likelihood。Hilbert phase 是混合信号的相位，不能当作独立物理分量真相位。E1 全局幅度缩放不变，但真实强干扰分量仍可比目标投影更高。图03固定选择第一个合格 persistent 案例，恰好展示错误强分量更相干，没有挑选正例。', '',
        '## Phase C 全部四项与直接 baseline', '',
        '| Evidence | E4 baseline % | raw accuracy % | gain pp | preservation % | error rescue % | net gain pp |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for feature in ('E1','E2','E3','E4raw'):
        row=metric(feature,'ALL')
        lines.append('| '+feature+' | '+' | '.join(percentage(row[k]) for k in (
            'baseline_accuracy','raw_accuracy','improvement','preservation_rate','rescue_rate','net_pairwise_gain'))+' |')
    lines += ['', '以上为waveform-macro。E1 pooled：13个错误pair救回，3个正确pair破坏，净+10/4863=0.206 pp；preservation=4789/4792=99.937%。waveform-macro E1 gain的95% cluster bootstrap区间为[0.018,0.423] pp。小幅正增益不满足+10 pp，也不满足困难层收益要求。E3 preservation约50.56%，明显失败，不继续调相位mask或统计定义。', '',
        '| 主要失败类别 | pairs / waveforms | E1 % | E2 % | E3 % | E4raw % |', '|---|---:|---:|---:|---:|---:|']
    for tag in ('PERSISTENT_SCORE_INFERIOR','SELECTION_LOSS'):
        row=metric('E1',tag)
        lines.append(f'| {tag} | {row["pairs"]} / {row["waveforms"]} | '+
                     ' | '.join(percentage(metric(feature,tag)['raw_accuracy']) for feature in ('E1','E2','E3','E4raw'))+' |')
    lines += ['', '两类baseline均为0%，因此上述百分比也等于该类提升pp。E1 persistent pooled为3/24=12.5%，waveform-macro16.667%；selection pooled为7/24=29.167%，waveform-macro28.889%。persistent bootstrap区间[0,41.667] pp，selection[8.889,51.111] pp，小样本不支持广泛因果外推。', '',
        '| Fresh困难层（E1） | pairs | gain pp | preservation % |', '|---|---:|---:|---:|']
    for tag in ('low_SNR','amplitude_fading','smooth_wrong_branch','branch_crossing','branch_merge',
                'temporary_fading','broadband_contamination','fast_descent'):
        row=metric('E1',tag)
        lines.append(f'| {tag} | {row["pairs"]} | {percentage(row["improvement"])} | {percentage(row["preservation_rate"])} |')
    lines += ['', 'low_SNR 是预登记 noise_sd≥0.3 V（原未衰减目标约3–7.45 dB），不是根据结果分箱。amplitude_exchange/fading无增益；dropout真正无目标部分没有GT，不进入truth-near频率pair，temporary_fading层的100%不能解释为恢复消失目标。branch crossing只有+0.518 pp、merge略负，smooth wrong branch+0.944 pp；均非主突破。所有原始分差、分位数、有限覆盖和局部子路径结果见CSV。', '',
        '## I1–I3 可辨识性', '',
        r'I1使用 $V_n=A\cos(2\pi f t_n+\theta)+\epsilon_n$，$\epsilon_n\sim N(0,\sigma^2)$、局部恒幅/恒频、未知相位。周期平均近似Fisher结果为 $\sigma_f\simeq\sqrt{2\sigma^2/[A^2(2\pi)^2\sum(t_n-\bar t)^2]}$。单位Hz；已和显式sinusoid Jacobian Fisher逆矩阵做单元测试。仅REFERENCE ONLY；不是多分量PDV的CRB，也不是低SNR下可达到的不确定度保证。', '',
        'I2完成432个全因子网格点×2profiles。使用原oscillator_phase、SignalRecord、40 GHz/80000点和加性高斯观测机制的受控适配器；原fresh generator distribution未动。separation、SNR、amplitude ratio、chirp差、fade五轴固定；共享同一标准高斯噪声实现，网格比例不能作自然数据发生率或独立重复实验置信区间。已知真实频率模板用于分量匹配诊断，不算冻结generated proposal。', '',
        'Balanced独立candidate峰可分145/432，High-time144/432。固定200 MHz全历史容差下不同proposal存在206/432和181/432；176/432及206/432没有触发中心搜索窗口。该proposal项容差在近分支时重叠，不证明两条物理支路已独立分辨，也不能与candidate半间隔匹配直接作同分母性能比较。图中proposal_separable列应按此“宽容差不同proposal存在”定义阅读。', '',
        'E1预声明|difference|≤0.01近似平局：Balanced75/432、High-time95/432。E2为150/432、95/432；E3为399/432、392/432，显示残余混合相位的分离力很弱。不能把这些feature平局当作观测分布相同的证明；只有I3严格same-observation换身份满足观测不可辨识定义。', '',
        '有限窗离散化限制：I2 High-time中心物理窗口实际包含511 raw样本，首个非零FFT频点78.278 MHz高于固定带宽78.125 MHz，E2仅含DC，故该扫描中E2等同E1；Balanced包含768点/3个基带频点。见spectral_grid_audit.json。本轮不调bandwidth/补零救结果，不能把E1/E2当四项独立支持中的两票。', '',
        'I3：16个观测组、32个profile检查，交换target label后raw、STFT、candidate、旧评分及冻结proposal图哈希完全相同；64个已知模板评分行在两套标签下完全相同。所有这些身份交换案例标记OBSERVATIONALLY NON-IDENTIFIABLE。原图无terminal pairs的限制已明示；未声称算法识别物理身份。真实数据中这类歧义的发生率未测。', '',
        '## 原1699帧：证据与搜索结构只能作谨慎诊断', '',
        '原G分类保持原状：DUPLICATE_OCCUPANCY600、FAMILY_COLLISION284、PERSISTENT_SCORE_INFERIOR479、NO_VALID_DESCENDANT220，其余116。前两类合计884/1699=52.03%具有搜索结构机制证据，不等于52.03%能被某个搜索修改恢复。', '',
        '在479个legacy persistent帧中，27个严格prefix配对事件覆盖260帧；其中E1更偏向truth-near的事件覆盖96帧（479的20.04%，1699的5.65%）。legacy该类E1 waveform-macro排序改善40.625%，但数据已看过，不能包装成fresh成果；其余219帧没有严格比较，不能推断raw evidence有效或无效。', '',
        '跨非NO_VALID类别，E1偏向正确严格prefix的事件共覆盖197个旧帧（11.60%），包括duplicate81、collision20、persistent96。这只是pairwise倾向，不是反事实实际retention恢复数；结构与评分可能交互。NO_VALID负对照有41个可比较prefix，其中12个E1偏好，仍没有合法后继保证，不能称scorer修复。详细帧权重见legacy_retention_evidence_summary.csv。', '',
        '## 真实数据与 informative interval 潜力', '',
        '完成原34streams，只读formal reader和保存F/P3 proposal；全部strongest帧有固定物理窗局部证据，另保存每条existing terminal的分差。没有GT、没有真实正确率/RMSE、没有从真实数据选择feature或threshold。ch3的Balanced/High-time分别有48/24条保存terminal（其中包含重复/strongest-like轨迹，不等于48/24独立物理替代支路）。', '',
        'ch3两种profile图中，记录中部短段的coherence、analytic RMS和spectral support同时升高；其前后存在低支持谷。这里只是全记录视觉行为描述，未估计自动区间边界，也未用人工区域计算任何准确率。E1全记录中位数/95分位：Balanced0.0347/0.2733，High-time0.0480/0.3504。', '',
        'Synthetic strongest-local E1：target-present中位数Balanced0.8420、High-time0.8433；no-target分别0.0111、0.0154。对应target-present第5分位约0.666，而no-target第95分位0.0208/0.0293。E2/E4raw亦有明显分布差异，支持未来有效信号支持检测研究；没有阈值或interval输出。无目标组主要是dropout/pure-noise，没有“目标消失但强相干干扰仍在”的充分负对照，不能把此统计量称为物理目标存在检测器。', '',
        '## 14项逐项回答', '',
        '1. 新fresh Candidate Recall=100%，error分母2532、all-valid分母148564；两个profile按waveform聚类。',
        '2. 当前K=20对原generator和200 MHz recall标准足够；不支持增加K，近频双分量独立分辨仍有限。',
        '3. PERSISTENT_SCORE_INFERIOR部分可区分：fresh E1 macro+16.667 pp（24pairs/12waveforms），legacy受限prefix+40.625 pp；不是全部479帧或全部retention问题已改善。',
        '4. Selection loss部分可区分：fresh E1 7/24 pooled，macro+28.889 pp；完整门槛仍失败。',
        '5. E1总体最有判别力且对照保留较好；E3虽有个别rescue，却大量破坏正确pair。没有挑选或部署新scorer。',
        '6. E1不偏爱同一观测的整体电压缩放，但仍会偏爱强相干物理干扰。图03为直接反例；归一化不等于幅度无偏身份识别。',
        '7. fresh amplitude fading层无净提升。不能声称fade问题已解决；完全dropout没有有效目标GT。',
        '8. crossing+0.518 pp、merge−0.057 pp（E1）；没有显著广泛改善证据。',
        '9. smooth wrong branch+0.944 pp（E1）；方向略正，远低于总体门槛。',
        '10. 构造的16组same-observation换身份严格不可辨识；I2有feature近似平局区域，但不能据此宣布大量真实PDV区间理论不可恢复，发生率未知。',
        '11. 884旧帧仍有结构机制证据；197旧帧所属严格pair显示E1偏向正确，包含96 persistent帧。两者不能相减形成完全因果归因，更不能算新算法恢复率。',
        '12. 不支持下一TASK直接正式实现raw-domain-informed scorer；应先人工审计小样本、分母门槛、phase表示误差和困难层失败。',
        '13. 对未来informative interval detection有潜力；仅分布/行为证据，无threshold、新interval或target identity保证。',
        '14. 若另立任务，优先Search structure的谱系/占位证据与Identifiability/目标身份约束；Scoring可做有可达gate的局部复验。Representation需检视长窗积分与近频分量，Candidate扩K不是当前优先项。本轮不启动后续任务。', '',
        '## 验证、停止与复现', '',
        '新增31项测试。最终pytest：792 passed、2既有launcher failed；初始额外CLI失败来自pytest argv传入，改用PYTEST_ADDOPTS后消失，未改业务或launcher。ruff通过；mypy --strict通过（最终文件数见validation_summary.json）；git diff --check通过，并用不写index的no-index检查新增文件。初次no-index返回1被误当失败，已按Git的“文件不同”语义修正检查器，原日志保留。', '',
        f'完整性：{integrity["frozen_files"]:,}个既有文件未变；48个raw条目哈希一致；Production/main和Research main引用不变；无commit/push/merge/rebase/cherry-pick/promotion。测试临时输出保留在artifact/tests。任务结束仅新增Research文件以及明确授权的Obsidian索引。', '',
        'Phase C未达SUPPORTED/MIXED-with-strong-signal。offline_counterfactual_ranking.csv保留表头，skipped reason另存JSON；未重新排序全部terminal、未模拟新Beam或生成最终trajectory。按early-stop停止feature/scorer探索；已完成预登记的独立I1–I3及真实描述性诊断，未借它们调回synthetic结果。', '',
        '复现命令和产物索引见README.md。protocol/frozen_manifest/evidence_code_freeze为冻结依据，CSV/JSON与源码高于本报告和Obsidian。八张核心图全部人工视觉检查，PNG 300dpi与PDF并存；图04/05中的proposal存在项与E2退化限制应结合上述说明阅读。', '',
        '## 核验文献与推导来源', '',
        'Rife与Boorstyn，1974，Single tone parameter estimation from discrete-time observations，IEEE Transactions on Information Theory 20(5),591–598，DOI [10.1109/TIT.1974.1055282](https://doi.org/10.1109/TIT.1974.1055282)。Strand等，2006，Compact system for high-speed velocimetry using heterodyne techniques，Review of Scientific Instruments 77,083108，DOI [10.1063/1.2336749](https://doi.org/10.1063/1.2336749)。', '',
        '两篇DOI、作者、年份、出版字段已由Crossref注册元数据核验，原响应保存在verified_reference_metadata.json；出版商全文访问受限，未声称核验全文公式。I1是本报告对明确实值sinusoid模型的独立Fisher近似推导及数值测试，不冒充上述复数单音论文原式，也不把单音结论外推到混合PDV。', '',
        '**结束：等待人工审计。**','']
    write_text(output/'final_research_report.md','\n'.join(lines))
    verdicts=dict(candidate_sufficiency='SUPPORTED',raw_domain_separability='NOT SUPPORTED',
        identifiability_headroom='LIMITED',potential_for_future_scorer='NOT SUPPORTED',
        potential_for_informative_interval='SUPPORTED')
    r.write_json(output/'metadata_completion.json',dict(status='COMPLETE_AUDIT_PHASE_C_EARLY_STOP',
        verdicts=verdicts,gate_ceiling_limitation=True,identity_frozen_terminal_pairs=0,
        no_algorithm_output=True,finished_utc=datetime.now(UTC).isoformat()))
    write_text(output/'visual_review.md','All eight PNGs inspected. Labels/units and comparison scopes readable; '
        'histogram axes are symlog counts. Persistent example is deterministic and favors a wrong strong component. '
        'ch3 both profiles show a central support elevation; no automated interval claim. '
        'I2 proposal panels are the frozen 200 MHz existence criterion, not independent physical component resolution; '
        'High-time E2 collapses to E1 in the 511-sample I2 window. No data or feature adjusted after viewing.\n')
    write_text(output/'README.md','''# TASK-023H artifact

Read final_research_report.md and phase_c_gate.json first. Full frozen provenance:
protocol.md, seed_registration.json, evidence_code_freeze.json, frozen_manifest.json.
Tables preserve FRESH versus LEGACY_DIAGNOSTIC, strict versus LOCAL_SUBPATH.
CSV structured fields may be JSON strings or Python-style lists; canonical per-stream
JSON retains complete types. Load text as UTF-8. Nonfinite scores are explicit NaN
with quality flags; do not replace with favourable numeric scores.

Runtime: D:/miniconda3/envs/dps-studio/python.exe; PYTHONPATH=src;.
Run from Research only. Use a NEW timestamp output via scripts/freeze_task023h.py.
For that new output, run in order:

1. scripts/run_task023h_raw_audit.py --output NEW --phase fresh --workers 4
2. scripts/run_task023h_raw_audit.py --output NEW --phase legacy --workers 4
3. scripts/run_task023h_identifiability.py --output NEW --workers 4
4. scripts/run_task023h_real_evidence.py --output NEW
5. scripts/audit_task023h_identity_proposals.py --output NEW
6. scripts/summarize_task023h_evidence.py --output NEW
7. scripts/finalize_task023h_audit.py --output NEW --phase diagnostics
8. scripts/plot_task023h_evidence.py --output NEW
9. scripts/finalize_task023h_audit.py --output NEW --phase integrity

Do not rerun exclusive final CSV writers into this completed artifact. Stream-level
resumption uses completed immutable JSON. Gate-qualified counterfactual is not
implemented because the observed gate failed; no scorer/selector was changed.

pytest was invoked with QT_QPA_PLATFORM=offscreen and options in PYTEST_ADDOPTS,
not argv, because the existing CLI smoke test consumes argv. Raw inputs are read-only.
All baseline/full test temporary files preserved under tests/baseline_tmp and tests/full_tmp.

Additional limitations: D identity controls have zero generated terminal pairs;
known-template invariance and frozen-graph invariance are separate. I2 known templates
are not generated proposal recall. The 1/T discrete-bin diagnostic is in spectral_grid_audit.json.
Obsidian is an index, not a source of truth. No promotion, Git write or production edit.
''')
    date=(datetime.now(UTC)+timedelta(hours=8)).strftime('%Y-%m-%d')
    note=Path('D:/Research/Notes/05项目/dps')/(date+'_TASK-023H_raw-domain-evidence.md')
    write_text(note,f'''---
task: TASK-023H (request title TASK-024)
date: {date}
branch: codex/research_2/global-path-ridge
status: completed_phase_c_early_stop
verdict: candidate_SUPPORTED; raw_NOT_SUPPORTED; identifiability_LIMITED; scorer_NOT_SUPPORTED; interval_potential_SUPPORTED
artifact: {output.as_posix()}
---

新增独立raw evidence/GT auditor、运行/汇总/绘图/边界脚本和31项测试；没有改既有算法。
Fresh 128波形/256profiles：Candidate Recall=100%，2532/2532 error帧，148564/148564有效GT帧。
严格fresh 4863pairs/113波形：E4 baseline98.614%，E1=98.817%，+0.203pp；preservation99.940%。
PERSISTENT：E1 macro16.667%（24pairs/12波形）；Selection-loss28.889%（24pairs/15波形）。
总体+10pp gate在98.614% baseline下不可达，且low-SNR略负、fading零增益；不实施正式scorer/反事实重排。
原1699 legacy帧：884有结构机制证据；严格E1倾向正确事件覆盖197帧，其中persistent96帧，不能称恢复数。
I2 432网格×2profiles；High-time 511样本使E2只含DC，非独立于E1。16组identity swap证据/冻结图完全相同，严格terminal pair为0，已明示未造轨迹。
真实34streams仅描述；ch3双profile中部coherence/幅度/谱支持同步升高，无threshold、新interval或真实正确率。
pytest792 passed/2既有launcher failed；ruff、strict mypy、git diff --check通过，详见validation_summary。
git status仅新增Research文件，tracked/staged diff空；HEAD2565eb0。48个raw SHA-256前后一致、14746既有文件未变。
Production/main07a1e0f clean不变；两处main引用不变；无commit/push/merge/promotion。
未解决：门槛分母天花板、strict错误pair数量小、fading/low-SNR、目标身份、近频proposal宽容差与raw频率模型误差。
建议：人工审计后优先search structure及identity约束；如复验E1须先预登记可达gate。下一阶段未启动。

[报告]({(output/'final_research_report.md').as_posix()})。该日志仅索引，源码/git/tests/artifact优先。
''')
    r.write_json(output/'obsidian_log_record.json',dict(path=str(note),sha256=r.sha256(note)))


if __name__=='__main__':
    main()
