"use strict";

const fs = require("fs");
const path = require("path");
const PptxGenJS = require("pptxgenjs");
const { imageSize } = require("image-size");

const ROOT = __dirname;
const OUTPUT =
  process.argv[2] || path.join(ROOT, "DPS_Studio_组会汇报_redesign.pptx");
const ASSET = (...parts) => path.join(ROOT, "assets", ...parts);

const pptx = new PptxGenJS();
pptx.defineLayout({ name: "DPS_WIDE", width: 13.333, height: 7.5 });
pptx.layout = "DPS_WIDE";
pptx.author = "DPS Studio project";
pptx.company = "DPS Studio";
pptx.subject = "DPS Studio 课题组组会汇报重制版";
pptx.title = "DPS Studio：从 PDV 原始信号到可追溯表观速度曲线";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};

const CN = "Microsoft YaHei";
const EN = "Times New Roman";
const CODE = "Consolas";
const S = pptx.ShapeType;

const C = {
  bg: "FBF8F3",
  paper: "FFFFFF",
  ink: "252525",
  muted: "6A6967",
  pale: "F0E8E1",
  line: "D9D2CA",
  red: "9E2A1B",
  red2: "B4432E",
  redSoft: "F0DDD8",
  redPale: "F7ECE8",
  teal: "167C80",
  tealSoft: "E4EFEE",
  gold: "C78926",
  gray: "A6A39E",
  graySoft: "EEECE9",
  dark: "151A1E",
  white: "FFFFFF",
};

function isChineseCharacter(char) {
  return /[\u3400-\u9FFF\uF900-\uFAFF\u3000-\u303F\uFF00-\uFFEF]/u.test(char);
}

function richRuns(text, options = {}) {
  const cnFace = options.cnFace || CN;
  const enFace = options.enFace || EN;
  const runs = [];
  let current = "";
  let currentFace = null;
  for (const char of String(text)) {
    const face = isChineseCharacter(char) ? cnFace : enFace;
    if (currentFace !== null && face !== currentFace) {
      runs.push({ text: current, options: { fontFace: currentFace } });
      current = "";
    }
    currentFace = face;
    current += char;
  }
  if (current) {
    runs.push({ text: current, options: { fontFace: currentFace || cnFace } });
  }
  return runs;
}

function addRichText(slide, text, opts = {}) {
  slide.addText(richRuns(text), {
    fontFace: CN,
    fontSize: 20,
    color: C.ink,
    margin: 0,
    valign: "mid",
    breakLine: false,
    ...opts,
  });
}

function addPlainText(slide, text, opts = {}) {
  slide.addText(text, {
    fontFace: CN,
    fontSize: 20,
    color: C.ink,
    margin: 0,
    valign: "mid",
    ...opts,
  });
}

function addShape(slide, type, opts) {
  slide.addShape(type, opts);
}

function addLine(slide, x, y, w, h = 0, color = C.line, width = 0.8, dash = "solid") {
  const x2 = x + w;
  const y2 = y + h;
  addShape(slide, S.line, {
    x: Math.min(x, x2),
    y: Math.min(y, y2),
    w: Math.max(0.001, Math.abs(w)),
    h: Math.max(0.001, Math.abs(h)),
    flipH: w < 0,
    flipV: h < 0,
    line: { color, width, dashType: dash },
  });
}

function addBase(slide, section, title) {
  slide.background = { color: C.bg };
  addShape(slide, S.rect, {
    x: 12.92,
    y: 0,
    w: 0.413,
    h: 7.5,
    fill: { color: C.pale, transparency: 22 },
    line: { color: C.pale, transparency: 100 },
  });
  addShape(slide, S.rect, {
    x: 12.72,
    y: 0,
    w: 0.04,
    h: 7.5,
    fill: { color: C.red, transparency: 18 },
    line: { color: C.red, transparency: 100 },
  });
  addRichText(slide, section, {
    x: 0.72,
    y: 0.26,
    w: 2.4,
    h: 0.25,
    fontSize: 14,
    bold: true,
    color: C.red,
    charSpacing: 1.2,
  });
  const size = title.length > 29 ? 28 : title.length > 23 ? 30 : 32;
  addRichText(slide, title, {
    x: 0.72,
    y: 0.62,
    w: 11.65,
    h: 0.56,
    fontSize: size,
    bold: true,
    color: C.ink,
    fit: "shrink",
  });
}

function addFooter(slide, text) {
  addRichText(slide, text, {
    x: 0.72,
    y: 6.98,
    w: 11.65,
    h: 0.24,
    fontSize: 14,
    color: C.muted,
    fit: "shrink",
  });
}

function addSectionStatement(slide, text, x, y, w, h, color = C.ink, size = 26) {
  addRichText(slide, text, {
    x,
    y,
    w,
    h,
    fontSize: size,
    bold: true,
    color,
    valign: "top",
    breakLine: true,
  });
}

function imageContain(slide, imagePath, x, y, w, h, altText) {
  const dimensions = imageSize(fs.readFileSync(imagePath));
  if (!dimensions.width || !dimensions.height) {
    throw new Error(`Could not read image dimensions: ${imagePath}`);
  }
  const scale = Math.min(w / dimensions.width, h / dimensions.height);
  const imageW = dimensions.width * scale;
  const imageH = dimensions.height * scale;
  slide.addImage({
    path: imagePath,
    x: x + (w - imageW) / 2,
    y: y + (h - imageH) / 2,
    w: imageW,
    h: imageH,
    altText,
  });
  return {
    x: x + (w - imageW) / 2,
    y: y + (h - imageH) / 2,
    w: imageW,
    h: imageH,
  };
}

function addImageFigure(slide, imagePath, x, y, w, h, caption, altText) {
  addShape(slide, S.rect, {
    x,
    y,
    w,
    h,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.7 },
  });
  const figureHeight = caption ? h - 0.38 : h;
  imageContain(slide, imagePath, x + 0.05, y + 0.05, w - 0.1, figureHeight - 0.08, altText);
  if (caption) {
    addRichText(slide, caption, {
      x: x + 0.12,
      y: y + h - 0.31,
      w: w - 0.24,
      h: 0.2,
      fontSize: 14,
      color: C.muted,
      align: "center",
      fit: "shrink",
    });
  }
}

function addStatusKey(slide, x, y) {
  const items = [
    ["已实现", C.red],
    ["初步实现", C.teal],
    ["未完成 / 待核验", C.gray],
  ];
  let cursor = x;
  for (const [label, color] of items) {
    addShape(slide, S.ellipse, {
      x: cursor,
      y: y + 0.06,
      w: 0.12,
      h: 0.12,
      fill: { color },
      line: { color, transparency: 100 },
    });
    addRichText(slide, label, {
      x: cursor + 0.18,
      y,
      w: label.length > 5 ? 1.65 : 1.05,
      h: 0.24,
      fontSize: 14,
      color: C.muted,
    });
    cursor += label.length > 5 ? 2.0 : 1.45;
  }
}

function readNotes() {
  const text = fs.readFileSync(path.join(ROOT, "speech.md"), "utf8");
  const notes = {};
  const regex = /## Slide (\d+):[^\n]*\n([\s\S]*?)(?=\n## Slide \d+:|$)/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    notes[Number(match[1])] = match[2].trim();
  }
  return notes;
}

const notes = readNotes();

function finishSlide(slide, number) {
  if (notes[number]) {
    slide.addNotes(notes[number]);
  }
}

// Slide 1 — cover
{
  const slide = pptx.addSlide();
  slide.background = { color: C.bg };
  addShape(slide, S.rect, {
    x: 10.62,
    y: 0,
    w: 2.713,
    h: 7.5,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addShape(slide, S.rect, {
    x: 10.22,
    y: 0,
    w: 0.16,
    h: 7.5,
    fill: { color: C.redSoft },
    line: { color: C.redSoft, transparency: 100 },
  });
  addRichText(slide, "DPS Studio", {
    x: 0.92,
    y: 0.84,
    w: 4.2,
    h: 0.45,
    fontSize: 22,
    bold: true,
    color: C.red,
    charSpacing: 1.1,
  });
  addRichText(slide, "从 PDV 原始信号到\n可追溯表观速度曲线", {
    x: 0.92,
    y: 1.47,
    w: 8.8,
    h: 1.62,
    fontSize: 42,
    bold: true,
    color: C.ink,
    breakLine: true,
    valign: "top",
  });
  addRichText(slide, "课题组组会汇报", {
    x: 0.96,
    y: 3.58,
    w: 3.5,
    h: 0.38,
    fontSize: 22,
    color: C.muted,
  });
  addRichText(slide, "2026 年 7 月 26 日", {
    x: 0.96,
    y: 4.42,
    w: 3.7,
    h: 0.35,
    fontSize: 20,
    color: C.ink,
  });
  addRichText(slide, "V(t)", {
    x: 0.96,
    y: 6.22,
    w: 1.15,
    h: 0.4,
    fontSize: 28,
    italic: true,
    color: C.red,
  });
  addRichText(slide, "/", {
    x: 2.22,
    y: 6.22,
    w: 0.35,
    h: 0.4,
    fontSize: 28,
    color: C.gray,
    align: "center",
  });
  addRichText(slide, "S(t, f)", {
    x: 2.67,
    y: 6.22,
    w: 1.5,
    h: 0.4,
    fontSize: 28,
    italic: true,
    color: C.teal,
  });
  addRichText(slide, "/", {
    x: 4.31,
    y: 6.22,
    w: 0.35,
    h: 0.4,
    fontSize: 28,
    color: C.gray,
    align: "center",
  });
  addRichText(slide, "v_app(t)", {
    x: 4.77,
    y: 6.22,
    w: 1.85,
    h: 0.4,
    fontSize: 28,
    italic: true,
    color: C.gold,
  });
  addRichText(slide, "可追溯 ≠ 已完成物理修正", {
    x: 10.84,
    y: 5.42,
    w: 2.08,
    h: 0.82,
    fontSize: 20,
    bold: true,
    color: C.white,
    valign: "top",
    breakLine: true,
  });
  finishSlide(slide, 1);
}

// Slide 2 — legacy problem
{
  const slide = pptx.addSlide();
  addBase(slide, "问题", "旧流程缺少参数、处理步骤与结果之间的可追溯映射");
  addSectionStatement(
    slide,
    "看到曲线后，\n仍难回答它如何产生。",
    0.78,
    1.72,
    4.55,
    1.25,
    C.red,
    29
  );
  addRichText(
    slide,
    "参数、人工选择、异常峰和源文件之间没有完整记录，结果接近也不代表过程相同。",
    {
      x: 0.8,
      y: 3.25,
      w: 4.55,
      h: 1.15,
      fontSize: 20,
      color: C.ink,
      breakLine: true,
      valign: "top",
    }
  );
  addRichText(slide, "因此要重建处理证据，不只是更换界面。", {
    x: 0.8,
    y: 5.25,
    w: 4.8,
    h: 0.8,
    fontSize: 22,
    bold: true,
    color: C.ink,
    breakLine: true,
  });
  const rows = [
    ["01", "看不到", "结果不能对应到完整参数和时间区间"],
    ["02", "说不清", "人工选峰与修改步骤难以复现"],
    ["03", "辨不出", "弱信号和假峰缺少可核验依据"],
    ["04", "回不去", "原始数据与处理结果边界不清"],
  ];
  rows.forEach((row, index) => {
    const y = 1.55 + index * 1.2;
    addRichText(slide, row[0], {
      x: 6.25,
      y,
      w: 0.65,
      h: 0.35,
      fontSize: 22,
      bold: true,
      color: C.red,
    });
    addRichText(slide, row[1], {
      x: 7.05,
      y,
      w: 1.35,
      h: 0.35,
      fontSize: 22,
      bold: true,
      color: C.ink,
    });
    addRichText(slide, row[2], {
      x: 8.42,
      y,
      w: 3.75,
      h: 0.58,
      fontSize: 20,
      color: C.muted,
      breakLine: true,
      valign: "top",
    });
    addLine(slide, 6.25, y + 0.76, 5.9, 0, C.line, 0.7);
  });
  finishSlide(slide, 2);
}

// Slide 3 — rebuild goals
{
  const slide = pptx.addSlide();
  addBase(slide, "目标", "当前优先级：数值链验证先于 GUI 完善");
  const layers = [
    {
      n: "01",
      title: "数据安全",
      body: "只读输入｜不覆盖原文件｜SI 单位｜异常明示",
      fill: C.redSoft,
      color: C.red,
    },
    {
      n: "02",
      title: "算法复刻",
      body: "文件读取｜STFT｜脊线｜拍频换算｜复现与导出",
      fill: C.redPale,
      color: C.red2,
    },
    {
      n: "03",
      title: "可信判断",
      body: "弱信号｜假峰｜起跳点｜双通道｜修正边界",
      fill: C.tealSoft,
      color: C.teal,
    },
  ];
  layers.forEach((layer, index) => {
    const y = 1.46 + index * 1.58;
    addShape(slide, S.rect, {
      x: 0.82 + index * 0.24,
      y,
      w: 11.18 - index * 0.24,
      h: 1.18,
      fill: { color: layer.fill },
      line: { color: layer.fill, transparency: 100 },
    });
    addRichText(slide, layer.n, {
      x: 1.05 + index * 0.24,
      y: y + 0.24,
      w: 0.7,
      h: 0.5,
      fontSize: 28,
      bold: true,
      color: layer.color,
    });
    addRichText(slide, layer.title, {
      x: 1.9 + index * 0.24,
      y: y + 0.2,
      w: 1.9,
      h: 0.5,
      fontSize: 26,
      bold: true,
      color: C.ink,
    });
    addRichText(slide, layer.body, {
      x: 3.72 + index * 0.24,
      y: y + 0.2,
      w: 7.83 - index * 0.24,
      h: 0.58,
      fontSize: 20,
      color: C.ink,
      fit: "shrink",
    });
  });
  addShape(slide, S.rect, {
    x: 8.85,
    y: 6.12,
    w: 3.15,
    h: 0.56,
    fill: { color: C.graySoft },
    line: { color: C.graySoft, transparency: 100 },
  });
  addRichText(slide, "GUI 排在可信判断之后", {
    x: 9.05,
    y: 6.22,
    w: 2.75,
    h: 0.3,
    fontSize: 20,
    bold: true,
    color: C.muted,
    align: "center",
  });
  addFooter(slide, "当前优先级：先把计算说清楚，再把操作做方便。");
  finishSlide(slide, 3);
}

// Slide 4 — Python rationale
{
  const slide = pptx.addSlide();
  addBase(slide, "工具选择", "Python 的价值在于让计算、配置和检查留在同一份记录里");
  const rows = [
    ["数值计算", "NumPy · SciPy · pandas", "读取、数组、STFT 和数据表"],
    ["可复现图", "Matplotlib", "同一输入和配置重复生成图"],
    ["交互界面", "PySide6 · PyQtGraph", "依赖已列入；GUI 尚未完成"],
    ["检查", "pytest · Ruff · mypy", "行为、代码和类型检查"],
  ];
  rows.forEach((row, index) => {
    const y = 1.55 + index * 1.2;
    addRichText(slide, row[0], {
      x: 0.82,
      y,
      w: 2.25,
      h: 0.38,
      fontSize: 22,
      bold: true,
      color: index === 2 ? C.gray : C.red,
    });
    addRichText(slide, row[1], {
      x: 3.1,
      y,
      w: 3.4,
      h: 0.38,
      fontSize: 22,
      bold: true,
      color: index === 2 ? C.gray : C.ink,
    });
    addRichText(slide, row[2], {
      x: 3.1,
      y: y + 0.47,
      w: 3.6,
      h: 0.35,
      fontSize: 20,
      color: C.muted,
    });
    addLine(slide, 0.82, y + 0.95, 5.9, 0, C.line, 0.7);
  });
  addShape(slide, S.rect, {
    x: 7.38,
    y: 1.47,
    w: 5.08,
    h: 4.95,
    fill: { color: "F1EDE8" },
    line: { color: "F1EDE8", transparency: 100 },
  });
  addPlainText(
    slide,
    '[project]\nname = "dps-studio"\n\n' +
      'dependencies = [\n  "numpy", "scipy", "pandas",\n  "matplotlib",\n  "PySide6", "pyqtgraph",\n  "pydantic"\n]\n\n' +
      '[project.optional-dependencies]\n' +
      'dev = ["pytest", "ruff",\n       "mypy", "pyinstaller"]',
    {
      x: 7.78,
      y: 1.83,
      w: 4.28,
      h: 4.05,
      fontFace: CODE,
      fontSize: 16,
      color: C.dark,
      breakLine: true,
      valign: "top",
    }
  );
  addPlainText(slide, "pyproject.toml · lines 8–27", {
    x: 7.8,
    y: 5.98,
    w: 4.2,
    h: 0.25,
    fontFace: CODE,
    fontSize: 14,
    color: C.muted,
  });
  addFooter(slide, "依赖被记录下来，结果才有机会对应到具体运行环境。");
  finishSlide(slide, 4);
}

// Slide 5 — current processing chain
{
  const slide = pptx.addSlide();
  addBase(slide, "数值链", "当前处理链已经到表观速度，物理修正仍在链路之外");
  addStatusKey(slide, 8.0, 1.25);
  const nodes = [
    ["01", "时间—电压", C.red],
    ["02", "文件读取", C.red],
    ["03", "SignalRecord", C.red],
    ["04", "STFT", C.red],
    ["05", "候选脊线", C.red],
    ["06", "亚频点精修", C.red],
    ["07", "表观速度", C.red],
    ["08", "描述性质量", C.teal],
    ["09", "CSV / 图 / manifest", C.red],
  ];
  const positions = [
    [1.0, 2.25],
    [3.55, 2.25],
    [6.1, 2.25],
    [8.65, 2.25],
    [11.2, 2.25],
    [11.2, 4.55],
    [8.15, 4.55],
    [5.1, 4.55],
    [2.05, 4.55],
  ];
  for (let i = 0; i < positions.length - 1; i += 1) {
    const [x1, y1] = positions[i];
    const [x2, y2] = positions[i + 1];
    if (x1 === x2) {
      addLine(slide, x1, y1 + 0.18, 0, y2 - y1 - 0.18, C.line, 1.2);
    } else {
      addLine(slide, x1, y1 + 0.18, x2 - x1, 0, C.line, 1.2);
    }
  }
  nodes.forEach((node, index) => {
    const [x, y] = positions[index];
    addShape(slide, S.ellipse, {
      x: x - 0.13,
      y: y + 0.05,
      w: 0.26,
      h: 0.26,
      fill: { color: node[2] },
      line: { color: node[2], transparency: 100 },
    });
    addRichText(slide, node[0], {
      x: x - 0.22,
      y: y - 0.42,
      w: 0.44,
      h: 0.28,
      fontSize: 14,
      bold: true,
      color: node[2],
      align: "center",
    });
    addRichText(slide, node[1], {
      x: x - 0.92,
      y: y + 0.48,
      w: 1.84,
      h: 0.65,
      fontSize: 20,
      bold: true,
      color: C.ink,
      align: "center",
      breakLine: true,
      valign: "top",
      fit: "shrink",
    });
  });
  addShape(slide, S.rect, {
    x: 0.82,
    y: 6.29,
    w: 11.58,
    h: 0.55,
    fill: { color: C.graySoft },
    line: { color: C.graySoft, transparency: 100 },
  });
  addRichText(slide, "链路之外：LiF 修正｜双通道自动择优 / 融合｜GUI", {
    x: 1.08,
    y: 6.38,
    w: 10.95,
    h: 0.32,
    fontSize: 20,
    color: C.muted,
    align: "center",
  });
  addFooter(slide, "当前结果是无符号表观速度，不是窗口修正后的真实界面速度。");
  finishSlide(slide, 5);
}

// Slide 6 — strict input
{
  const slide = pptx.addSlide();
  addBase(slide, "输入", "输入层先保留差异，再决定如何比较");
  addRichText(slide, "01", {
    x: 0.82,
    y: 1.6,
    w: 0.48,
    h: 0.34,
    fontSize: 22,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "只读与 SI", {
    x: 1.35,
    y: 1.58,
    w: 1.7,
    h: 0.38,
    fontSize: 22,
    bold: true,
    color: C.ink,
  });
  addRichText(slide, "时间为秒，电压为伏特；数组只读。", {
    x: 1.35,
    y: 2.03,
    w: 2.35,
    h: 0.72,
    fontSize: 20,
    color: C.muted,
    breakLine: true,
    valign: "top",
  });
  addLine(slide, 0.82, 2.88, 2.9, 0, C.line, 0.7);
  addRichText(slide, "02", {
    x: 0.82,
    y: 3.12,
    w: 0.48,
    h: 0.34,
    fontSize: 22,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "不静默处理", {
    x: 1.35,
    y: 3.1,
    w: 1.9,
    h: 0.38,
    fontSize: 22,
    bold: true,
    color: C.ink,
  });
  addRichText(slide, "非均匀采样会报错，不静默重采样。", {
    x: 1.35,
    y: 3.55,
    w: 2.35,
    h: 0.72,
    fontSize: 20,
    color: C.muted,
    breakLine: true,
    valign: "top",
  });
  addLine(slide, 0.82, 4.4, 2.9, 0, C.line, 0.7);
  addRichText(slide, "2.48×", {
    x: 0.82,
    y: 4.73,
    w: 1.45,
    h: 0.62,
    fontSize: 36,
    bold: true,
    color: C.teal,
  });
  addRichText(slide, "峰峰值比（显示窗）", {
    x: 0.84,
    y: 5.32,
    w: 2.75,
    h: 0.42,
    fontSize: 20,
    color: C.ink,
    breakLine: true,
    valign: "top",
  });
  addRichText(slide, "量程不同：不在电压层平均。", {
    x: 0.84,
    y: 6.02,
    w: 2.75,
    h: 0.58,
    fontSize: 20,
    bold: true,
    color: C.red,
  });
  addImageFigure(
    slide,
    ASSET("real", "raw_voltage_dual_channel.png"),
    3.95,
    1.48,
    8.35,
    5.38,
    "data/raw/20260607.csv · 事件附近显示窗 · 无平滑、插值或重采样",
    "同一原始文件的两个 PDV 电压通道"
  );
  finishSlide(slide, 6);
}

// Slide 7 — STFT
{
  const slide = pptx.addSlide();
  addBase(slide, "STFT", "单次 FFT 无法定位拍频在何时改变");
  addRichText(
    slide,
    "STFT 将局部频谱沿时间展开；白线只是候选脊线，不是物理真值。",
    {
      x: 0.76,
      y: 1.22,
      w: 11.8,
      h: 0.48,
      fontSize: 20,
      color: C.ink,
    }
  );
  addImageFigure(
    slide,
    ASSET("real", "stft_balanced_channel1.png"),
    1.55,
    1.78,
    10.25,
    5.08,
    "Balanced / pdv_channel_1 · 真实 production 输出",
    "Balanced profile channel 1 STFT with refined candidate ridge"
  );
  finishSlide(slide, 7);
}

// Slide 8 — parameters
{
  const slide = pptx.addSlide();
  addBase(slide, "参数", "参数共同决定时间、频率分辨率与搜索范围");
  const x0 = 0.72;
  const y0 = 1.5;
  const col = [2.55, 1.85, 1.9];
  const tableW = col.reduce((a, b) => a + b, 0);
  addShape(slide, S.rect, {
    x: x0,
    y: y0,
    w: tableW,
    h: 0.58,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  ["参数", "Balanced", "High time"].forEach((label, index) => {
    const x = x0 + col.slice(0, index).reduce((a, b) => a + b, 0);
    addRichText(slide, label, {
      x: x + 0.13,
      y: y0 + 0.1,
      w: col[index] - 0.26,
      h: 0.34,
      fontSize: 20,
      bold: true,
      color: C.white,
      align: index === 0 ? "left" : "center",
    });
  });
  const tableRows = [
    ["window", "Hann", "Hann"],
    ["window length", "768", "512"],
    ["overlap", "640", "384"],
    ["hop", "128", "128"],
    ["nfft", "4096", "4096"],
    ["ridge search", "0.05–2.0 GHz", "0.05–2.0 GHz"],
  ];
  tableRows.forEach((row, rowIndex) => {
    const y = y0 + 0.58 + rowIndex * 0.5;
    addShape(slide, S.rect, {
      x: x0,
      y,
      w: tableW,
      h: 0.5,
      fill: { color: rowIndex % 2 === 0 ? C.paper : "F5F1ED" },
      line: { color: C.line, width: 0.5 },
    });
    row.forEach((value, index) => {
      const x = x0 + col.slice(0, index).reduce((a, b) => a + b, 0);
      addRichText(slide, value, {
        x: x + 0.13,
        y: y + 0.08,
        w: col[index] - 0.26,
        h: 0.32,
        fontSize: 20,
        color: index === 0 ? C.ink : C.muted,
        bold: index === 0,
        align: index === 0 ? "left" : "center",
      });
    });
  });
  addRichText(slide, "40 GHz：窗长 19.2 / 12.8 ns；hop ≈ 3.2 ns。", {
    x: x0,
    y: 5.18,
    w: tableW,
    h: 0.45,
    fontSize: 20,
    bold: true,
    color: C.teal,
    fit: "shrink",
  });
  addImageFigure(
    slide,
    ASSET("code", "analysis_profiles_balanced_excerpt.png"),
    7.35,
    1.48,
    5.2,
    3.18,
    "src/dps_studio/core/analysis_profiles.py:136–145",
    "Balanced analysis profile source code excerpt"
  );
  const reasons = [
    ["窗长", "越长，频率估计更稳；时间定位更宽。"],
    ["hop", "越小，时间网格更密；计算量更大。"],
    ["nfft", "加密频率网格，不等于提高分辨率"],
    ["搜索带", "排除明显假峰，不任意排除真实信号"],
  ];
  reasons.forEach((reason, index) => {
    const x = 0.78 + (index % 2) * 6.08;
    const y = 5.83 + Math.floor(index / 2) * 0.64;
    addRichText(slide, reason[0], {
      x,
      y,
      w: 0.85,
      h: 0.35,
      fontSize: 20,
      bold: true,
      color: index < 2 ? C.red : C.teal,
    });
    addRichText(slide, reason[1], {
      x: x + 0.95,
      y,
      w: 4.95,
      h: 0.45,
      fontSize: 20,
      color: C.ink,
      fit: "shrink",
    });
  });
  finishSlide(slide, 8);
}

// Slide 9 — ridge to apparent velocity
{
  const slide = pptx.addSlide();
  addBase(slide, "物理换算", "脊线先给出拍频，波长明确后才能换算表观速度");
  addRichText(slide, "vₐₚₚ = λ₀ fᵦ / 2", {
    x: 0.9,
    y: 1.75,
    w: 5.2,
    h: 1.0,
    fontSize: 44,
    italic: true,
    bold: true,
    color: C.red,
    align: "center",
  });
  addRichText(slide, "normal-incidence reflection PDV", {
    x: 1.18,
    y: 2.9,
    w: 4.65,
    h: 0.38,
    fontSize: 20,
    color: C.muted,
    align: "center",
  });
  addLine(slide, 6.45, 1.55, 0, 4.65, C.line, 1.0);
  const boundaries = [
    ["拍频不是速度", "脊线纵坐标先是 f_b；只有显式波长后才换算。", C.red],
    ["当前是无符号表观速度", "一侧频谱不提供方向；当前输出不带符号。", C.teal],
    ["修正仍未实现", "没有 LiF、折射率或入射角修正。", C.gray],
  ];
  boundaries.forEach((item, index) => {
    const y = 1.62 + index * 1.45;
    addShape(slide, S.ellipse, {
      x: 7.02,
      y: y + 0.08,
      w: 0.16,
      h: 0.16,
      fill: { color: item[2] },
      line: { color: item[2], transparency: 100 },
    });
    addRichText(slide, item[0], {
      x: 7.38,
      y,
      w: 3.7,
      h: 0.38,
      fontSize: 22,
      bold: true,
      color: C.ink,
    });
    addRichText(slide, item[1], {
      x: 7.38,
      y: y + 0.48,
      w: 4.35,
      h: 0.62,
      fontSize: 20,
      color: C.muted,
      breakLine: true,
      valign: "top",
    });
  });
  addShape(slide, S.rect, {
    x: 0.9,
    y: 4.14,
    w: 5.2,
    h: 1.42,
    fill: { color: C.redPale },
    line: { color: C.redPale, transparency: 100 },
  });
  addRichText(slide, "λ₀ = 1.55 μm", {
    x: 1.22,
    y: 4.36,
    w: 2.0,
    h: 0.45,
    fontSize: 27,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "配置中的演示值，尚未与实验记录核验。", {
    x: 1.22,
    y: 4.93,
    w: 4.4,
    h: 0.38,
    fontSize: 20,
    color: C.ink,
  });
  addFooter(slide, "apparent velocity 与 corrected velocity 必须分开记录和表述。");
  finishSlide(slide, 9);
}

// Slide 10 — real run
{
  const slide = pptx.addSlide();
  addBase(slide, "真实结果", "同一次真实运行把时频脊线对应到表观速度曲线");
  addImageFigure(
    slide,
    ASSET("real", "stft_balanced_channel1.png"),
    0.7,
    1.45,
    6.03,
    4.55,
    "左：Balanced / channel 1 · STFT 与 refined candidate ridge",
    "STFT and refined candidate ridge from the latest production run"
  );
  addImageFigure(
    slide,
    ASSET("real", "velocity_balanced_channel1_event.png"),
    6.95,
    1.45,
    5.65,
    4.55,
    "右：同一 run / profile / channel · 事件区表观速度",
    "Apparent velocity event detail from the same latest production run"
  );
  addRichText(
    slide,
    "左：候选谱线位置；右：同一候选频率换算为表观速度。结果可复现，但弱信号区仍需核验。",
    {
      x: 0.82,
      y: 6.12,
      w: 11.55,
      h: 0.5,
      fontSize: 20,
      color: C.ink,
      breakLine: true,
      valign: "top",
    }
  );
  addFooter(slide, "run_20260724_004901_103968 · display-only bridge 不写入中间测量点。");
  finishSlide(slide, 10);
}

// Slide 11 — two channels
{
  const slide = pptx.addSlide();
  addBase(slide, "双通道", "双通道一致性不能替代通道可信度判定");
  addImageFigure(
    slide,
    ASSET("real", "two_channel_latest_candidates.png"),
    0.7,
    1.5,
    8.35,
    5.42,
    "最新 Balanced run · formal candidate · 无平滑、插值、平均或融合",
    "Latest two-channel formal candidate apparent velocity comparison"
  );
  addRichText(slide, "538 / 532", {
    x: 9.45,
    y: 1.67,
    w: 2.4,
    h: 0.62,
    fontSize: 36,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "m/s · 两通道首个候选", {
    x: 9.47,
    y: 2.32,
    w: 2.65,
    h: 0.35,
    fontSize: 20,
    color: C.muted,
  });
  addLine(slide, 9.45, 2.88, 2.55, 0, C.line, 0.7);
  addRichText(slide, "52.5 / 55.8 dB", {
    x: 9.45,
    y: 3.18,
    w: 2.6,
    h: 0.42,
    fontSize: 25,
    bold: true,
    color: C.teal,
  });
  addRichText(slide, "peak-to-background median", {
    x: 9.45,
    y: 3.7,
    w: 2.7,
    h: 0.35,
    fontSize: 20,
    color: C.muted,
  });
  addRichText(slide, "13.3 / 19.9 dB", {
    x: 9.45,
    y: 4.25,
    w: 2.6,
    h: 0.42,
    fontSize: 25,
    bold: true,
    color: C.teal,
  });
  addRichText(slide, "peak-to-competitor median", {
    x: 9.45,
    y: 4.77,
    w: 2.75,
    h: 0.35,
    fontSize: 20,
    color: C.muted,
  });
  addShape(slide, S.rect, {
    x: 9.34,
    y: 5.36,
    w: 3.0,
    h: 1.55,
    fill: { color: C.redPale },
    line: { color: C.redPale, transparency: 100 },
  });
  addRichText(slide, "这些 dB 量仅是\n描述性证据\n不是 SNR\n也不是自动择优阈值", {
    x: 9.57,
    y: 5.55,
    w: 2.55,
    h: 1.2,
    fontSize: 18,
    bold: true,
    color: C.ink,
    breakLine: true,
    valign: "top",
  });
  finishSlide(slide, 11);
}

// Slide 12 — capability ledger
{
  const slide = pptx.addSlide();
  addBase(slide, "完成度", "目前已经复刻了核心数值链，但完成度不等于可信度");
  addStatusKey(slide, 8.0, 1.22);
  const rows = [
    ["原始数据只读读取", "已实现", "core/models/signal.py"],
    ["SignalRecord 数据模型", "已实现", "SI、只读数组、采样信息"],
    ["STFT 时频计算", "已实现", "core/time_frequency/stft.py"],
    ["脊线提取与亚频点精修", "已实现", "core/ridge/peak.py · refinement.py"],
    ["拍频到无符号表观速度", "已实现", "core/physics/velocity.py"],
    ["双通道独立分析与输出", "已实现", "core/workflow/analysis.py"],
    ["连续性与谱质量证据", "初步实现", "没有正式可信阈值"],
    ["CSV、图片与 manifest", "已实现", "scripts/production_outputs.py"],
    ["LiF 修正、完整 GUI、打包", "未完成", "不得写成当前成果"],
  ];
  const colorFor = (status) =>
    status === "已实现" ? C.red : status === "初步实现" ? C.teal : C.gray;
  addRichText(slide, "能力", {
    x: 0.9,
    y: 1.42,
    w: 3.35,
    h: 0.35,
    fontSize: 20,
    bold: true,
    color: C.muted,
  });
  addRichText(slide, "状态", {
    x: 6.1,
    y: 1.42,
    w: 1.2,
    h: 0.35,
    fontSize: 20,
    bold: true,
    color: C.muted,
  });
  addRichText(slide, "证据 / 边界", {
    x: 8.05,
    y: 1.42,
    w: 3.2,
    h: 0.35,
    fontSize: 20,
    bold: true,
    color: C.muted,
  });
  addLine(slide, 0.85, 1.85, 11.45, 0, C.line, 0.8);
  rows.forEach((row, index) => {
    const y = 1.95 + index * 0.55;
    addRichText(slide, row[0], {
      x: 0.9,
      y,
      w: 4.8,
      h: 0.36,
      fontSize: 20,
      color: C.ink,
      bold: index === 8,
    });
    addShape(slide, S.ellipse, {
      x: 6.12,
      y: y + 0.1,
      w: 0.13,
      h: 0.13,
      fill: { color: colorFor(row[1]) },
      line: { color: colorFor(row[1]), transparency: 100 },
    });
    addRichText(slide, row[1], {
      x: 6.4,
      y,
      w: 1.15,
      h: 0.36,
      fontSize: 20,
      bold: true,
      color: colorFor(row[1]),
    });
    addPlainText(slide, row[2], {
      x: 8.05,
      y,
      w: 4.05,
      h: 0.36,
      fontFace: row[2].includes("/") || row[2].includes(".py") ? CODE : CN,
      fontSize: row[2].includes("/") || row[2].includes(".py") ? 14 : 20,
      color: C.muted,
      fit: "shrink",
    });
    addLine(slide, 0.85, y + 0.47, 11.45, 0, C.line, 0.5);
  });
  addFooter(slide, "能力状态来自当前工作树；未提交内容不等于稳定发布。");
  finishSlide(slide, 12);
}

// Slide 13 — current gaps
{
  const slide = pptx.addSlide();
  addBase(slide, "当前问题", "当前结果能展示流程，还不能宣称是最终科研结果");
  addRichText(slide, "曲线可生成", {
    x: 0.85,
    y: 3.11,
    w: 1.65,
    h: 0.42,
    fontSize: 22,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "曲线可信", {
    x: 10.83,
    y: 3.11,
    w: 1.45,
    h: 0.42,
    fontSize: 22,
    bold: true,
    color: C.gray,
    align: "right",
  });
  addLine(slide, 2.45, 3.36, 8.25, 0, C.line, 1.2, "dash");
  addShape(slide, S.ellipse, {
    x: 2.3,
    y: 3.19,
    w: 0.34,
    h: 0.34,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addShape(slide, S.ellipse, {
    x: 10.57,
    y: 3.19,
    w: 0.34,
    h: 0.34,
    fill: { color: C.bg },
    line: { color: C.gray, width: 1.5, dashType: "dash" },
  });
  const issues = [
    [3.0, 1.6, "弱信号区\n可能追错分支", C.red],
    [5.7, 1.45, "起跳点、平台和零速度区\n缺少物理判据", C.red2],
    [8.6, 1.62, "参数改变\n时频图细节", C.gold],
    [4.15, 4.3, "双通道择优\n没有正式规则", C.teal],
    [7.05, 4.5, "波长与 LiF\n修正尚未核验", C.teal],
    [9.85, 4.35, "GUI、打包和验收\n尚未完成", C.gray],
  ];
  issues.forEach((issue, index) => {
    const [x, y, text, color] = issue;
    const anchorX = x + 0.75;
    const anchorY = y < 3 ? 3.24 : 3.49;
    addLine(slide, anchorX, y < 3 ? y + 0.9 : y - 0.55, 0, anchorY - (y < 3 ? y + 0.9 : y - 0.55), color, 0.8);
    addShape(slide, S.ellipse, {
      x: anchorX - 0.07,
      y: anchorY - 0.07,
      w: 0.14,
      h: 0.14,
      fill: { color },
      line: { color, transparency: 100 },
    });
    addRichText(slide, text, {
      x,
      y,
      w: index === 1 || index === 5 ? 2.3 : 1.9,
      h: 0.82,
      fontSize: 20,
      bold: true,
      color: C.ink,
      align: "center",
      breakLine: true,
      valign: "top",
    });
  });
  addShape(slide, S.rect, {
    x: 1.65,
    y: 6.05,
    w: 10.05,
    h: 0.65,
    fill: { color: C.redPale },
    line: { color: C.redPale, transparency: 100 },
  });
  addRichText(slide, "当前结果适合检查数值流程和定位问题，不适合直接宣称为最终科研数据。", {
    x: 1.95,
    y: 6.18,
    w: 9.45,
    h: 0.35,
    fontSize: 22,
    bold: true,
    color: C.red,
    align: "center",
  });
  finishSlide(slide, 13);
}

// Slide 14 — next stage
{
  const slide = pptx.addSlide();
  addBase(slide, "下一阶段", "下一阶段按依赖顺序推进，AI 只做后期辅助识别");
  addLine(slide, 1.28, 1.62, 0, 4.88, C.line, 1.2);
  const steps = [
    ["01", "非 AI 谱线增强与连续性约束", "输出：候选谱线连续性与分支证据"],
    ["02", "起跳点、平台区和弱信号判据", "输出：可解释的区间标记与拒绝理由"],
    ["03", "双通道质量择优", "输出：规则、证据和不确定状态"],
    ["04", "波长、LiF 修正与实验条件核验", "输出：经核对的参数和修正模型"],
    ["05", "GUI 操作流程", "输出：围绕已验证数值链的交互界面"],
    ["06", "打包部署与用户测试", "输出：跨机器安装、日志和验收记录"],
  ];
  steps.forEach((step, index) => {
    const y = 1.43 + index * 0.88;
    const color = index < 3 ? C.red : index === 3 ? C.teal : C.gray;
    addShape(slide, S.ellipse, {
      x: 1.07,
      y: y + 0.12,
      w: 0.42,
      h: 0.42,
      fill: { color: C.bg },
      line: { color, width: 1.5 },
    });
    addRichText(slide, step[0], {
      x: 1.07,
      y: y + 0.16,
      w: 0.42,
      h: 0.25,
      fontSize: 14,
      bold: true,
      color,
      align: "center",
    });
    addRichText(slide, step[1], {
      x: 1.8,
      y,
      w: 4.55,
      h: 0.4,
      fontSize: 22,
      bold: true,
      color: C.ink,
    });
    addRichText(slide, step[2], {
      x: 6.7,
      y,
      w: 5.35,
      h: 0.42,
      fontSize: 20,
      color: C.muted,
    });
    if (index < steps.length - 1) {
      addLine(slide, 1.8, y + 0.68, 10.2, 0, C.line, 0.5);
    }
  });
  addShape(slide, S.rect, {
    x: 6.35,
    y: 6.39,
    w: 5.75,
    h: 0.66,
    fill: { color: C.tealSoft },
    line: { color: C.tealSoft, transparency: 100 },
  });
  addRichText(slide, "AI 的位置：标记可疑区域，不直接生成或决定最终速度曲线。", {
    x: 6.58,
    y: 6.45,
    w: 5.3,
    h: 0.52,
    fontSize: 20,
    bold: true,
    color: C.teal,
    align: "center",
  });
  finishSlide(slide, 14);
}

// Slide 15 — summary
{
  const slide = pptx.addSlide();
  slide.background = { color: C.bg };
  addShape(slide, S.rect, {
    x: 0,
    y: 0,
    w: 0.44,
    h: 7.5,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addRichText(slide, "总结", {
    x: 0.95,
    y: 0.58,
    w: 1.5,
    h: 0.38,
    fontSize: 18,
    bold: true,
    color: C.red,
    charSpacing: 1.2,
  });
  addRichText(slide, "当前重点已由曲线生成转向\n谱线追踪的可信度验证。", {
    x: 0.95,
    y: 1.3,
    w: 10.9,
    h: 1.35,
    fontSize: 36,
    bold: true,
    color: C.ink,
    breakLine: true,
    valign: "top",
  });
  const summaries = [
    ["现状", "真实 PDV 原始数据到表观速度的基础数值链已经存在。", C.red],
    ["当前", "弱信号谱线、双通道判断、波长与窗口修正仍需证据。", C.teal],
    ["后续", "可信判断稳定后，再完善 GUI、打包和用户测试。", C.muted],
  ];
  summaries.forEach((item, index) => {
    const y = 3.28 + index * 1.0;
    addRichText(slide, item[0], {
      x: 1.0,
      y,
      w: 0.9,
      h: 0.42,
      fontSize: 22,
      bold: true,
      color: item[2],
    });
    addLine(slide, 2.03, y + 0.2, 0.58, 0, item[2], 1.3);
    addRichText(slide, item[1], {
      x: 2.88,
      y: y - 0.03,
      w: 8.75,
      h: 0.5,
      fontSize: 22,
      color: C.ink,
    });
  });
  addRichText(slide, "DPS Studio · 组会汇报 · 2026.07.26", {
    x: 0.98,
    y: 6.72,
    w: 4.6,
    h: 0.3,
    fontSize: 16,
    color: C.muted,
  });
  finishSlide(slide, 15);
}

pptx
  .writeFile({ fileName: OUTPUT })
  .then(() => {
    process.stdout.write(`Wrote redesign deck: ${OUTPUT}\n`);
  })
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
