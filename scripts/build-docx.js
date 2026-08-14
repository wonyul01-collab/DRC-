const fs = require('fs');
const path = require('path');
const D = require('docx');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  PageBreak, Footer, PageNumber, TableOfContents, ExternalHyperlink,
  LevelFormat, convertMillimetersToTwip,
} = D;

const SRC = process.argv[2];
const OUT = process.argv[3];

const FONT = 'Malgun Gothic';
const MONO = 'Consolas';
const ACCENT = '1F4E79';   // deep blue
const ACCENT2 = '2E74B5';
const HEADER_BG = 'DCE6F1';
const ZEBRA_BG = 'F5F8FC';
const RULE = 'BFBFBF';

// A4 portrait, 20mm side margins
const MARGIN = convertMillimetersToTwip(20);
const PAGE_W = 11906;
const USABLE = PAGE_W - MARGIN * 2;

// ---------------------------------------------------------------- inline
function parseInline(text, opts = {}) {
  const base = { font: FONT, size: opts.size || 20, color: opts.color, bold: opts.bold };
  const runs = [];
  // tokenise on **bold**, `code`, [label](url)
  const re = /(\*\*[^*]+\*\*)|(`[^`]+`)|(\[[^\]]+\]\([^)]+\))/g;
  let last = 0, m;
  const push = (t, extra = {}) => {
    if (!t) return;
    runs.push(new TextRun({ ...base, ...extra, text: t }));
  };
  while ((m = re.exec(text)) !== null) {
    push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith('**')) {
      push(tok.slice(2, -2), { bold: true });
    } else if (tok.startsWith('`')) {
      push(tok.slice(1, -1), { font: MONO, size: (opts.size || 20) - 2, color: 'A31515' });
    } else {
      const mm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok);
      runs.push(new ExternalHyperlink({
        link: mm[2],
        children: [new TextRun({ ...base, text: mm[1], color: ACCENT2, underline: {} })],
      }));
    }
    last = m.index + tok.length;
  }
  push(text.slice(last));
  return runs.length ? runs : [new TextRun({ ...base, text: '' })];
}

// ---------------------------------------------------------------- tables
function columnWeights(rows) {
  const n = rows[0].length;
  const w = new Array(n).fill(1);
  for (let c = 0; c < n; c++) {
    let max = 0;
    for (const r of rows) {
      const len = (r[c] || '').replace(/\*\*|`/g, '').length;
      if (len > max) max = len;
    }
    w[c] = Math.max(3, Math.min(max, 46));
  }
  return w;
}

function buildTable(header, body) {
  const all = [header, ...body];
  const weights = columnWeights(all);
  const total = weights.reduce((a, b) => a + b, 0);
  const widths = weights.map(x => Math.floor(USABLE * x / total));
  widths[widths.length - 1] += USABLE - widths.reduce((a, b) => a + b, 0);

  const cell = (txt, i, isHead, rowIdx) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    shading: {
      type: ShadingType.CLEAR, fill: isHead ? HEADER_BG : (rowIdx % 2 ? ZEBRA_BG : 'FFFFFF'), color: 'auto',
    },
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({
      spacing: { before: 20, after: 20 },
      alignment: isHead ? AlignmentType.CENTER : AlignmentType.LEFT,
      children: parseInline(txt || '', { size: 18, bold: isHead, color: isHead ? ACCENT : undefined }),
    })],
  });

  return new Table({
    columnWidths: widths,
    width: { size: USABLE, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: ACCENT2 },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: ACCENT2 },
      left: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: RULE },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: header.map((t, i) => cell(t, i, true, 0)),
      }),
      ...body.map((r, ri) => new TableRow({
        children: widths.map((_, i) => cell(r[i], i, false, ri)),
      })),
    ],
  });
}

// ---------------------------------------------------------------- parser
function splitRow(line) {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|')) s = s.slice(0, -1);
  return s.split('|').map(c => c.trim());
}

const md = fs.readFileSync(SRC, 'utf8').split('\n');
const body = [];
const spacer = (after = 120) => new Paragraph({ spacing: { after }, children: [] });

let i = 0;
while (i < md.length) {
  const line = md[i];
  const t = line.trim();

  // ---- skip the front-matter blockquote block and the top H1 (cover handles it)
  if (t === '') { i++; continue; }

  // ---- horizontal rule
  if (/^-{3,}$/.test(t)) {
    body.push(new Paragraph({
      spacing: { before: 160, after: 160 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 1 } },
      children: [],
    }));
    i++; continue;
  }

  // ---- code fence
  if (t.startsWith('```')) {
    i++;
    const lines = [];
    while (i < md.length && !md[i].trim().startsWith('```')) { lines.push(md[i]); i++; }
    i++;
    const paras = lines.map((l, idx) => new Paragraph({
      spacing: { before: idx === 0 ? 60 : 0, after: idx === lines.length - 1 ? 60 : 0, line: 240 },
      indent: { left: 200 },
      shading: { type: ShadingType.CLEAR, fill: 'F4F6F8', color: 'auto' },
      children: [new TextRun({ text: l || ' ', font: MONO, size: 16 })],
    }));
    body.push(new Table({
      columnWidths: [USABLE],
      width: { size: USABLE, type: WidthType.DXA },
      borders: {
        top: { style: BorderStyle.SINGLE, size: 2, color: RULE },
        bottom: { style: BorderStyle.SINGLE, size: 2, color: RULE },
        left: { style: BorderStyle.SINGLE, size: 12, color: ACCENT2 },
        right: { style: BorderStyle.SINGLE, size: 2, color: RULE },
        insideHorizontal: { style: BorderStyle.NONE },
        insideVertical: { style: BorderStyle.NONE },
      },
      rows: [new TableRow({
        children: [new TableCell({
          width: { size: USABLE, type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill: 'F4F6F8', color: 'auto' },
          margins: { top: 100, bottom: 100, left: 140, right: 100 },
          children: paras.length ? paras : [new Paragraph({ children: [] })],
        })],
      })],
    }));
    body.push(spacer(160));
    continue;
  }

  // ---- table
  if (t.startsWith('|') && i + 1 < md.length && /^\|[\s:|-]+\|$/.test(md[i + 1].trim())) {
    const header = splitRow(md[i]);
    i += 2;
    const rows = [];
    while (i < md.length && md[i].trim().startsWith('|')) { rows.push(splitRow(md[i])); i++; }
    body.push(buildTable(header, rows));
    body.push(spacer(180));
    continue;
  }

  // ---- headings
  const h = /^(#{1,4})\s+(.*)$/.exec(t);
  if (h) {
    const lvl = h[1].length;
    const txt = h[2];
    if (lvl === 1) {
      // top-level document title is rendered on the cover page — skip the first one
      if (!body.length) { i++; continue; }
    }
    const cfg = {
      1: { heading: HeadingLevel.HEADING_1, size: 30, color: ACCENT, before: 360, after: 160, rule: true },
      2: { heading: HeadingLevel.HEADING_1, size: 26, color: ACCENT, before: 360, after: 140, rule: true },
      3: { heading: HeadingLevel.HEADING_2, size: 22, color: ACCENT2, before: 260, after: 100 },
      4: { heading: HeadingLevel.HEADING_3, size: 20, color: '333333', before: 200, after: 80 },
    }[lvl];
    body.push(new Paragraph({
      heading: cfg.heading,
      spacing: { before: cfg.before, after: cfg.after },
      ...(cfg.rule ? { border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT2, space: 4 } } } : {}),
      children: parseInline(txt, { size: cfg.size, bold: true, color: cfg.color }),
    }));
    i++; continue;
  }

  // ---- blockquote (callout box)
  if (t.startsWith('>')) {
    const lines = [];
    while (i < md.length && md[i].trim().startsWith('>')) {
      lines.push(md[i].trim().replace(/^>\s?/, ''));
      i++;
    }
    const paras = lines.filter(l => l !== '').map((l, idx, arr) => new Paragraph({
      spacing: { before: idx === 0 ? 40 : 60, after: idx === arr.length - 1 ? 40 : 0 },
      children: parseInline(l.replace(/^[-*]\s+/, '• '), { size: 19 }),
    }));
    body.push(new Table({
      columnWidths: [USABLE],
      width: { size: USABLE, type: WidthType.DXA },
      borders: {
        top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
        left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT2 },
        right: { style: BorderStyle.NONE },
        insideHorizontal: { style: BorderStyle.NONE }, insideVertical: { style: BorderStyle.NONE },
      },
      rows: [new TableRow({
        children: [new TableCell({
          width: { size: USABLE, type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill: 'EEF4FA', color: 'auto' },
          margins: { top: 120, bottom: 120, left: 180, right: 140 },
          children: paras.length ? paras : [new Paragraph({ children: [] })],
        })],
      })],
    }));
    body.push(spacer(180));
    continue;
  }

  // ---- checklist
  const chk = /^-\s+\[([ xX])\]\s+(.*)$/.exec(t);
  if (chk) {
    body.push(new Paragraph({
      spacing: { before: 30, after: 30 },
      indent: { left: 340, hanging: 240 },
      children: [
        new TextRun({ text: '☐  ', font: FONT, size: 20 }),
        ...parseInline(chk[2], { size: 20 }),
      ],
    }));
    i++; continue;
  }

  // ---- bullet
  const bul = /^[-*]\s+(.*)$/.exec(t);
  if (bul) {
    body.push(new Paragraph({
      numbering: { reference: 'bullets', level: 0 },
      spacing: { before: 30, after: 30 },
      children: parseInline(bul[1], { size: 20 }),
    }));
    i++; continue;
  }

  // ---- ordered
  const num = /^(\d+)\.\s+(.*)$/.exec(t);
  if (num) {
    body.push(new Paragraph({
      numbering: { reference: 'numbers', level: 0 },
      spacing: { before: 30, after: 30 },
      children: parseInline(num[2], { size: 20 }),
    }));
    i++; continue;
  }

  // ---- plain paragraph
  body.push(new Paragraph({
    spacing: { before: 60, after: 100, line: 300 },
    children: parseInline(t, { size: 20 }),
  }));
  i++;
}

// ---------------------------------------------------------------- cover
const coverLine = (text, opts) => new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: opts.spacing,
  children: [new TextRun({ font: FONT, text, size: opts.size, bold: opts.bold, color: opts.color })],
});

const cover = [
  new Paragraph({ spacing: { before: 2600 }, children: [] }),
  coverLine('벤치마킹 기술 분석 보고서', { size: 24, color: ACCENT2, bold: true, spacing: { after: 200 } }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: ACCENT, space: 8 } },
    children: [new TextRun({ font: FONT, text: 'Tytex SafeHip® 패드', size: 48, bold: true, color: ACCENT })],
  }),
  coverLine('심층 분석 및 벤치마킹 전략', { size: 36, bold: true, color: ACCENT, spacing: { before: 160, after: 900 } }),
  coverLine('소재 · 구조 · 성능 분석  |  특허 · IP 리스크 검토', { size: 22, color: '444444', spacing: { after: 100 } }),
  coverLine('분석기관 시험 의뢰 사양서  |  차별화 제품 개발 전략', { size: 22, color: '444444', spacing: { after: 1400 } }),
  coverLine('2026년 8월 14일', { size: 22, color: '444444', spacing: { after: 80 } }),
  coverLine('대외비 — 사내 및 지정 분석기관 한정 배포', { size: 18, color: 'A6A6A6', spacing: { after: 0 } }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({
    spacing: { after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT2, space: 4 } },
    children: [new TextRun({ font: FONT, text: '목  차', size: 30, bold: true, color: ACCENT })],
  }),
  new TableOfContents('목차', { hyperlink: true, headingStyleRange: '1-2' }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ---------------------------------------------------------------- document
const doc = new Document({
  creator: 'DRC',
  title: 'Tytex SafeHip 패드 심층 분석 및 벤치마킹 전략',
  description: 'Tytex SafeHip 패드 소재·구조·성능 분석, 특허/IP 리스크, 분석기관 의뢰 사양서, 제품 차별화 전략',
  features: { updateFields: true },
  styles: {
    default: {
      document: { run: { font: FONT, size: 20 }, paragraph: { spacing: { line: 300 } } },
      heading1: { run: { font: FONT, bold: true, color: ACCENT } },
      heading2: { run: { font: FONT, bold: true, color: ACCENT2 } },
      heading3: { run: { font: FONT, bold: true, color: '333333' } },
    },
  },
  numbering: {
    config: [
      {
        reference: 'bullets',
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 400, hanging: 240 } }, run: { font: FONT } },
        }],
      },
      {
        reference: 'numbers',
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 400, hanging: 260 } }, run: { font: FONT } },
        }],
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_W, height: 16838 },
        margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN },
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 120 },
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: RULE, space: 6 } },
          children: [
            new TextRun({ font: FONT, size: 16, color: '808080', text: 'Tytex SafeHip 패드 분석 보고서   |   대외비   |   ' }),
            new TextRun({ font: FONT, size: 16, color: '808080', children: [PageNumber.CURRENT] }),
            new TextRun({ font: FONT, size: 16, color: '808080', text: ' / ' }),
            new TextRun({ font: FONT, size: 16, color: '808080', children: [PageNumber.TOTAL_PAGES] }),
          ],
        })],
      }),
    },
    children: [...cover, ...body],
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(OUT, buf);
  console.log('wrote', OUT, (buf.length / 1024).toFixed(1) + ' KB');
});
