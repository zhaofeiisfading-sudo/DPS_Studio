"use strict";

const fs = require("fs");
const path = require("path");
const PptxGenJS = require("pptxgenjs");

const ROOT = __dirname;
const OUTPUT =
  process.argv[2] || path.join(ROOT, "_qa_tmp", "editable_v1.pptx");
const ASSET = (...parts) =>
  path.join(ROOT, "assets", "project_outputs", ...parts);

const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_16x9";
pptx.author = "DPS Studio project";
pptx.company = "DPS Studio";
pptx.subject = "DPS Studio 课题组组会汇报";
pptx.title = "DPS Studio：从原始 PDV 信号到可追溯的表观速度";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};
pptx.defineLayout({ name: "CUSTOM_16X9", width: 10, height: 5.625 });
pptx.layout = "CUSTOM_16X9";

const C = {
  red: "B42318",
  deepRed: "8E1B10",
  redSoft: "F7E7E2",
  teal: "0F7785",
  tealSoft: "E7F2F3",
  orange: "D96B27",
  orangeSoft: "F9EEE5",
  ink: "202124",
  muted: "62676D",
  border: "E5D6D0",
  warm: "F6F1EE",
  warm2: "FBF8F6",
  gray: "F1F2F3",
  gray2: "D7D9DC",
  white: "FFFFFF",
  black: "111111",
};

const FONT = "Microsoft YaHei";
const EN = "Aptos";
const S = pptx.ShapeType;

function shadow() {
  return {
    type: "outer",
    color: "7B5E55",
    blur: 2,
    offset: 1,
    angle: 45,
    opacity: 0.1,
  };
}

function addText(slide, text, opts = {}) {
  slide.addText(text, {
    fontFace: FONT,
    fontSize: 15,
    color: C.ink,
    margin: 0,
    valign: "mid",
    breakLine: false,
    ...opts,
  });
}

function addShape(slide, type, opts) {
  slide.addShape(type, opts);
}

function addBase(slide, title, number) {
  slide.background = { color: C.warm2 };
  addShape(slide, S.rect, {
    x: 0,
    y: 0,
    w: 10,
    h: 0.88,
    fill: { color: C.white },
    line: { color: C.white, transparency: 100 },
  });
  addShape(slide, S.roundRect, {
    x: 0.34,
    y: 0.22,
    w: 0.11,
    h: 0.43,
    rectRadius: 0.04,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  const titleSize = title.length > 30 ? 19.5 : title.length > 24 ? 21.5 : 24.5;
  addText(slide, title, {
    x: 0.62,
    y: 0.21,
    w: 8.72,
    h: 0.4,
    fontSize: titleSize,
    bold: true,
    color: C.deepRed,
    fit: "shrink",
  });
  addShape(slide, S.chevron, {
    x: 9.45,
    y: 0.14,
    w: 0.42,
    h: 0.54,
    fill: { color: C.warm },
    line: { color: C.warm, transparency: 100 },
  });
  addText(slide, String(number).padStart(2, "0"), {
    x: 9.42,
    y: 5.28,
    w: 0.35,
    h: 0.17,
    fontFace: EN,
    fontSize: 8,
    color: "A99A94",
    align: "right",
  });
}

function addFooter(slide, text) {
  addText(slide, text, {
    x: 0.55,
    y: 5.24,
    w: 8.75,
    h: 0.18,
    fontSize: 9.2,
    color: C.muted,
    fit: "shrink",
  });
}

function addCard(slide, x, y, w, h, title, body, opts = {}) {
  const fill = opts.fill || C.white;
  const lineColor = opts.line || C.border;
  addShape(slide, S.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.08,
    fill: { color: fill },
    line: { color: lineColor, width: opts.lineWidth || 1 },
    shadow: opts.noShadow ? undefined : shadow(),
  });
  if (opts.accent) {
    addShape(slide, S.roundRect, {
      x: x + 0.14,
      y: y + 0.16,
      w: 0.07,
      h: h - 0.32,
      rectRadius: 0.03,
      fill: { color: opts.accent },
      line: { color: opts.accent, transparency: 100 },
    });
  }
  const textX = x + (opts.accent ? 0.32 : 0.18);
  const textW = w - (opts.accent ? 0.48 : 0.36);
  if (!title) {
    addText(slide, body, {
      x: textX,
      y: y + 0.08,
      w: textW,
      h: Math.max(0.12, h - 0.16),
      fontSize: opts.bodySize || 12.5,
      color: opts.bodyColor || C.ink,
      valign: "mid",
      breakLine: true,
      fit: "shrink",
      align: opts.bodyAlign || "left",
    });
    return;
  }
  if (h < 0.85) {
    const titleW = Math.min(0.75, Math.max(0.48, w * 0.18));
    addText(slide, title, {
      x: textX,
      y: y + 0.08,
      w: titleW,
      h: Math.max(0.16, h - 0.16),
      fontSize: opts.titleSize || 14,
      bold: true,
      color: opts.titleColor || C.deepRed,
      fit: "shrink",
    });
    addText(slide, body, {
      x: textX + titleW + 0.12,
      y: y + 0.08,
      w: Math.max(0.25, textW - titleW - 0.12),
      h: Math.max(0.16, h - 0.16),
      fontSize: opts.bodySize || 11,
      color: opts.bodyColor || C.ink,
      valign: "mid",
      fit: "shrink",
    });
    return;
  }
  addText(slide, title, {
    x: textX,
    y: y + 0.14,
    w: textW,
    h: 0.32,
    fontSize: opts.titleSize || 17,
    bold: true,
    color: opts.titleColor || C.deepRed,
    fit: "shrink",
  });
  addText(slide, body, {
    x: textX,
    y: y + 0.51,
    w: textW,
    h: Math.max(0.16, h - 0.63),
    fontSize: opts.bodySize || 12.5,
    color: opts.bodyColor || C.ink,
    valign: "top",
    breakLine: true,
    fit: "shrink",
  });
}

function addPill(slide, x, y, w, text, fill, color = C.white) {
  addShape(slide, S.roundRect, {
    x,
    y,
    w,
    h: 0.38,
    rectRadius: 0.1,
    fill: { color: fill },
    line: { color: fill, transparency: 100 },
  });
  addText(slide, text, {
    x,
    y: y + 0.01,
    w,
    h: 0.32,
    fontSize: 12.5,
    bold: true,
    color,
    align: "center",
  });
}

function addBadge(slide, x, y, text, fill = C.red, size = 0.42) {
  addShape(slide, S.ellipse, {
    x,
    y,
    w: size,
    h: size,
    fill: { color: fill },
    line: { color: fill, transparency: 100 },
  });
  addText(slide, text, {
    x,
    y: y + 0.01,
    w: size,
    h: size - 0.02,
    fontFace: EN,
    fontSize: 13,
    bold: true,
    color: C.white,
    align: "center",
  });
}

function addArrow(slide, x, y, w, h = 0, color = C.red, width = 1.8) {
  const x2 = x + w;
  const y2 = y + h;
  addShape(slide, S.line, {
    x: Math.min(x, x2),
    y: Math.min(y, y2),
    w: Math.max(0.001, Math.abs(w)),
    h: Math.max(0.001, Math.abs(h)),
    flipH: w < 0,
    flipV: h < 0,
    line: { color, width, endArrowType: "triangle" },
  });
}

function addImagePanel(slide, imagePath, x, y, w, h, caption) {
  addShape(slide, S.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.05,
    fill: { color: C.white },
    line: { color: C.border, width: 1 },
    shadow: shadow(),
  });
  slide.addImage({
    path: imagePath,
    x: x + 0.08,
    y: y + 0.08,
    w: w - 0.16,
    h: h - (caption ? 0.36 : 0.16),
    altText: caption || "DPS Studio project figure",
  });
  if (caption) {
    addText(slide, caption, {
      x: x + 0.12,
      y: y + h - 0.25,
      w: w - 0.24,
      h: 0.14,
      fontSize: 8.5,
      color: C.muted,
      align: "center",
      fit: "shrink",
    });
  }
}

function polyline(slide, points, x, y, w, h, color, width = 2) {
  for (let i = 0; i < points.length - 1; i += 1) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[i + 1];
    const startX = x + x1 * w;
    const startY = y + (1 - y1) * h;
    const endX = x + x2 * w;
    const endY = y + (1 - y2) * h;
    addShape(slide, S.line, {
      x: Math.min(startX, endX),
      y: Math.min(startY, endY),
      w: Math.max(0.001, Math.abs(endX - startX)),
      h: Math.max(0.001, Math.abs(endY - startY)),
      flipH: endX < startX,
      flipV: endY < startY,
      line: { color, width },
    });
  }
}

function parseVelocityCsv(csvPath) {
  const lines = fs.readFileSync(csvPath, "utf8").trim().split(/\r?\n/);
  const headers = lines[0].split(",");
  const timeIdx = headers.indexOf("time_relative_to_event_s");
  const velocityIdx = headers.indexOf("apparent_velocity_m_s");
  const rows = [];
  for (const line of lines.slice(1)) {
    const cells = line.split(",");
    const t = Number(cells[timeIdx]) * 1e6;
    const v = Number(cells[velocityIdx]);
    if (Number.isFinite(t) && Number.isFinite(v) && t >= 0 && t <= 0.2) {
      rows.push({ t, v });
    }
  }
  const maxPoints = 10;
  const step = Math.max(1, Math.floor(rows.length / maxPoints));
  const sampled = rows.filter((_, index) => index % step === 0);
  if (sampled[sampled.length - 1] !== rows[rows.length - 1]) {
    sampled.push(rows[rows.length - 1]);
  }
  return {
    labels: sampled.map((row) => row.t.toFixed(3)),
    values: sampled.map((row) => Number(row.v.toFixed(2))),
    count: rows.length,
  };
}

function readNotes() {
  const notesPath = path.join(ROOT, "speech.md");
  const text = fs.readFileSync(notesPath, "utf8");
  const notes = {};
  const regex = /## Slide (\d+):[^\n]*\n([\s\S]*?)(?=\n## Slide \d+:|$)/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    notes[Number(match[1])] = match[2].trim();
  }
  return notes;
}

const notes = readNotes();
const v1 = parseVelocityCsv(
  path.join(
    ROOT,
    "..",
    "..",
    "..",
    "outputs",
    "production_runs",
    "run_20260724_004901_103968",
    "balanced",
    "pdv_channel_1",
    "apparent_velocity.csv",
  ),
);
const v2 = parseVelocityCsv(
  path.join(
    ROOT,
    "..",
    "..",
    "..",
    "outputs",
    "production_runs",
    "run_20260724_004901_103968",
    "balanced",
    "pdv_channel_2",
    "apparent_velocity.csv",
  ),
);

function finishSlide(slide, number) {
  if (notes[number]) {
    slide.addNotes(notes[number]);
  }
}

function addVelocityChart(slide, data, x, y, w, h, name) {
  slide.addChart(
    pptx.ChartType.line,
    [{ name, labels: data.labels, values: data.values }],
    {
      x,
      y,
      w,
      h,
      chartColors: [C.teal],
      showTitle: false,
      showLegend: false,
      showValue: false,
      showCatName: false,
      lineSize: 2.5,
      showMarker: true,
      markerSize: 3,
      catAxisLabelFontFace: EN,
      catAxisLabelFontSize: 8,
      catAxisLabelColor: C.muted,
      catAxisLabelRotate: 0,
      valAxisLabelFontFace: EN,
      valAxisLabelFontSize: 8,
      valAxisLabelColor: C.muted,
      valAxisMinVal: 0,
      valAxisMaxVal: 600,
      valAxisMajorUnit: 100,
      valGridLine: { color: "E5E7E9", size: 0.5 },
      catGridLine: { style: "none" },
      chartArea: {
        fill: { color: C.white },
        border: { color: C.border, size: 0.7 },
        roundedCorners: true,
      },
      showBorder: false,
    },
  );
}

// Slide 1
{
  const slide = pptx.addSlide();
  slide.background = { color: C.warm2 };
  addShape(slide, S.roundRect, {
    x: -0.15,
    y: 0.48,
    w: 6.45,
    h: 4.55,
    rectRadius: 0.15,
    fill: { color: C.deepRed },
    line: { color: C.deepRed, transparency: 100 },
  });
  addText(slide, "DPS Studio：", {
    x: 0.48,
    y: 1.15,
    w: 4.9,
    h: 0.58,
    fontFace: EN,
    fontSize: 34,
    bold: true,
    color: C.white,
  });
  addText(slide, "从原始 PDV 信号到\n可追溯的表观速度", {
    x: 0.48,
    y: 1.72,
    w: 5.1,
    h: 1.24,
    fontSize: 31,
    bold: true,
    color: C.white,
    breakLine: true,
    valign: "top",
    fit: "shrink",
  });
  addText(slide, "面向冲击波实验的 PDV 数据分析软件开发进展", {
    x: 0.5,
    y: 3.17,
    w: 4.9,
    h: 0.34,
    fontSize: 16,
    color: "FCEDE8",
  });
  addText(slide, "课题组组会｜开发进展与下一阶段", {
    x: 0.5,
    y: 3.85,
    w: 4.9,
    h: 0.35,
    fontSize: 17,
    bold: true,
    color: C.white,
  });
  addText(slide, "2026年7月25日", {
    x: 0.5,
    y: 4.35,
    w: 2.4,
    h: 0.3,
    fontSize: 14,
    color: "F6D9D1",
  });
  addShape(slide, S.chevron, {
    x: 8.9,
    y: 0.15,
    w: 0.8,
    h: 0.55,
    fill: { color: C.warm },
    line: { color: C.warm, transparency: 100 },
  });
  const points = [];
  for (let i = 0; i <= 36; i += 1) {
    points.push([i / 36, 0.5 + 0.27 * Math.sin(i * 0.72)]);
  }
  polyline(slide, points, 6.5, 1.5, 3.0, 1.5, "D2A096", 1.8);
  addShape(slide, S.ellipse, {
    x: 8.2,
    y: 2.09,
    w: 0.16,
    h: 0.16,
    fill: { color: C.red },
    line: { color: C.white, width: 1 },
  });
  addText(slide, "可追溯 · 可验证 · 可交付", {
    x: 6.63,
    y: 3.34,
    w: 2.85,
    h: 0.4,
    fontSize: 17,
    bold: true,
    color: C.deepRed,
    align: "center",
  });
  addText(slide, "当前是可运行的数值分析工作流\n尚不是完成发布的 GUI 软件", {
    x: 6.75,
    y: 3.9,
    w: 2.65,
    h: 0.76,
    fontSize: 13,
    color: C.muted,
    align: "center",
    breakLine: true,
  });
  finishSlide(slide, 1);
}

// Slide 2
{
  const slide = pptx.addSlide();
  addBase(slide, "速度曲线连接实验信号与后续物理判断", 2);
  const stages = [
    ["1", "实验信号", "双通道时间—电压序列"],
    ["2", "拍频脊线", "STFT 能量与谱峰轨迹"],
    ["3", "表观速度", "显式波长换算，无符号"],
    ["4", "物理分析", "质量判断与修正后解释"],
  ];
  stages.forEach((stage, index) => {
    const x = 0.48 + index * 2.38;
    addBadge(slide, x + 0.1, 1.22, stage[0]);
    addCard(slide, x, 1.62, 2.05, 2.25, stage[1], stage[2], {
      fill: index === 3 ? C.warm : C.white,
      accent: index === 2 ? C.teal : C.red,
      bodySize: 13,
      titleSize: 18,
    });
    if (index < stages.length - 1) {
      addArrow(slide, x + 2.08, 2.72, 0.29, 0);
    }
  });
  addPill(slide, 3.86, 3.32, 2.28, "质量 / 修正闸门", C.teal);
  addCard(
    slide,
    0.55,
    4.25,
    8.9,
    0.7,
    "关键结论",
    "软件是实验信号与物理判断之间的关键桥梁；只有跨过质量与物理修正闸门，结果才具备进一步解释的基础。",
    {
      fill: C.redSoft,
      line: C.redSoft,
      noShadow: true,
      titleSize: 14,
      bodySize: 12,
      titleColor: C.red,
    },
  );
  finishSlide(slide, 2);
}

// Slide 3
{
  const slide = pptx.addSlide();
  addBase(slide, "旧流程的核心风险不是界面陈旧，而是证据链不完整", 3);
  addCard(slide, 0.42, 1.22, 2.45, 3.4, "旧输出曲线", "", {
    fill: C.white,
    accent: C.red,
    titleSize: 19,
  });
  addShape(slide, S.line, {
    x: 0.75,
    y: 3.42,
    w: 1.75,
    h: 0,
    line: { color: C.muted, width: 1 },
  });
  addShape(slide, S.line, {
    x: 0.75,
    y: 2.0,
    w: 0,
    h: 1.42,
    line: { color: C.muted, width: 1 },
  });
  polyline(
    slide,
    [
      [0, 0.15],
      [0.15, 0.26],
      [0.32, 0.5],
      [0.48, 0.78],
      [0.63, 0.65],
      [0.82, 0.38],
      [1, 0.27],
    ],
    0.83,
    2.08,
    1.55,
    1.18,
    C.teal,
    2.4,
  );
  addPill(slide, 0.72, 3.63, 1.85, "回归指纹 ≠ 物理真值", C.red);
  addText(slide, "曲线连续，不代表分支身份正确", {
    x: 0.68,
    y: 4.1,
    w: 1.9,
    h: 0.34,
    fontSize: 11.5,
    color: C.muted,
    align: "center",
  });
  const risks = [
    ["参数缺失", "波长、窗长、搜索带和人工选择不可追溯"],
    ["谱证据缺失", "只有 measured / zero_masked，无法重建谱状态"],
    ["质量状态缺失", "连续曲线仍可能跟踪错误谱分支"],
  ];
  risks.forEach((risk, index) => {
    addCard(slide, 3.18, 1.22 + index * 1.1, 3.72, 0.88, risk[0], risk[1], {
      fill: index === 1 ? C.tealSoft : C.white,
      accent: index === 1 ? C.teal : C.red,
      titleSize: 16,
      bodySize: 11.5,
      noShadow: true,
    });
  });
  addArrow(slide, 6.95, 2.73, 0.42, 0);
  addShape(slide, S.roundRect, {
    x: 7.42,
    y: 1.45,
    w: 2.15,
    h: 2.65,
    rectRadius: 0.08,
    fill: { color: C.warm },
    line: { color: C.red, width: 1 },
    shadow: shadow(),
  });
  addText(slide, "物理结论？", {
    x: 7.65,
    y: 1.68,
    w: 1.7,
    h: 0.38,
    fontSize: 22,
    bold: true,
    color: C.red,
    align: "center",
  });
  addText(slide, "?", {
    x: 8.05,
    y: 2.1,
    w: 0.9,
    h: 0.85,
    fontFace: EN,
    fontSize: 50,
    bold: true,
    color: C.red,
    align: "center",
  });
  addText(slide, "证据不完整\n结论不可确认", {
    x: 7.68,
    y: 3.18,
    w: 1.62,
    h: 0.62,
    fontSize: 15,
    color: C.ink,
    align: "center",
    breakLine: true,
  });
  finishSlide(slide, 3);
}

// Slide 4
{
  const slide = pptx.addSlide();
  addBase(slide, "Python 重建：把算法、配置和验证放进同一工作流", 4);
  addCard(slide, 3.42, 2.03, 3.16, 1.1, "Python core / workflow", "算法 · 配置 · 验证", {
    fill: C.white,
    line: C.red,
    titleSize: 15.5,
    bodySize: 11.5,
    titleColor: C.red,
  });
  const cards = [
    [0.55, 1.18, "数值计算", "NumPy + SciPy\n数组、Hann 窗、STFT", C.teal],
    [6.9, 1.18, "可复现输出", "Matplotlib\nproduction 图与实验输出", C.red],
    [0.55, 3.27, "交互与交付", "PySide6 + PyQtGraph：GUI 待实现\nPyInstaller：跨机器打包待验证", C.red],
    [6.9, 3.27, "质量验证", "pytest + Ruff + mypy\n271 passed｜39 个源文件", C.teal],
  ];
  cards.forEach(([x, y, title, body, accent]) =>
    addCard(slide, x, y, 2.55, 1.25, title, body, {
      accent,
      fill: C.white,
      titleSize: 17,
      bodySize: 11.5,
    }),
  );
  addArrow(slide, 3.1, 1.77, 0.6, 0.55, C.red, 1.3);
  addArrow(slide, 6.9, 1.77, -0.6, 0.55, C.red, 1.3);
  addArrow(slide, 3.1, 3.82, 0.6, -0.55, C.red, 1.3);
  addArrow(slide, 6.9, 3.82, -0.6, -0.55, C.red, 1.3);
  addPill(slide, 1.55, 4.78, 2.0, "271 tests passed", C.teal);
  addPill(slide, 4.0, 4.78, 2.0, "Ruff 全部通过", C.red);
  addPill(slide, 6.45, 4.78, 2.0, "mypy 39 files", C.teal);
  finishSlide(slide, 4);
}

// Slide 5
{
  const slide = pptx.addSlide();
  addBase(slide, "处理链已打通表观速度闭环，物理修正仍被明确隔离", 5);
  addText(slide, "已实现", {
    x: 0.55,
    y: 1.02,
    w: 1.1,
    h: 0.3,
    fontSize: 16,
    bold: true,
    color: C.red,
  });
  const implemented = [
    "只读输入",
    "STFT",
    "峰脊线",
    "三点精修",
    "无符号\n表观速度",
    "描述性\n质量",
    "非覆盖\n输出",
  ];
  implemented.forEach((label, index) => {
    const x = 0.48 + index * 1.11;
    addShape(slide, S.roundRect, {
      x,
      y: 1.45,
      w: 0.92,
      h: 0.86,
      rectRadius: 0.06,
      fill: { color: C.red },
      line: { color: C.red, transparency: 100 },
    });
    addText(slide, label, {
      x: x + 0.05,
      y: 1.58,
      w: 0.82,
      h: 0.56,
      fontSize: 12,
      bold: true,
      color: C.white,
      align: "center",
      breakLine: true,
      fit: "shrink",
    });
    if (index < implemented.length - 1) {
      addArrow(slide, x + 0.92, 1.88, 0.18, 0, C.red, 1.4);
    }
  });
  addArrow(slide, 7.82, 1.88, 0.18, 0, C.red, 1.4);
  addShape(slide, S.rect, {
    x: 8.03,
    y: 1.22,
    w: 0.12,
    h: 1.35,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addShape(slide, S.rect, {
    x: 8.17,
    y: 1.22,
    w: 0.15,
    h: 1.35,
    fill: { color: C.teal },
    line: { color: C.teal, transparency: 100 },
  });
  addText(slide, "物理修正隔离闸门", {
    x: 7.62,
    y: 0.92,
    w: 1.35,
    h: 0.3,
    fontSize: 11.5,
    bold: true,
    color: C.red,
    align: "center",
  });
  addText(slide, "尚未实现", {
    x: 8.38,
    y: 1.03,
    w: 1.05,
    h: 0.3,
    fontSize: 13.5,
    bold: true,
    color: C.muted,
    align: "center",
  });
  addShape(slide, S.roundRect, {
    x: 8.4,
    y: 1.38,
    w: 1.05,
    h: 1.72,
    rectRadius: 0.05,
    fill: { color: C.gray },
    line: { color: "9EA2A6", width: 1, dash: "dash" },
  });
  addText(slide, "LiF 修正\ncorrected velocity\n有符号速度\n通道融合\nGUI", {
    x: 8.5,
    y: 1.55,
    w: 0.85,
    h: 1.38,
    fontSize: 9.5,
    color: C.muted,
    align: "center",
    breakLine: true,
    fit: "shrink",
  });
  addText(slide, "正在完善", {
    x: 0.55,
    y: 2.82,
    w: 1.2,
    h: 0.3,
    fontSize: 16,
    bold: true,
    color: C.orange,
  });
  const improving = [
    ["弱信号判据", "从描述性质量推进到可验证阈值"],
    ["双通道质量决策", "先输出证据，再建立择优规则"],
    ["preview 语义", "明确 development preview 与正式结果"],
  ];
  improving.forEach((item, index) => {
    addCard(slide, 0.55 + index * 3.0, 3.2, 2.72, 1.05, item[0], item[1], {
      fill: C.orangeSoft,
      line: "E8AE82",
      accent: C.orange,
      titleColor: C.orange,
      titleSize: 15,
      bodySize: 11,
      noShadow: true,
    });
  });
  addCard(
    slide,
    0.55,
    4.48,
    8.9,
    0.62,
    "边界",
    "当前闭环止于无符号表观速度与描述性质量；全时段 preview 不是正式测量。",
    {
      fill: C.redSoft,
      line: C.redSoft,
      noShadow: true,
      titleSize: 13,
      bodySize: 11.5,
      titleColor: C.red,
    },
  );
  finishSlide(slide, 5);
}

// Slide 6
{
  const slide = pptx.addSlide();
  addBase(slide, "可信输入从只读原始数据、SI 单位和显式列映射开始", 6);
  const constraints = [
    ["1", "显式列映射", "time=0｜channel_1=1｜channel_2=2\n写入单一 TOML 配置"],
    ["2", "双通道独立", "分别构造 SignalRecord\n不做输入层电压平均"],
    ["3", "只读与 SI", "秒、伏特、赫兹；记录源文件 SHA-256"],
    ["4", "不静默处理", "不丢列、不插值、不平滑、不重采样；问题传递为 NaN/状态"],
  ];
  constraints.forEach((item, index) => {
    const y = 1.08 + index * 0.94;
    addBadge(slide, 0.52, y + 0.22, item[0], index % 2 ? C.teal : C.red);
    addCard(slide, 1.03, y, 2.65, 0.86, item[1], item[2], {
      fill: index % 2 ? C.tealSoft : C.white,
      line: index % 2 ? "B8DADD" : C.border,
      noShadow: true,
      titleSize: 14,
      bodySize: 9.8,
    });
  });
  addImagePanel(
    slide,
    ASSET("raw_voltage_event.png"),
    3.95,
    1.08,
    5.52,
    3.87,
    "真实输出｜data/raw/20260607.csv｜仅截取显示窗口，未平滑、未插值、未重采样",
  );
  addFooter(slide, "源数据只读使用；任务前后 SHA-256 保持不变。");
  finishSlide(slide, 6);
}

// Slide 7
{
  const slide = pptx.addSlide();
  addBase(slide, "STFT 将时变拍频转换为可追踪的时频脊线", 7);
  addImagePanel(
    slide,
    ASSET("balanced_ch1_stft_ridge.png"),
    0.48,
    1.08,
    6.35,
    4.0,
    "真实输出｜Balanced｜PDV 通道 1｜搜索 0.05–2.0 GHz",
  );
  addCard(slide, 7.08, 1.08, 2.4, 0.88, "滑动时间窗", "保留频率随时间的演化", {
    accent: C.red,
    fill: C.white,
    titleSize: 15,
    bodySize: 11,
    noShadow: true,
  });
  addCard(slide, 7.08, 2.08, 2.4, 0.96, "Balanced", "Hann｜768｜hop 128｜NFFT 4096", {
    accent: C.teal,
    fill: C.tealSoft,
    titleSize: 15,
    bodySize: 11,
    noShadow: true,
  });
  addCard(slide, 7.08, 3.16, 2.4, 0.96, "边界说明", "NFFT 加密频格，不等于真实分辨率提升", {
    accent: C.red,
    fill: C.white,
    titleSize: 15,
    bodySize: 11,
    noShadow: true,
  });
  addPill(slide, 7.08, 4.44, 2.4, "白色脊线是候选轨迹", C.red);
  finishSlide(slide, 7);
}

// Slide 8
{
  const slide = pptx.addSlide();
  addBase(slide, "脊线给出拍频轨迹；只有显式波长才能换算表观速度", 8);
  addText(slide, "带内最大谱峰 → 三点对数幅值精修", {
    x: 0.55,
    y: 1.08,
    w: 3.2,
    h: 0.35,
    fontSize: 17,
    bold: true,
  });
  addText(slide, "vₐₚₚ = λ₀ fᵦ / 2", {
    x: 0.62,
    y: 1.55,
    w: 2.9,
    h: 0.7,
    fontFace: "Cambria Math",
    fontSize: 31,
    italic: true,
    color: C.teal,
    align: "center",
  });
  addCard(slide, 0.55, 2.25, 3.25, 0.86, "λ₀ = 1.55 μm", "未确认的演示值，不作为实验参数结论", {
    fill: C.redSoft,
    line: C.redSoft,
    noShadow: true,
    titleSize: 15,
    bodySize: 10.3,
  });
  addCard(slide, 0.55, 3.2, 3.25, 0.86, "失败保持 NaN", "精修失败与 PRE_EVENT 核心速度均不伪造数值", {
    fill: C.white,
    noShadow: true,
    titleSize: 15,
    bodySize: 10.3,
  });
  addCard(slide, 0.55, 4.15, 3.25, 0.86, "物理量分离", "apparent velocity 与未来 corrected velocity 必须分开", {
    fill: C.tealSoft,
    line: "B8DADD",
    noShadow: true,
    titleSize: 15,
    bodySize: 10.3,
  });
  addText(slide, "Balanced / 通道 1｜正式候选帧", {
    x: 4.05,
    y: 1.05,
    w: 5.3,
    h: 0.3,
    fontSize: 14,
    bold: true,
    color: C.deepRed,
  });
  addVelocityChart(slide, v1, 4.02, 1.38, 5.42, 3.65, "通道 1");
  addText(slide, "相对事件时间 (μs)｜无符号表观速度 (m/s)", {
    x: 4.25,
    y: 4.96,
    w: 5.0,
    h: 0.18,
    fontSize: 9,
    color: C.muted,
    align: "center",
  });
  finishSlide(slide, 8);
}

// Slide 9
{
  const slide = pptx.addSlide();
  addBase(slide, "双通道必须独立分析；质量量只提供诊断证据", 9);
  slide.addChart(
    pptx.ChartType.bar,
    [
      {
        name: "峰—背景幅值对比度中位数",
        labels: ["Balanced\n通道1", "Balanced\n通道2", "High time\n通道1", "High time\n通道2"],
        values: [52.5, 55.8, 48.1, 51.1],
      },
      {
        name: "峰—竞争峰幅值对比度中位数",
        labels: ["Balanced\n通道1", "Balanced\n通道2", "High time\n通道1", "High time\n通道2"],
        values: [13.3, 19.9, 13.3, 19.9],
      },
    ],
    {
      x: 0.48,
      y: 1.18,
      w: 6.0,
      h: 3.75,
      barDir: "col",
      grouping: "clustered",
      chartColors: [C.red, C.teal],
      showTitle: true,
      title: "最近真实运行的描述性谱质量统计（不是正式 SNR）",
      titleFontFace: FONT,
      titleFontSize: 13,
      showLegend: true,
      legendPos: "b",
      legendFontFace: FONT,
      legendFontSize: 8,
      showValue: true,
      dataLabelPosition: "outEnd",
      dataLabelColor: C.ink,
      dataLabelFormatCode: "0.0",
      catAxisLabelFontFace: FONT,
      catAxisLabelFontSize: 9,
      valAxisLabelFontFace: EN,
      valAxisLabelFontSize: 8,
      valAxisMinVal: 0,
      valAxisMaxVal: 65,
      valAxisMajorUnit: 10,
      valGridLine: { color: "E2E4E5", size: 0.5 },
      catGridLine: { style: "none" },
      chartArea: {
        fill: { color: C.white },
        border: { color: C.border, size: 0.7 },
        roundedCorners: true,
      },
    },
  );
  addCard(slide, 6.75, 1.18, 2.72, 1.65, "可以说", "· 两个量程分别执行 STFT、脊线与速度换算\n· dB 量描述当前谱结构", {
    fill: C.tealSoft,
    line: C.teal,
    titleColor: C.teal,
    titleSize: 19,
    bodySize: 12.5,
    noShadow: true,
  });
  addCard(slide, 6.75, 3.05, 2.72, 1.88, "不能说", "· 通道 2 数值较高 ≠ 自动更可信\n· 这些 dB 不是正式 SNR\n· 当前没有 GOOD/BAD 阈值或自动融合", {
    fill: C.redSoft,
    line: C.red,
    titleColor: C.red,
    titleSize: 19,
    bodySize: 12.2,
    noShadow: true,
  });
  addFooter(slide, "来源：run_20260724_004901_103968；数值只描述当前数据，不自动决定可信通道。");
  finishSlide(slide, 9);
}

// Slide 10
{
  const slide = pptx.addSlide();
  addBase(slide, "core/workflow 与 GUI 解耦，让数值链可以独立验证", 10);
  addText(slide, "入口与配置", {
    x: 0.55,
    y: 1.0,
    w: 1.3,
    h: 0.3,
    fontSize: 15,
    bold: true,
    color: C.deepRed,
  });
  const topNodes = [
    [0.55, "run_demo_pipeline.py"],
    [2.6, "TOML（只读配置）"],
    [4.65, "production_outputs.py"],
  ];
  topNodes.forEach(([x, label], index) => {
    addShape(slide, S.roundRect, {
      x,
      y: 1.38,
      w: 1.65,
      h: 0.58,
      rectRadius: 0.05,
      fill: { color: C.white },
      line: { color: index === 1 ? C.teal : C.red, width: 1 },
    });
    addText(slide, label, {
      x: x + 0.06,
      y: 1.48,
      w: 1.53,
      h: 0.35,
      fontFace: EN,
      fontSize: 10,
      bold: index === 1,
      align: "center",
      fit: "shrink",
    });
    if (index < 2) addArrow(slide, x + 1.67, 1.67, 0.35, 0, C.ink, 1.2);
  });
  addShape(slide, S.roundRect, {
    x: 2.7,
    y: 2.55,
    w: 2.2,
    h: 0.72,
    rectRadius: 0.06,
    fill: { color: C.tealSoft },
    line: { color: C.teal, width: 1.2 },
  });
  addText(slide, "core.workflow", {
    x: 2.8,
    y: 2.7,
    w: 2.0,
    h: 0.34,
    fontFace: EN,
    fontSize: 20,
    bold: true,
    color: C.teal,
    align: "center",
  });
  addArrow(slide, 5.42, 1.98, -1.25, 0.62, C.ink, 1.2);
  addArrow(slide, 5.85, 1.98, 0, 0.38, C.teal, 1.2);
  addCard(slide, 5.3, 2.42, 1.55, 0.9, "manifest", "配置｜源哈希｜Git 状态｜生成文件", {
    fill: C.white,
    line: C.teal,
    titleColor: C.teal,
    titleSize: 15,
    bodySize: 9.5,
    noShadow: true,
  });
  addShape(slide, S.roundRect, {
    x: 0.55,
    y: 2.62,
    w: 1.35,
    h: 0.62,
    rectRadius: 0.05,
    fill: { color: C.gray },
    line: { color: "969A9F", width: 1, dash: "dash" },
  });
  addText(slide, "GUI 占位", {
    x: 0.65,
    y: 2.75,
    w: 1.15,
    h: 0.28,
    fontSize: 13.5,
    bold: true,
    color: C.muted,
    align: "center",
  });
  addArrow(slide, 1.9, 2.93, 0.72, 0, "969A9F", 1.2);
  addText(slide, "未来：仅调用公共 API", {
    x: 1.42,
    y: 2.52,
    w: 1.2,
    h: 0.2,
    fontSize: 8.5,
    color: C.muted,
  });
  const modules = ["io", "time_frequency", "ridge", "physics"];
  modules.forEach((module, index) => {
    const x = 0.88 + index * 1.52;
    addShape(slide, S.roundRect, {
      x,
      y: 4.02,
      w: 1.25,
      h: 0.52,
      rectRadius: 0.04,
      fill: { color: C.white },
      line: { color: C.teal, width: 1 },
    });
    addText(slide, module, {
      x: x + 0.05,
      y: 4.12,
      w: 1.15,
      h: 0.28,
      fontFace: EN,
      fontSize: index === 1 ? 8.5 : 12,
      bold: true,
      color: C.teal,
      align: "center",
      fit: "shrink",
    });
    addArrow(slide, 3.8, 3.28, x + 0.62 - 3.8, 0.68, C.ink, 1);
  });
  const principles = [
    ["A", "单向依赖", "入口 → production I/O → core.workflow → 算法模块"],
    ["B", "边界明确", "core 不导入 scripts、Matplotlib 或 GUI"],
    ["C", "GUI 尚未实现", "未来只能调用 core 公共 API"],
    ["D", "输出可追溯", "manifest 记录配置、哈希、Git 状态和文件"],
  ];
  principles.forEach((item, index) => {
    addBadge(slide, 7.15, 1.15 + index * 0.96, item[0], index % 2 ? C.teal : C.red, 0.36);
    addText(slide, item[1], {
      x: 7.62,
      y: 1.12 + index * 0.96,
      w: 1.5,
      h: 0.28,
      fontSize: 15,
      bold: true,
      color: index % 2 ? C.teal : C.red,
    });
    addText(slide, item[2], {
      x: 7.62,
      y: 1.42 + index * 0.96,
      w: 1.8,
      h: 0.4,
      fontSize: 10,
      color: C.muted,
      valign: "top",
      fit: "shrink",
    });
  });
  finishSlide(slide, 10);
}

// Slide 11
{
  const slide = pptx.addSlide();
  addBase(slide, "当前工作树已形成可运行闭环；质量门通过但尚未发布", 11);
  const levels = [
    ["1", "基础闭环", "输入安全 · STFT · 脊线 · 精修 · 表观速度 · 描述性质量", C.red],
    ["2", "基本可用", "双 Profile · 双通道 production · manifest · 真实输出", C.teal],
    ["3", "正在优化", "弱信号决策 · preview 语义 · 文档与输出契约同步", C.teal],
    ["4", "尚未实现", "GUI · 完整 CLI · LiF 修正 · 可靠阈值 · 部署验证", "767A7F"],
  ];
  levels.forEach((item, index) => {
    const y = 1.15 + index * 0.88;
    addShape(slide, S.chevron, {
      x: 0.55,
      y,
      w: 1.5,
      h: 0.7,
      fill: { color: item[3] },
      line: { color: item[3], transparency: 100 },
    });
    addText(slide, item[1], {
      x: 0.65,
      y: y + 0.12,
      w: 1.15,
      h: 0.42,
      fontSize: 13.5,
      bold: true,
      color: C.white,
      align: "center",
      fit: "shrink",
    });
    addShape(slide, S.roundRect, {
      x: 1.92,
      y,
      w: 4.48,
      h: 0.7,
      rectRadius: 0.04,
      fill: { color: index === 0 ? C.redSoft : index < 3 ? C.tealSoft : C.gray },
      line: { color: index === 0 ? C.red : index < 3 ? C.teal : "A6A9AC", width: 0.8 },
    });
    addText(slide, item[2], {
      x: 2.15,
      y: y + 0.16,
      w: 4.0,
      h: 0.38,
      fontSize: 12.5,
      color: C.ink,
      fit: "shrink",
    });
  });
  const stats = [
    ["271", "tests passed"],
    ["39", "source files · mypy passed"],
    ["30", "production files · 最新真实 run"],
  ];
  stats.forEach((stat, index) => {
    const y = 1.22 + index * 1.15;
    addText(slide, stat[0], {
      x: 6.85,
      y,
      w: 1.2,
      h: 0.62,
      fontFace: EN,
      fontSize: 36,
      bold: true,
      color: C.red,
      align: "right",
    });
    addText(slide, stat[1], {
      x: 8.18,
      y: y + 0.2,
      w: 1.25,
      h: 0.28,
      fontSize: 11,
      color: C.muted,
      fit: "shrink",
    });
  });
  addPill(slide, 7.0, 4.45, 2.35, "Ruff · All checks passed", C.teal);
  addCard(
    slide,
    0.58,
    4.72,
    5.85,
    0.5,
    "状态",
    "HEAD 11b761f｜dirty worktree ≠ released version｜尚未发布",
    {
      fill: C.redSoft,
      line: C.redSoft,
      noShadow: true,
      titleSize: 12,
      bodySize: 10.5,
      titleColor: C.red,
    },
  );
  finishSlide(slide, 11);
}

// Slide 12
{
  const slide = pptx.addSlide();
  addBase(slide, "真实运行显示两通道结果同量级，但不能自动判定“哪个更可信”", 12);
  const stats = [
    ["244", "两通道各 244 个候选帧"],
    ["538 / 532 m/s", "两通道首候选表观速度"],
    ["≈212 m/s", "候选最低表观速度"],
  ];
  stats.forEach((stat, index) => {
    const x = 0.55 + index * 3.05;
    addText(slide, stat[0], {
      x,
      y: 1.04,
      w: 2.7,
      h: 0.48,
      fontFace: EN,
      fontSize: index === 0 ? 29 : 25,
      bold: true,
      color: C.teal,
      align: "center",
      fit: "shrink",
    });
    addText(slide, stat[1], {
      x,
      y: 1.52,
      w: 2.7,
      h: 0.24,
      fontSize: 11,
      color: C.ink,
      align: "center",
      fit: "shrink",
    });
  });
  addText(slide, "Balanced / 通道 1", {
    x: 0.55,
    y: 1.9,
    w: 4.25,
    h: 0.28,
    fontSize: 13,
    bold: true,
    color: C.deepRed,
  });
  addText(slide, "Balanced / 通道 2", {
    x: 5.18,
    y: 1.9,
    w: 4.25,
    h: 0.28,
    fontSize: 13,
    bold: true,
    color: C.deepRed,
  });
  addVelocityChart(slide, v1, 0.5, 2.18, 4.42, 2.55, "通道 1");
  addVelocityChart(slide, v2, 5.08, 2.18, 4.42, 2.55, "通道 2");
  addText(slide, "相对事件时间 (μs)｜无符号表观速度 (m/s)", {
    x: 0.85,
    y: 4.66,
    w: 3.7,
    h: 0.18,
    fontSize: 8.5,
    color: C.muted,
    align: "center",
  });
  addText(slide, "相对事件时间 (μs)｜无符号表观速度 (m/s)", {
    x: 5.43,
    y: 4.66,
    w: 3.7,
    h: 0.18,
    fontSize: 8.5,
    color: C.muted,
    align: "center",
  });
  addCard(
    slide,
    0.55,
    4.92,
    8.9,
    0.36,
    "",
    "一致性是重复性线索，不是物理准确度证明；不得自动选择、平均或融合通道。",
    {
      fill: C.redSoft,
      line: C.redSoft,
      noShadow: true,
      titleSize: 1,
      bodySize: 11,
      bodyColor: C.red,
    },
  );
  finishSlide(slide, 12);
}

// Slide 13
{
  const slide = pptx.addSlide();
  addBase(slide, "软件能运行，不等于结果已达到科研使用标准", 13);
  addCard(slide, 0.6, 1.08, 3.65, 0.9, "基础闭环已建立", "可运行｜工程质量门已通过", {
    fill: C.tealSoft,
    line: C.teal,
    titleColor: C.teal,
    titleSize: 22,
    bodySize: 13,
    noShadow: true,
  });
  addText(slide, "≠", {
    x: 4.48,
    y: 1.1,
    w: 1.0,
    h: 0.75,
    fontFace: EN,
    fontSize: 44,
    bold: true,
    color: C.red,
    align: "center",
  });
  addCard(slide, 5.72, 1.08, 3.65, 0.9, "科研级可信仍未完成", "需实验依据｜需质量判断｜需交付验证", {
    fill: C.redSoft,
    line: C.red,
    titleColor: C.red,
    titleSize: 22,
    bodySize: 13,
    noShadow: true,
  });
  const issues = [
    ["1", "脊线连续性", "逐帧最大峰仍无最大跳频、动态规划或连续性约束"],
    ["2", "质量阈值", "描述性质量量无正式阈值，不能自动拒绝假峰"],
    ["3", "物理参数", "1550 nm 未确认；LiF、折射率与 corrected velocity 未实现"],
    ["4", "preview 语义", "全时段 preview 未经过正式质量门，不是正式低速测量"],
    ["5", "交付能力", "GUI、完整 CLI、集成测试、打包和跨机器部署未完成"],
  ];
  const positions = [
    [0.55, 2.32, 2.76],
    [3.62, 2.32, 2.76],
    [6.69, 2.32, 2.76],
    [2.03, 3.85, 2.76],
    [5.21, 3.85, 2.76],
  ];
  issues.forEach((item, index) => {
    const [x, y, w] = positions[index];
    addBadge(slide, x + 0.14, y + 0.16, item[0], index % 2 ? C.teal : C.red, 0.34);
    addCard(slide, x, y, w, 1.18, item[1], item[2], {
      fill: index % 2 ? C.tealSoft : C.white,
      line: index % 2 ? "B8DADD" : C.border,
      noShadow: true,
      titleSize: 15,
      bodySize: 10.3,
    });
  });
  finishSlide(slide, 13);
}

// Slide 14
{
  const slide = pptx.addSlide();
  addBase(slide, "下一阶段优先建立可信判据，再推进修正模型和 GUI", 14);
  addText(slide, "下一阶段计划｜按依赖推进", {
    x: 3.5,
    y: 0.96,
    w: 3.0,
    h: 0.35,
    fontSize: 17,
    bold: true,
    color: C.red,
    align: "center",
  });
  const roadmap = [
    ["01", "谱线连续性", "非 AI 连续跟踪\n搜索范围 · 物理先验", 0.65, 3.65],
    ["02", "可验证判据", "起跳点 · 平台区 · 弱信号\n自动测试 / 验收", 2.35, 3.0],
    ["03", "通道质量择优", "先输出证据，再标定阈值\n对照测试 / 验收", 4.15, 2.45],
    ["04", "修正模型", "核验波长与 LiF\n验证后接入 corrected velocity", 6.0, 1.9],
    ["05", "交付链", "CLI → GUI → 打包部署\n真实用户验收", 7.85, 1.38],
  ];
  roadmap.forEach((item, index) => {
    const [number, title, body, x, y] = item;
    addBadge(slide, x, y - 0.12, number, C.red, 0.45);
    addCard(slide, x + 0.34, y, 1.4, 1.18, title, body, {
      fill: index % 2 ? C.warm : C.white,
      line: C.red,
      noShadow: true,
      titleSize: 11.5,
      bodySize: 8.2,
    });
    if (index < roadmap.length - 1) {
      addArrow(slide, x + 1.65, y + 0.25, 0.5, -0.34, C.red, 1.8);
    }
  });
  addShape(slide, S.roundRect, {
    x: 0.65,
    y: 1.22,
    w: 2.55,
    h: 0.72,
    rectRadius: 0.06,
    fill: { color: C.tealSoft },
    line: { color: C.teal, width: 1 },
  });
  addText(slide, "AI 辅助识别（后期）", {
    x: 0.82,
    y: 1.34,
    w: 1.08,
    h: 0.38,
    fontSize: 12.5,
    bold: true,
    color: C.teal,
    fit: "shrink",
  });
  addText(slide, "仅辅助候选识别，\n不直接生成最终速度", {
    x: 1.95,
    y: 1.32,
    w: 1.05,
    h: 0.42,
    fontSize: 9.5,
    color: C.ink,
    breakLine: true,
    fit: "shrink",
  });
  addCard(
    slide,
    0.6,
    4.96,
    8.8,
    0.36,
    "",
    "验收原则：每个功能都必须有自动测试和明确验收标准｜以上均为计划，非已完成。",
    {
      fill: C.warm,
      line: C.border,
      noShadow: true,
      titleSize: 1,
      bodySize: 10.5,
      bodyColor: C.deepRed,
    },
  );
  finishSlide(slide, 14);
}

// Slide 15
{
  const slide = pptx.addSlide();
  slide.background = { color: C.warm2 };
  addText(slide, "从“跑通”到“可信”：DPS Studio 的下一阶段", {
    x: 0.65,
    y: 0.45,
    w: 8.7,
    h: 0.48,
    fontSize: 22.5,
    bold: true,
    color: C.deepRed,
    align: "center",
    fit: "shrink",
  });
  addShape(slide, S.roundRect, {
    x: 0.55,
    y: 1.35,
    w: 8.9,
    h: 3.25,
    rectRadius: 0.12,
    fill: { color: C.deepRed },
    line: { color: C.deepRed, transparency: 100 },
  });
  ["可信", "可复现", "可交付"].forEach((word, index) => {
    addText(slide, word, {
      x: 1.0 + index * 3.0,
      y: 1.72,
      w: 2.0,
      h: 0.68,
      fontSize: 37,
      bold: true,
      color: C.white,
      align: "center",
    });
    if (index < 2) {
      addShape(slide, S.line, {
        x: 3.26 + index * 3.0,
        y: 1.78,
        w: 0,
        h: 0.56,
        line: { color: "EBC8BE", width: 1.2 },
      });
    }
  });
  const rows = [
    ["已有", "双通道、双 Profile、正式 core workflow、真实 production 输出"],
    ["仍需", "可信谱线、通道决策、波长与 LiF 模型验证"],
    ["后续", "数值链稳定后推进 CLI / GUI、打包和用户验收"],
  ];
  rows.forEach((row, index) => {
    const y = 2.72 + index * 0.62;
    addShape(slide, S.roundRect, {
      x: 1.0,
      y,
      w: 0.92,
      h: 0.42,
      rectRadius: 0.04,
      fill: { color: C.white },
      line: { color: C.white, transparency: 100 },
    });
    addText(slide, `${row[0]}：`, {
      x: 1.04,
      y: y + 0.03,
      w: 0.84,
      h: 0.32,
      fontSize: 16,
      bold: true,
      color: C.deepRed,
      align: "center",
    });
    addText(slide, row[1], {
      x: 2.18,
      y: y + 0.04,
      w: 6.3,
      h: 0.32,
      fontSize: 14,
      color: C.white,
      fit: "shrink",
    });
  });
  addText(slide, "请老师批评指正", {
    x: 3.3,
    y: 4.88,
    w: 3.4,
    h: 0.45,
    fontSize: 25,
    bold: true,
    color: C.deepRed,
    align: "center",
  });
  finishSlide(slide, 15);
}

fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
pptx
  .writeFile({ fileName: OUTPUT })
  .then(() => {
    process.stdout.write(`Wrote editable deck: ${OUTPUT}\n`);
  })
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
