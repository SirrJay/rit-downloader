/* Rit Downloader - built-in media player.
   Plays downloaded files (every format: unsupported ones are converted on the fly by the app) and online
   videos straight from search results (streamed, no download needed). One <video> element plays both audio
   and video; it keeps playing while you use the rest of the app (mini-player at the bottom). */
"use strict";
const Player = (() => {
  const LS = (k, d) => { try { const v = JSON.parse(localStorage.getItem("rit.pl." + k)); return v ?? d; } catch { return d; } };
  const SS = (k, v) => localStorage.setItem("rit.pl." + k, JSON.stringify(v));
  const P = {
    items: [], byKey: new Map(), remote: LS("remote", {}), queue: LS("queue", []), index: LS("index", -1),
    speed: LS("speed", 1), volume: LS("volume", 1), muted: false, shuffle: LS("shuffle", false), repeat: LS("repeat", "off"),
    pos: LS("pos", {}), dur: LS("dur", {}), done: LS("done", {}), sleepAt: null, sleepEnd: false, side: "queue", loaded: false,
    mode: "direct", base: 0, src: null, token: 0, retried: false, lastKey: null,
  };
  const v = () => $("#plVideo");
  const cur = () => P.queue[P.index];
  const isRemote = (k) => String(k || "").startsWith("remote:");
  const item = (k) => P.byKey.get(k) || P.remote[k] || { key: k, path: k, title: String(k).split(/[\\/]/).pop(), channel: "",
    type: /\.(mp4|webm|mkv|mov|m4v|avi|wmv|flv|ts|3gp|mpg|mpeg)$/i.test(k) ? "video" : "audio" };
  const now = () => P.base + (v().currentTime || 0);
  const total = () => {
    const k = cur(), it = k ? item(k) : null, known = (it && it.duration) || P.dur[k] || 0;
    return P.mode === "pipe" ? known : ((isFinite(v().duration) && v().duration) || known);
  };

  async function load(force) {
    if (P.loaded && !force) return;
    try {
      const { items } = await api("player/items");
      const old = P.byKey;   // keep what the player already learned (length, type) about each file
      P.items = items.map((x) => ({ ...x, ...(old.get(x.path) ? { duration: old.get(x.path).duration, type: old.get(x.path).type } : {}), key: x.path }));
      P.byKey = new Map(P.items.map((x) => [x.key, x]));
      P.loaded = true;
      P.queue = P.queue.filter((k) => P.byKey.has(k) || P.remote[k]);
      if (P.index >= P.queue.length) P.index = P.queue.length - 1;
      fillChannels(); renderList(); renderNow();
    } catch { /* locked or restarting */ }
  }

  // ------------------------------------------------------------------ queue + playing
  function setQueue(keys, start = 0, opts = {}) {
    if (!keys.length) return;
    P.queue = keys.slice(); P.index = Math.max(0, Math.min(start, keys.length - 1));
    if (P.shuffle && !opts.keepOrder) {
      const first = P.queue[P.index]; const rest = P.queue.filter((_, i) => i !== P.index);
      for (let i = rest.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [rest[i], rest[j]] = [rest[j], rest[i]]; }
      P.queue = [first, ...rest]; P.index = 0;
    }
    save(); open(true);
    if (!opts.background) showView("player");
  }
  async function open(autoplay) {
    const key = cur(), el = v(), token = ++P.token;
    if (P.lastKey !== key) P.retried = false;
    P.lastKey = key;
    if (!key) { el.removeAttribute("src"); el.load(); renderNow(); return; }
    const it = item(key);
    setLoading(true);
    $("#plStage").classList.toggle("is-video", it.type === "video");
    renderNow();
    let srcFor;
    try {
      if (isRemote(key)) {
        const s = await api("stream/open", { url: it.url, audio: !!it.audioOnly });
        if (token !== P.token) return;
        Object.assign(it, { type: s.type, duration: s.duration || it.duration, title: it.title || s.title,
          thumb: it.thumb || s.thumb, channel: it.channel || s.channel, vid: it.vid || s.vid });
        P.remote[key] = it; SS("remote", P.remote);
        if (s.duration) { P.dur[key] = s.duration; SS("dur", P.dur); }
        P.mode = s.kind === "proxy" ? "direct" : "pipe";
        srcFor = (tt) => `/api/stream/${s.id}` + (P.mode === "pipe" ? `?t=${tt.toFixed(1)}` : "");
      } else {
        const info = await api("play/info?path=" + encodeURIComponent(key));
        if (token !== P.token) return;
        Object.assign(it, { type: info.type, duration: info.duration || it.duration });
        if (info.duration) { P.dur[key] = info.duration; SS("dur", P.dur); }
        P.mode = info.mode === "direct" ? "direct" : "pipe";
        const base = "/api/play/stream?path=" + encodeURIComponent(key);
        srcFor = (tt) => base + (P.mode === "pipe" ? `&t=${tt.toFixed(1)}` : "");
      }
    } catch (e) {
      if (token !== P.token) return;
      setLoading(false);
      toast(e.message || t("This file could not be played. It may have been moved or deleted."), "bad");
      return;
    }
    P.src = srcFor;
    const d = it.duration || P.dur[key] || 0;
    const resume = P.pos[key] || 0;
    const canResume = resume > Math.min(5, (d || 100) / 10) && (!d || resume < d - Math.min(10, d * 0.05));
    P.base = P.mode === "pipe" && canResume ? resume : 0;
    el.src = srcFor(P.base);
    el.playbackRate = P.speed; el.volume = P.volume; el.muted = P.muted;
    el.onloadedmetadata = () => {
      if (token !== P.token) return;
      el.onloadedmetadata = null;
      if (P.mode === "direct" && canResume) el.currentTime = resume;
      if (canResume) toast(t("Continuing where you stopped ({t})", { t: fmtDur(resume) }));
      if (P.mode === "direct" && el.duration && isFinite(el.duration)) { P.dur[key] = el.duration; SS("dur", P.dur); }
      else if (d) { P.dur[key] = d; SS("dur", P.dur); }
      el.playbackRate = P.speed;
      setLoading(false); tick();
    };
    if (autoplay) el.play().catch(() => {});
    $("#plStage").classList.toggle("is-video", it.type === "video");
    renderNow(); renderList(); mediaSession(it);
  }
  function seekTo(target) {
    const el = v(); if (!cur() || !P.src) return;
    const d = total();
    target = Math.max(0, d ? Math.min(d - 0.5, target) : target);
    if (P.mode === "direct") { el.currentTime = target; return; }
    // converted or online stream: restart the stream at the new position
    const wasPlaying = !el.paused;
    P.base = target; setLoading(true);
    el.src = P.src(target); el.playbackRate = P.speed;
    if (wasPlaying) el.play().catch(() => {});
    tick();
  }
  function toggle() { const el = v(); if (!cur()) { if (P.queue.length) { P.index = 0; open(true); } return; } el.paused ? el.play().catch(() => {}) : el.pause(); }
  function next(manual = true) {
    if (!P.queue.length) return;
    if (P.repeat === "one" && !manual) { seekTo(0); v().play().catch(() => {}); return; }
    if (P.index < P.queue.length - 1) P.index++;
    else if (P.repeat === "all") P.index = 0;
    else { v().pause(); renderNow(); return; }
    save(); open(true);
  }
  function prev() {
    if (now() > 4) { seekTo(0); return; }
    if (P.index > 0) { P.index--; save(); open(true); }
  }
  const seekBy = (s) => seekTo(now() + s);
  function stop() { const el = v(); el.pause(); el.removeAttribute("src"); el.load(); P.index = -1; P.token++; P.src = null; save(); setLoading(false); renderNow(); }
  function setSpeed(x) { P.speed = +x; v().playbackRate = P.speed; SS("speed", P.speed); renderNow(); }
  function save() { SS("queue", P.queue); SS("index", P.index); }
  function setLoading(on) { $("#plLoading").classList.toggle("hidden", !on); }

  function addNext(keys) {
    if (!P.queue.length || P.index < 0) return setQueue(keys, 0, { background: true });
    P.queue.splice(P.index + 1, 0, ...keys.filter((k) => !P.queue.includes(k)));
    save(); renderList(); toast(t("Added to Up next"), "ok");
  }
  function removeAt(i) {
    if (i === P.index) { P.queue.splice(i, 1); if (P.index >= P.queue.length) P.index = P.queue.length - 1; save(); open(true); return; }
    P.queue.splice(i, 1); if (i < P.index) P.index--; save(); renderList();
  }
  function addRemote(entries, audio) {
    return entries.map((e) => {
      const key = "remote:" + (audio ? "a:" : "v:") + e.url;
      P.remote[key] = { key, url: e.url, title: e.title, thumb: e.thumb, channel: e.channel, duration: e.duration, vid: e.vid,
        type: audio ? "audio" : "video", audioOnly: !!audio, remote: true, date: e.date };
      return key;
    });
  }

  // ------------------------------------------------------------------ rendering
  function renderNow() {
    const key = cur(), it = key ? item(key) : null, el = v();
    $("#plEmpty").classList.toggle("hidden", !!it);
    $("#plTitle").textContent = it ? it.title : t("Nothing playing");
    const bits = it ? [it.channel, it.type === "audio" ? t("Audio") : t("Video"), it.remote ? t("Streaming online") : "", fmtDate(it.date)] : [];
    $("#plSub").textContent = it ? bits.filter(Boolean).join(" · ") : t("Choose something from your downloads.");
    const cover = $("#plCover");
    if (it && it.type === "audio" && it.thumb) { cover.src = it.thumb; cover.classList.remove("hidden"); } else cover.classList.add("hidden");
    $("#plArt").classList.toggle("hidden", !(it && it.type === "audio" && !it.thumb));
    $("#plDownload").classList.toggle("hidden", !(it && it.remote));
    const playing = it && !el.paused;
    $$(".pl-playbtn").forEach((b) => { b.innerHTML = playing ? ICON_PAUSE : ICON_PLAY; b.title = playing ? t("Pause") : t("Play"); });
    $("#plShuffle").classList.toggle("on", P.shuffle);
    $("#plRepeat").classList.toggle("on", P.repeat !== "off");
    $("#plRepeat").innerHTML = P.repeat === "one" ? ICON_REPEAT1 : ICON_REPEAT;
    $("#plRepeat").title = { off: t("Repeat: off"), all: t("Repeat: all"), one: t("Repeat: this one") }[P.repeat];
    $("#plSpeed").value = String(P.speed);
    $("#plVol").value = P.muted ? 0 : P.volume;
    $("#plPip").classList.toggle("hidden", !(it && it.type === "video" && document.pictureInPictureEnabled));
    const onPlayer = $("#view-player").classList.contains("on");
    $("#miniPlayer").classList.toggle("hidden", !it || onPlayer);
    if (it) {
      $("#mpTitle").textContent = it.title;
      $("#mpSub").textContent = [it.channel, it.remote ? t("Streaming online") : ""].filter(Boolean).join(" · ");
      const th = $("#mpThumb"); if (it.thumb) { th.src = it.thumb; th.classList.remove("hidden"); } else th.classList.add("hidden");
      $("#mpSpeed").textContent = P.speed + "×";
    }
    updateSleepLabel();
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = playing ? "playing" : "paused";
  }
  let seeking = false;
  function tick() {
    const el = v(), key = cur();
    if (!key) return;
    const d = total(), c = now();
    if (!seeking) $("#plSeek").value = d ? Math.round(1000 * c / d) : 0;
    $("#plCur").textContent = fmtDur(c); $("#plDur").textContent = d ? fmtDur(d) : "0:00";
    $("#mpBar").style.width = (d ? Math.min(100, 100 * c / d) : 0) + "%";
    $("#mpTime").textContent = `${fmtDur(c)} / ${d ? fmtDur(d) : "0:00"}`;
    if (d && Math.abs((P.pos[key] || 0) - c) > Math.min(4, d / 20)) {
      P.pos[key] = c > d - Math.min(15, d * 0.05) ? 0 : c; SS("pos", P.pos);
      const row = $(`#plList [data-key="${CSS.escape(key)}"] .pl-prog i`); if (row) row.style.width = (100 * c / d) + "%";
    }
    if ("mediaSession" in navigator && d && navigator.mediaSession.setPositionState) {
      try { navigator.mediaSession.setPositionState({ duration: d, playbackRate: el.playbackRate, position: Math.min(c, d) }); } catch { /* ignore */ }
    }
    if (P.sleepAt && Date.now() >= P.sleepAt) { el.pause(); P.sleepAt = null; $("#plSleep").value = "0"; toast(t("Sleep timer: playback stopped."), "ok"); }
    updateSleepLabel();
  }
  function updateSleepLabel() {
    const lbl = $("#plSleepLeft");
    if (P.sleepAt) lbl.textContent = fmtDur(Math.max(0, (P.sleepAt - Date.now()) / 1000));
    else lbl.textContent = P.sleepEnd ? t("end of this item") : "";
  }
  function filtered() {
    const q = ($("#plSearch").value || "").toLowerCase().trim();
    const ty = $("#plType").value, ch = $("#plChannel").value;
    return P.items.filter((x) => (!ty || x.type === ty) && (!ch || (x.channel || "") === ch)
      && (!q || (x.title + " " + x.channel).toLowerCase().includes(q)));
  }
  function fillChannels() {
    const sel = $("#plChannel"), keep = sel.value;
    const names = [...new Set(P.items.map((x) => x.channel || ""))].filter(Boolean).sort((a, b) => a.localeCompare(b));
    sel.innerHTML = `<option value="">${esc(t("All channels"))}</option>` + names.map((n) => `<option>${esc(n)}</option>`).join("");
    sel.value = names.includes(keep) ? keep : "";
  }
  function rowHtml(it, i, inQueue) {
    const key = it.key || it.path, on = key === cur();
    const d = P.dur[key] || it.duration, p = P.pos[key] || 0, done = P.done[key];
    const pct = done ? 100 : (d ? Math.min(100, 100 * p / d) : 0);
    const sym = it.type === "audio" ? "♪" : "▶";
    const pic = it.thumb ? `<img loading="lazy" src="${esc(it.thumb)}" alt="" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'pl-ph',textContent:'${sym}'}))">`
      : `<span class="pl-ph">${sym}</span>`;
    return `<div class="pl-row${on ? " on" : ""}${done ? " done" : ""}" data-key="${esc(key)}" data-i="${i}">
      <div class="pl-pic">${pic}${on && !v().paused ? '<span class="eq"><i></i><i></i><i></i></span>' : ""}${it.remote ? '<span class="pl-live" title="' + esc(t("Streaming online")) + '">🌐</span>' : ""}</div>
      <div class="pl-txt"><div class="pl-t" title="${esc(it.title)}">${esc(it.title)}</div>
        <div class="pl-m">${esc(it.channel || "")}${it.channel ? " · " : ""}${it.type === "audio" ? esc(t("Audio")) : esc(t("Video"))}${d ? " · " + fmtDur(d) : ""}${done ? " · ✓ " + esc(t("Played")) : (p > 5 ? " · " + esc(t("{t} played", { t: fmtDur(p) })) : "")}</div>
        <div class="pl-prog"><i style="width:${pct}%"></i></div></div>
      <div class="pl-acts">${inQueue ? `<button class="btn ghost icon sm" data-pa="rm" title="${esc(t("Remove from Up next"))}">✕</button>` :
        `<button class="btn ghost icon sm" data-pa="next" title="${esc(t("Play next"))}">＋</button>`}</div></div>`;
  }
  function renderList() {
    const box = $("#plList"); if (!box) return;
    $$("#plSideTabs button").forEach((b) => b.classList.toggle("on", b.dataset.pl === P.side));
    $("#plFilters").classList.toggle("hidden", P.side !== "library");
    $("#plQueueTools").classList.toggle("hidden", P.side !== "queue");
    if (P.side === "queue") {
      box.innerHTML = P.queue.length ? P.queue.map((k, i) => rowHtml(item(k), i, true)).join("")
        : `<div class="pl-emptylist">${esc(t("Up next is empty. Open All media and click a file, or use Play in Downloads and Library."))}</div>`;
      $("#plQCount").textContent = P.queue.length ? t("{n} items", { n: P.queue.length }) : "";
    } else {
      const list = filtered();
      box.innerHTML = list.length ? list.map((it, i) => rowHtml(it, i, false)).join("")
        : `<div class="pl-emptylist">${esc(P.items.length ? t("Nothing matches.") : t("No audio or video downloaded yet."))}</div>`;
      $("#plLibCount").textContent = t("{n} items", { n: list.length });
    }
  }
  function mediaSession(it) {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({ title: it.title, artist: it.channel || "Rit Downloader", album: "Rit Downloader",
        artwork: it.thumb ? [{ src: it.thumb, sizes: "320x180", type: "image/jpeg" }] : [] });
      const h = { play: () => v().play(), pause: () => v().pause(), previoustrack: prev, nexttrack: () => next(true),
        seekbackward: () => seekBy(-10), seekforward: () => seekBy(30), seekto: (d) => seekTo(d.seekTime) };
      for (const [k, fn] of Object.entries(h)) { try { navigator.mediaSession.setActionHandler(k, fn); } catch { /* unsupported */ } }
    } catch { /* ignore */ }
  }

  // ------------------------------------------------------------------ events
  function bind() {
    const el = v();
    el.addEventListener("timeupdate", tick);
    el.addEventListener("playing", () => setLoading(false));
    el.addEventListener("waiting", () => setLoading(true));
    el.addEventListener("canplay", () => setLoading(false));
    el.addEventListener("play", () => { renderNow(); renderList(); });
    el.addEventListener("pause", () => { renderNow(); renderList(); tick(); });
    el.addEventListener("ended", () => {
      const key = cur(); if (key) { P.done[key] = true; P.pos[key] = 0; SS("done", P.done); SS("pos", P.pos); }
      if (P.sleepEnd) { P.sleepEnd = false; $("#plSleep").value = "0"; renderNow(); toast(t("Sleep timer: playback stopped."), "ok"); return; }
      next(false);
    });
    el.addEventListener("error", () => {
      const key = cur(); if (!key || !el.getAttribute("src")) return;
      setLoading(false);
      if (!P.retried) { P.retried = true; P.pos[key] = now(); open(true); return; }   // e.g. an expired online stream: try once more
      toast(t("This file could not be played. It may have been moved or deleted."), "bad");
      setTimeout(() => next(false), 1500);
    });
    el.addEventListener("dblclick", fullscreen);
    el.addEventListener("click", toggle);
    $("#plSeek").addEventListener("input", () => { seeking = true; $("#plCur").textContent = fmtDur(total() * $("#plSeek").value / 1000); });
    $("#plSeek").addEventListener("change", () => { seeking = false; seekTo(total() * $("#plSeek").value / 1000); });
    $("#mpProgress").addEventListener("click", (e) => { const r = e.currentTarget.getBoundingClientRect(); seekTo(total() * (e.clientX - r.left) / r.width); });
    $$(".pl-playbtn").forEach((b) => b.addEventListener("click", toggle));
    $$("[data-plc]").forEach((b) => b.addEventListener("click", () => {
      const a = b.dataset.plc;
      if (a === "prev") prev(); if (a === "next") next(true);
      if (a === "back") seekBy(-10); if (a === "fwd") seekBy(30);
      if (a === "expand") showView("player");
      if (a === "stop") stop();
      if (a === "speed") { const sp = [0.75, 1, 1.25, 1.5, 1.75, 2]; setSpeed(sp[(sp.indexOf(P.speed) + 1) % sp.length]); }
    }));
    $("#plShuffle").addEventListener("click", () => { P.shuffle = !P.shuffle; SS("shuffle", P.shuffle); renderNow(); toast(P.shuffle ? t("Shuffle on") : t("Shuffle off")); });
    $("#plRepeat").addEventListener("click", () => { P.repeat = { off: "all", all: "one", one: "off" }[P.repeat]; SS("repeat", P.repeat); renderNow(); });
    $("#plSpeed").addEventListener("change", (e) => setSpeed(e.target.value));
    $("#plVol").addEventListener("input", (e) => { P.volume = +e.target.value; P.muted = P.volume === 0; el.volume = P.volume; el.muted = P.muted; SS("volume", P.volume); });
    $("#plMute").addEventListener("click", () => { P.muted = !P.muted; el.muted = P.muted; renderNow(); });
    $("#plFull").addEventListener("click", fullscreen);
    $("#plPip").addEventListener("click", () => { if (document.pictureInPictureElement) document.exitPictureInPicture(); else el.requestPictureInPicture().catch(() => {}); });
    $("#plDownload").addEventListener("click", async () => {
      const it = item(cur()); if (!it || !it.remote) return;
      const r = await api("download", { items: [{ url: it.url, title: it.title, thumb: it.thumb, channel: it.channel, vid: it.vid, duration: it.duration }],
        options: barOptions({ mode: it.audioOnly ? "audio" : "video" }) });
      toast(r.added ? t("Added to downloads") : r.already ? t("{n} already downloaded (skipped)", { n: 1 }) : t("Already in the download list"), "ok");
    });
    $("#plSleep").addEventListener("change", (e) => {
      const m = e.target.value; P.sleepAt = null; P.sleepEnd = false;
      if (m === "end") P.sleepEnd = true; else if (+m) P.sleepAt = Date.now() + (+m) * 60000;
      if (m !== "0") toast(t("Sleep timer set."), "ok");
      updateSleepLabel();
    });
    $("#plSideTabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; P.side = b.dataset.pl; renderList(); });
    ["#plSearch", "#plType", "#plChannel"].forEach((s) => $(s).addEventListener("input", renderList));
    $("#plPlayAll").addEventListener("click", () => { const l = filtered(); if (l.length) setQueue(l.map((x) => x.key), 0, { keepOrder: !P.shuffle }); });
    $("#plClearQ").addEventListener("click", () => { P.queue = cur() ? [cur()] : []; P.index = P.queue.length ? 0 : -1; save(); renderList(); });
    $("#plRefresh").addEventListener("click", () => load(true));
    $("#plList").addEventListener("click", (e) => {
      const row = e.target.closest(".pl-row"); if (!row) return;
      const btn = e.target.closest("[data-pa]");
      const i = +row.dataset.i, key = row.dataset.key;
      if (btn && btn.dataset.pa === "rm") return removeAt(i);
      if (btn && btn.dataset.pa === "next") return addNext([key]);
      if (P.side === "queue") { P.index = i; save(); open(true); }
      else { const l = filtered(); setQueue(l.map((x) => x.key), i, { keepOrder: true }); }
    });
    document.addEventListener("keydown", (e) => {
      if (!cur() || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.target.closest("input, textarea, select, [contenteditable]")) return;
      if (!$("#authScreen").classList.contains("hidden")) return;
      const k = e.key, onPlayer = $("#view-player").classList.contains("on");
      if (k === " " || k === "k" || k === "K") { e.preventDefault(); toggle(); }
      else if (k === "ArrowRight" || k === "l") { e.preventDefault(); e.shiftKey ? next(true) : seekBy(k === "l" ? 30 : 10); }
      else if (k === "ArrowLeft" || k === "j") { e.preventDefault(); e.shiftKey ? prev() : seekBy(-10); }
      else if (k === "ArrowUp" && onPlayer) { e.preventDefault(); el.volume = P.volume = Math.min(1, P.volume + 0.1); SS("volume", P.volume); renderNow(); }
      else if (k === "ArrowDown" && onPlayer) { e.preventDefault(); el.volume = P.volume = Math.max(0, P.volume - 0.1); SS("volume", P.volume); renderNow(); }
      else if (k === "m" || k === "M") { P.muted = !P.muted; el.muted = P.muted; renderNow(); }
      else if ((k === "f" || k === "F") && onPlayer) fullscreen();
      else if (k === "n" || k === "N") next(true);
      else if (k === "p" || k === "P") prev();
    });
    document.addEventListener("langchange", () => { fillChannels(); renderList(); renderNow(); });
  }
  function fullscreen() {
    const st = $("#plScreen");
    if (document.fullscreenElement) document.exitFullscreen(); else st.requestFullscreen().catch(() => {});
  }
  const ICON_PLAY = '<svg class="ico" viewBox="0 0 24 24"><path d="M7 4v16l13-8z" fill="currentColor"/></svg>';
  const ICON_PAUSE = '<svg class="ico" viewBox="0 0 24 24"><rect x="6" y="4" width="4" height="16" fill="currentColor"/><rect x="14" y="4" width="4" height="16" fill="currentColor"/></svg>';
  const ICON_REPEAT = '<svg class="ico" viewBox="0 0 24 24"><path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/></svg>';
  const ICON_REPEAT1 = ICON_REPEAT.replace("</svg>", '<text x="10" y="15" font-size="7" fill="currentColor" stroke="none">1</text></svg>');

  return {
    init() { bind(); renderNow(); if (P.index >= 0 && P.queue[P.index]) load().then(() => open(false)); },
    load, addNext, renderNow, item,
    /** play downloaded files (paths); queue = the given list */
    play(path, list) { const keys = list && list.length ? list : [path]; setQueue(keys, Math.max(0, keys.indexOf(path)), { keepOrder: true }); },
    /** play online videos from search results without downloading; audio=true streams the sound only */
    playRemote(entries, start = 0, audio = false) { const keys = addRemote(entries, audio); SS("remote", P.remote); setQueue(keys, start, { keepOrder: true }); },
    queueRemote(entries, audio = false) { const keys = addRemote(entries, audio); SS("remote", P.remote); addNext(keys); },
    async playVideo(vid, mode) {
      await load(true);
      const it = P.items.find((x) => x.vid === vid && x.type === (mode === "video" ? "video" : "audio")) || P.items.find((x) => x.vid === vid);
      if (it) setQueue([it.key], 0); else toast(t("This file could not be played. It may have been moved or deleted."), "bad");
    },
    onView(view) { if (view === "player") load(true); renderNow(); },
  };
})();
