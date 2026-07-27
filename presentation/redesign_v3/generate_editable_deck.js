"use strict";

const fs = require("fs");
const path = require("path");
const PptxGenJS = require("pptxgenjs");
const { imageSize } = require("image-size");

const ROOT = __dirname;
const OUTPUT =
  process.argv[2] || path.join(ROOT, "DPS_Studio_组会汇报.pptx");
const ASSET = (...parts) => path.join(ROOT, "assets", ...parts);

const pptx = new PptxGenJS();
pptx.defineLayout({ name: "DPS_WIDE", width: 13.333, height: 7.5 });
pptx.layout = "DPS_WIDE";
pptx.author = "DPS Studio";
pptx.company = "DPS Studio";
pptx.subject = "DPS Studio 课题组组会汇报";
pptx.title = "DPS Studio：从原始 PDV 信号到可追溯的表观速度";
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
  bg: "F7F2EA",
  paper: "FFFDFC",
  ink: "201E1C",
  muted: "69635E",
  red: "8F2118",
  red2: "A63227",
  redSoft: "EBD8D3",
  redPale: "F3E7E3",
  line: "D6CEC4",
  light: "EEE8E0",
  pale: "E6DED4",
  gray: "9B958E",
  white: "FFFFFF",
  black: "111111",
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
    fontSize: 18,
    color: C.ink,
    margin: 0,
    breakLine: false,
    valign: "mid",
    ...opts,
  });
}

function addPlainText(slide, text, opts = {}) {
  slide.addText(text, {
    fontFace: CN,
    fontSize: 18,
    color: C.ink,
    margin: 0,
    valign: "mid",
    ...opts,
  });
}

function addShape(slide, type, opts) {
  slide.addShape(type, opts);
}

function addLine(
  slide,
  x,
  y,
  w,
  h = 0,
  color = C.line,
  width = 0.8,
  dash = "solid",
  endArrowType = undefined
) {
  const x2 = x + w;
  const y2 = y + h;
  addShape(slide, S.line, {
    x: Math.min(x, x2),
    y: Math.min(y, y2),
    w: Math.max(0.001, Math.abs(w)),
    h: Math.max(0.001, Math.abs(h)),
    flipH: w < 0,
    flipV: h < 0,
    line: { color, width, dashType: dash, endArrowType },
  });
}

function addBase(slide, section, title, number) {
  slide.background = { color: C.bg };
  addShape(slide, S.rect, {
    x: 0,
    y: 0,
    w: 0.18,
    h: 7.5,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addRichText(slide, section, {
    x: 0.55,
    y: 0.25,
    w: 2.2,
    h: 0.24,
    fontSize: 12,
    bold: true,
    color: C.red,
    charSpacing: 1.1,
  });
  const size = title.length > 27 ? 27 : title.length > 21 ? 29 : 31;
  addRichText(slide, title, {
    x: 0.55,
    y: 0.58,
    w: 11.85,
    h: 0.55,
    fontSize: size,
    bold: true,
    color: C.ink,
    fit: "shrink",
  });
  addLine(slide, 0.55, 1.25, 12.18, 0, C.line, 0.8);
  addPlainText(slide, String(number).padStart(2, "0"), {
    x: 12.27,
    y: 0.27,
    w: 0.45,
    h: 0.24,
    fontFace: EN,
    fontSize: 12,
    color: C.muted,
    align: "right",
  });
}

function addFooter(slide, text) {
  addRichText(slide, text, {
    x: 0.55,
    y: 7.09,
    w: 12.15,
    h: 0.18,
    fontSize: 10.5,
    color: C.muted,
    fit: "shrink",
  });
}

function addLead(slide, text, opts = {}) {
  addRichText(slide, text, {
    x: 0.65,
    y: 1.38,
    w: 12.0,
    h: 0.42,
    fontSize: 20,
    bold: true,
    color: C.red,
    fit: "shrink",
    ...opts,
  });
}

function addTag(slide, text, x, y, w, opts = {}) {
  addShape(slide, S.rect, {
    x,
    y,
    w,
    h: opts.h || 0.34,
    fill: { color: opts.fill || C.redPale },
    line: { color: opts.line || C.redSoft, width: 0.5 },
  });
  addRichText(slide, text, {
    x: x + 0.08,
    y,
    w: w - 0.16,
    h: opts.h || 0.34,
    fontSize: opts.fontSize || 12,
    bold: opts.bold ?? true,
    color: opts.color || C.red,
    align: opts.align || "center",
    fit: "shrink",
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

function addFigure(slide, imagePath, x, y, w, h, caption, altText) {
  addShape(slide, S.rect, {
    x,
    y,
    w,
    h,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.65 },
  });
  const captionH = caption ? 0.34 : 0;
  imageContain(
    slide,
    imagePath,
    x + 0.06,
    y + 0.05,
    w - 0.12,
    h - captionH - 0.08,
    altText
  );
  if (caption) {
    addRichText(slide, caption, {
      x: x + 0.12,
      y: y + h - 0.28,
      w: w - 0.24,
      h: 0.18,
      fontSize: 10.5,
      color: C.muted,
      align: "center",
      fit: "shrink",
    });
  }
}

function addBullet(slide, number, title, detail, x, y, w, opts = {}) {
  addPlainText(slide, String(number).padStart(2, "0"), {
    x,
    y: y + 0.01,
    w: 0.43,
    h: 0.28,
    fontFace: EN,
    fontSize: opts.numberSize || 16,
    bold: true,
    color: opts.numberColor || C.red,
  });
  addRichText(slide, title, {
    x: x + 0.52,
    y,
    w: w - 0.52,
    h: 0.29,
    fontSize: opts.titleSize || 17,
    bold: true,
    color: opts.titleColor || C.ink,
    fit: "shrink",
  });
  if (detail) {
    addRichText(slide, detail, {
      x: x + 0.52,
      y: y + 0.34,
      w: w - 0.52,
      h: opts.detailH || 0.47,
      fontSize: opts.detailSize || 13,
      color: C.muted,
      valign: "top",
      breakLine: true,
      fit: "shrink",
    });
  }
}

function addSimpleTable(slide, rows, x, y, w, h, widths) {
  slide.addTable(rows, {
    x,
    y,
    w,
    h,
    colW: widths,
    border: { type: "solid", color: C.line, pt: 0.7 },
    fill: C.paper,
    color: C.ink,
    fontFace: CN,
    fontSize: 13,
    margin: 0.08,
    valign: "mid",
    breakLine: false,
    rowH: h / rows.length,
    autoFit: false,
  });
}

function addGridTable(slide, rows, x, y, widths, rowHeights, defaults = {}) {
  let cursorY = y;
  rows.forEach((row, rowIndex) => {
    let cursorX = x;
    const rowH = rowHeights[rowIndex] || rowHeights[rowHeights.length - 1];
    row.forEach((cell, columnIndex) => {
      const descriptor =
        typeof cell === "object" && cell !== null && "text" in cell
          ? cell
          : { text: String(cell), options: {} };
      const options = descriptor.options || {};
      const fill =
        options.fill ||
        (rowIndex === 0
          ? defaults.headerFill || C.red
          : rowIndex % 2 === 0
            ? defaults.altFill || C.bg
            : defaults.bodyFill || C.paper);
      const color =
        options.color ||
        (rowIndex === 0
          ? defaults.headerColor || C.white
          : defaults.bodyColor || C.ink);
      addShape(slide, S.rect, {
        x: cursorX,
        y: cursorY,
        w: widths[columnIndex],
        h: rowH,
        fill: { color: fill },
        line: { color: C.line, width: 0.55 },
      });
      addRichText(slide, descriptor.text, {
        x: cursorX + 0.09,
        y: cursorY + 0.02,
        w: widths[columnIndex] - 0.18,
        h: rowH - 0.04,
        fontSize: options.fontSize || defaults.fontSize || 12.5,
        bold: options.bold ?? rowIndex === 0,
        color,
        align:
          options.align ||
          (columnIndex === 0 ? defaults.firstAlign || "left" : "center"),
        fit: "shrink",
      });
      cursorX += widths[columnIndex];
    });
    cursorY += rowH;
  });
}

function addNotes(slide, text) {
  slide.addNotes(text);
}

function drawSine(slide, x, y, w, h, cycles, color, width = 1.1) {
  const segments = 90;
  let px = x;
  let py = y + h / 2;
  for (let i = 1; i <= segments; i += 1) {
    const t = i / segments;
    const nx = x + t * w;
    const ny = y + h / 2 - Math.sin(t * Math.PI * 2 * cycles) * h * 0.38;
    addLine(slide, px, py, nx - px, ny - py, color, width);
    px = nx;
    py = ny;
  }
}

function drawSpectrogramGrid(slide, x, y, w, h) {
  addShape(slide, S.rect, {
    x,
    y,
    w,
    h,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.8 },
  });
  for (let i = 1; i < 7; i += 1) {
    addLine(slide, x + (w * i) / 7, y, 0, h, C.light, 0.55);
  }
  for (let i = 1; i < 5; i += 1) {
    addLine(slide, x, y + (h * i) / 5, w, 0, C.light, 0.55);
  }
  const points = [
    [0.06, 0.72],
    [0.18, 0.60],
    [0.32, 0.46],
    [0.48, 0.35],
    [0.62, 0.35],
    [0.75, 0.44],
    [0.9, 0.7],
  ];
  for (let i = 1; i < points.length; i += 1) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    addLine(
      slide,
      x + x0 * w,
      y + y0 * h,
      (x1 - x0) * w,
      (y1 - y0) * h,
      C.red,
      2.0
    );
  }
}

const notes = {
  1: "本次汇报不把软件运行结果等同于最终物理结论。重点是展示真实材料、当前数值处理过程，以及每个结论的适用边界。",
  2: "PDV 指 Photon Doppler Velocimetry。这里的表观速度只由拍频与显式波长换算，尚未包含 LiF、折射率和入射角修正。",
  3: "两个采集通道分别读取和分析。当前流程没有在原始电压层平均、平滑、插值或通道融合。",
  4: "时域振荡能说明存在干涉信号，但要回答频率随时间如何变化，需要短时傅里叶变换。此页为原生示意，不是实验结果图。",
  5: "完整单边频谱上限由实际采样率决定，约为 20 GHz。脊线搜索仅在 0.05 到 2.0 GHz 内进行，显示范围和搜索范围需要分开。",
  6: "当前每一帧先在固定搜索带中取最大幅值频点，再用三点对数幅值二次模型做亚频点精修。当前没有动态规划或物理分支识别。",
  7: "拍频乘以显式真空波长后得到无符号表观速度。配置中的 1.55 微米仍是演示值，必须等待实验记录确认。",
  8: "正式配置负责输入、事件时间、波长、质量参数和输出；两个 AnalysisProfile 负责 STFT 和搜索参数。运行清单会记录这些值。",
  9: "Balanced 与 High time 的 hop 相同，但窗口长度不同。较短窗口缩短时间支持，也使窗限频率尺度更大。nfft 只加密频率采样网格。",
  10: "这两个图来自同一原始数据和同一通道。Balanced 在这次数据的平台区更稳定，High time 不能解释为更高准确度。",
  11: "正式全时间图只连接有定义的候选区。前事件零只为显示，核心表观速度保留 NaN；显示桥只含两个端点。",
  12: "起跳、平台和下降段分别检查，可看到窗口支持、平台微小波动和下降段连续变化。所有图仍是基于临时波长的表观速度。",
  13: "两通道趋势接近，只能作为本次数据的一致性观察。dB 数值是谱对比度，不是 SNR，也不能用于自动通道选择。",
  14: "旧软件图和 CSV 的来源与处理参数仍需实验组确认，因此只能用于开发历史。当前变化的核心是配置、源数据和结果可回查。",
  15: "已经完成的是数值处理和可追溯输出。GUI、物理修正和经实验验证的判据仍未完成，不能写成当前能力。",
  16: "诊断量已经可以揭示谱背景、竞争峰和连续性变化，但尚无经实验验证的可用或不可用阈值。",
  17: "下一步需要按依赖顺序推进。实验元数据和判据不确认，物理修正和界面工作都缺少稳定基础。",
  18: "结论分为已有、边界和下一步三层。当前已能复现表观速度处理过程，但科研解释仍需额外证据。",
};

// Slide 01 — cover
{
  const slide = pptx.addSlide();
  slide.background = { color: C.bg };
  addShape(slide, S.rect, {
    x: 0,
    y: 0,
    w: 0.52,
    h: 7.5,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addRichText(slide, "DPS Studio", {
    x: 0.88,
    y: 0.72,
    w: 2.2,
    h: 0.3,
    fontSize: 15,
    bold: true,
    color: C.red,
    charSpacing: 1.6,
  });
  addRichText(slide, "从原始 PDV 信号到\n可追溯的表观速度", {
    x: 0.88,
    y: 1.34,
    w: 7.9,
    h: 1.5,
    fontSize: 34,
    bold: true,
    color: C.ink,
    breakLine: true,
    valign: "top",
    fit: "shrink",
  });
  addRichText(slide, "课题组组会汇报", {
    x: 0.9,
    y: 3.16,
    w: 2.4,
    h: 0.34,
    fontSize: 17,
    color: C.muted,
  });
  addPlainText(slide, "2026.07.26", {
    x: 0.9,
    y: 3.65,
    w: 2.0,
    h: 0.3,
    fontFace: EN,
    fontSize: 15,
    color: C.muted,
  });
  addLine(slide, 0.9, 4.52, 6.0, 0, C.line, 0.8);
  const labels = [
    ["V(t)", "原始电压"],
    ["S(t, f)", "时频表示"],
    ["v_app(t)", "表观速度"],
  ];
  labels.forEach(([symbol, label], index) => {
    const x = 0.92 + index * 2.28;
    addPlainText(slide, symbol, {
      x,
      y: 4.82,
      w: 1.3,
      h: 0.36,
      fontFace: EN,
      italic: true,
      fontSize: 22,
      color: index === 2 ? C.red : C.ink,
    });
    addRichText(slide, label, {
      x,
      y: 5.25,
      w: 1.4,
      h: 0.25,
      fontSize: 12,
      color: C.muted,
    });
    if (index < 2) {
      addLine(slide, x + 1.46, 5.02, 0.55, 0, C.gray, 0.8, "solid", "triangle");
    }
  });
  drawSine(slide, 8.72, 1.45, 3.72, 0.76, 4.4, C.redSoft, 1.3);
  drawSine(slide, 8.72, 2.42, 3.72, 0.48, 8.0, C.line, 0.85);
  addRichText(slide, "可复现的数值过程\n仍需验证的物理解释", {
    x: 9.05,
    y: 3.56,
    w: 3.15,
    h: 0.92,
    fontSize: 19,
    bold: true,
    color: C.red,
    breakLine: true,
    align: "right",
    fit: "shrink",
  });
  addLine(slide, 8.76, 4.85, 3.7, 0, C.red, 1.15);
  addRichText(slide, "真空波长未确认｜无 LiF 修正｜无符号表观速度", {
    x: 8.58,
    y: 5.08,
    w: 3.9,
    h: 0.55,
    fontSize: 12.5,
    color: C.muted,
    align: "right",
    fit: "shrink",
  });
  addNotes(slide, notes[1]);
}

// Slide 02 — task
{
  const slide = pptx.addSlide();
  addBase(slide, "任务", "这次汇报要回答三个问题", 2);
  addLead(slide, "解释输入、算法和结论边界，而不是只展示一条曲线。");
  const questions = [
    ["原始电压如何变成随时间变化的拍频？", "输入与 STFT"],
    ["当前参数如何影响时间支持与频率稳定？", "参数与 profile"],
    ["表观速度可以支持什么，仍不能支持什么？", "结果与边界"],
  ];
  questions.forEach(([question, label], index) => {
    const y = 2.05 + index * 1.18;
    addPlainText(slide, String(index + 1).padStart(2, "0"), {
      x: 0.68,
      y,
      w: 0.52,
      h: 0.38,
      fontFace: EN,
      fontSize: 20,
      bold: true,
      color: C.red,
    });
    addRichText(slide, question, {
      x: 1.42,
      y: y - 0.02,
      w: 7.65,
      h: 0.43,
      fontSize: 21,
      bold: true,
      fit: "shrink",
    });
    addTag(slide, label, 9.55, y - 0.01, 2.45, {
      fill: C.light,
      line: C.line,
      color: C.muted,
      bold: false,
      fontSize: 12.5,
    });
    addLine(slide, 1.42, y + 0.56, 10.58, 0, C.line, 0.65);
  });
  addShape(slide, S.rect, {
    x: 0.68,
    y: 5.7,
    w: 11.45,
    h: 0.9,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.65 },
  });
  addRichText(slide, "PDV", {
    x: 0.92,
    y: 5.88,
    w: 0.75,
    h: 0.28,
    fontSize: 18,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "Photon Doppler Velocimetry，光子多普勒测速。", {
    x: 1.7,
    y: 5.84,
    w: 4.2,
    h: 0.36,
    fontSize: 13.5,
    color: C.muted,
    fit: "shrink",
  });
  addLine(slide, 6.1, 5.85, 0, 0.42, C.line, 0.7);
  addRichText(slide, "表观速度", {
    x: 6.38,
    y: 5.88,
    w: 1.05,
    h: 0.28,
    fontSize: 17,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "由显式波长与拍频换算；尚未做 LiF、折射率或入射角修正。", {
    x: 7.5,
    y: 5.84,
    w: 4.28,
    h: 0.36,
    fontSize: 13.2,
    color: C.muted,
    fit: "shrink",
  });
  addFooter(slide, "边界：数据事实、数值处理与物理解释分开陈述。");
  addNotes(slide, notes[2]);
}

// Slide 03 — raw input
{
  const slide = pptx.addSlide();
  addBase(slide, "原始输入", "原始数据保留两路采集差异", 3);
  addLead(slide, "两列电压分别读入，不平均、不融合、不平滑。", {
    w: 4.1,
  });
  addBullet(slide, 1, "列映射显式", "time = 0；channel 1 = 1；channel 2 = 2", 0.65, 2.08, 3.15, {
    detailH: 0.5,
  });
  addBullet(slide, 2, "单位保持 SI", "时间和电压在核心计算中不改写物理单位", 0.65, 3.08, 3.15, {
    detailH: 0.5,
  });
  addBullet(slide, 3, "通道独立", "每列建立独立 SignalRecord，分别进行 STFT 与脊线分析", 0.65, 4.08, 3.15, {
    detailH: 0.65,
  });
  addFigure(
    slide,
    ASSET("real", "raw_voltage_dual_channel.png"),
    3.95,
    1.66,
    8.35,
    4.93,
    "真实输入：data/raw/20260607.csv 的两个电压通道；既有图，无平滑、无插值",
    "原始双通道 PDV 电压随相对事件时间变化"
  );
  addFooter(slide, "来源：configs/demo_dual_profile.toml；scripts/run_demo_pipeline.py");
  addNotes(slide, notes[3]);
}

// Slide 04 — why time trace is insufficient
{
  const slide = pptx.addSlide();
  addBase(slide, "方法起点", "波形振荡并不直接给出频率何时改变", 4);
  addLead(slide, "需要把短时间段内的频率内容沿时间排列。");
  addTag(slide, "时域电压", 0.78, 2.0, 2.45, {
    fill: C.light,
    line: C.line,
    color: C.ink,
    fontSize: 14,
  });
  drawSine(slide, 0.82, 2.55, 2.45, 1.05, 7.5, C.red, 1.15);
  addRichText(slide, "振幅和周期同时变化", {
    x: 0.82,
    y: 3.78,
    w: 2.45,
    h: 0.28,
    fontSize: 13,
    color: C.muted,
    align: "center",
  });
  addLine(slide, 3.5, 3.05, 0.72, 0, C.gray, 0.85, "solid", "triangle");
  addTag(slide, "滑动 Hann 窗", 4.42, 2.0, 2.45, {
    fill: C.light,
    line: C.line,
    color: C.ink,
    fontSize: 14,
  });
  addShape(slide, S.arc, {
    x: 4.58,
    y: 2.56,
    w: 2.1,
    h: 0.95,
    adjustPoint: 0.5,
    rotate: 180,
    fill: { color: C.redPale, transparency: 25 },
    line: { color: C.red, width: 1.0 },
  });
  addRichText(slide, "每个时间窗独立做傅里叶变换", {
    x: 4.42,
    y: 3.78,
    w: 2.45,
    h: 0.28,
    fontSize: 13,
    color: C.muted,
    align: "center",
    fit: "shrink",
  });
  addLine(slide, 7.08, 3.05, 0.72, 0, C.gray, 0.85, "solid", "triangle");
  addTag(slide, "时间—频率矩阵", 8.0, 2.0, 3.7, {
    fill: C.light,
    line: C.line,
    color: C.ink,
    fontSize: 14,
  });
  drawSpectrogramGrid(slide, 8.0, 2.5, 3.7, 1.62);
  addRichText(slide, "亮带的位置给出候选拍频轨迹", {
    x: 8.0,
    y: 4.3,
    w: 3.7,
    h: 0.28,
    fontSize: 13,
    color: C.muted,
    align: "center",
  });
  addShape(slide, S.rect, {
    x: 0.78,
    y: 5.12,
    w: 10.92,
    h: 0.92,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.65 },
  });
  addRichText(slide, "拍频", {
    x: 1.0,
    y: 5.35,
    w: 0.7,
    h: 0.28,
    fontSize: 17,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "参考光与运动表面反射光干涉形成的频率差。", {
    x: 1.72,
    y: 5.31,
    w: 3.75,
    h: 0.36,
    fontSize: 13.5,
    color: C.muted,
    fit: "shrink",
  });
  addLine(slide, 5.74, 5.28, 0, 0.48, C.line, 0.7);
  addRichText(slide, "STFT", {
    x: 6.02,
    y: 5.35,
    w: 0.75,
    h: 0.28,
    fontSize: 17,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "Short-Time Fourier Transform，短时傅里叶变换。", {
    x: 6.82,
    y: 5.31,
    w: 4.45,
    h: 0.36,
    fontSize: 13.2,
    color: C.muted,
    fit: "shrink",
  });
  addFooter(slide, "本页为原生算法示意，不是实验结果图。");
  addNotes(slide, notes[4]);
}

// Slide 05 — full spectrogram
{
  const slide = pptx.addSlide();
  addBase(slide, "完整频谱", "完整单边频谱先交代能量分布", 5);
  addLead(slide, "实际 Nyquist 约 20 GHz；数值脊线只在 0.05–2.0 GHz 搜索。", {
    fontSize: 19,
  });
  addFigure(
    slide,
    ASSET("real", "full_stft_balanced_ch1.png"),
    0.72,
    1.85,
    11.75,
    4.55,
    "Balanced / pdv_channel_1：完整单边 STFT，纵轴由实际频率轴确定",
    "Balanced 通道一的完整单边 STFT 频谱"
  );
  addTag(slide, "完整单边频谱：0–约 20 GHz", 0.8, 6.5, 3.46, {
    fill: C.light,
    line: C.line,
    color: C.ink,
    fontSize: 12.2,
  });
  addTag(slide, "分析显示：0–2.0 GHz", 4.48, 6.5, 3.14, {
    fill: C.light,
    line: C.line,
    color: C.ink,
    fontSize: 12.2,
  });
  addTag(slide, "数值搜索：0.05–2.0 GHz", 7.84, 6.5, 3.42, {
    fill: C.redPale,
    line: C.redSoft,
    color: C.red,
    fontSize: 12.2,
  });
  addFooter(slide, "来源：run_20260724_004901_103968 / balanced / pdv_channel_1");
  addNotes(slide, notes[5]);
}

// Slide 06 — ridge
{
  const slide = pptx.addSlide();
  addBase(slide, "候选脊线", "局部 STFT 中的亮带提供可追踪候选", 6);
  addLead(slide, "固定搜索带内取离散峰，再用相邻三点对数幅值做亚频点精修。", {
    fontSize: 18.5,
  });
  addFigure(
    slide,
    ASSET("real", "local_stft_balanced_ch1.png"),
    0.65,
    1.9,
    5.8,
    4.55,
    "局部 STFT：先观察事件附近的时频结构",
    "事件附近的局部 STFT 频谱"
  );
  addFigure(
    slide,
    ASSET("real", "local_stft_ridge_balanced_ch1.png"),
    6.72,
    1.9,
    5.8,
    4.55,
    "诊断叠加：离散峰、亚频点精修与相关频率局部峰",
    "局部 STFT 与亚频点精修脊线"
  );
  addTag(slide, "脊线：逐帧候选频率轨迹", 0.82, 6.52, 3.37, {
    fill: C.light,
    line: C.line,
    color: C.ink,
    fontSize: 12.2,
  });
  addTag(slide, "亚频点精修：估计 FFT 网格之间的峰位", 4.42, 6.52, 4.32, {
    fill: C.redPale,
    line: C.redSoft,
    color: C.red,
    fontSize: 12.2,
  });
  addTag(slide, "当前无动态规划或物理分支识别", 8.98, 6.52, 3.25, {
    fill: C.light,
    line: C.line,
    color: C.muted,
    fontSize: 12,
    bold: false,
  });
  addFooter(slide, "来源：presentations/data/balanced_diagnostic；仅作开发诊断说明");
  addNotes(slide, notes[6]);
}

// Slide 07 — physics conversion
{
  const slide = pptx.addSlide();
  addBase(slide, "物理换算", "拍频不是速度；显式波长后才能换算", 7);
  addLead(slide, "当前模型只给出无符号表观速度。");
  addShape(slide, S.rect, {
    x: 0.78,
    y: 2.08,
    w: 7.35,
    h: 2.82,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.65 },
  });
  addPlainText(slide, "v_app(t) = λ₀ f_b(t) / 2", {
    x: 1.28,
    y: 2.7,
    w: 6.28,
    h: 0.58,
    fontFace: EN,
    fontSize: 32,
    italic: true,
    color: C.red,
    align: "center",
    fit: "shrink",
  });
  addRichText(slide, "法向反射 PDV 的当前换算式", {
    x: 1.42,
    y: 3.58,
    w: 5.95,
    h: 0.3,
    fontSize: 14,
    color: C.muted,
    align: "center",
  });
  addLine(slide, 1.42, 4.15, 5.95, 0, C.line, 0.7);
  addRichText(slide, "精修拍频 f_b(t)", {
    x: 1.35,
    y: 4.35,
    w: 1.95,
    h: 0.3,
    fontSize: 14,
    bold: true,
    align: "center",
  });
  addLine(slide, 3.38, 4.5, 0.55, 0, C.gray, 0.8, "solid", "triangle");
  addRichText(slide, "显式波长 λ₀", {
    x: 4.03,
    y: 4.35,
    w: 1.8,
    h: 0.3,
    fontSize: 14,
    bold: true,
    align: "center",
  });
  addLine(slide, 5.9, 4.5, 0.55, 0, C.gray, 0.8, "solid", "triangle");
  addRichText(slide, "v_app(t)", {
    x: 6.54,
    y: 4.35,
    w: 1.05,
    h: 0.3,
    fontSize: 14,
    bold: true,
    color: C.red,
    align: "center",
  });
  addBullet(slide, 1, "波长尚未确认", "λ₀ = 1.55 µm 是配置中的演示值，实验记录尚未核实", 8.55, 2.08, 3.82, {
    detailH: 0.58,
    detailSize: 12.5,
  });
  addBullet(slide, 2, "修正项未接入", "不含 LiF、折射率、入射角或窗口修正", 8.55, 3.45, 3.82, {
    detailH: 0.5,
    detailSize: 12.5,
  });
  addBullet(slide, 3, "当前无速度符号", "单边 STFT 只保留正频率，结果为无符号量", 8.55, 4.72, 3.82, {
    detailH: 0.5,
    detailSize: 12.5,
  });
  addShape(slide, S.rect, {
    x: 0.78,
    y: 5.54,
    w: 11.58,
    h: 0.82,
    fill: { color: C.redPale },
    line: { color: C.redSoft, width: 0.6 },
  });
  addRichText(slide, "当前输出应称为“无符号表观速度”，不能称为 LiF 修正后的真实界面速度。", {
    x: 1.02,
    y: 5.76,
    w: 11.08,
    h: 0.34,
    fontSize: 16,
    bold: true,
    color: C.red,
    align: "center",
    fit: "shrink",
  });
  addFooter(slide, "来源：src/dps_studio/core/physics/velocity.py；configs/demo_dual_profile.toml");
  addNotes(slide, notes[7]);
}

// Slide 08 — parameters
{
  const slide = pptx.addSlide();
  addBase(slide, "当前参数", "所有主要参数来自正式配置与 profile", 8);
  addLead(slide, "参数入口已集中，运行清单记录本次实际值。");
  const rows = [
    [
      { text: "参数", options: { bold: true, color: C.white, fill: C.red, align: "center" } },
      { text: "balanced", options: { bold: true, color: C.white, fill: C.red, align: "center" } },
      { text: "high_time_resolution", options: { bold: true, color: C.white, fill: C.red, align: "center" } },
    ],
    ["window", "Hann", "Hann"],
    ["window length", "768", "512"],
    ["overlap", "640", "384"],
    ["hop", "128", "128"],
    ["nfft", "4096", "4096"],
    ["ridge search", "0.05–2.0 GHz", "0.05–2.0 GHz"],
  ];
  addGridTable(
    slide,
    rows,
    0.7,
    1.95,
    [2.35, 2.05, 2.7],
    [0.56, 0.61, 0.61, 0.61, 0.61, 0.61, 0.61],
    { fontSize: 12.5, firstAlign: "left" }
  );
  addShape(slide, S.rect, {
    x: 8.12,
    y: 1.95,
    w: 4.32,
    h: 4.45,
    fill: { color: "181818" },
    line: { color: "181818", width: 0.6 },
  });
  addPlainText(
    slide,
    [
      "[analysis]",
      "profiles = [",
      '  "balanced",',
      '  "high_time_resolution"',
      "]",
      "event_start_time_s = 5.54668e-4",
      "analysis_end_time_s = 5.55450e-4",
      "vacuum_wavelength_m = 1.55e-6",
      "",
      "[quality]",
      "background_guard_window_scale = 2.0",
      "minimum_background_bin_count = 2",
    ].join("\n"),
    {
      x: 8.42,
      y: 2.23,
      w: 3.72,
      h: 3.62,
      fontFace: CODE,
      fontSize: 12.8,
      color: "F3F1EE",
      valign: "top",
      breakLine: true,
      fit: "shrink",
    }
  );
  addRichText(slide, "配置路径", {
    x: 8.42,
    y: 5.92,
    w: 0.82,
    h: 0.22,
    fontSize: 12,
    bold: true,
    color: C.redSoft,
  });
  addPlainText(slide, "configs/demo_dual_profile.toml", {
    x: 9.26,
    y: 5.9,
    w: 2.8,
    h: 0.25,
    fontFace: CODE,
    fontSize: 10.8,
    color: C.white,
    fit: "shrink",
  });
  addTag(slide, "profile 定义：src/dps_studio/core/analysis_profiles.py", 0.72, 6.55, 5.15, {
    fill: C.light,
    line: C.line,
    color: C.muted,
    fontSize: 11.5,
    bold: false,
  });
  addTag(slide, "配置解析：src/dps_studio/core/workflow/config.py", 6.05, 6.55, 5.05, {
    fill: C.light,
    line: C.line,
    color: C.muted,
    fontSize: 11.5,
    bold: false,
  });
  addFooter(slide, "波长 1.55 µm 仍为未确认演示值；该状态同时写入 manifest。");
  addNotes(slide, notes[8]);
}

// Slide 09 — tradeoff
{
  const slide = pptx.addSlide();
  addBase(slide, "参数取舍", "窗口长度同时决定时间支持与频率稳定", 9);
  addLead(slide, "nfft 加密 FFT 网格，但不能单独提高真实频率分辨能力。", {
    fontSize: 18.8,
  });
  addLine(slide, 1.05, 3.02, 10.9, 0, C.line, 1.2);
  addLine(slide, 1.08, 3.02, 0.01, 0, C.red, 5.0);
  addLine(slide, 11.91, 3.02, 0.01, 0, C.red, 5.0);
  addRichText(slide, "更短时间支持", {
    x: 0.76,
    y: 2.34,
    w: 2.2,
    h: 0.36,
    fontSize: 18,
    bold: true,
    color: C.red,
    align: "left",
  });
  addRichText(slide, "更稳定的频率估计", {
    x: 9.76,
    y: 2.34,
    w: 2.42,
    h: 0.36,
    fontSize: 18,
    bold: true,
    color: C.red,
    align: "right",
  });
  addShape(slide, S.rect, {
    x: 2.02,
    y: 2.78,
    w: 0.12,
    h: 0.48,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addRichText(slide, "High time", {
    x: 1.37,
    y: 3.38,
    w: 1.4,
    h: 0.28,
    fontSize: 15,
    bold: true,
    color: C.red,
    align: "center",
  });
  addShape(slide, S.rect, {
    x: 9.63,
    y: 2.78,
    w: 0.12,
    h: 0.48,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addRichText(slide, "Balanced", {
    x: 8.98,
    y: 3.38,
    w: 1.42,
    h: 0.28,
    fontSize: 15,
    bold: true,
    color: C.red,
    align: "center",
  });
  const metrics = [
    ["窗口时间支持", "12.8 ns", "19.2 ns"],
    ["窗限频率尺度", "78.1 MHz", "52.1 MHz"],
    ["hop 时间", "约 3.2 ns", "约 3.2 ns"],
    ["FFT 网格", "约 9.77 MHz", "约 9.77 MHz"],
  ];
  metrics.forEach(([label, high, balanced], index) => {
    const y = 4.18 + index * 0.56;
    addRichText(slide, label, {
      x: 2.66,
      y,
      w: 2.1,
      h: 0.26,
      fontSize: 13.5,
      color: C.muted,
      align: "right",
    });
    addPlainText(slide, high, {
      x: 5.05,
      y,
      w: 1.55,
      h: 0.26,
      fontFace: EN,
      fontSize: 15,
      bold: true,
      color: C.ink,
      align: "center",
    });
    addPlainText(slide, balanced, {
      x: 7.3,
      y,
      w: 1.55,
      h: 0.26,
      fontFace: EN,
      fontSize: 15,
      bold: true,
      color: C.ink,
      align: "center",
    });
    addLine(slide, 2.66, y + 0.38, 6.18, 0, C.light, 0.5);
  });
  addRichText(slide, "High time", {
    x: 5.05,
    y: 3.84,
    w: 1.55,
    h: 0.24,
    fontSize: 12,
    bold: true,
    color: C.red,
    align: "center",
  });
  addRichText(slide, "Balanced", {
    x: 7.3,
    y: 3.84,
    w: 1.55,
    h: 0.24,
    fontSize: 12,
    bold: true,
    color: C.red,
    align: "center",
  });
  addShape(slide, S.rect, {
    x: 9.25,
    y: 4.05,
    w: 2.72,
    h: 1.83,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.65 },
  });
  addRichText(slide, "解释边界", {
    x: 9.52,
    y: 4.3,
    w: 2.0,
    h: 0.28,
    fontSize: 15,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "这些数值只对应本次约 40 GS/s 的真实输入。\n高重叠帧不是独立测量。", {
    x: 9.52,
    y: 4.72,
    w: 2.18,
    h: 0.83,
    fontSize: 12.8,
    color: C.muted,
    valign: "top",
    breakLine: true,
    fit: "shrink",
  });
  addFooter(slide, "来源：profile_manifest.json；PROJECT_STRUCTURE_AND_PARAMETER_AUDIT.md §17");
  addNotes(slide, notes[9]);
}

// Slide 10 — real profile comparison
{
  const slide = pptx.addSlide();
  addBase(slide, "真实 profile 对比", "同一原始数据下，两套 profile 强调不同取舍", 10);
  addLead(slide, "Balanced 在本次数据的平台区更稳定；High time 不代表更高准确度。", {
    fontSize: 18.2,
  });
  addFigure(
    slide,
    ASSET("real", "ridge_balanced_ch1.png"),
    0.64,
    1.85,
    5.92,
    3.58,
    "Balanced / channel 1",
    "Balanced profile 的带脊线分析频谱"
  );
  addFigure(
    slide,
    ASSET("real", "ridge_high_time_ch1.png"),
    6.76,
    1.85,
    5.92,
    3.58,
    "High time resolution / channel 1",
    "High time resolution profile 的带脊线分析频谱"
  );
  const rows = [
    [
      { text: "本次 run / channel 1", options: { bold: true, fill: C.light, color: C.ink } },
      { text: "Balanced", options: { bold: true, fill: C.light, color: C.red, align: "center" } },
      { text: "High time", options: { bold: true, fill: C.light, color: C.red, align: "center" } },
    ],
    ["首个候选表观速度", "537.9 m/s", "532.0 m/s"],
    ["最大相邻频率步长", "21.8 MHz", "25.0 MHz"],
    ["峰—背景谱对比度中位数", "52.5 dB", "48.1 dB"],
  ];
  addGridTable(
    slide,
    rows,
    1.42,
    5.56,
    [4.2, 3.15, 3.15],
    [0.31, 0.31, 0.31, 0.31],
    { fontSize: 11.5, firstAlign: "left", headerFill: C.light, headerColor: C.ink }
  );
  addFooter(slide, "dB 为描述性谱对比度，不是 SNR；结果不外推到其他数据。");
  addNotes(slide, notes[10]);
}

// Slide 11 — full velocity
{
  const slide = pptx.addSlide();
  addBase(slide, "完整时间—速度", "正式结果只连接有定义的候选区间", 11);
  addLead(slide, "前事件零是显示假设；核心表观速度保持 NaN。");
  addFigure(
    slide,
    ASSET("real", "full_velocity_balanced_ch1.png"),
    0.65,
    1.82,
    8.75,
    4.93,
    "Balanced / pdv_channel_1：正式全时间表观速度",
    "Balanced 通道一的正式全时间表观速度"
  );
  addBullet(slide, 1, "正式候选", "只有事件窗口内且精修有效的帧写入表观速度", 9.68, 2.05, 2.67, {
    detailH: 0.7,
    detailSize: 12.5,
    titleSize: 16,
  });
  addBullet(slide, 2, "显示零", "前事件仅 display_velocity_m_s 假设为 0；核心量仍为 NaN", 9.68, 3.54, 2.67, {
    detailH: 0.78,
    detailSize: 12.2,
    titleSize: 16,
  });
  addBullet(slide, 3, "显示桥", "只保留两个端点，不写入中间 CSV 数据", 9.68, 5.1, 2.67, {
    detailH: 0.62,
    detailSize: 12.4,
    titleSize: 16,
  });
  addFooter(slide, "来源：run_20260724_004901_103968 / balanced / pdv_channel_1；未使用 quality-unfiltered preview");
  addNotes(slide, notes[11]);
}

// Slide 12 — local velocity details
{
  const slide = pptx.addSlide();
  addBase(slide, "局部速度细节", "起跳、平台和下降段应分别检查", 12);
  addLead(slide, "完整曲线会掩盖窗口支持、平台抖动和下降段连续性。", {
    fontSize: 18.5,
  });
  const figures = [
    [
      "event_detail_balanced_ch1.png",
      "起跳",
      "事件起点附近：窗口支持跨越起点，显示桥不是测量",
      "事件起点附近的表观速度细节",
    ],
    [
      "plateau_detail_balanced_ch1.png",
      "平台",
      "平台区：逐个精修帧可见小幅波动",
      "平台全貌与逐帧细节",
    ],
    [
      "decline_detail_balanced_ch1.png",
      "下降",
      "下降段：逐帧频率轨迹转为连续速度下降",
      "下降段的逐帧表观速度",
    ],
  ];
  figures.forEach(([file, label, caption, alt], index) => {
    const x = 0.62 + index * 4.16;
    addTag(slide, label, x, 1.92, 1.08, {
      fill: index === 1 ? C.redPale : C.light,
      line: index === 1 ? C.redSoft : C.line,
      color: index === 1 ? C.red : C.ink,
      fontSize: 13.5,
    });
    addFigure(
      slide,
      ASSET("real", file),
      x,
      2.42,
      3.88,
      3.72,
      "",
      alt
    );
    addRichText(slide, caption, {
      x: x + 0.1,
      y: 6.25,
      w: 3.68,
      h: 0.48,
      fontSize: 12.3,
      color: C.muted,
      align: "center",
      fit: "shrink",
    });
  });
  addFooter(slide, "三图均为真实 Balanced / channel 1；临时 1.55 µm，无 LiF 修正。");
  addNotes(slide, notes[12]);
}

// Slide 13 — two channels
{
  const slide = pptx.addSlide();
  addBase(slide, "双通道", "两通道趋势接近，但仍是两次独立观测", 13);
  addLead(slide, "当前只支持“本次数据中趋势同量级”，不能推出准确度或自动择优。", {
    fontSize: 18.2,
  });
  addFigure(
    slide,
    ASSET("real", "two_channel_velocity.png"),
    0.64,
    1.82,
    8.45,
    4.95,
    "Balanced：两采集通道表观速度叠加，仅作一致性观察",
    "两个采集通道的表观速度对比"
  );
  const stats = [
    ["首个候选", "537.9 / 531.8 m/s"],
    ["峰—背景中位数", "52.5 / 55.8 dB"],
    ["峰—竞争峰中位数", "13.3 / 19.9 dB"],
  ];
  stats.forEach(([label, value], index) => {
    const y = 2.1 + index * 0.92;
    addRichText(slide, label, {
      x: 9.47,
      y,
      w: 2.65,
      h: 0.25,
      fontSize: 12.5,
      color: C.muted,
    });
    addPlainText(slide, value, {
      x: 9.47,
      y: y + 0.3,
      w: 2.65,
      h: 0.3,
      fontFace: EN,
      fontSize: 17,
      bold: true,
      color: C.red,
      fit: "shrink",
    });
    addLine(slide, 9.47, y + 0.72, 2.65, 0, C.line, 0.6);
  });
  addShape(slide, S.rect, {
    x: 9.47,
    y: 5.15,
    w: 2.72,
    h: 1.32,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.65 },
  });
  addRichText(slide, "不能推出", {
    x: 9.72,
    y: 5.38,
    w: 1.0,
    h: 0.25,
    fontSize: 14,
    bold: true,
    color: C.red,
  });
  addRichText(slide, "准确度｜SNR｜自动通道选择｜通道融合", {
    x: 9.72,
    y: 5.72,
    w: 2.18,
    h: 0.48,
    fontSize: 12.3,
    color: C.muted,
    breakLine: true,
    fit: "shrink",
  });
  addFooter(slide, "dB 仅为描述性谱对比度；两通道分别完成 STFT、脊线和速度换算。");
  addNotes(slide, notes[13]);
}

// Slide 14 — history
{
  const slide = pptx.addSlide();
  addBase(slide, "开发历史", "软件从手动导出走向可追溯运行", 14);
  addLead(slide, "变化重点是参数、源数据与结果之间可回查，而不是曲线外观。", {
    fontSize: 18.4,
  });
  addFigure(
    slide,
    ASSET("real", "legacy_velocity.png"),
    0.68,
    1.86,
    5.62,
    3.34,
    "旧软件导出：来源和处理参数待实验组确认",
    "旧软件导出的速度时间曲线"
  );
  addFigure(
    slide,
    ASSET("real", "current_presentation_velocity.png"),
    6.64,
    1.86,
    5.62,
    3.34,
    "当前开发输出：参数、原始数据哈希和解释边界可记录",
    "当前软件的表观速度展示图"
  );
  addLine(slide, 1.18, 5.86, 10.35, 0, C.line, 1.0);
  const timeline = [
    ["旧软件本地导出", "来源待确认"],
    ["不可变数据模型", "SI 单位"],
    ["STFT 与亚频点精修", "逐帧状态"],
    ["workflow / config / manifest", "可回查"],
  ];
  timeline.forEach(([title, sub], index) => {
    const x = 0.86 + index * 3.04;
    addShape(slide, S.rect, {
      x: x + 0.45,
      y: 5.76,
      w: 0.16,
      h: 0.2,
      fill: { color: index === 0 ? C.gray : C.red },
      line: { color: index === 0 ? C.gray : C.red, transparency: 100 },
    });
    addRichText(slide, title, {
      x,
      y: 6.13,
      w: 2.42,
      h: 0.26,
      fontSize: 13.2,
      bold: true,
      color: C.ink,
      align: "center",
      fit: "shrink",
    });
    addRichText(slide, sub, {
      x,
      y: 6.46,
      w: 2.42,
      h: 0.22,
      fontSize: 11.5,
      color: C.muted,
      align: "center",
      fit: "shrink",
    });
  });
  addFooter(slide, "旧软件数据不是物理真值；本页只用于开发阶段对照。");
  addNotes(slide, notes[14]);
}

// Slide 15 — completed capabilities
{
  const slide = pptx.addSlide();
  addBase(slide, "已完成能力", "已完成部分集中在数值处理与可追溯输出", 15);
  addLead(slide, "软件能稳定复现当前数值过程；科研解释仍需外部实验信息。", {
    fontSize: 18.2,
  });
  const groups = [
    [
      "输入与数据",
      "已实现",
      "双通道只读输入\nSignalRecord 不可变\n内部计算使用 SI 单位",
    ],
    [
      "数值方法",
      "已实现",
      "STFT\n离散峰与亚频点精修\n无符号表观速度",
    ],
    [
      "运行与输出",
      "已实现",
      "双 profile 正式 workflow\nCSV / PNG / manifest\n原始数据 SHA-256",
    ],
    [
      "诊断",
      "初步实现",
      "谱背景与竞争峰对比度\n相邻帧连续性量\n相关频率局部证据",
    ],
  ];
  groups.forEach(([title, status, body], index) => {
    const x = 0.65 + index * 3.03;
    addShape(slide, S.rect, {
      x,
      y: 2.0,
      w: 2.78,
      h: 3.35,
      fill: { color: C.paper },
      line: { color: C.line, width: 0.65 },
    });
    addShape(slide, S.rect, {
      x,
      y: 2.0,
      w: 2.78,
      h: 0.08,
      fill: { color: index === 3 ? C.gray : C.red },
      line: { color: index === 3 ? C.gray : C.red, transparency: 100 },
    });
    addRichText(slide, title, {
      x: x + 0.22,
      y: 2.38,
      w: 2.34,
      h: 0.34,
      fontSize: 18,
      bold: true,
      color: C.ink,
      align: "center",
    });
    addTag(slide, status, x + 0.76, 2.88, 1.26, {
      fill: index === 3 ? C.light : C.redPale,
      line: index === 3 ? C.line : C.redSoft,
      color: index === 3 ? C.muted : C.red,
      fontSize: 12.5,
    });
    addRichText(slide, body, {
      x: x + 0.26,
      y: 3.5,
      w: 2.26,
      h: 1.45,
      fontSize: 13.5,
      color: C.muted,
      breakLine: true,
      valign: "top",
      align: "center",
      fit: "shrink",
    });
  });
  addShape(slide, S.rect, {
    x: 0.65,
    y: 5.72,
    w: 11.87,
    h: 0.86,
    fill: { color: C.redPale },
    line: { color: C.redSoft, width: 0.65 },
  });
  addRichText(slide, "尚未完成：GUI｜LiF / 折射率 / 入射角修正｜有符号速度｜经实验验证的分支与可信判据", {
    x: 0.95,
    y: 5.97,
    w: 11.3,
    h: 0.32,
    fontSize: 15.2,
    bold: true,
    color: C.red,
    align: "center",
    fit: "shrink",
  });
  addFooter(slide, "来源：当前源代码、README、pyproject.toml、PROJECT_STRUCTURE_AND_PARAMETER_AUDIT.md §17");
  addNotes(slide, notes[15]);
}

// Slide 16 — current problems
{
  const slide = pptx.addSlide();
  addBase(slide, "当前问题", "当前问题集中在物理校正与可信判据", 16);
  addLead(slide, "诊断量已经可见，但还没有经实验验证的“可用 / 不可用”规则。", {
    fontSize: 18.2,
  });
  addFigure(
    slide,
    ASSET("real", "two_channel_quality.png"),
    0.62,
    1.86,
    7.65,
    4.82,
    "两通道逐帧谱对比度；只描述频谱结构，不是 SNR 或准确度",
    "两个通道的逐帧谱质量诊断对比"
  );
  const problems = [
    ["波长", "1.55 µm 尚未由实验记录确认"],
    ["物理修正", "LiF、折射率、入射角与不确定度模型未接入"],
    ["判据", "谱对比度和连续性不等于分支正确或可信度"],
    ["历史材料", "旧软件来源、参数和处理步骤仍待确认"],
  ];
  problems.forEach(([title, detail], index) => {
    const y = 1.98 + index * 1.18;
    addPlainText(slide, String(index + 1).padStart(2, "0"), {
      x: 8.62,
      y,
      w: 0.42,
      h: 0.26,
      fontFace: EN,
      fontSize: 15,
      bold: true,
      color: C.red,
    });
    addRichText(slide, title, {
      x: 9.18,
      y,
      w: 2.7,
      h: 0.26,
      fontSize: 16,
      bold: true,
    });
    addRichText(slide, detail, {
      x: 9.18,
      y: y + 0.34,
      w: 2.98,
      h: 0.47,
      fontSize: 12.4,
      color: C.muted,
      valign: "top",
      fit: "shrink",
    });
    addLine(slide, 9.18, y + 0.94, 2.98, 0, C.line, 0.55);
  });
  addFooter(slide, "来源：balanced_diagnostic/two_channel_spectral_quality_comparison.png；当前配置与源代码");
  addNotes(slide, notes[16]);
}

// Slide 17 — next steps
{
  const slide = pptx.addSlide();
  addBase(slide, "下一步", "按证据依赖顺序推进", 17);
  addLead(slide, "先确认实验元数据和判据，再实现物理修正，最后完善界面与部署。", {
    fontSize: 18.3,
  });
  const steps = [
    ["固化实验元数据", "波长、窗口材料、几何条件、时间基准"],
    ["建立复核记录", "多数据集人工复核与分支判据"],
    ["实现物理修正", "公式、单位、参数来源与不确定度"],
    ["验证失效案例", "双通道、双 profile、重复性与异常数据"],
    ["接入 GUI 与部署", "判据稳定后再做界面、打包和用户测试"],
  ];
  addLine(slide, 1.12, 3.22, 10.72, 0, C.line, 1.0);
  steps.forEach(([title, detail], index) => {
    const x = 0.68 + index * 2.42;
    addShape(slide, S.rect, {
      x: x + 0.64,
      y: 3.11,
      w: 0.18,
      h: 0.22,
      fill: { color: index === 4 ? C.gray : C.red },
      line: { color: index === 4 ? C.gray : C.red, transparency: 100 },
    });
    addPlainText(slide, String(index + 1).padStart(2, "0"), {
      x,
      y: 2.28,
      w: 0.55,
      h: 0.34,
      fontFace: EN,
      fontSize: 18,
      bold: true,
      color: index === 4 ? C.gray : C.red,
      align: "center",
    });
    addRichText(slide, title, {
      x: x - 0.15,
      y: 3.63,
      w: 2.15,
      h: 0.36,
      fontSize: 16,
      bold: true,
      color: C.ink,
      align: "center",
      fit: "shrink",
    });
    addRichText(slide, detail, {
      x: x - 0.15,
      y: 4.16,
      w: 2.15,
      h: 0.88,
      fontSize: 12.4,
      color: C.muted,
      align: "center",
      valign: "top",
      breakLine: true,
      fit: "shrink",
    });
  });
  addShape(slide, S.rect, {
    x: 1.14,
    y: 5.62,
    w: 10.68,
    h: 0.86,
    fill: { color: C.paper },
    line: { color: C.line, width: 0.65 },
  });
  addRichText(slide, "依赖关系：实验元数据 → 判据 → 修正模型 → 多数据验证 → GUI / 部署", {
    x: 1.42,
    y: 5.88,
    w: 10.12,
    h: 0.32,
    fontSize: 15.2,
    bold: true,
    color: C.red,
    align: "center",
    fit: "shrink",
  });
  addFooter(slide, "先证据，后物理修正；判据稳定后再扩大软件交付范围。");
  addNotes(slide, notes[17]);
}

// Slide 18 — summary
{
  const slide = pptx.addSlide();
  slide.background = { color: C.bg };
  addShape(slide, S.rect, {
    x: 0,
    y: 0,
    w: 0.52,
    h: 7.5,
    fill: { color: C.red },
    line: { color: C.red, transparency: 100 },
  });
  addRichText(slide, "总结", {
    x: 0.92,
    y: 0.66,
    w: 1.0,
    h: 0.3,
    fontSize: 14,
    bold: true,
    color: C.red,
    charSpacing: 1.4,
  });
  addRichText(slide, "已经能复现表观速度；\n科研解释仍需验证。", {
    x: 0.92,
    y: 1.18,
    w: 9.7,
    h: 1.28,
    fontSize: 32,
    bold: true,
    color: C.ink,
    breakLine: true,
    valign: "top",
    fit: "shrink",
  });
  const summary = [
    [
      "已有",
      "真实双通道输入、正式 STFT / 脊线 / 亚频点精修、表观速度与可追溯输出",
    ],
    [
      "边界",
      "临时波长、无 LiF 修正、无符号、无自动通道选择与物理可信判据",
    ],
    [
      "下一步",
      "先补实验元数据与判据，再推进修正模型和 GUI",
    ],
  ];
  summary.forEach(([label, text], index) => {
    const y = 3.06 + index * 1.05;
    addRichText(slide, label, {
      x: 1.0,
      y,
      w: 0.9,
      h: 0.3,
      fontSize: 16,
      bold: true,
      color: index === 1 ? C.muted : C.red,
    });
    addLine(slide, 2.04, y + 0.16, 0.46, 0, index === 1 ? C.gray : C.red, 1.0);
    addRichText(slide, text, {
      x: 2.7,
      y: y - 0.03,
      w: 8.9,
      h: 0.46,
      fontSize: 18,
      bold: index !== 1,
      color: C.ink,
      fit: "shrink",
    });
  });
  addLine(slide, 0.92, 6.45, 11.1, 0, C.line, 0.8);
  addRichText(slide, "请老师批评指正", {
    x: 0.92,
    y: 6.72,
    w: 3.2,
    h: 0.36,
    fontSize: 18,
    color: C.red,
  });
  addPlainText(slide, "DPS Studio · 2026.07.26", {
    x: 9.36,
    y: 6.73,
    w: 2.65,
    h: 0.3,
    fontFace: EN,
    fontSize: 12,
    color: C.muted,
    align: "right",
  });
  addNotes(slide, notes[18]);
}

function warnIfSlideElementsOutOfBounds(slide, number) {
  const objects = slide._slideObjects || [];
  const problems = [];
  objects.forEach((object, index) => {
    const options = object.options || object._options || {};
    const values = ["x", "y", "w", "h"].map((key) => Number(options[key]));
    if (values.some((value) => !Number.isFinite(value))) {
      return;
    }
    const [x, y, w, h] = values;
    if (x < -0.001 || y < -0.001 || x + w > 13.334 || y + h > 7.501) {
      problems.push({ index, x, y, w, h });
    }
  });
  if (problems.length) {
    process.stderr.write(
      `[layout] slide ${number}: out-of-bounds ${JSON.stringify(problems)}\n`
    );
  }
}

function warnIfSlideHasOverlaps(slide, number) {
  const objects = slide._slideObjects || [];
  const boxes = objects
    .map((object, index) => {
      const options = object.options || object._options || {};
      const x = Number(options.x);
      const y = Number(options.y);
      const w = Number(options.w);
      const h = Number(options.h);
      if (![x, y, w, h].every(Number.isFinite)) {
        return null;
      }
      return { index, x, y, w, h, type: object._type || object.type || "" };
    })
    .filter(Boolean);
  let count = 0;
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      const overlapW = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const overlapH = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (overlapW <= 0.02 || overlapH <= 0.02) {
        continue;
      }
      const area = overlapW * overlapH;
      const smaller = Math.min(a.w * a.h, b.w * b.h);
      if (smaller > 0 && area / smaller > 0.92) {
        count += 1;
      }
    }
  }
  if (count > 0) {
    process.stderr.write(
      `[layout] slide ${number}: ${count} intentional/possible full-overlay pairs; inspect render.\n`
    );
  }
}

if (process.env.SLIDE_LIMIT) {
  const limit = Number(process.env.SLIDE_LIMIT);
  if (Number.isInteger(limit) && limit > 0) {
    pptx._slides = pptx._slides.slice(0, limit);
  }
}

pptx._slides.forEach((slide, index) => {
  warnIfSlideHasOverlaps(slide, index + 1);
  warnIfSlideElementsOutOfBounds(slide, index + 1);
});

pptx
  .writeFile({ fileName: OUTPUT })
  .then(() => {
    process.stdout.write(`Wrote editable deck: ${OUTPUT}\n`);
  })
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
