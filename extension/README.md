# Clip this (browser extension)

Adds the video you are watching to ViralCut with one click.

1. In ViralCut: Settings, Browser extension. Copy the key.
2. In Chrome or Edge open `chrome://extensions` (`edge://extensions`), switch on Developer mode, choose Load unpacked, pick this folder.
3. Click the extension, open Settings in it, paste the key, Save.
4. On a YouTube, Twitch or Kick video page, click the extension, then "Clip this video".

It only talks to ViralCut on this computer (127.0.0.1 or localhost) and reads only the address of the current tab.

**YouTube sign-in (optional).** If YouTube says "Sign in to confirm you are not a bot", tick the box in the popup. The browser then asks to read YouTube
cookies (only YouTube), and the extension sends them to ViralCut on this computer every 30 minutes. ViralCut keeps them in `data/youtube-cookies.txt`
and uses them only after YouTube refuses, and only if Settings, YouTube access is on. This works with Chrome, Edge and Brave, whose saved cookies other programs cannot read.
Use a spare Google account. Press Forget in ViralCut (or untick the box) to remove them.
