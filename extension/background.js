const APP = "http://127.0.0.1:8765/";

async function appRunning() {
  try { const r = await fetch(APP + "api/ping"); return r.ok; } catch { return false; }
}

function notify(msg) {
  chrome.notifications.create({ type: "basic", iconUrl: "icon128.png", title: "Rit Downloader", message: msg });
}

async function sendDownload(url, title, mode) {
  if (!(await appRunning())) {
    notify("The Rit Downloader app isn't running. Start it from your desktop shortcut, then try again.");
    return false;
  }
  const r = await fetch(APP + "api/download", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: [{ url, title }], options: { mode } }),
  });
  const j = await r.json().catch(() => ({}));
  notify(j.added ? `Added to downloads (${mode}).` : "It's already in the download list.");
  return true;
}

async function openInApp(url) {
  if (!(await appRunning())) {
    notify("The Rit Downloader app isn't running. Start it from your desktop shortcut, then try again.");
    return;
  }
  chrome.tabs.create({ url: APP + "?url=" + encodeURIComponent(url) });
}

chrome.runtime.onInstalled.addListener(() => {
  const ctx = ["page", "link", "video", "audio"];
  chrome.contextMenus.create({ id: "rit-open", title: "Open in Rit Downloader (list everything)", contexts: ctx });
  chrome.contextMenus.create({ id: "rit-video", title: "Download video with Rit Downloader", contexts: ctx });
  chrome.contextMenus.create({ id: "rit-audio", title: "Download audio (MP3) with Rit Downloader", contexts: ctx });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const url = info.linkUrl || info.srcUrl || info.pageUrl || (tab && tab.url);
  if (!url) return;
  if (info.menuItemId === "rit-open") openInApp(url);
  if (info.menuItemId === "rit-video") sendDownload(url, info.linkUrl ? "" : tab?.title, "video");
  if (info.menuItemId === "rit-audio") sendDownload(url, info.linkUrl ? "" : tab?.title, "audio");
});

chrome.runtime.onMessage.addListener((msg, _s, reply) => {
  if (msg.type === "ping") appRunning().then(reply);
  if (msg.type === "download") sendDownload(msg.url, msg.title, msg.mode).then(reply);
  if (msg.type === "open") { openInApp(msg.url); reply(true); }
  return true;
});
