// Sends the address of the tab you are on to your own ViralCut. Nothing else is read or sent.
const $ = id => document.getElementById(id);
const DEFAULT_SERVER = "http://127.0.0.1:8765";
const say = (text, kind = "") => { $("msg").textContent = text; $("msg").className = kind; };

function cleanServer(value) {
  let u;
  try { u = new URL((value || DEFAULT_SERVER).trim()); } catch { return null; }
  // the extension is only allowed to talk to this computer (see manifest.json)
  if (u.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(u.hostname)) return null;
  return u.origin;
}

async function load() {
  const saved = await chrome.storage.local.get(["server", "token"]);
  $("server").value = saved.server || DEFAULT_SERVER;
  $("token").value = saved.token || "";
  if (!saved.token) { $("setup").open = true; say("Paste your key in Settings first."); }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $("page").textContent = tab && tab.url ? tab.url : "";
  const ok = tab && /^https?:\/\//i.test(tab.url || "");
  $("go").disabled = !ok || !saved.token;
  if (!ok) say("Open a video page first.");
  return tab;
}

$("save").addEventListener("click", async () => {
  const server = cleanServer($("server").value);
  if (!server) return say("The address must be this computer, for example http://127.0.0.1:8765", "bad");
  await chrome.storage.local.set({ server, token: $("token").value.trim() });
  say("Saved.", "ok");
  load();
});

$("go").addEventListener("click", async () => {
  const saved = await chrome.storage.local.get(["server", "token"]);
  const server = cleanServer(saved.server);
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!server || !saved.token || !tab || !/^https?:\/\//i.test(tab.url || "")) return say("Check the settings and the page.", "bad");
  $("go").disabled = true;
  say("Sending ...");
  try {
    const r = await fetch(server + "/api/ext/clip", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Token": saved.token }, body: JSON.stringify({ url: tab.url }),
    });
    const j = await r.json().catch(() => ({}));
    if (r.ok) say(j.message || "Added.", "ok");
    else say(j.detail || "ViralCut said no (" + r.status + ").", "bad");
  } catch {
    say("Could not reach ViralCut. Is it running on this computer?", "bad");
  }
  $("go").disabled = false;
});

load();
