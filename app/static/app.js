/* Rit Downloader front-end */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = {
  settings: {}, sys: {}, kind: "search",
  entries: [], byId: new Map(), sel: new Set(), shown: [],
  browseId: null, since: 0, loading: false, req: null, title: "", group: "",
  history: [], lastIdx: null, view: "grid", renderedCount: 0,
};

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch("/api/" + path, opt);
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && j.locked) { showAuth(); throw new Error(t("The app is locked")); }
  if (!r.ok) { const e = new Error(j.error || r.statusText); e.data = j; throw e; }
  return j;
}

function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "bad" ? 7000 : 3200);
}

/* ---------------------------------------------------------------- formatting */
const fmtDur = (s) => {
  if (!s && s !== 0) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0");
};
const fmtLong = (s) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? t("{h} h {m} min", { h, m }) : t("{m} min", { m });
};
const fmtNum = (n) => (n || n === 0 ? new Intl.NumberFormat(I18N.lang, { notation: "compact", maximumFractionDigits: 1 }).format(n) : "");
const fmtDate = (d) => {
  if (!d || d.length !== 8) return "";
  try {
    return new Intl.DateTimeFormat(I18N.lang, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
      .format(new Date(Date.UTC(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6))));
  } catch { return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}`; }
};
const fmtBytes = (b) => {
  if (!b) return "";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < 4) { b /= 1024; i++; }
  return b.toFixed(b < 10 && i > 1 ? 1 : 0) + " " + u[i];
};

/* ---------------------------------------------------------------- settings */
function applySettings() {
  const s = S.settings;
  document.documentElement.dataset.theme = s.theme || "dark";
  $$("[data-set]").forEach((el) => {
    const v = s[el.dataset.set];
    if (el.type === "checkbox") el.checked = !!v;
    else if (v !== undefined && v !== null) el.value = String(v);
  });
  $$("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === s.mode));
  $("#videoOpts").classList.toggle("hidden", s.mode !== "video");
  $("#audioOpts").classList.toggle("hidden", s.mode !== "audio");
  $("#dlDir").textContent = s.download_dir;
  $("#cookieSource").value = s.cookies_file ? "file" : (s.cookies_browser || "");
  $("#cookieFileRow").classList.toggle("hidden", $("#cookieSource").value !== "file");
  $("#cookieFilePath").textContent = s.cookies_file || t("No file chosen");
  renderDrives();
  updateSelInfo();
  if (S.lastMode !== s.mode) { S.lastMode = s.mode; updateMarks(); }
}

let saveT;
async function saveSetting(changes, quiet) {
  Object.assign(S.settings, changes);
  applySettings();
  clearTimeout(saveT);
  saveT = setTimeout(async () => {
    try { S.settings = await api("settings", changes); if (!quiet) toast(t("Saved"), "ok"); } catch (e) { toast(t("Couldn't save settings:") + " " + e.message, "bad"); }
  }, 150);
}

document.addEventListener("change", (ev) => {
  const el = ev.target.closest("[data-set]");
  if (!el) return;
  let v = el.type === "checkbox" ? el.checked : el.value;
  if (el.dataset.num !== undefined) v = Number(v);
  if (el.dataset.bool !== undefined) v = v === "true";
  const inBar = !!el.closest("#actionbar");
  saveSetting({ [el.dataset.set]: v }, inBar);
});
$("#modeSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (b) saveSetting({ mode: b.dataset.mode }, true);
});

/* ---------------------------------------------------------------- system info */
async function refreshSystem() {
  try {
    S.sys = await api("system");
    const free = S.sys.free_gb;
    const drive = (S.settings.download_dir || "").slice(0, 3);
    $("#sysinfo").innerHTML = free == null ? "" :
      `<svg class="ico" viewBox="0 0 24 24"><path d="M22 12H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>
       <span class="${free < 10 ? "warn" : ""}">${esc(drive)} &middot; ${esc(t("{n} GB free", { n: free }))}</span>`;
    $("#ytv").textContent = S.sys.ytdlp;
    $("#appv").textContent = S.sys.version || "";
    $("#ffv").textContent = S.sys.ffmpeg ? t("Installed") : t("Missing (needed for MP3, merging HD and conversion)");
    $("#ffBtn").classList.toggle("hidden", !!S.sys.ffmpeg);
    renderBanners();
    renderDrives();
    updateSelInfo();
  } catch { /* server restarting */ }
}

function renderDrives() {
  const el = $("#drives"); if (!el || !S.sys.drives) return;
  const cur = (S.settings.download_dir || "").slice(0, 3).toUpperCase();
  el.innerHTML = S.sys.drives.map((d) => {
    const usedPct = Math.round(100 * (1 - d.free_gb / d.total_gb));
    return `<button class="drive ${d.drive.toUpperCase() === cur ? "on" : ""}" data-drive="${esc(d.drive)}" title="${esc(t("Save to {path}", { path: d.drive + "Rit Downloads" }))}">
      <b>${esc(d.drive)}</b><small>${esc(t("{free} GB free of {total}", { free: d.free_gb, total: Math.round(d.total_gb) }))}</small><i><u style="width:${usedPct}%"></u></i></button>`;
  }).join("");
}
$("#drives").addEventListener("click", (e) => {
  const b = e.target.closest("[data-drive]"); if (!b) return;
  saveSetting({ download_dir: b.dataset.drive + "Rit Downloads" }).then(() => setTimeout(refreshSystem, 400));
});

/* ---------------------------------------------------------------- tabs */
function showView(v) {
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  $$(".view").forEach((s) => s.classList.toggle("on", s.id === "view-" + v));
  document.body.classList.toggle("no-actions", v !== "browse");
  if (v === "downloads") pollJobs();
  if (v === "settings") refreshSystem();
  if (v === "library") loadLibrary();
}
$("#tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) showView(b.dataset.view); });

/* ---------------------------------------------------------------- search */
const PLACEHOLDER = {
  search: "Search for a preacher, a topic or a title",
  channels: "Type a person's or ministry's name, e.g. a pastor or a church",
  playlists: "Search playlists, e.g. a sermon series",
  url: "Paste a link to a channel, playlist or video from YouTube, Facebook, TikTok...",
};
function setKind(k, focus = true) {
  S.kind = k;
  $$("#kindSeg button").forEach((b) => b.classList.toggle("on", b.dataset.kind === k));
  $("#q").placeholder = t(PLACEHOLDER[k]);
  $("#urlOpts").classList.toggle("hidden", k !== "url");
  $("#platform").disabled = k !== "search";
  if (k !== "search") $("#platform").value = "youtube";
  $("#limit").disabled = k === "url";
  $("#go").textContent = k === "url" ? t("Load") : t("Search");
  if (focus) $("#q").focus();
}
$("#kindSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setKind(b.dataset.kind); });
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
$("#q").addEventListener("paste", () => setTimeout(() => {
  const v = $("#q").value.trim();
  if (/^https?:\/\//i.test(v) && S.kind !== "url") setKind("url");
}, 0));
$("#go").addEventListener("click", doSearch);

function urlTabs() { return $$("#urlOpts input:checked").map((i) => i.value); }

function doSearch() {
  let q = $("#q").value.trim();
  if (!q) { $("#q").focus(); return; }
  let kind = S.kind;
  if (/^https?:\/\//i.test(q) || /^(www\.)?[\w-]+\.(com|be|tv|net|org)\//i.test(q)) {
    kind = "url"; if (!/^https?:/i.test(q)) q = "https://" + q;
  }
  const req = { kind, query: q, platform: $("#platform").value, limit: +$("#limit").value };
  if (kind === "url") req.tabs = urlTabs().length ? urlTabs() : ["videos"];
  startBrowse(req, true);
}

function snapshotCurrent() {
  if (!S.req) return null;
  return { req: S.req, entries: S.entries.slice(), title: S.title, group: S.group, channel: S.channel, scroll: $("main").scrollTop };
}

async function startBrowse(req, pushHistory) {
  if (pushHistory && S.req) {
    const snap = snapshotCurrent(); if (snap) S.history.push(snap);
    if (S.history.length > 15) S.history.shift();
  }
  if (S.browseId && S.loading) api(`browse/${S.browseId}/stop`, {}).catch(() => {});
  S.req = req; S.entries = []; S.byId.clear(); S.sel.clear(); S.since = 0; S.lastIdx = null; S.channel = null;
  renderChanBar();
  S.title = req.kind === "search" ? t('Results for "{q}"', { q: req.query }) : t("Loading..."); S.group = req.kind === "search" ? req.query : "";
  $("#filter").value = ""; $("#durFilter").value = ""; $("#sort").value = "";
  $("#hero").classList.add("hidden");
  $("#resultsHead").classList.remove("hidden");
  $("#backBtn").classList.toggle("hidden", !S.history.length);
  render(true);
  setLoading(true, t("Contacting the site..."));
  try {
    const { id } = await api("browse", req);
    S.browseId = id;
    pollBrowse(id);
  } catch (e) { setLoading(false); toast(e.message, "bad"); }
}

function setLoading(on, text) {
  S.loading = on;
  $("#loadingMore").classList.toggle("hidden", !on);
  $("#stopLoad").classList.toggle("hidden", !on);
  if (text) $("#loadingText").textContent = text;
  renderChanBar();
}

async function pollBrowse(id) {
  if (id !== S.browseId) return;
  let snap;
  try { snap = await api(`browse/${id}?since=${S.since}`); } catch (e) { setLoading(false); toast(e.message, "bad"); return; }
  if (id !== S.browseId) return;
  if (snap.entries.length) {
    for (const e of snap.entries) { if (!S.byId.has(e.id)) { S.byId.set(e.id, e); S.entries.push(e); } }
    S.since = snap.total;
    render(false);
  }
  if (snap.title && S.req.kind !== "search") {
    S.title = snap.title.replace(/ - (Videos|Live|Shorts|Home)$/i, "");
    S.group = S.req.kind === "url" ? S.title : S.group;
  }
  if (S.req.kind === "channels" || S.req.kind === "playlists") S.title = snap.title;
  if (snap.channel) { S.channel = snap.channel; }
  renderChanBar();
  $("#rTitle").textContent = S.title;
  $("#rTitle").title = S.title;
  const n = S.entries.length;
  if (snap.done) {
    setLoading(false);
    $("#rStatus").textContent = snap.error && !n ? t("Error") : countText(n);
    if (snap.error) toast(snap.error, "bad");
    if (!n && !snap.error) $("#results").innerHTML = `<div class="hero small"><h2>${esc(t("Nothing found"))}</h2><p class="muted">${t("Try different words, or choose <em>Channels &amp; people</em> to find the person's channel.")}</p></div>`;
  } else {
    $("#rStatus").textContent = t("{n} loaded", { n: n.toLocaleString() });
    $("#loadingText").textContent = n ? t("Loading more... {n} so far. Large channels can take a minute.", { n: n.toLocaleString() }) : t("Contacting the site...");
    setTimeout(() => pollBrowse(id), 700);
  }
}
$("#stopLoad").addEventListener("click", () => { if (S.browseId) api(`browse/${S.browseId}/stop`, {}); });
$("#backBtn").addEventListener("click", () => {
  const snap = S.history.pop(); if (!snap) return;
  if (S.browseId && S.loading) api(`browse/${S.browseId}/stop`, {}).catch(() => {});
  S.browseId = null; setLoading(false);
  S.req = snap.req; S.entries = snap.entries; S.byId = new Map(snap.entries.map((e) => [e.id, e]));
  S.title = snap.title; S.group = snap.group; S.sel.clear(); S.channel = snap.channel || null;
  renderChanBar();
  $("#rTitle").textContent = S.title;
  $("#rStatus").textContent = countText(S.entries.length);
  $("#backBtn").classList.toggle("hidden", !S.history.length);
  render(true);
  $("main").scrollTop = snap.scroll || 0;
});

const countText = (n) => (n === 1 ? t("1 item") : t("{n} items", { n: n.toLocaleString() }));

/* ---------------------------------------------------------------- filtering + rendering */
function computeShown() {
  const words = $("#filter").value.toLowerCase().split(/\s+/).filter(Boolean);
  const [lo, hi] = ($("#durFilter").value || "-").split("-").map((x) => (x === "" ? null : +x));
  const hideHave = $("#hideHave").checked;
  let list = S.entries.filter((e) => {
    if (hideHave && hasIt(e)) return false;
    if (words.length) {
      const hay = (e.title + " " + e.channel + " " + (e.date || "")).toLowerCase();
      if (!words.every((w) => hay.includes(w))) return false;
    }
    if (lo != null || hi != null) {
      if (e.kind !== "video") return false;
      const d = e.duration || 0;
      if (lo != null && d < lo) return false;
      if (hi != null && d >= hi) return false;
    }
    return true;
  });
  const by = $("#sort").value;
  const cmp = {
    new: (a, b) => (b.date || "").localeCompare(a.date || ""),
    old: (a, b) => (a.date || "99999999").localeCompare(b.date || "99999999"),
    long: (a, b) => (b.duration || 0) - (a.duration || 0),
    short: (a, b) => (a.duration || 1e9) - (b.duration || 1e9),
    views: (a, b) => (b.views || 0) - (a.views || 0),
    az: (a, b) => a.title.localeCompare(b.title),
  }[by];
  if (cmp) list = list.slice().sort(cmp);
  return list;
}
const isFiltered = () => $("#filter").value.trim() || $("#durFilter").value || $("#sort").value || $("#hideHave").checked;
const curMode = () => S.settings.mode || "video";
const hasIt = (e, mode = curMode()) => !!(e.dl && e.dl[mode]);

const ICON = {
  video: '<svg class="ico" viewBox="0 0 24 24"><rect x="2" y="5" width="15" height="14" rx="2"/><path d="m17 10 5-3v10l-5-3z"/></svg>',
  audio: '<svg class="ico" viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
  q: '<svg class="ico" viewBox="0 0 24 24"><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/></svg>',
  ext: '<svg class="ico" viewBox="0 0 24 24"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg>',
};

const MEDIA_EXT = new Set(["mp3", "m4a", "opus", "ogg", "oga", "flac", "wav", "aac", "mp4", "mkv", "webm", "mov", "m4v"]);
const fileExt = (p) => (String(p || "").split(/[\\/]/).pop().split(".").pop() || "").toLowerCase();
function fileCard(e, idx) {
  const sel = S.sel.has(e.id) ? " sel" : "";
  const ext = (e.ext || fileExt(e.title)).split(".").pop().slice(0, 6) || "file";
  return `<div class="item file${sel}" data-id="${esc(e.id)}" data-idx="${idx}">
    <div class="thumb" data-act="toggle"><span class="filebadge">${esc(ext)}</span><span class="tick">${ICON.check}</span>
      ${e.executable ? `<span class="exe" title="${esc(t("Programs can harm your computer. Only run software from websites you trust."))}">${esc(t("Program"))}</span>` : ""}
      ${e.size ? `<span class="dur">${esc(fmtBytes(e.size))}</span>` : ""}</div>
    <div class="body"><div class="title" title="${esc(e.url)}">${esc(e.title)}</div>
      ${e.text && e.text !== e.title ? `<div class="ftext">${esc(e.text)}</div>` : ""}
      <div class="meta"><span>${esc(e.host || "")}</span></div>
      <div class="acts">
        <button class="btn primary" data-act="dl-file"><svg class="ico" viewBox="0 0 24 24"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>${esc(t("Download file"))}</button>
        <button class="btn ghost" data-act="copy" title="${esc(t("Copy link"))}">${esc(t("Copy link"))}</button>
      </div></div></div>`;
}
function card(e, idx) {
  if (e.kind === "file") return fileCard(e, idx);
  const sel = S.sel.has(e.id) ? " sel" : "";
  const img = e.thumb ? `<img loading="lazy" src="${esc(e.thumb)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
  if (e.kind === "channel") {
    return `<div class="item channel" data-id="${esc(e.id)}" data-idx="${idx}">
      <div class="thumb" data-act="loadch">${img}<span class="kindtag">${esc(t("Channel"))}</span></div>
      <div class="body"><div class="title">${esc(e.title)}</div>
        <div class="meta">${e.followers ? `<span>${esc(t("{n} subscribers", { n: fmtNum(e.followers) }))}</span>` : ""}${e.count ? `<span>${esc(t("{n} videos", { n: fmtNum(e.count) }))}</span>` : ""}</div>
        <div class="acts"><button class="btn primary" data-act="loadch">${esc(t("Load all videos"))}</button>
        <button class="btn ghost" data-act="open" title="${esc(t("Open on the website"))}">${ICON.ext}</button></div></div></div>`;
  }
  if (e.kind === "playlist") {
    return `<div class="item playlist" data-id="${esc(e.id)}" data-idx="${idx}">
      <div class="thumb" data-act="openpl">${img}<span class="kindtag">${esc(t("Playlist"))}</span>${e.count ? `<span class="dur">${esc(t("{n} videos", { n: e.count }))}</span>` : ""}</div>
      <div class="body"><div class="title">${esc(e.title)}</div>
        <div class="meta"><span>${esc(e.channel)}</span></div>
        <div class="acts"><button class="btn primary" data-act="openpl">${esc(t("Open playlist"))}</button>
        <button class="btn ghost" data-act="open" title="${esc(t("Open on the website"))}">${ICON.ext}</button></div></div></div>`;
  }
  const haveCur = hasIt(e) ? " have-cur" : "";
  const live = e.live === "is_live" ? `<span class="live">${esc(t("LIVE"))}</span>` : e.live === "is_upcoming" ? `<span class="live">${esc(t("UPCOMING"))}</span>` : "";
  const chan = e.channel ? (e.channel_url ? `<a href="#" data-act="channel" title="${esc(t("Show all videos by {name}", { name: e.channel }))}">${esc(e.channel)}</a>` : `<span>${esc(e.channel)}</span>`) : "";
  return `<div class="item${sel}${haveCur}" data-id="${esc(e.id)}" data-idx="${idx}">
    <div class="thumb" data-act="toggle">${img}<span class="tick">${ICON.check}</span>${haveBadge(e)}${e.duration ? `<span class="dur">${fmtDur(e.duration)}</span>` : ""}${live}</div>
    <div class="body"><div class="title" title="${esc(e.title)}">${esc(e.title)}</div>
      <div class="meta">${chan}${e.views ? `<span>${esc(t("{n} views", { n: fmtNum(e.views) }))}</span>` : ""}${e.date ? `<span>${fmtDate(e.date)}</span>` : ""}</div>
      <div class="acts">
        ${dlButton(e, "video")}${dlButton(e, "audio")}
        ${hasIt(e) ? `<button class="btn ghost trash" data-act="del" title="${esc(t("Delete the downloaded file (moves it to the Recycle Bin)"))}">✕</button>` : ""}
        <button class="btn ghost" data-act="quality" title="${esc(t("See every available quality"))}">${ICON.q}</button>
        <button class="btn ghost" data-act="open" title="${esc(t("Open on the website"))}">${ICON.ext}</button>
      </div></div></div>`;
}

function haveBadge(e) {
  if (!e.dl || !(e.dl.audio || e.dl.video)) return "";
  const icons = (e.dl.audio ? ICON.audio : "") + (e.dl.video ? ICON.video : "");
  return `<span class="have" title="${esc(t("Downloaded"))}">${ICON.check.replace("<svg", '<svg class="ico"')}${icons}</span>`;
}
function dlButton(e, mode) {
  const have = hasIt(e, mode);
  const label = mode === "video" ? t("Video") : t("Audio");
  const title = have ? t("Already downloaded. Click again to download it again.") :
    t(mode === "video" ? "Download video with the settings below" : "Download audio with the settings below");
  return `<button class="btn${have ? " done" : ""}" data-act="dl-${mode}" title="${esc(title)}">${ICON[mode]}${esc(label)}${have ? " ✓" : ""}</button>`;
}
function updateMarks() {
  // refresh "downloaded" marks in place (keeps scroll position)
  $$("#results .item").forEach((el) => {
    const e = S.byId.get(el.dataset.id); if (!e || e.kind !== "video") return;
    el.classList.toggle("have-cur", hasIt(e));
    const th = el.querySelector(".thumb"); const old = th.querySelector(".have");
    const html = haveBadge(e);
    if (old) old.remove();
    if (html) th.querySelector(".tick").insertAdjacentHTML("afterend", html);
    el.querySelectorAll("[data-act^=dl-]").forEach((b) => { b.outerHTML = dlButton(e, b.dataset.act.slice(3)); });
    const tr = el.querySelector("[data-act=del]");
    if (hasIt(e) && !tr) el.querySelector(".acts [data-act=quality]").insertAdjacentHTML("beforebegin", `<button class="btn ghost trash" data-act="del" title="${esc(t("Delete the downloaded file (moves it to the Recycle Bin)"))}">✕</button>`);
    if (!hasIt(e) && tr) tr.remove();
  });
  renderChanBar();
  updateSelInfo();
}
async function refreshMarks() {
  const vids = S.entries.filter((e) => e.kind === "video" && e.vid).map((e) => e.vid);
  if (!vids.length) return;
  try {
    const st = await api("library/status", { vids });
    for (const e of S.entries) if (e.kind === "video") e.dl = st[e.vid] || { audio: false, video: false };
    if ($("#hideHave").checked) render(true); else updateMarks();
  } catch { /* locked or restarting */ }
}

let renderT;
function render(full) {
  const grid = $("#results");
  grid.className = "grid" + (S.view === "list" ? " list" : "") + (S.sel.size ? " selecting" : "");
  if (!full && !isFiltered() && S.renderedCount <= S.entries.length && S.shown.length === S.renderedCount) {
    // fast path: append new items only
    const add = S.entries.slice(S.renderedCount);
    if (add.length) {
      grid.insertAdjacentHTML("beforeend", add.map((e, i) => card(e, S.renderedCount + i)).join(""));
      S.shown = S.entries.slice();
      S.renderedCount = S.entries.length;
    }
    updateSelInfo();
    return;
  }
  clearTimeout(renderT);
  renderT = setTimeout(() => {
    S.shown = computeShown();
    grid.innerHTML = S.shown.map(card).join("");
    S.renderedCount = isFiltered() ? -1 : S.shown.length;
    updateSelInfo();
  }, full ? 0 : 120);
}
["#filter", "#durFilter", "#sort", "#hideHave"].forEach((s) => $(s).addEventListener("input", () => render(true)));
$("#viewSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  S.view = b.dataset.v; localStorage.setItem("rit.view", S.view);
  $$("#viewSeg button").forEach((x) => x.classList.toggle("on", x === b));
  render(true);
});

function selectable() { return S.shown.filter((e) => e.kind === "video" || e.kind === "file"); }
function refreshSelClasses() {
  $$("#results .item").forEach((el) => el.classList.toggle("sel", S.sel.has(el.dataset.id)));
  $("#results").classList.toggle("selecting", S.sel.size > 0);
  updateSelInfo();
}
async function deleteVideos(list, mode = curMode()) {
  // only the file of the current mode (Audio or Video) is deleted
  const vids = list.filter((e) => e.dl && e.dl[mode]).map((e) => ({ vid: e.vid, mode }));
  if (!vids.length) return;
  const r = await api("files/delete", { vids });
  toast(t("{n} files moved to the Recycle Bin.", { n: r.deleted }) + (r.failed.length ? " " + t("{n} could not be deleted.", { n: r.failed.length }) : ""), r.failed.length ? "bad" : "ok");
  refreshMarks();
}
$("#delSel").addEventListener("click", () => {
  const list = S.entries.filter((e) => S.sel.has(e.id) && hasIt(e));
  if (!confirmInline(t("Move the downloaded files of {n} selected videos to the Recycle Bin?", { n: list.length }))) return;
  deleteVideos(list); S.sel.clear(); refreshSelClasses();
});
$("#clearResults").addEventListener("click", () => {
  if (S.browseId && S.loading) api(`browse/${S.browseId}/stop`, {}).catch(() => {});
  S.browseId = null; setLoading(false);
  S.req = null; S.entries = []; S.byId.clear(); S.sel.clear(); S.shown = []; S.history = []; S.channel = null;
  $("#results").innerHTML = ""; $("#resultsHead").classList.add("hidden"); $("#hero").classList.remove("hidden");
  renderChanBar(); updateSelInfo();
});
$("#selAll").addEventListener("click", () => { selectable().forEach((e) => S.sel.add(e.id)); refreshSelClasses(); });
$("#selNew").addEventListener("click", () => {
  S.sel.clear();
  selectable().filter((e) => !hasIt(e) && e.live !== "is_upcoming").forEach((e) => S.sel.add(e.id));
  refreshSelClasses();
});
$("#selNone").addEventListener("click", () => { S.sel.clear(); refreshSelClasses(); });

$("#results").addEventListener("click", (ev) => {
  const actEl = ev.target.closest("[data-act]");
  const item = ev.target.closest(".item");
  if (!item) return;
  const e = S.byId.get(item.dataset.id);
  const act = actEl ? actEl.dataset.act : null;
  if (!act) return;
  ev.preventDefault();
  if (act === "toggle") {
    const idx = +item.dataset.idx;
    if (ev.shiftKey && S.lastIdx != null) {
      const [a, b] = [Math.min(S.lastIdx, idx), Math.max(S.lastIdx, idx)];
      S.shown.slice(a, b + 1).forEach((x) => { if (x.kind === "video" || x.kind === "file") S.sel.add(x.id); });
    } else {
      S.sel.has(e.id) ? S.sel.delete(e.id) : S.sel.add(e.id);
    }
    S.lastIdx = idx;
    refreshSelClasses();
  } else if (act === "dl-video" || act === "dl-audio") {
    const mode = act === "dl-video" ? "video" : "audio";
    if (hasIt(e, mode)) {
      if (!confirmInline(t("Already downloaded. Click again to download it again."))) return;
      enqueue([e], { mode }, null, true);
    } else enqueue([e], { mode });
  } else if (act === "dl-file") {
    enqueue([e]);
  } else if (act === "copy") {
    navigator.clipboard.writeText(e.url).then(() => toast(t("Link copied"), "ok"));
  } else if (act === "del") {
    if (!confirmInline(t("Delete the downloaded file of this video? It goes to the Recycle Bin."))) return;
    deleteVideos([e]);
  } else if (act === "quality") {
    openQualities(e);
  } else if (act === "open") {
    window.open(e.url, "_blank");
  } else if (act === "loadch") {
    startBrowse({ kind: "url", query: e.url, tabs: urlTabs().length ? urlTabs() : ["videos", "streams"] }, true);
  } else if (act === "channel") {
    startBrowse({ kind: "url", query: e.channel_url, tabs: urlTabs().length ? urlTabs() : ["videos", "streams"] }, true);
  } else if (act === "openpl") {
    startBrowse({ kind: "url", query: e.url }, true);
  }
});

/* ---------------------------------------------------------------- channel bar ("download new only") */
function channelNew() {
  const minS = (+S.settings.min_minutes_sync || 0) * 60;
  return S.entries.filter((e) => e.kind === "video" && !hasIt(e) && e.live !== "is_upcoming" && e.live !== "is_live"
    && !(minS && e.duration && e.duration < minS));
}
function renderChanBar() {
  const ch = S.channel, bar = $("#chanBar");
  if (!ch) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const vids = S.entries.filter((e) => e.kind === "video");
  const fresh = channelNew();
  $("#cbThumb").src = ch.thumb || "";
  $("#cbCount").textContent = `${ch.name} · ${t("{n} new of {total}", { n: fresh.length.toLocaleString(), total: vids.length.toLocaleString() })}`;
  $("#cbFolder").textContent = ch.folder ? t("Folder: {path}", { path: ch.folder }) : "";
  $("#cbFolder").title = ch.folder || "";
  $("#cbTrack").checked = !!(ch.tracked && ch.auto);
  const b = $("#cbNew");
  b.disabled = !fresh.length || S.loading;
  b.textContent = fresh.length ? t("Download new ({n})", { n: fresh.length.toLocaleString() }) : (S.loading ? t("Loading...") : t("Up to date"));
}
$("#cbNew").addEventListener("click", () => {
  const fresh = channelNew().slice().reverse();   // oldest first
  if (fresh.length > 25 && !confirmInline(t("Download all {n} shown items?", { n: fresh.length }))) return;
  enqueue(fresh);
});
$("#cbTrack").addEventListener("change", async (ev) => {
  const ch = S.channel; if (!ch) return;
  const on = ev.target.checked;
  try {
    const r = await api("library/channel", { id: ch.id, name: ch.name, url: ch.url, thumb: ch.thumb, tracked: on, auto: on, opts: barOptions() });
    ch.tracked = on; ch.auto = on; ch.folder = r.channel && r.channel.folder;
    renderChanBar();
    toast(on ? t("New videos from this channel are downloaded automatically into its folder.") : t("Saved"), "ok");
  } catch (e) { ev.target.checked = !on; toast(e.message, "bad"); }
});

/* ---------------------------------------------------------------- selection summary + size estimate */
const VKBPS = { best: 5000, 2160: 18000, 1440: 9000, 1080: 4500, 720: 2400, 480: 1100, 360: 650, 240: 350, 144: 180 };
function estimateBytes(seconds) {
  const s = S.settings;
  let kbps;
  if (s.mode === "audio") {
    kbps = { wav: 1411, flac: 900 }[s.audio_format] || (+s.audio_quality || 190);
    if (s.audio_format === "original") kbps = 130;
  } else kbps = (VKBPS[s.video_quality] || 4500) + 130;
  return seconds * kbps * 1000 / 8;
}
function updateSelInfo() {
  const picked = S.entries.filter((e) => S.sel.has(e.id));
  const n = picked.length;
  const shownVideos = selectable().filter((e) => !hasIt(e) && e.live !== "is_upcoming");   // only what is still missing
  $("#dlSel").disabled = !n;
  $("#dlSel").textContent = n ? t("Download selected ({n})", { n: n.toLocaleString() }) : t("Download selected");
  $("#dlShown").textContent = t("Download all shown ({n})", { n: shownVideos.length.toLocaleString() });
  $("#dlShown").disabled = !shownVideos.length;
  $("#delSel").classList.toggle("hidden", !picked.some((e) => hasIt(e)));
  document.body.classList.toggle("files-only", S.shown.length > 0 && S.shown.every((e) => e.kind === "file"));
  const base = n ? picked : shownVideos;
  if (!base.length) { $("#selInfo").textContent = t("Nothing selected"); return; }
  const secs = base.reduce((t, e) => t + (e.duration || 0), 0);
  const est = estimateBytes(secs);
  const free = S.sys.free_gb;
  const tooBig = free != null && est / 2 ** 30 > free * 0.95;
  const cnt = n ? t("{n} selected", { n: `<b>${n.toLocaleString()}</b>` }) : t("{n} shown", { n: `<b>${base.length.toLocaleString()}</b>` });
  const size = secs ? ` &middot; ${t("about {size}", { size: `<b class="${tooBig ? "warn" : ""}">${fmtBytes(est)}</b>` })}${tooBig ? ` <span class="warn">${esc(t("(more than the {n} GB free on this drive)", { n: free }))}</span>` : ""}` : "";
  $("#selInfo").innerHTML = `${cnt}${secs ? ` &middot; ${esc(fmtLong(secs))}` : ""}${size}`;
}

/* ---------------------------------------------------------------- enqueue */
function barOptions(over = {}) {
  const s = S.settings;
  return Object.assign({ mode: s.mode, video_quality: s.video_quality, video_container: s.video_container,
    audio_format: s.audio_format, audio_quality: s.audio_quality }, over);
}
async function enqueue(entries, over = {}, formatId, force = false, section = null) {
  const items = entries.filter((e) => e.kind === "video" || e.kind === "file").map((e) => (e.kind === "file" ?
    { kind: "file", url: e.url, title: e.title, host: e.host, referrer: S.req && S.req.query } : {
    url: e.url, title: e.title, thumb: e.thumb, channel: e.channel, duration: e.duration, format_id: formatId || null,
    vid: e.vid, site: e.site, channel_id: e.channel_id, section,
  }));
  if (!items.length) return;
  try {
    const r = await api("download", { items, options: barOptions(over), group: S.group || S.title, force: force || !!formatId });
    const audio = (over.mode || S.settings.mode) === "audio";
    const parts = [];
    const onlyFiles = items.every((x) => x.kind === "file");
    if (r.added) parts.push(onlyFiles ? `${t("Added to downloads")} (${r.added})` : t(audio ? "Added {n} audio downloads" : "Added {n} video downloads", { n: r.added }));
    if (r.already) parts.push(t("{n} already downloaded (skipped)", { n: r.already }));
    if (r.queued) parts.push(t("({n} already in the list)", { n: r.queued }));
    const msg = parts.join(" · ") || t("Already in the download list");
    toast(msg, r.added ? "ok" : "");
    pollJobs();
  } catch (e) { toast(e.message, "bad"); }
}
$("#dlSel").addEventListener("click", () => {
  enqueue(S.entries.filter((e) => S.sel.has(e.id)));
  S.sel.clear(); refreshSelClasses();
});
$("#dlShown").addEventListener("click", () => {
  const list = selectable().filter((e) => !hasIt(e) && e.live !== "is_upcoming");
  if (list.length > 25 && !confirmInline(t("Download all {n} shown items?", { n: list.length }))) return;
  enqueue(list);
});
let confirmArmed = 0;
function confirmInline(msg) {
  // two-click confirmation (avoids blocking browser dialogs)
  if (Date.now() - confirmArmed < 4000) { confirmArmed = 0; return true; }
  confirmArmed = Date.now();
  toast(msg + " " + t("Click again to confirm."));
  return false;
}

$("#exportBtn").addEventListener("click", () => {
  const rows = [[t("Title"), t("Channel"), t("Date"), t("Duration"), t("Views"), "URL"]].concat(
    S.shown.map((e) => [e.title, e.channel, fmtDate(e.date), fmtDur(e.duration), e.views || "", e.url]));
  const csv = "﻿" + rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = (S.title || "list").replace(/[\\/:*?"<>|]+/g, "_").slice(0, 80) + ".csv";
  a.click();
});

/* ---------------------------------------------------------------- quality picker */
async function openQualities(e) {
  const m = $("#fmtModal"), body = $("#fmtBody");
  m.classList.remove("hidden");
  body.innerHTML = `<div class="loadmore"><span class="spin"></span> ${esc(t("Checking available qualities..."))}</div>`;
  let f;
  try { f = await api("formats", { url: e.url }); } catch (err) { body.innerHTML = `<p class="jerr">${esc(err.message)}</p>`; return; }
  const cont = S.settings.video_container || "mp4";
  const seen = new Set();
  const vrows = f.video.filter((v) => { const k = `${v.height}|${v.vcodec}|${v.fps}`; if (seen.has(k)) return false; seen.add(k); return true; }).map((v) => `
    <tr><td class="res">${v.height ? v.height + "p" : esc(v.note || v.id)}${v.fps > 30 ? ` <span class="tag">${Math.round(v.fps)} fps</span>` : ""}${v.vcodec === "h264" ? `<span class="tag good">${esc(t("plays everywhere"))}</span>` : ""}</td>
    <td>${esc(v.vcodec)}${v.has_audio ? " + " + esc(t("audio")) : ""}</td><td>${esc(v.ext)}${v.proto && v.proto.startsWith("m3u8") ? `<span class="tag">${esc(t("stream"))}</span>` : ""}</td>
    <td>${v.size_total ? "≈ " + fmtBytes(v.size_total) : ""}</td>
    <td><button class="btn sm primary" data-fid="${esc(v.id)}" data-mode="video">${esc(t("Download {fmt}", { fmt: cont.toUpperCase() }))}</button></td></tr>`).join("");
  const af = S.settings.audio_format === "original" ? "mp3" : S.settings.audio_format;
  const arows = f.audio.map((a) => `
    <tr><td class="res">${a.abr ? Math.round(a.abr) + " kbps" : esc(a.note || a.id)}${a.lang ? `<span class="tag">${esc(a.lang)}</span>` : ""}</td>
    <td>${esc(a.acodec)}</td><td>${esc(a.ext)}</td><td>${a.size ? "≈ " + fmtBytes(a.size) : ""}</td>
    <td><button class="btn sm" data-fid="${esc(a.id)}" data-mode="audio" data-af="original">${esc(t("Keep .{ext}", { ext: a.ext }))}</button>
        <button class="btn sm primary" data-fid="${esc(a.id)}" data-mode="audio" data-af="${esc(af)}">${esc(t("To {fmt}", { fmt: af.toUpperCase() }))}</button></td></tr>`).join("");
  body.innerHTML = `
    <div class="fhead">${f.thumb ? `<img src="${esc(f.thumb)}" alt="">` : ""}
      <div><h3>${esc(f.title)}</h3><div class="meta">${esc(f.channel || "")} &middot; ${fmtDur(f.duration)} ${f.date ? "&middot; " + fmtDate(f.date) : ""}</div>
      <p class="muted small">${esc(t("The best audio is added to any video quality you pick. Sizes are estimates. The output file type comes from the bar at the bottom (now {fmt}).", { fmt: cont.toUpperCase() }))}</p></div></div>
    <div class="clipbox">
      <label class="field">${esc(t("Only from"))}<input id="clipFrom" placeholder="0:00:00" spellcheck="false"></label>
      <label class="field">${esc(t("to"))}<input id="clipTo" placeholder="${esc(fmtDur(f.duration) || "1:00:00")}" spellcheck="false"></label>
      <span class="muted small">${esc(t("Optional: download just part of the video, for example only the sermon. Leave empty for the whole video."))}</span>
    </div>
    <div class="ftitle">${ICON.video}<h4>${esc(t("Video qualities"))}</h4></div>
    ${vrows ? `<table class="ftable"><tr><th>${esc(t("Quality"))}</th><th>${esc(t("Codec"))}</th><th>${esc(t("Source"))}</th><th>${esc(t("Size"))}</th><th></th></tr>${vrows}</table>` : `<p class="muted">${esc(t("No separate video qualities."))}</p>`}
    <div class="ftitle">${ICON.audio}<h4>${esc(t("Audio only"))}</h4></div>
    ${arows ? `<table class="ftable"><tr><th>${esc(t("Bitrate"))}</th><th>${esc(t("Codec"))}</th><th>${esc(t("Source"))}</th><th>${esc(t("Size"))}</th><th></th></tr>${arows}</table>` : `<p class="muted">${esc(t("No separate audio streams."))}</p>`}`;
  body.onclick = (ev) => {
    const b = ev.target.closest("[data-fid]"); if (!b) return;
    const over = { mode: b.dataset.mode };
    if (b.dataset.af) over.audio_format = b.dataset.af;
    const sec = clipSection(f.duration);
    if (sec === false) return;
    enqueue([e], over, b.dataset.fid, false, sec);
  };
}
function parseTime(v) {
  v = String(v || "").trim(); if (!v) return null;
  const p = v.split(":").map(Number); if (p.some(isNaN)) return NaN;
  return p.reduce((a, x) => a * 60 + x, 0);
}
const hms = (s) => [Math.floor(s / 3600), Math.floor(s % 3600 / 60), Math.floor(s % 60)].map((x) => String(x).padStart(2, "0")).join(":");
function clipSection(dur) {
  const a = parseTime($("#clipFrom").value), b = parseTime($("#clipTo").value);
  if (a === null && b === null) return null;
  const from = a || 0, to = b === null ? (dur || 0) : b;
  if (isNaN(from) || isNaN(to) || to <= from) { toast(t("Check the start and end times (for example 0:05:00 to 1:20:00)."), "bad"); return false; }
  return `${hms(from)}-${hms(to)}`;
}
function playFile(path, title) {
  const ext = fileExt(path);
  const audio = ["mp3", "m4a", "opus", "ogg", "oga", "flac", "wav", "aac"].includes(ext);
  const src = "/api/media?path=" + encodeURIComponent(path);
  $("#playerTitle").textContent = title || path.split(/[\\/]/).pop();
  $("#playerBox").innerHTML = audio ? `<audio controls autoplay src="${src}"></audio>` : `<video controls autoplay src="${src}"></video>`;
  $("#playerModal").classList.remove("hidden");
}
function closePlayer() { $("#playerBox").innerHTML = ""; $("#playerModal").classList.add("hidden"); }
$("#playerModal").addEventListener("click", (ev) => { if (ev.target.id === "playerModal" || ev.target.closest("[data-close]")) closePlayer(); });
$("#filesModal").addEventListener("click", (ev) => { if (ev.target.id === "filesModal" || ev.target.closest("[data-close]")) $("#filesModal").classList.add("hidden"); });

$("#fmtModal").addEventListener("click", (ev) => {
  if (ev.target.id === "fmtModal" || ev.target.closest("[data-close]")) $("#fmtModal").classList.add("hidden");
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#fmtModal").classList.add("hidden"); $("#filesModal").classList.add("hidden"); closePlayer(); } });

/* ---------------------------------------------------------------- downloads view */
const STATUS_LABEL = { queued: "Waiting", running: "Downloading", done: "Done", skipped: "Skipped", error: "Failed", canceled: "Canceled", paused: "Paused" };
function jobFmt(j) {
  if (j.kind === "file") return `${t("File")}${j.total ? " · " + fmtBytes(j.total) : ""}`;
  const o = j.opts || {};
  if (o.mode === "audio") {
    const f = (o.audio_format || "mp3").toUpperCase();
    return `${f === "ORIGINAL" ? t("Original audio") : f} · ${o.audio_quality === "0" || o.audio_quality === 0 ? t("best") : o.audio_quality + " kbps"}${j && j.section ? " · " + t("part") + " " + j.section : ""}`;
  }
  return `${(o.video_container || "mp4").toUpperCase()} · ${j.format_id ? t("chosen quality") : o.video_quality === "best" ? t("best") : o.video_quality + "p"}${j.section ? " · " + t("part") + " " + j.section : ""}`;
}
function jobRow(j) {
  const el = document.createElement("div");
  el.className = "job"; el.dataset.id = j.id;
  el.innerHTML = `<img alt="" referrerpolicy="no-referrer"><div class="jmain"><div class="jtitle"></div>
    <div class="jsub"><span class="tag"></span><span class="st"></span><span class="jinfo"></span><span class="jgroup"></span></div>
    <div class="bar"><i></i></div><div class="jerr hidden"></div></div><div class="jacts"></div>`;
  return el;
}
function jobActs(j) {
  const b = (a, label, cls = "btn sm ghost") => `<button class="${cls}" data-jact="${a}">${esc(t(label))}</button>`;
  switch (j.status) {
    case "running": return b("pause", "Pause") + b("cancel", "Cancel");
    case "queued": return b("top", "Download next") + b("pause", "Pause") + b("cancel", "Remove");
    case "paused": return b("resume", "Resume", "btn sm") + b("top", "Download next") + b("remove", "Remove");
    case "error": return b("retry", "Retry", "btn sm") + b("remove", "Remove");
    case "canceled": return b("retry", "Retry", "btn sm") + b("remove", "Remove");
    default: return (j.filepath ? (MEDIA_EXT.has(fileExt(j.filepath)) ? b("listen", "Play", "btn sm") : "") +
      b("play", "Open", "btn sm ghost") + b("show", "Show in folder") + b("delfile", "Delete file", "btn sm ghost trash") : "") + b("remove", "Remove");
  }
}
const jobChan = (j) => j.channel || j.group || "";
function jobVisible(j) {
  if (S.jobChannel !== undefined && S.jobChannel !== null && jobChan(j) !== S.jobChannel) return false;
  const q = ($("#jobFilter").value || "").trim().toLowerCase();
  const f = $("#jobStatusFilter").value;
  if (q && !((j.title || "") + " " + (j.channel || "") + " " + (j.group || "")).toLowerCase().includes(q)) return false;
  if (f === "active") return ["running", "queued"].includes(j.status);
  if (f === "done") return ["done", "skipped"].includes(j.status);
  if (f) return j.status === f;
  return true;
}
["#jobFilter", "#jobStatusFilter"].forEach((s) => $(s).addEventListener("input", () => pollJobs()));

function offerClip(c) {
  $$(".toast.action").forEach((x) => x.remove());
  const el = document.createElement("div");
  el.className = "toast action";
  const isFile = c.kind === "file";
  el.innerHTML = `<b>${esc(t("Link copied. Download it?"))}</b><div class="u">${esc(c.url)}</div><div class="row">
    ${isFile ? `<button class="btn sm primary" data-c="file">${esc(t("Download file"))}</button>` :
      `<button class="btn sm primary" data-c="audio">${esc(t("Audio"))}</button><button class="btn sm primary" data-c="video">${esc(t("Video"))}</button>`}
    <button class="btn sm" data-c="open">${esc(t("Open in Browse"))}</button><button class="btn sm ghost" data-c="no">${esc(t("Close"))}</button></div>`;
  $("#toasts").appendChild(el);
  const close = () => { el.remove(); api("clip/dismiss", {}).catch(() => {}); };
  setTimeout(() => el.isConnected && el.remove(), 20000);
  el.onclick = async (ev) => {
    const b = ev.target.closest("[data-c]"); if (!b) return;
    const a = b.dataset.c;
    if (a === "open") { showView("browse"); setKind("url"); $("#q").value = c.url; doSearch(); }
    else if (a === "file") await api("download", { items: [{ kind: "file", url: c.url, title: c.url.split("/").pop() }] }).then(() => toast(t("Added to downloads"), "ok"));
    else if (a === "audio" || a === "video") await api("download", { items: [{ url: c.url, title: c.url }], options: barOptions({ mode: a }) }).then((r) =>
      toast(r.added ? t("Added to downloads") : r.already ? t("{n} already downloaded (skipped)", { n: 1 }) : t("Already in the download list"), "ok"));
    close();
  };
}

function renderChannelStrip(jobs) {
  const groups = new Map();
  for (const jb of jobs) {
    const k = jobChan(jb);
    const g = groups.get(k) || { name: k, running: 0, queued: 0, paused: 0, done: 0, error: 0, ids: [], batch: 0 };
    if (jb.status === "running") g.running++;
    else if (jb.status === "queued") g.queued++;
    else if (jb.status === "paused") g.paused++;
    else if (jb.status === "done" || jb.status === "skipped") g.done++;
    else if (jb.status === "error") g.error++;
    if (["running", "queued", "paused", "error", "canceled"].includes(jb.status)) g.ids.push(jb.id);
    g.batch = Math.max(g.batch, jb.batch || 0);
    groups.set(k, g);
  }
  const list = [...groups.values()].filter((g) => g.running + g.queued + g.paused + g.error > 0)
    .sort((a, b) => (b.running - a.running) || (b.batch - a.batch));
  const box = $("#dlChannels");
  if (S.jobChannel != null && !groups.has(S.jobChannel)) S.jobChannel = null;
  if (list.length < 2 && S.jobChannel == null) { box.innerHTML = ""; return; }
  box.innerHTML = list.map((g) => {
    const total = g.running + g.queued + g.paused + g.done + g.error;
    const pct = total ? Math.round(100 * g.done / total) : 0;
    const parts = [];
    if (g.running) parts.push(`<b>${g.running}</b> ${esc(t("Downloading"))}`);
    if (g.queued) parts.push(`<b>${g.queued}</b> ${esc(t("Waiting"))}`);
    if (g.paused) parts.push(`<b>${g.paused}</b> ${esc(t("Paused"))}`);
    if (g.error) parts.push(`<b>${g.error}</b> ${esc(t("Failed"))}`);
    parts.push(`<b>${g.done}</b> ${esc(t("Done"))}`);
    const key = esc(g.name);
    return `<div class="dlch${S.jobChannel === g.name ? " on" : ""}" data-ch="${key}">
      <span class="nm" data-chact="filter" title="${esc(t("Show only this channel"))}">${esc(g.name || t("Other"))}</span>
      <span class="cnt">${parts.join(" · ")}</span>
      <div class="bar"><i style="width:${pct}%"></i></div>
      <button class="btn sm" data-chact="top" title="${esc(t("Download this channel before the others"))}">${esc(t("Download first"))}</button>
      ${g.running + g.queued ? `<button class="btn sm ghost" data-chact="pause">${esc(t("Pause"))}</button>` : ""}
      ${g.paused || g.error ? `<button class="btn sm ghost" data-chact="resume">${esc(t("Resume"))}</button>` : ""}
      <button class="btn sm ghost" data-chact="remove" title="${esc(t("Remove this channel's unfinished downloads from the list"))}">${esc(t("Remove"))}</button>
    </div>`;
  }).join("");
  box._groups = groups;
}
$("#dlChannels").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-chact]"); if (!b) return;
  const name = b.closest(".dlch").dataset.ch;
  const g = ($("#dlChannels")._groups || new Map()).get(name); if (!g) return;
  const act = b.dataset.chact;
  if (act === "filter") { S.jobChannel = S.jobChannel === name ? null : name; return pollJobs(); }
  if (act === "remove" && !confirmInline(t("Remove {n} unfinished downloads of {name} from the list?", { n: g.ids.length, name: name || t("Other") }))) return;
  await api("jobs/action", { ids: g.ids, action: act === "remove" ? "cancel" : act });
  if (act === "remove") await api("jobs/action", { ids: g.ids, action: "remove" });
  if (act === "top") toast(t("{name} will download next.", { name: name || t("Other") }), "ok");
  pollJobs();
});

function renderBanners() {
  const sys = S.sys || {}, box = $("#dlBanners"); if (!box) return;
  const out = [];
  const ck = sys.cookies;
  if (ck && !ck.ok) out.push(["warn", t("Your sign-in from {name} could not be read, so downloads continue without it. Public videos are not affected.", { name: ck.name }), "fixcookies", t("Fix sign-in")]);
  if (sys.hold === "offline") out.push(["warn", t("No internet connection. Downloads continue automatically when you are back online."), "", ""]);
  if (sys.hold === "disk") out.push(["warn", t("Downloads are paused because the disk is almost full. Free up space, then click Resume all."), "", ""]);
  if (sys.hold === "schedule" && sys.window) out.push(["info", t("Downloads wait for your download hours ({from} to {to}).", { from: sys.window[0], to: sys.window[1] }), "", ""]);
  if (sys.power) {
    const left = Math.max(0, Math.round((sys.power_at - Date.now() / 1000)));
    out.push(["warn", t(sys.power === "shutdown" ? "The computer will shut down in {n} seconds." : "The computer will sleep in {n} seconds.", { n: left }), "cancelpower", t("Cancel")]);
  }
  box.innerHTML = out.map(([k, msg, act, label]) => `<div class="banner2 ${k}"><span>${esc(msg)}</span>${act ? `<button class="btn sm" data-banner="${act}">${esc(label)}</button>` : ""}</div>`).join("");
}
$("#dlBanners").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-banner]"); if (!b) return;
  if (b.dataset.banner === "fixcookies") { showView("settings"); $("#cookieSource").scrollIntoView({ block: "center" }); $("#cookieSource").focus(); }
  if (b.dataset.banner === "cancelpower") { await api("power/cancel", {}); toast(t("Canceled"), "ok"); refreshSystem(); }
});

let jobsT;
async function pollJobs() {
  clearTimeout(jobsT);
  let data;
  try { data = await api("jobs"); } catch { jobsT = setTimeout(pollJobs, 3000); return; }
  const { jobs, stats } = data;
  if (data.clip && data.clip.at > (S.clipSeen || 0)) { S.clipSeen = data.clip.at; offerClip(data.clip); }
  if (S.sys && (S.sys.hold !== data.hold || S.sys.power !== data.power)) {
    S.sys.hold = data.hold; S.sys.power = data.power; S.sys.power_at = data.power_at;
    if (data.hold === "schedule" && !S.sys.window) refreshSystem(); else renderBanners();
  }
  const finished = (stats.done || 0) + (stats.skipped || 0);
  if (S.lastFinished !== undefined && finished > S.lastFinished) refreshMarks();
  S.lastFinished = finished;
  const active = (stats.running || 0) + (stats.queued || 0);
  const badge = $("#dlBadge");
  badge.textContent = active; badge.classList.toggle("hidden", !active);
  const labels = [["running", "Downloading"], ["queued", "Waiting"], ["paused", "Paused"], ["done", "Done"], ["skipped", "Skipped"], ["error", "Failed"]];
  $("#dlStats").innerHTML = labels.filter(([k]) => stats[k]).map(([k, l]) => `<span class="chip">${esc(t(l))}<b>${stats[k]}</b></span>`).join("") || `<span class="chip">${esc(t("Queue is empty"))}</span>`;
  const box = $("#jobs");
  $("#jobsEmpty").classList.toggle("hidden", jobs.length > 0);
  const existing = new Map($$(".job", box).map((el) => [el.dataset.id, el]));
  // newest first, but keep running at top
  const order = { running: 0, queued: 1, paused: 2, error: 3, canceled: 4, done: 5, skipped: 5 };
  jobs.sort((a, b) => (order[a.status] - order[b.status]) ||
    (a.status === "queued" ? (a.position || 1e9) - (b.position || 1e9) : (b.finished || b.created) - (a.finished || a.created)));
  renderChannelStrip(jobs);
  let prev = null;
  for (const j of jobs) {
    let el = existing.get(j.id);
    if (!el) el = jobRow(j);
    existing.delete(j.id);
    el.className = "job " + j.status;
    const img = el.querySelector("img");
    if (j.thumb && img.getAttribute("src") !== j.thumb) img.src = j.thumb;
    el.querySelector(".jtitle").textContent = j.title;
    el.querySelector(".jtitle").title = j.filepath || j.title;
    el.querySelector(".tag").textContent = jobFmt(j);
    const st = el.querySelector(".st"); st.className = "st " + j.status; st.textContent = t(STATUS_LABEL[j.status] || j.status);
    let info = j.stage ? t(j.stage) : "";
    if (j.status === "queued" && j.position && !j.retry_at && j.stage !== "Waiting for internet connection...") info = t("Number {n} in line", { n: j.position }) + (info ? " · " + info : "");
    if (j.status === "running" && j.total) {
      info = `${info} · ${t("{p}% of {size}", { p: Math.round(j.percent), size: fmtBytes(j.total) })}${j.speed ? " · " + fmtBytes(j.speed) + "/s" : ""}${j.eta != null ? " · " + t("{t} left", { t: fmtDur(j.eta) }) : ""}`;
    }
    el.querySelector(".jinfo").textContent = info;
    el.querySelector(".jgroup").textContent = j.group ? "📁 " + j.group : (j.kind === "file" ? "🌐 " + (j.channel || "") : "");
    let sha = el.querySelector(".sha");
    if (j.sha256 && !sha) { el.querySelector(".jsub").insertAdjacentHTML("beforeend", `<span class="sha" title="${esc(t("Click to copy. Compare it with the checksum on the download website to make sure the file is genuine."))}">SHA-256 ${esc(j.sha256.slice(0, 16))}…</span>`); sha = el.querySelector(".sha"); sha.onclick = () => navigator.clipboard.writeText(j.sha256).then(() => toast(t("SHA-256 copied"), "ok")); }
    el.querySelector(".bar > i").style.width = (["done", "skipped"].includes(j.status) ? 100 : j.percent || 0) + "%";
    const err = el.querySelector(".jerr"); err.textContent = j.error ? t(j.error) : ""; err.title = j.error_raw || "";
    err.classList.toggle("hidden", !j.error);
    el.classList.toggle("hidden", !jobVisible(j));
    const acts = jobActs(j);
    const ab = el.querySelector(".jacts"); if (ab.dataset.k !== j.status + !!j.filepath) { ab.innerHTML = acts; ab.dataset.k = j.status + !!j.filepath; }
    el._job = j;
    if (prev ? prev.nextSibling !== el : box.firstChild !== el) prev ? prev.after(el) : box.prepend(el);
    prev = el;
  }
  existing.forEach((el) => el.remove());
  const viewing = $("#view-downloads").classList.contains("on");
  jobsT = setTimeout(pollJobs, active ? 900 : viewing ? 2000 : 4000);
}
$("#jobs").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-jact]"); if (!b) return;
  const row = b.closest(".job"); const j = row._job; const a = b.dataset.jact;
  if (a === "play") return api("open", { path: j.filepath });
  if (a === "listen") return playFile(j.filepath, j.title);
  if (a === "delfile") {
    if (!confirmInline(t("Delete this file? It goes to the Recycle Bin."))) return;
    const r = await api("files/delete", { paths: [j.filepath] });
    toast(r.deleted ? t("{n} files moved to the Recycle Bin.", { n: r.deleted }) : t("{n} could not be deleted.", { n: 1 }), r.deleted ? "ok" : "bad");
    refreshMarks();
    return pollJobs();
  }
  if (a === "show") return api("open", { path: j.filepath, select: true });
  await api("jobs/action", { ids: [j.id], action: a });
  pollJobs();
});
$$("[data-all]").forEach((b) => b.addEventListener("click", async () => {
  const a = b.dataset.all;
  if (a === "cancel" && !confirmInline(t("Cancel every download?"))) return;
  if (a === "clear_all" && !confirmInline(t("Empty the whole download list? Downloads in progress stop. Files already downloaded stay on disk."))) return;
  const ids = a.startsWith("clear") ? [] : "all";
  await api("jobs/action", { ids, action: a });
  pollJobs();
}));
$("#openFolder").addEventListener("click", () => api("open", {}));

/* ---------------------------------------------------------------- sign-in (cookies) */
const COOKIE_ERR = {
  locked: "The browser is open and has locked its sign-in data. Close it completely, or use Firefox or a cookies.txt file.",
  decrypt: "This browser encrypts its sign-in data so other apps cannot read it. Use Firefox or a cookies.txt file instead.",
  unreadable: "The sign-in data could not be read. Close the browser completely, or use Firefox or a cookies.txt file.",
  file_missing: "The cookies file was not found. Choose it again.",
};
function showCookieResult(st) {
  const el = $("#cookieResult");
  if (!st) { el.textContent = t("Sign-in is off."); el.className = "small"; return; }
  if (st.ok) {
    el.textContent = st.youtube ? t("Working: {n} YouTube/Google sign-in cookies found.", { n: st.youtube }) :
      t("Readable, but no YouTube sign-in found. Sign in to youtube.com in that browser first.");
    el.className = "small " + (st.youtube ? "cookie-ok" : "cookie-bad");
  } else { el.textContent = t(COOKIE_ERR[st.error] || COOKIE_ERR.unreadable); el.className = "small cookie-bad"; }
}
$("#cookieSource").addEventListener("change", async (ev) => {
  const v = ev.target.value;
  $("#cookieFileRow").classList.toggle("hidden", v !== "file");
  if (v === "file") {
    if (!S.settings.cookies_file) { $("#cookieFileBtn").click(); return; }
    await saveSetting({ cookies_browser: "" });
  } else await saveSetting({ cookies_browser: v, cookies_file: "" });
  setTimeout(() => $("#cookieTest").click(), 400);
});
$("#cookieFileBtn").addEventListener("click", async () => {
  toast(t("A file picker opened. It may be behind this window."));
  const r = await api("cookies/file", {});
  if (r.path) { S.settings = r.settings; applySettings(); showCookieResult(r.status); refreshSystem(); }
  else applySettings();
});
$("#cookieTest").addEventListener("click", async () => {
  $("#cookieResult").textContent = t("Checking..."); $("#cookieResult").className = "small";
  const r = await api("cookies/test", {}); showCookieResult(r.status); refreshSystem();
});

/* ---------------------------------------------------------------- settings buttons */
$("#pickDir").addEventListener("click", async () => {
  toast(t("A folder picker opened. It may be behind this window."));
  const r = await api("pick-folder", {});
  if (r.path) { S.settings = r.settings; applySettings(); refreshSystem(); toast(t("Download folder: {path}", { path: r.path }), "ok"); }
});
$("#openDir").addEventListener("click", () => api("open", {}));
$("#updBtn").addEventListener("click", async (e) => {
  const b = e.currentTarget; b.disabled = true; b.textContent = t("Updating...");
  try {
    const r = await api("update-ytdlp", {});
    if (r.ok && r.restart) {
      toast(r.output + ". " + t("Restarting the app..."), "ok");
      await api("restart", {}); setTimeout(() => location.reload(), 4500);
    } else if (r.ok) toast(r.output, "ok");
    else toast(t("Update failed:") + " " + r.output, "bad");
  } finally { b.disabled = false; b.textContent = t("Update"); }
});
$("#ffBtn").addEventListener("click", async (e) => {
  const b = e.currentTarget; b.disabled = true; b.textContent = t("Downloading (about 140 MB)...");
  const r = await api("install-ffmpeg", {}).catch((x) => ({ ok: false, output: x.message }));
  toast(r.ok ? t("ffmpeg installed") : t("Install failed:") + " " + (r.output || ""), r.ok ? "ok" : "bad");
  b.disabled = false; b.textContent = t("Repair"); refreshSystem();
});
$("#restartBtn").addEventListener("click", async () => { await api("restart", {}); toast(t("Restarting...")); setTimeout(() => location.reload(), 3500); });
$("#quitBtn").addEventListener("click", async () => {
  if (!confirmInline(t("Quit the app? Any downloads in progress will stop."))) return;
  await api("quit", {}).catch(() => {});
  document.body.innerHTML = `<div class="hero"><h1>${esc(t("Rit Downloader has stopped."))}</h1><p>${esc(t("You can close this window. Open it again from the desktop shortcut."))}</p></div>`;
});

/* ---------------------------------------------------------------- boot */
async function boot() {
  S.view = localStorage.getItem("rit.view") || "grid";
  $$("#viewSeg button").forEach((x) => x.classList.toggle("on", x.dataset.v === S.view));
  try { S.settings = await api("settings"); } catch (e) { toast(t("Can't reach the app server:") + " " + e.message, "bad"); }
  applySettings();
  if (S.settings.language !== I18N.lang) saveSetting({ language: I18N.lang }, true);
  setKind("search");
  refreshSystem(); setInterval(() => { if (S.sys && S.sys.power) refreshSystem(); }, 2000); setInterval(refreshSystem, 20000);
  api("app-update").then((u) => {
    if (!u.available) return;
    const bar = $("#updateBanner");
    bar.innerHTML = `${esc(t("A new version of Rit Downloader ({v}) is available.", { v: u.latest }))} <a href="${esc(u.url)}" target="_blank">${esc(t("Download it"))}</a>`;
    bar.classList.remove("hidden");
  }).catch(() => {});
  pollJobs();
  const p = new URLSearchParams(location.search);
  if (p.get("url")) {
    setKind("url"); $("#q").value = p.get("url");
    history.replaceState(null, "", "/");
    doSearch();
  } else if (p.get("q")) {
    $("#q").value = p.get("q"); history.replaceState(null, "", "/"); doSearch();
  }
}

/* ---------------------------------------------------------------- library */
let libT;
const rtf = () => new Intl.RelativeTimeFormat(I18N.lang, { numeric: "auto" });
function ago(ts) {
  if (!ts) return "";
  const s = (Date.now() / 1000) - ts;
  if (s < 60) return rtf().format(0, "minute");
  if (s < 3600) return rtf().format(-Math.round(s / 60), "minute");
  if (s < 86400) return rtf().format(-Math.round(s / 3600), "hour");
  return rtf().format(-Math.round(s / 86400), "day");
}
function optsLabel(o) {
  if (!o) return "";
  return jobFmt({ opts: o });
}
async function loadLibrary() {
  clearTimeout(libT);
  if (!$("#view-library").classList.contains("on")) return;
  let d;
  try { d = await api("library"); } catch { libT = setTimeout(loadLibrary, 4000); return; }
  S.lib = d;
  const tot = d.totals;
  $("#libTotals").innerHTML = [t("{n} files", { n: tot.files.toLocaleString() }), fmtBytes(tot.bytes) || "0 B",
    t("{n} channels", { n: tot.channels })].map((x) => `<span class="chip">${esc(x)}</span>`).join("");
  const sc = d.scan || {};
  $("#libScanState").textContent = sc.state === "scanning" ? t("Scanning... {n} files found", { n: sc.found || 0 }) :
    sc.state === "done" ? t("Library updated: {n} files found.", { n: (sc.found || 0).toLocaleString() }) + " " + ago(sc.finished) : "";
  renderDupes(sc.duplicates || []);
  const box = $("#libChannels");
  if (!d.channels.length) {
    box.innerHTML = `<div class="empty-lib">${esc(t("No channels yet. Download from a channel, or open one in Browse and choose Keep up to date."))}</div>`;
  } else {
    box.innerHTML = d.channels.map(libRow).join("");
  }
  const busy = d.channels.some((c) => c.sync && c.sync.state === "checking") || sc.state === "scanning";
  libT = setTimeout(loadLibrary, busy ? 1500 : 6000);
}
function libRow(c) {
  const sy = c.sync || {};
  let status = "";
  if (sy.state === "checking") status = `<span class="pill"><span class="spin"></span> ${esc(t("Checking..."))}</span>`;
  else if (sy.state === "error") status = `<span class="pill err" title="${esc(t(sy.error || ""))}">${esc(t("Error"))}</span>`;
  else if (sy.state === "done") status = sy.queued ? `<span class="pill new">${esc(t("Found {n} new videos. Added to downloads.", { n: sy.queued }))}</span>` :
    sy.new ? `<span class="pill new">${esc(t("{n} new", { n: sy.new }))}</span>` : `<span class="pill ok">${esc(t("Up to date"))}</span>`;
  else if (c.new_count) status = `<span class="pill new">${esc(t("{n} new", { n: c.new_count }))}</span>`;
  const initial = esc((c.name || "?").trim().charAt(0).toUpperCase());
  const pic = c.thumb ? `<img src="${esc(c.thumb)}" alt="" referrerpolicy="no-referrer">` : `<div class="ph">${initial}</div>`;
  const key = esc(c.channel_id);
  const newN = sy.state === "done" && !sy.queued ? sy.new : c.new_count;
  return `<div class="lch" data-key="${key}">${pic}
    <div><h4>${esc(c.name || c.channel_id)}</h4>
      <div class="lmeta">
        <span>${esc(t("{a} audio · {v} video", { a: c.n_audio || 0, v: c.n_video || 0 }))} · ${esc(fmtBytes(c.bytes) || "0 B")}</span>
        <span>${esc(c.last_sync ? t("Last checked {t}", { t: ago(c.last_sync) }) : t("Never checked"))}</span>
        ${c.folder ? `<a data-lact="open" title="${esc(c.folder)}">${esc(t("Folder: {path}", { path: c.folder }))}</a>` : ""}
        ${c.tracked && c.opts ? `<span>${esc(t("Uses: {opts}", { opts: optsLabel(c.opts) }))}</span>` : ""}
      </div></div>
    <div class="lacts">${status}
      <label class="toggle"><input type="checkbox" data-lact="track" ${c.tracked && c.auto ? "checked" : ""}><span></span> ${esc(t("Keep up to date"))}</label>
      <button class="btn sm" data-lact="check">${esc(t("Check for new"))}</button>
      <button class="btn sm primary" data-lact="sync">${esc(newN ? t("Download new ({n})", { n: newN }) : t("Download new"))}</button>
      ${c.url ? `<button class="btn sm ghost" data-lact="view">${esc(t("View videos"))}</button>` : ""}
      <button class="btn sm ghost" data-lact="folder">${esc(t("Change folder"))}</button>
      ${c.tracked ? `<button class="btn sm ghost" data-lact="opts">${esc(t("Use current settings"))}</button>` : ""}
      ${c.tracked ? `<button class="btn sm ghost" data-lact="untrack">${esc(t("Stop tracking"))}</button>` : ""}
      <button class="btn sm ghost" data-lact="files">${esc(t("Files"))}</button>
    </div></div>`;
}
function renderDupes(list) {
  const box = $("#libDupes");
  if (!list.length) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const size = list.reduce((a, d) => a + (d.size || 0), 0);
  box.innerHTML = `<h4>${esc(t("Duplicate copies found: {n}", { n: list.length }))}</h4>
    <div class="muted small">${esc(t("These files are extra copies of videos you already have. Nothing was deleted. Review and delete them yourself if you want to free {size}.", { size: fmtBytes(size) }))}</div>
    <div class="inline" style="margin-top:8px"><button class="btn sm danger" data-dupeall="1">${esc(t("Delete all extra copies"))}</button></div>
    <ul>${list.map((d, i) => `<li><span title="${esc(d.copy)}">${esc(d.copy)}</span>
      <button class="btn sm ghost" data-dupe="${i}">${esc(t("Show in folder"))}</button>
      <button class="btn sm ghost trash" data-dupedel="${i}">${esc(t("Delete copy"))}</button></li>`).join("")}</ul>`;
  box.onclick = async (ev) => {
    const b = ev.target.closest("[data-dupe],[data-dupedel],[data-dupeall]"); if (!b) return;
    if (b.dataset.dupe !== undefined) return api("open", { path: list[+b.dataset.dupe].copy, select: true });
    const paths = b.dataset.dupeall ? list.map((d) => d.copy) : [list[+b.dataset.dupedel].copy];
    if (!confirmInline(t("Move {n} extra copies to the Recycle Bin? The original files are kept.", { n: paths.length }))) return;
    const r = await api("files/delete", { paths });
    toast(t("{n} files moved to the Recycle Bin.", { n: r.deleted }), "ok");
    S.lib.scan.duplicates = (S.lib.scan.duplicates || []).filter((d) => !paths.includes(d.copy));
    renderDupes(S.lib.scan.duplicates);
  };
}
$("#libChannels").addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-lact]"); if (!el || el.tagName === "INPUT") return;
  const row = el.closest(".lch"); const key = row.dataset.key;
  const c = (S.lib.channels || []).find((x) => x.channel_id === key) || {};
  const a = el.dataset.lact;
  if (a === "open") return api("open", { path: c.folder });
  if (a === "check" || a === "sync") { await api("library/sync", { keys: [key], download: a === "sync" }); return loadLibrary(); }
  if (a === "view") { showView("browse"); startBrowse({ kind: "url", query: c.url, tabs: ["videos", "streams"] }, true); return; }
  if (a === "folder") {
    toast(t("A folder picker opened. It may be behind this window."));
    const r = await api("library/channel/folder", { key });
    if (r.path) toast(t("Channel folder changed. New downloads will go to: {path}", { path: r.path }), "ok");
    return loadLibrary();
  }
  if (a === "opts") { await api("library/channel", { key, opts: barOptions() }); toast(t("Saved"), "ok"); return loadLibrary(); }
  if (a === "files") return openChannelFiles(c);
  if (a === "untrack") { await api("library/remove", { key }); toast(t("Stopped tracking. Files and history are kept."), "ok"); return loadLibrary(); }
});
async function openChannelFiles(c) {
  const m = $("#filesModal"), body = $("#filesBody");
  m.classList.remove("hidden");
  body.innerHTML = `<div class="loadmore"><span class="spin"></span></div>`;
  const { files } = await api("library/files?key=" + encodeURIComponent(c.channel_id));
  const total = files.reduce((a, f) => a + (f.size || 0), 0);
  body.innerHTML = `<div class="fhead2"><h3>${esc(c.name || "")} · ${esc(t("{n} files", { n: files.length }))} · ${esc(fmtBytes(total) || "0 B")}</h3>
      <button class="btn sm danger" data-fact="delsel" disabled>${esc(t("Delete selected files"))}</button>
      <button class="btn sm danger" data-fact="delall">${esc(t("Delete all files"))}</button>
      <button class="btn sm ghost" data-fact="forget" title="${esc(t("Forget this channel's download history. Files stay on disk, and the videos can be downloaded again."))}">${esc(t("Remove from library"))}</button></div>
    <table class="flist"><tr><th><input type="checkbox" data-fall></th><th>${esc(t("Title"))}</th><th>${esc(t("Date"))}</th><th>${esc(t("Size"))}</th><th></th></tr>
    ${files.map((f, i) => `<tr class="${f.exists ? "" : "missing"}"><td><input type="checkbox" data-fi="${i}" ${f.exists ? "" : "disabled"}></td>
      <td class="t" title="${esc(f.filepath || "")}">${f.mode === "audio" ? ICON.audio : ICON.video} ${esc(f.title || f.video_id)}</td><td>${esc(fmtDate(f.upload_date))}</td><td>${esc(fmtBytes(f.size))}</td>
      <td><div class="acts2">${f.exists ? `<button class="btn sm" data-fp="${i}">${esc(t("Play"))}</button><button class="btn sm ghost" data-fs="${i}">${esc(t("Show in folder"))}</button>` : esc(t("File deleted"))}</div></td></tr>`).join("")}</table>`;
  const sel = () => $$("[data-fi]:checked", body).map((x) => files[+x.dataset.fi]);
  body.onchange = (ev) => {
    if (ev.target.dataset.fall !== undefined) $$("[data-fi]:not(:disabled)", body).forEach((x) => { x.checked = ev.target.checked; });
    body.querySelector("[data-fact=delsel]").disabled = !sel().length;
  };
  body.onclick = async (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    if (b.dataset.fp !== undefined) { const f = files[+b.dataset.fp]; return playFile(f.filepath, f.title); }
    if (b.dataset.fs !== undefined) return api("open", { path: files[+b.dataset.fs].filepath, select: true });
    const act = b.dataset.fact;
    if (act === "forget") {
      if (!confirmInline(t("Remove {name} from the library? Files stay on disk.", { name: c.name || "" }))) return;
      await api("library/forget", { key: c.channel_id, delete: false });
      toast(t("Removed from the library. Files were kept."), "ok"); m.classList.add("hidden"); return loadLibrary();
    }
    if (act === "delall") {
      if (!confirmInline(t("Move all {n} files of {name} to the Recycle Bin and remove the channel from the library?", { n: files.length, name: c.name || "" }))) return;
      const r = await api("library/forget", { key: c.channel_id, delete: true });
      toast(t("{n} files moved to the Recycle Bin.", { n: r.deleted }), "ok"); m.classList.add("hidden"); refreshMarks(); return loadLibrary();
    }
    if (act === "delsel") {
      const list = sel();
      if (!confirmInline(t("Move {n} selected files to the Recycle Bin?", { n: list.length }))) return;
      const r = await api("files/delete", { paths: list.map((f) => f.filepath) });
      toast(t("{n} files moved to the Recycle Bin.", { n: r.deleted }), "ok"); refreshMarks(); loadLibrary(); return openChannelFiles(c);
    }
  };
}

$("#libChannels").addEventListener("change", async (ev) => {
  const el = ev.target.closest("[data-lact=track]"); if (!el) return;
  const key = el.closest(".lch").dataset.key;
  const c = (S.lib.channels || []).find((x) => x.channel_id === key) || {};
  await api("library/channel", { key, tracked: el.checked, auto: el.checked, opts: c.opts || barOptions() });
  if (el.checked) toast(t("New videos from this channel are downloaded automatically into its folder."), "ok");
  loadLibrary();
});
$("#libSyncAll").addEventListener("click", async () => { await api("library/sync", { keys: "all", download: false }); loadLibrary(); });
$("#libScan").addEventListener("click", async () => { await api("library/scan", {}); loadLibrary(); });
$("#libAddFolder").addEventListener("click", async () => {
  toast(t("A folder picker opened. It may be behind this window."));
  await api("library/scan", { pick: true }); loadLibrary();
});

/* ---------------------------------------------------------------- language */
$$("select.langsel").forEach((sel) => {
  sel.innerHTML = langOptions();
  sel.addEventListener("change", async () => {
    await setLang(sel.value);
    if (S.booted) saveSetting({ language: sel.value }, true);
  });
});
document.addEventListener("langchange", () => {
  if (!S.booted) return;
  setKind(S.kind, false);
  if (S.req && S.req.kind === "search") { S.title = t('Results for "{q}"', { q: S.req.query }); $("#rTitle").textContent = S.title; }
  updateSelInfo();
  if (S.entries.length) {
    render(true);
    $("#rStatus").textContent = S.loading ? t("{n} loaded", { n: S.entries.length.toLocaleString() }) : countText(S.entries.length);
  }
  $$("#jobs .jacts").forEach((el) => { el.dataset.k = ""; });
  renderChanBar();
  loadLibrary();
  pollJobs();
  refreshSystem();
});

/* ---------------------------------------------------------------- sign-in / app lock */
const AUTH_ERR = {
  bad_user: "Enter a username (up to 40 characters).",
  short_password: "Use at least 4 characters for the password.",
  invalid: "Wrong username or password.",
  no_account: "No account exists yet.",
  exists: "An account already exists on this computer.",
};
S.auth = {};

async function showAuth(st) {
  if (!st) { try { st = await api("auth/status"); } catch { st = { setup: false }; } }
  S.auth = st;
  if (st.authed) { $("#authScreen").classList.add("hidden"); return; }
  $("#authScreen").classList.remove("hidden");
  $("#setupForm").classList.toggle("hidden", !st.setup);
  $("#loginForm").classList.toggle("hidden", !!st.setup);
  $("#forgotText").classList.add("hidden");
  $("#liPass").value = "";
  setTimeout(() => (st.setup ? $("#suUser") : $("#liUser")).focus(), 50);
}

function afterSignIn(st) {
  S.auth = st;
  $("#authScreen").classList.add("hidden");
  $("#acctUser").textContent = st.user || "";
  $("#lockEnabled").checked = st.enabled !== false;
  $("#autoLock").value = String(st.auto_lock || 0);
  $("#lockBtn").classList.toggle("hidden", st.enabled === false);
  if (!S.booted) { S.booted = true; boot(); } else { pollJobs(); refreshSystem(); }
}

$("#setupForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("#suErr"); err.textContent = "";
  if ($("#suPass").value !== $("#suPass2").value) { err.textContent = t("The passwords do not match."); return; }
  try {
    await api("auth/setup", { user: $("#suUser").value, password: $("#suPass").value, hint: $("#suHint").value });
    afterSignIn(await api("auth/status"));
    toast(t("Account created. Welcome!"), "ok");
  } catch (e) { err.textContent = t(AUTH_ERR[e.message] || e.message); }
});

$("#loginForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("#liErr"); err.textContent = "";
  try {
    await api("auth/login", { user: $("#liUser").value, password: $("#liPass").value, remember: $("#liRemember").checked });
    afterSignIn(await api("auth/status"));
  } catch (e) {
    const d = e.data || {};
    err.textContent = d.error === "wait" ? t("Too many attempts. Try again in {n} seconds.", { n: d.wait }) : t(AUTH_ERR[e.message] || e.message);
  }
});

$("#forgotBtn").addEventListener("click", () => {
  const st = S.auth || {};
  const el = $("#forgotText");
  el.textContent = (st.hint ? t("Your hint: {hint}", { hint: st.hint }) + " " : "") +
    t("If you cannot remember it, quit the app and delete the file auth.json in {path}. Your downloads and settings are kept.", { path: st.data_dir || "" });
  el.classList.remove("hidden");
});

$("#lockBtn").addEventListener("click", async () => {
  await api("auth/logout", {}).catch(() => {});
  showAuth();
});

$("#autoLock").addEventListener("change", async (ev) => {
  await api("auth/autolock", { minutes: +ev.target.value });
  toast(t("Saved"), "ok");
});

$("#lockEnabled").addEventListener("change", async (ev) => {
  const want = ev.target.checked;
  const current = $("#acCurrent").value;
  if (!current) {
    ev.target.checked = !want;
    $("details.acct").open = true; $("#acCurrent").focus();
    toast(t("Type your current password first."), "bad");
    return;
  }
  try {
    const r = await api("auth/update", { current, enabled: want });
    $("#acCurrent").value = "";
    $("#lockBtn").classList.toggle("hidden", !want);
    S.auth = r.status;
    toast(want ? t("The app will ask for your password.") : t("The app will open without a password."), "ok");
  } catch (e) { ev.target.checked = !want; toast(t(AUTH_ERR[e.message] || e.message), "bad"); }
});

$("#acSave").addEventListener("click", async () => {
  const body = { current: $("#acCurrent").value };
  if ($("#acUser").value.trim()) body.user = $("#acUser").value.trim();
  if ($("#acPass").value) {
    if ($("#acPass").value !== $("#acPass2").value) { toast(t("The passwords do not match."), "bad"); return; }
    body.password = $("#acPass").value;
  }
  if ($("#acHint").value.trim()) body.hint = $("#acHint").value.trim();
  try {
    const r = await api("auth/update", body);
    ["#acCurrent", "#acUser", "#acPass", "#acPass2", "#acHint"].forEach((s) => { $(s).value = ""; });
    $("#acctUser").textContent = r.status.user || "";
    toast(t("Account updated"), "ok");
  } catch (e) {
    toast(e.message === "invalid" ? t("Your current password is wrong.") : t(AUTH_ERR[e.message] || e.message), "bad");
  }
});

// Activity heartbeat (keeps auto-lock from firing while you use the app) + lock check
let active = false;
["mousedown", "keydown", "wheel", "touchstart"].forEach((ev) => document.addEventListener(ev, () => { active = true; }, { passive: true }));
setInterval(async () => {
  if (!S.booted || !$("#authScreen").classList.contains("hidden")) return;
  try {
    if (active) { active = false; await api("auth/touch", {}); }
    const st = await api("auth/status");
    if (!st.authed) showAuth(st);
  } catch { /* server restarting */ }
}, 45000);

(async function start() {
  let st = { setup: false, authed: false };
  try { st = await api("auth/status"); } catch (e) { toast(t("Can't reach the app server:") + " " + e.message, "bad"); }
  await setLang(detectLang(st.language), false);
  if (st.authed) afterSignIn(st); else showAuth(st);
})();
