#!/usr/bin/env bash
# Builds "Rit Downloader.app" and a .dmg.  Must run on a Mac (locally or in GitHub Actions).
#   bash packaging/mac/build_mac.sh [mac-arm64|mac-x64]
# Optional env: RIT_VERSION, RIT_UPDATE_REPO, PYTHON
#   Signing/notarization (removes the "unidentified developer" warning):
#   MAC_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)", APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  if [ "$(uname -m)" = "arm64" ]; then TARGET=mac-arm64; else TARGET=mac-x64; fi
fi
LABEL=$([ "$TARGET" = "mac-arm64" ] && echo "AppleSilicon" || echo "Intel")
PY="${PYTHON:-python3}"

[ -n "${RIT_VERSION:-}" ] && sed -i '' "s/^VERSION = .*/VERSION = \"${RIT_VERSION}\"/" app/version.py
[ -n "${RIT_UPDATE_REPO:-}" ] && sed -i '' "s|^UPDATE_REPO = .*|UPDATE_REPO = \"${RIT_UPDATE_REPO}\"|" app/version.py
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' app/version.py)
echo "== Building Rit Downloader ${VERSION} for ${TARGET}"

"$PY" -m venv build/venv
# shellcheck disable=SC1091
source build/venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q --upgrade -r packaging/requirements.txt

python app/setup_ffmpeg.py --dest "build/tools/${TARGET}" --target "${TARGET}" --deno

RIT_TOOLS="${ROOT}/build/tools/${TARGET}" python -m PyInstaller --noconfirm --clean \
  --distpath build/dist --workpath build/work packaging/rit.spec

APP="build/dist/Rit Downloader.app"
if [ -n "${MAC_SIGN_IDENTITY:-}" ]; then
  echo "== Signing with ${MAC_SIGN_IDENTITY}"
  codesign --force --deep --options runtime --timestamp \
    --entitlements packaging/mac/entitlements.plist -s "${MAC_SIGN_IDENTITY}" "${APP}"
else
  echo "== Ad-hoc signing (users will need to approve the app the first time)"
  codesign --force --deep -s - "${APP}"
fi

STAGE=build/dmg
rm -rf "${STAGE}" && mkdir -p "${STAGE}" build/installer
cp -R "${APP}" "${STAGE}/"
ln -s /Applications "${STAGE}/Applications"
cp packaging/mac/README-FIRST.txt "${STAGE}/Read me first.txt"
cp -R extension "${STAGE}/Browser extension"
DMG="build/installer/RitDownloader-macOS-${LABEL}.dmg"
rm -f "${DMG}"
hdiutil create -volname "Rit Downloader" -srcfolder "${STAGE}" -ov -format UDZO "${DMG}"

if [ -n "${MAC_SIGN_IDENTITY:-}" ] && [ -n "${APPLE_ID:-}" ]; then
  echo "== Notarizing (a few minutes)"
  codesign -s "${MAC_SIGN_IDENTITY}" --timestamp "${DMG}"
  xcrun notarytool submit "${DMG}" --apple-id "${APPLE_ID}" --team-id "${APPLE_TEAM_ID}" \
    --password "${APPLE_APP_PASSWORD}" --wait
  xcrun stapler staple "${DMG}"
fi
ls -lh build/installer
