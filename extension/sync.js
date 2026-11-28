// Sends the YouTube sign-in of THIS browser to your own ViralCut on this computer, only if you switched it on in the popup.
// Used by the popup (right away) and by background.js (now and then, because YouTube renews these cookies).
const VC_DEFAULT_SERVER = "http://127.0.0.1:8765";

function vcServer(value) {
  let u;
  try { u = new URL((value || VC_DEFAULT_SERVER).trim()); } catch { return null; }
  if (u.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(u.hostname)) return null;
  return u.origin;
}

// Netscape cookie file text: the format yt-dlp reads.
function vcNetscape(cookies) {
  const now = Math.floor(Date.now() / 1000);
  const lines = ["# Netscape HTTP Cookie File"];
  for (const c of cookies) {
    if (!c.name || String(c.value || "").length > 4096) continue;
    const dom = c.domain || "";
    const expiry = c.expirationDate ? Math.floor(c.expirationDate) : now + 30 * 86400;
    lines.push([c.httpOnly ? "#HttpOnly_" + dom : dom, dom.startsWith(".") ? "TRUE" : "FALSE", c.path || "/", c.secure ? "TRUE" : "FALSE", expiry, c.name, c.value].join("\t"));
  }
  return lines.join("\n") + "\n";
}

// Returns {ok, message}. Never throws.
async function vcSendYouTubeCookies() {
  try {
    const saved = await chrome.storage.local.get(["server", "token", "shareYT"]);
    if (!saved.shareYT) return { ok: false, message: "Off." };
    const server = vcServer(saved.server);
    if (!server || !saved.token) return { ok: false, message: "Paste the ViralCut key in Settings first." };
    if (!(await chrome.permissions.contains({ permissions: ["cookies"], origins: ["https://*.youtube.com/*"] }))) return { ok: false, message: "Allow reading YouTube cookies first." };
    const cookies = await chrome.cookies.getAll({ domain: "youtube.com" });
    if (!cookies.length) return { ok: false, message: "Sign in to YouTube in this browser first." };
    const r = await fetch(server + "/api/ext/cookies", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Token": saved.token }, body: JSON.stringify({ cookies: vcNetscape(cookies) }),
    });
    const j = await r.json().catch(() => ({}));
    return r.ok ? { ok: true, message: j.message || "Sent." } : { ok: false, message: j.detail || "ViralCut said no (" + r.status + ")." };
  } catch {
    return { ok: false, message: "Could not reach ViralCut. Is it running on this computer?" };
  }
}
