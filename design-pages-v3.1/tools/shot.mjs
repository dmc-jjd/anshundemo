// v3.1 截图 + 就地取证：headless Chrome + CDP 真实渲染（无 Playwright / 无 CDN / 无外链）
// 用法: node tools/shot.mjs
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SHOTS = path.join(ROOT, "shots");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9341;

const PAGES = [
  "01-工作台.html",
  "02-模板确认.html",
  "03-数据处理.html",
  "04-事件组审核.html",
  "05-报告撰写.html",
  "06-数据总览.html",
  "07-终稿审核.html",
];

const VIEWPORTS = [
  { w: 1440, h: 900, tag: "", only: null },
  { w: 1024, h: 768, tag: "-1024", only: ["01-工作台.html", "02-模板确认.html"] },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Map();
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      } else if (msg.method) {
        (this.listeners.get(msg.method) || []).forEach((fn) => fn(msg.params));
        this.listeners.delete(msg.method);
      }
    });
  }
  static async connect(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => {
      ws.addEventListener("open", res, { once: true });
      ws.addEventListener("error", rej, { once: true });
    });
    return new CDP(ws);
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  once(method) {
    return new Promise((resolve) => {
      const arr = this.listeners.get(method) || [];
      arr.push(resolve);
      this.listeners.set(method, arr);
    });
  }
}

async function waitForEndpoint() {
  for (let i = 0; i < 160; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return await r.json();
    } catch {}
    await sleep(120);
  }
  throw new Error("chrome devtools endpoint not ready");
}

// ---- in-page audit（真实 DOM 取证）----
const AUDIT = `
(() => {
  const out = {};
  out.title = document.title;
  out.scrollH = document.documentElement.scrollHeight;
  out.scrollW = document.documentElement.scrollWidth;

  // tab 序列与选中态
  out.tabs = [...document.querySelectorAll('.stage-progress .stage')].map(el => ({
    text: el.innerText.replace(/\\s+/g, ' ').trim(),
    state: el.getAttribute('data-state'),
    task: el.getAttribute('data-task'),
    hasDot: !!el.querySelector('.dot'),
    bg: getComputedStyle(el).backgroundColor,
    radius: getComputedStyle(el).borderTopLeftRadius,
    shadow: getComputedStyle(el).boxShadow,
    topLine: getComputedStyle(el, '::before').backgroundColor,
    topLineH: getComputedStyle(el, '::before').height,
    edge: getComputedStyle(el).borderTopWidth + ' ' + getComputedStyle(el).borderTopColor,
  }));
  out.currentTab = (out.tabs.find(t => t.state === 'current') || {}).text || null;

  // 溢出/裁切检查
  const sel = ['.main', '.body', '.card', '.card-body', '.sheet', '.sheet-wrap', '.draft', '.canvas', '.leaf'];
  out.clipped = [];
  document.querySelectorAll(sel.join(',')).forEach(el => {
    const sh = el.scrollHeight, ch = el.clientHeight;
    if (ch > 0 && sh > ch + 1) {
      out.clipped.push({ sel: el.className.split(' ')[0], sh, ch, over: sh - ch });
    }
  });

  // 文档式模板取证
  out.docSections = [...document.querySelectorAll('.doc-sec')].map(e => e.textContent.trim());
  out.fields = document.querySelectorAll('.fld').length;
  out.fieldSample = [...document.querySelectorAll('.fld')].slice(0, 3).map(e => e.textContent.trim());
  const sheet = document.querySelector('.sheet');
  if (sheet) {
    out.sheet = { w: Math.round(sheet.getBoundingClientRect().width), h: Math.round(sheet.getBoundingClientRect().height), sh: sheet.scrollHeight, ch: sheet.clientHeight };
  }
  out.fontFamilies = [...new Set([...document.querySelectorAll('.page *')].map(e => getComputedStyle(e).fontFamily))];

  const txt = document.body.innerText;
  const banned = ['提示', '说明：', '点击', '如图', '注：', '可选'];
  out.bannedHits = banned.filter(w => txt.includes(w));
  out.hasSkeleton = txt.includes('报告骨架');
  out.hasStatBadge = /\\d+\\s*动态/.test(txt);

  out.h1 = document.querySelectorAll('h1').length;
  out.primary = document.querySelectorAll('.btn-primary').length;
  out.tables = document.querySelectorAll('table').length;
  return out;
})()
`;

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  const profile = path.join(process.env.TEMP || ".", "dsh-cdp-v31-" + Date.now());

  const chrome = spawn(CHROME, [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--force-color-profile=srgb",
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    "--window-size=1440,900",
    "about:blank",
  ], { stdio: "ignore" });

  try {
    await waitForEndpoint();
    const created = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" })).json();
    const page = await CDP.connect(created.webSocketDebuggerUrl);
    await page.send("Page.enable");
    await page.send("Runtime.enable");

    const report = [];
    const audits = [];

    for (const vp of VIEWPORTS) {
      for (const file of PAGES) {
        if (vp.only && !vp.only.includes(file)) continue;
        const url = pathToFileURL(path.join(ROOT, file)).href;
        await page.send("Emulation.setDeviceMetricsOverride", {
          width: vp.w, height: vp.h, deviceScaleFactor: 1, mobile: false,
        });
        const loaded = page.once("Page.loadEventFired");
        await page.send("Page.navigate", { url });
        await loaded;
        await page.send("Runtime.evaluate", { expression: "document.fonts.ready" });
        await sleep(340);

        const m = await page.send("Runtime.evaluate", { expression: AUDIT, returnByValue: true });
        const audit = m.result.value;

        const shot = await page.send("Page.captureScreenshot", {
          format: "png", captureBeyondViewport: false, fromSurface: true,
        });
        const out = path.join(SHOTS, file.replace(/\.html$/, vp.tag + ".png"));
        const buf = Buffer.from(shot.data, "base64");
        fs.writeFileSync(out, buf);

        report.push({
          file: path.basename(out),
          viewport: `${vp.w}x${vp.h}`,
          bytes: buf.length,
          kb: +(buf.length / 1024).toFixed(1),
          currentTab: audit.currentTab,
          clipped: audit.clipped,
        });
        if (vp.tag === "") audits.push({ file, ...audit });
        const flag = audit.clipped.length ? "CLIP" : "ok  ";
        console.log(
          `${flag} ${path.basename(out)}  tab=${audit.currentTab}  fld=${audit.fields}  ` +
          `clip=${audit.clipped.length}  banned=${audit.bannedHits.join("|") || "-"}`
        );
        if (audit.clipped.length) console.log("     " + JSON.stringify(audit.clipped));
      }
    }

    fs.writeFileSync(path.join(ROOT, "shots-report.json"), JSON.stringify(report, null, 2));
    fs.writeFileSync(path.join(ROOT, "audit-report.json"), JSON.stringify(audits, null, 2));
    console.log("done");
  } finally {
    chrome.kill();
    await sleep(200);
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch {}
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
