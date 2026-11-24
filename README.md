# Rit Downloader

Search YouTube (and other sites), load every video a person or channel has published, and download them one at a time or in bulk, as video or audio, in the quality you choose.

## Languages and sign-in
- **13 languages**: English, Français, Español, Português, Deutsch, Bahasa Indonesia, Русский, Kiswahili, Hausa, Yorùbá, العربية (right-to-left), 中文 and हिन्दी. The app follows your computer's language, and you can change it with the selector in the top bar or on the sign-in screen.
- **App lock**: on first launch you create a username and password for this computer. You can choose "Keep me signed in", lock the app with the padlock button, set auto-lock after a period of inactivity, or turn the password off in **Settings > Account and security**. Downloads keep running while the app is locked.
- Forgot your password? Quit the app and delete `auth.json` in the app's data folder: `%LOCALAPPDATA%\RitDownloader` on Windows, `~/Library/Application Support/RitDownloader` on a Mac. Your downloads and settings are kept.
- To add or fix a translation, edit `app/static/i18n/<code>.json` (English text maps to the translation), then run `python packaging/i18n_keys.py` to check coverage.

## Start
Double-click **Rit Downloader** on the Desktop or in the Start menu. You can also run `Rit Downloader.bat`.
The app opens in its own window. Downloads keep running if you close the window. To stop everything, go to **Settings > Quit app**.

## Download all of a preacher's sermons
1. **Browse > Channels & people**, then type the name and click **Search**.
2. On the right channel, click **Load all videos**. This loads the channel's videos and its live-stream services.
3. Optional: filter by words in the title or by length (for example *Over 1 hour*), and sort by *Newest first*.
4. Choose **Video** (Best / 4K / 1080p / 720p / ..., MP4 / MKV / WebM / MOV / AVI) or **Audio** (MP3 / M4A / Opus / OGG / FLAC / WAV, Best to 64 kbps).
5. Click **Download all shown**, or select items (Shift+click selects a range) and click **Download selected**.

Run the same channel again later. Files you already downloaded are skipped automatically, so you get only the new ones.
To pick an exact stream, click the slider icon on any video to see every quality it offers.

## Other sites
- Keyword search: YouTube, SoundCloud, Bilibili, Niconico.
- **Paste a link** works for about 1,800 sites: Facebook, Instagram, TikTok, X, Vimeo, Rumble, Twitch, Dailymotion and more. It accepts playlist and profile links as well as single videos.
- Private, members-only or age-restricted videos, and sites that need a login: sign in with your browser, then turn on **Settings > Sign-in > Use cookies from a browser**.

## Browser extension (optional)
In Chrome or Edge, open `chrome://extensions` (or `edge://extensions`), turn on **Developer mode**, click **Load unpacked**, and choose the `extension` folder.
You then get a toolbar button and right-click options: *Open in Rit Downloader*, *Download video* and *Download audio (MP3)*. The app must be running.

## Maintenance
- If downloads start failing, go to **Settings > Update**. Sites change often and the engine (yt-dlp) needs to keep up.
- **Install.bat** repairs or reinstalls everything, including ffmpeg and the desktop shortcut.
- By default, files are saved to `F:\Rit Downloads`, on the drive with the most free space. You can change this in Settings.

## Files
- `app/engine.py`: search, listing, download queue (yt-dlp)
- `app/server.py`: local server, available only at http://127.0.0.1:8765
- `app/static/`: the user interface
- `bin/`: ffmpeg
- `data/`: settings and the download queue
- `extension/`: browser extension

Please download only content you have the right to keep, such as freely shared sermons or your own uploads, and respect each site's terms.
