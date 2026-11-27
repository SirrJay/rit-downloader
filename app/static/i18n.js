/* Rit Downloader - translations.
   English text is the key. Each language file (static/i18n/xx.json) maps English -> translation.
   Missing entries fall back to English, so a partial translation never breaks the UI. */
"use strict";
const LANGS = [
  ["en", "English"], ["fr", "Français"], ["es", "Español"], ["pt", "Português"], ["de", "Deutsch"],
  ["id", "Bahasa Indonesia"], ["ru", "Русский"], ["sw", "Kiswahili"], ["ha", "Hausa"], ["yo", "Yorùbá"],
  ["ar", "العربية"], ["zh", "中文"], ["hi", "हिन्दी"],
];
const RTL = new Set(["ar"]);
const I18N = { lang: "en", dict: {} };

function t(s, vars) {
  let r = I18N.dict[s];
  if (r === undefined || r === "") r = s;
  if (vars) r = r.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? vars[k] : m));
  return r;
}

function detectLang(serverLang) {
  const codes = LANGS.map((l) => l[0]);
  const saved = serverLang || localStorage.getItem("rit.lang");
  if (saved && codes.includes(saved)) return saved;
  for (const l of navigator.languages || [navigator.language || "en"]) {
    const c = String(l).toLowerCase().split("-")[0];
    if (codes.includes(c)) return c;
  }
  return "en";
}

// Elements whose content is rendered by app.js with t() - the DOM walker leaves them alone.
const I18N_SKIP = "script,style,code,#plList,#miniPlayer .mp-txt,#results,#jobs,#dlBanners,#dlChannels,#fmtBody,#dlStats,#selInfo,#sysinfo,#drives,#rTitle,#rStatus,#toasts,#dlDir,#appv,#ytv,#ffv,#updateBanner,[data-no-i18n]";

function translateDOM(root = document.body) {
  // 1. blocks with inline markup are translated as a whole
  root.querySelectorAll("[data-i18n-html]").forEach((el) => {
    if (el.__en === undefined) el.__en = el.innerHTML.trim().replace(/\s+/g, " ");
    el.innerHTML = t(el.__en);
  });
  // 2. plain text nodes
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      const p = n.parentElement;
      if (!p || p.closest(I18N_SKIP) || p.closest("[data-i18n-html]")) return NodeFilter.FILTER_REJECT;
      if (n.__en === undefined && !/[A-Za-z]/.test(n.nodeValue)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) {
    if (n.__en === undefined) {
      const m = n.nodeValue.match(/^(\s*)([\s\S]*?)(\s*)$/);
      n.__pre = m[1]; n.__en = m[2].replace(/\s+/g, " "); n.__post = m[3];
    }
    n.nodeValue = n.__pre + t(n.__en) + n.__post;
  }
  // 3. attributes
  root.querySelectorAll("[placeholder],[title]").forEach((el) => {
    if (el.closest(I18N_SKIP)) return;
    el.__enAttr = el.__enAttr || {};
    for (const a of ["placeholder", "title"]) {
      if (!el.hasAttribute(a)) continue;
      if (el.__enAttr[a] === undefined) el.__enAttr[a] = el.getAttribute(a);
      el.setAttribute(a, t(el.__enAttr[a]));
    }
  });
}

async function setLang(code, persist = true) {
  if (code !== "en") {
    try {
      const r = await fetch(`/static/i18n/${code}.json`);
      I18N.dict = r.ok ? await r.json() : {};
    } catch { I18N.dict = {}; }
  } else I18N.dict = {};
  I18N.lang = code;
  document.documentElement.lang = code;
  document.documentElement.dir = RTL.has(code) ? "rtl" : "ltr";
  if (persist) localStorage.setItem("rit.lang", code);
  translateDOM(document.body);
  document.querySelectorAll("select.langsel").forEach((s) => { s.value = code; });
  document.dispatchEvent(new CustomEvent("langchange"));
}

function langOptions() {
  return LANGS.map(([c, n]) => `<option value="${c}">${n}</option>`).join("");
}
