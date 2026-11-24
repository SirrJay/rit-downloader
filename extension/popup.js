chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
  document.getElementById("t").textContent = tab.title || tab.url;
  chrome.runtime.sendMessage({ type: "ping" }, (ok) => { document.getElementById("off").hidden = !!ok; });
  document.getElementById("open").onclick = () => { chrome.runtime.sendMessage({ type: "open", url: tab.url }); window.close(); };
  for (const mode of ["video", "audio"]) {
    document.getElementById(mode).onclick = () => {
      chrome.runtime.sendMessage({ type: "download", url: tab.url, title: tab.title, mode }, () => window.close());
    };
  }
});
