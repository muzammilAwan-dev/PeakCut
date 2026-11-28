// Keeps ViralCut's copy of the YouTube sign-in fresh (only when you switched sharing on in the popup).
importScripts("sync.js");

function plan() { chrome.alarms.create("vc-sync", { periodInMinutes: 30 }); }
chrome.runtime.onInstalled.addListener(plan);
chrome.runtime.onStartup.addListener(() => { plan(); vcSendYouTubeCookies(); });
chrome.alarms.onAlarm.addListener(a => { if (a.name === "vc-sync") vcSendYouTubeCookies(); });
