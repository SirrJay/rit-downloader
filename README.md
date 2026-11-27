# Rit Downloader

Search YouTube (and other sites), load every video a person or channel has published, and download them one at a time or in bulk, as video or audio, in the quality you choose.

## Sign-in for restricted videos ("Could not copy Chrome cookie database")
Public videos never need a sign-in, so keep **Settings > Sign-in** set to **Off** unless you download age-restricted, members-only or private videos.
- **On Windows, Chrome and Edge can't be used for sign-in.** They lock their sign-in data while open and encrypt it even when closed. That causes the error "Could not copy Chrome cookie database".
- **What works:** **Firefox** (signed in to YouTube), or a **cookies.txt file**. To get one, install the free browser extension "Get cookies.txt LOCALLY", open youtube.com while signed in, click Export, then choose the file in Settings > Sign-in.
- Click **Test sign-in** to check the source right away.
- If a sign-in can't be read, downloads **continue without it** and a banner explains what happened. Downloads no longer fail because of this.

## Built-in player
Open the **Player** tab to watch and listen to everything you have downloaded.
- **All media** lists your audio and video. Search it, filter by channel or type, then click a file or **Play all**. **Up next** is your play queue; use ＋ to add an item to play next.
- It **continues where you stopped** in every file, and shows how much of each you have played.
- **Speed** from 0.75× to 2×, **sleep timer** (15–60 minutes, or at the end of an item), **shuffle**, **repeat** (all or one), **full screen** and **picture-in-picture** for video.
- A **mini-player** at the bottom keeps playing while you search, download or browse your library.
- **Keys:** Space play/pause, ← → 10 seconds, Shift+← → previous/next, M mute, F full screen. Keyboard media keys work too.
- **Play** buttons appear in Downloads, in Library (per channel, and in each channel's Files window) and on downloaded videos in Browse.

## Software and any file
- Choose **Browse > Software & files**, or try one of the example programs shown there (VLC, 7-Zip, LibreOffice, OBS Studio, Audacity, GIMP, Python…). Then paste a direct download link (.exe, .msi, .zip, .7z, .dmg, .pkg, .apk, .iso, .pdf…) to download that file.
- Or paste a program's **download page** from any website. Rit Downloader lists every downloadable file on the page, labelled with its type (EXE, MSI, ZIP…). If a page only links to another page that holds the files, the app follows it.
- **GitHub projects:** paste any github.com project link to get the files of its latest release.
- A few websites block automatic downloads. For those, right-click the download button in your browser, choose "Copy link", and paste that link.
- Files download with **several connections at once** (Settings > Speed) and can be **paused and resumed**, even after a restart.
- Each finished file shows its **SHA-256** checksum. Click it to copy, then compare it with the checksum on the website to make sure the file is genuine.
- Programs are labelled **Program** and are never run automatically. On Windows they keep the "downloaded from the internet" mark, so SmartScreen still checks them.
- Files are saved in a **Software** folder inside your download folder. You can rename it in Settings.

## Play, delete and clear
- **Play** audio and video right inside the app (Downloads list and Library > Files).
- **Delete files** from Downloads ("Delete file"), from Browse (✕ on a downloaded video, or "Delete selected files") and from Library ("Files" for any channel: delete selected, delete all, or "Remove from library" to keep the files and forget the history).
- Deleted files go to the **Recycle Bin**, so you can get them back. Only files that Rit Downloader downloaded can be deleted.
- **Clear results** in Browse. Duplicate copies found by the library can be deleted with one click.
- **Optional:** turn on Settings > "Offer to download links I copy". When you copy a video or download link anywhere, the app offers to download it.

## The download list
- **What you ask for last downloads first.** A new request goes to the front of the queue, and older unfinished items wait behind it. Every waiting item shows its place ("Number 3 in line").
- **One row per channel** when several channels are in the list, each with **Download first**, **Pause**, **Resume** and **Remove**. Click a channel's name to show only that channel.
- **Download next** on any waiting item moves it to the front.
- **Clear finished**, **Clear failed** and **Clear all** empty the list. Clear all stops running downloads. Files already downloaded are never deleted.
- **No internet?** Downloads wait ("Waiting for internet connection") and continue by themselves when the connection is back. No attempts are wasted.

## Reliability and extra options
- **Clear errors.** Messages such as "private video", "members only", "age-restricted", "not available in your country", "live stream not started" or "disk full" explain what to do.
- **Automatic retries.** Network problems and YouTube rate limits are retried up to 3 times, with growing waits.
- **Disk guard.** Downloads pause before the disk fills up. You choose how much space to keep free.
- **Download hours.** Download only during set hours, such as cheap night-time data.
- **When finished.** Optionally put the computer to sleep or shut it down. You get 2 minutes to cancel, and the option resets after each use.
- **Notifications** when downloads finish, via the tray or menu-bar icon.
- **Part of a video.** Open a video's quality list and set "Only from … to …" to keep, for example, just the sermon.
- **Even out the volume** of audio downloads, which helps with live-recorded sermons.
- **Proxy** support, plus a search box and filter in Downloads.
- **Skip short clips** when getting new videos from a channel (Library).

## No duplicates, and every channel keeps its own folder
- **Library**: Rit Downloader remembers every file you've downloaded, in any folder. Videos you already have are marked **Downloaded** with a green tick, and they're skipped automatically. They're never queued twice, even from the browser extension.
- **One folder per channel**: each channel's videos always go to that channel's folder. The folder stays the same even if you change the download folder later. You can move a channel's folder in **Library > Change folder**.
- **New videos only**: open a channel and click **Download new (N)**, or click **Check for new** in the **Library** tab. Turn on **Keep up to date** and new sermons download automatically into the channel's folder (every 6, 12 or 24 hours).
- **Existing downloads are recognised**: on first start, the app reads earlier skip lists and your download history, then scans your download folders. Use **Rescan folders** or **Add a folder** in Library for other locations.
- **Duplicate report**: if two copies of the same video exist, Library lists them with **Show in folder**. Nothing is ever deleted for you.
- **Want it again?** Click a video's ✓ button twice to download it again. In Library, "If I delete a downloaded file" decides whether deleted files come back.

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
