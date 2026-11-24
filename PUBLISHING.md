# Building and publishing Rit Downloader

## What you get

| File | For | Notes |
|---|---|---|
| `RitDownloader-Setup-Windows.exe` | Windows 10 and 11, 64-bit (also runs on Windows on ARM) | Normal installer. No admin rights needed. Adds Start menu and desktop shortcuts and an uninstaller. |
| `RitDownloader-Portable-Windows.zip` | Windows, without installing | Unzip and run `RitDownloader.exe`. |
| `RitDownloader-macOS-AppleSilicon.dmg` | Macs with M1, M2, M3 or M4, macOS 11 or newer | Drag to Applications. |
| `RitDownloader-macOS-Intel.dmg` | Intel Macs, macOS 11 or newer | Drag to Applications. |

Everything the app needs is included: Python, ffmpeg, the Deno JavaScript runtime and the download engine. Users install nothing else.
Not supported: Windows 7 and 8, 32-bit Windows, and macOS 10.x. Current Python no longer runs on them.

## 1. Build the Windows installer on this PC

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -Version 1.0.0
```

The output goes to `build\installer\`.

## 2. Build the Mac versions

A Mac app can only be built on a Mac. You don't need to own one: **GitHub builds both Mac versions and the Windows version for free** on its cloud computers, using the workflow in `.github/workflows/release.yml`.
If you do have a Mac, you can run `bash packaging/mac/build_mac.sh` on it instead.

## 3. Publish on the internet with GitHub (free)

### One-time setup
1. Create a free account at https://github.com.
2. Create a new repository, for example `rit-downloader`. Make it **Public**: free unlimited build minutes and public downloads need this.
3. Upload this folder from this PC:
   ```powershell
   cd "C:\Rit Playlist Download"
   git init
   git add .
   git commit -m "Rit Downloader 1.0.0"
   git branch -M main
   git remote add origin https://github.com/YOUR-NAME/rit-downloader.git
   git push -u origin main
   ```
   `.gitignore` keeps out large and personal files: `.venv`, `bin`, `build` and `data`.

### Release a version
```powershell
git tag v1.0.0
git push origin v1.0.0
```
GitHub then builds the Windows installer and both Mac disk images, which takes about 15 to 25 minutes. It publishes them on a **Releases** page:
`https://github.com/YOUR-NAME/rit-downloader/releases`

Each build has your repository name built in, so the apps tell users when a new version is out.

### Download website (GitHub Pages)
In your repository, go to **Settings > Pages**. Under Source, choose *Deploy from a branch*, then select the **main** branch and the **/docs** folder, and click Save.
After a minute your site is live at `https://YOUR-NAME.github.io/rit-downloader/`.
It detects Windows or Mac and offers the right file. These download links always point to the newest release:

```
https://github.com/YOUR-NAME/rit-downloader/releases/latest/download/RitDownloader-Setup-Windows.exe
https://github.com/YOUR-NAME/rit-downloader/releases/latest/download/RitDownloader-macOS-AppleSilicon.dmg
https://github.com/YOUR-NAME/rit-downloader/releases/latest/download/RitDownloader-macOS-Intel.dmg
```

Optional: take a screenshot of the app, save it as `docs/screenshot.png`, and it appears on the site. To use your own domain, add it under Settings > Pages > Custom domain.

### Updating later
Change the code, push it, then tag the next version (`git tag v1.0.1 && git push origin v1.0.1`). Users see an "update available" banner.
The download engine (yt-dlp) updates separately. Users click **Settings > Update** inside the app, with no reinstall.

## 4. Remove the security warnings (optional, paid)

Without code signing, the apps work, but first-time users see a warning.

| | Warning without signing | How to remove it | Cost (approx.) |
|---|---|---|---|
| Windows | "Windows protected your PC" (SmartScreen). Users click *More info > Run anyway*. | Code-signing certificate. **Azure Trusted Signing** is the cheapest option, or an OV/EV certificate from Certum, Sectigo, SSL.com and others. Set `RIT_SIGN_CMD` in the workflow. | about $10 a month (Azure), $100 to $400 a year (certificate) |
| Mac | "Apple could not verify..." Users must click *Open Anyway* in System Settings. | **Apple Developer Program** membership, then a Developer ID certificate and notarization. Add the repository secrets `MAC_CERT_P12`, `MAC_CERT_PASSWORD`, `MAC_SIGN_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID` and `APPLE_APP_PASSWORD`. The workflow already signs and notarizes when they are present. | $99 a year |

The SmartScreen warning also fades by itself as more people download the same signed file.

## 5. Other places to publish (optional)
- **winget** (Windows Package Manager): submit a manifest to https://github.com/microsoft/winget-pkgs. Users can then run `winget install RitDownloader`.
- **Homebrew** (Mac): create a "tap" with a cask that points to your .dmg.
- **Microsoft Store and Mac App Store**: these usually reject YouTube downloaders, so publishing on your own site or GitHub is the realistic route.

## Things to know before publishing
- **Content rights.** Downloading from YouTube is against YouTube's Terms of Service except where YouTube allows it. Present the app as a tool for content users have rights to, such as a ministry's own sermons or freely shared material. Don't use YouTube's logo or name in your branding.
- **Licenses.** FFmpeg is GPL software. Ship `THIRD_PARTY_NOTICES.txt`, which the installer already includes, and keep the links to FFmpeg's source.
- **Hosting.** GitHub Releases is free for public projects, with no bandwidth bill. Pick a name that doesn't impersonate another product.
