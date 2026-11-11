#!/bin/sh
# Build a local native front end; no developer account or Xcode app required.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/build/Bedrock for Mac.app"
WORK="$ROOT/build"
VERSION="0.3.0"
BUILD="3"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) APP="$2"; shift 2 ;;
    --work-dir) WORK="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --build-number) BUILD="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -e "$APP" ] || [ -L "$APP" ]; then
  echo "Output already exists; choose a new --output path." >&2
  exit 1
fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$WORK/swift-module-cache"
# Full Xcode's compiler needs an explicit macOS SDK when invoked directly.
# Select its matching Apple toolchain/SDK instead of inheriting an SDKROOT or
# TOOLCHAINS value from another build environment.
SWIFTC=$(/usr/bin/xcrun --sdk macosx --toolchain default --find swiftc)
SDKROOT=$(/usr/bin/xcrun --sdk macosx --toolchain default --show-sdk-path)
export SDKROOT
# Some upgraded Command Line Tools retain an obsolete second definition of
# SwiftBridging. Shadow that one file locally; never edit the system toolchain.
/usr/bin/python3 - "$SWIFTC" "$WORK" <<'PY_OVERLAY'
import json, pathlib, sys
compiler, work = map(pathlib.Path, sys.argv[1:])
headers = compiler.parent.parent / 'include/swift'
legacy, current = headers / 'module.modulemap', headers / 'bridging.modulemap'
if all(p.is_file() and 'module SwiftBridging {' in p.read_text() for p in (legacy, current)):
    empty = work.absolute() / 'empty-swift.modulemap'
    empty.write_text('// Build-local shadow of obsolete duplicate module map.\n')
    (work / 'swift-overlay.json').write_text(json.dumps({'version': 0, 'roots': [
        {'type': 'file', 'name': str(legacy), 'external-contents': str(empty)}]}))
PY_OVERLAY
set --
if [ -f "$WORK/swift-overlay.json" ]; then
  set -- -vfsoverlay "$WORK/swift-overlay.json" -Xcc -ivfsoverlay -Xcc "$WORK/swift-overlay.json"
fi
"$SWIFTC" "$@" -sdk "$SDKROOT" -parse-as-library -O -target arm64-apple-macos15.0 -module-cache-path "$WORK/swift-module-cache" \
  "$ROOT/launcher/BedrockLauncher.swift" -o "$APP/Contents/MacOS/BedrockLauncher"
"$SWIFTC" "$@" -sdk "$SDKROOT" -O -module-cache-path "$WORK/swift-module-cache" "$ROOT/launcher/Icon.swift" -o "$WORK/make-icon"
"$WORK/make-icon" "$WORK/AppIcon.iconset"
iconutil -c icns "$WORK/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
/usr/bin/python3 - "$ROOT" "$APP" "$VERSION" "$BUILD" <<'PY'
import pathlib, plistlib, sys
root, app, version, build = sys.argv[1:]
with (pathlib.Path(app) / 'Contents/Info.plist').open('wb') as out:
    plistlib.dump(dict(CFBundleExecutable='BedrockLauncher', CFBundleIdentifier='local.bedrock.mac.launcher',
        CFBundleName='Macrock', CFBundleDisplayName='Macrock',
        CFBundlePackageType='APPL', CFBundleIconFile='AppIcon', CFBundleVersion=build, CFBundleShortVersionString=version,
        LSMinimumSystemVersion='15.0', NSHighResolutionCapable=True, BedrockProjectPath=root), out)
PY
codesign --force --sign - "$APP"
printf 'Built %s\n' "$APP"
