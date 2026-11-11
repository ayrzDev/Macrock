#!/bin/sh
# Compile the patched WineGDK source without any CrossOver binaries.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD="$ROOT/build/standalone-wine"
PREFIX="$ROOT/runtime/standalone/wine"
JOBS=${STANDALONE_JOBS:-3}
SOURCE="$BUILD/source"
# Autoconf/make consume these paths inside compiler flags. Reject unsupported
# lexical paths and resolved symlink targets before any cache/runtime mutation.
if [ -z "${STANDALONE_DEPENDENCY_PREFIX:-}" ]; then
  printf 'Build pinned native dependencies first, then set STANDALONE_DEPENDENCY_PREFIX.\n' >&2
  exit 1
fi
python3 -B - "$ROOT" "$STANDALONE_DEPENDENCY_PREFIX" "$BUILD" "$PREFIX" "$SOURCE" <<'PYPATHS'
import importlib.util, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("native_paths", root / "tools/build-native-dependencies.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    for value, label in zip(sys.argv[1:], ("source checkout", "dependency prefix", "Wine build", "Wine runtime", "Wine source")):
        module.require_build_path(value, label)
    for name in ("lib", "include", "notices"):
        module.require_build_path(pathlib.Path(sys.argv[4]) / name, "Wine " + name)
except ValueError as error:
    raise SystemExit("Wine build stopped: " + str(error)) from None
PYPATHS
SDK=$(/usr/bin/xcrun --show-sdk-path)
CLANG=$(/usr/bin/xcrun --find clang)
CLANGXX=$(/usr/bin/xcrun --find clang++)
RUST_TOOLCHAIN=$(rustup run 1.98.0 rustc --print sysroot)
PKG_CONFIG_BIN=$(command -v "${PKG_CONFIG:-pkg-config}" || true)
case "$PKG_CONFIG_BIN" in
  /*|'') ;;
  *) PKG_CONFIG_BIN="$PWD/$PKG_CONFIG_BIN" ;;
esac
if [ -z "$PKG_CONFIG_BIN" ]; then
  printf 'pkg-config is required to build Wine.\n' >&2
  exit 1
fi
python3 -B - "$ROOT" "$SDK" "$CLANG" "$CLANGXX" "$RUST_TOOLCHAIN" "$PKG_CONFIG_BIN" <<'PYTOOLS'
import importlib.util, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("native_paths", root / "tools/build-native-dependencies.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    for value, label in zip(sys.argv[2:], ("macOS SDK", "C compiler", "C++ compiler", "Rust sysroot", "pkg-config")):
        module.require_build_path(value, label)
    module.require_build_path(pathlib.Path(sys.argv[5]) / "lib/rustlib/aarch64-apple-darwin/bin/rust-lld", "Rust linker")
    module.require_build_path("/opt/homebrew/opt/llvm/bin/clang", "MinGW compiler")
except ValueError as error:
    raise SystemExit("Wine build stopped: " + str(error)) from None
PYTOOLS
export PKG_CONFIG="$PKG_CONFIG_BIN"
# Refuse runtime mutation while a prefix is using these installed Unix libraries.
if [ -f "$PREFIX/lib/wine/x86_64-unix/ntdll.so" ] &&
   /usr/sbin/lsof -t "$PREFIX/lib/wine/x86_64-unix/ntdll.so" 2>/dev/null | read -r runtime_pid; then
  printf 'Close standalone Wine applications before rebuilding this runtime.\n' >&2
  exit 1
fi
mkdir -p "$BUILD/toolbin" "$BUILD/downloads" "$PREFIX/lib"
export LC_ALL=en_US.UTF-8
# Only a verified, source-built dependency closure is accepted. Prepare it in
# a separate directory with tools/build-native-dependencies.py; do not reuse unknown
# libraries from an older binary archive.
python3 - "$ROOT" "$STANDALONE_DEPENDENCY_PREFIX" "$PREFIX" <<'PYDEPS'
import importlib.util, pathlib, shutil, sys
root, dependencies, prefix = map(pathlib.Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("native_dependencies", root / "tools/build-native-dependencies.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.verify(dependencies)
if prefix.is_symlink() or any((prefix / name).is_symlink() for name in ("lib", "include", "notices")):
    raise SystemExit("Runtime dependency directories must not be symlinks")
for existing in (prefix / "lib").iterdir():
    if existing.name != "wine" and not (dependencies / "lib" / existing.name).exists():
        raise SystemExit("Existing runtime has untracked dependencies; use a fresh isolated runtime: " + existing.name)
retained_links = set()
for name in ("lib", "include", "notices"):
    for source in (dependencies / name).rglob("*"):
        target = prefix / source.relative_to(dependencies)
        if source.is_symlink() and target.is_symlink() and source.readlink() == target.readlink():
            retained_links.add(source)
        elif target.is_symlink() or (source.is_symlink() and target.exists()):
            raise SystemExit("Existing runtime has a conflicting dependency link: " + str(target))

def ignore_retained(directory, names):
    return [name for name in names if pathlib.Path(directory) / name in retained_links]

for name in ("lib", "include", "notices"):
    shutil.copytree(dependencies / name, prefix / name, symlinks=True, dirs_exist_ok=True, ignore=ignore_retained)
shutil.copyfile(dependencies / "dependency-manifest.json", prefix / "native-dependency-manifest.json")
PYDEPS
if [ ! -d "$SOURCE" ]; then
  cp -cRp "$ROOT/sources/winegdk" "$SOURCE"
fi
# Later patches can alter earlier hunks, so check the complete reviewed tree
# before attempting individual reverse checks on an existing build.
if ! python3 "$ROOT/tools/verify-wine-source.py" --source "$SOURCE" --output "$BUILD/source-verification.json" >/dev/null 2>&1; then
  for PATCH in "$ROOT"/patches/standalone-wine-*.patch; do
    if ! git -C "$SOURCE" apply --reverse --check "$PATCH" 2>/dev/null; then
      git -C "$SOURCE" apply --check "$PATCH"
      git -C "$SOURCE" apply "$PATCH"
    fi
  done
  python3 "$ROOT/tools/verify-wine-source.py" --source "$SOURCE" --output "$BUILD/source-verification.json"
fi
cat > "$BUILD/toolbin/lld-link" <<EOF
#!/bin/sh
export DYLD_LIBRARY_PATH='$RUST_TOOLCHAIN/lib'
exec '$RUST_TOOLCHAIN/lib/rustlib/aarch64-apple-darwin/bin/rust-lld' -flavor link "\$@"
EOF
chmod +x "$BUILD/toolbin/lld-link"
export PATH="$BUILD/toolbin:/opt/homebrew/opt/llvm/bin:/opt/homebrew/opt/bison/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"
export CC="$CLANG -arch x86_64 -isysroot $SDK"
export CXX="$CLANGXX -arch x86_64 -isysroot $SDK"
export OBJC="$CC"
export MACOSX_DEPLOYMENT_TARGET=15.0
export CFLAGS='-O2 -mmacosx-version-min=15.0'
export CXXFLAGS='-O2 -mmacosx-version-min=15.0'
export OBJCFLAGS='-O2 -mmacosx-version-min=15.0'
export LDFLAGS='-mmacosx-version-min=15.0'
export CROSSCFLAGS='-O2'
export LC_ALL=en_US.UTF-8
# Use headers from the same verified source build as the linked libraries.
export GNUTLS_CFLAGS="-I$PREFIX/include"
export GNUTLS_LIBS="-L$PREFIX/lib -lgnutls"
export FREETYPE_CFLAGS="-I$PREFIX/include/freetype2"
export FREETYPE_LIBS="-L$PREFIX/lib -Wl,-rpath,$PREFIX/lib -lfreetype"
export DYLD_FALLBACK_LIBRARY_PATH="$PREFIX/lib:/usr/lib"
# Portable install names avoid configure misparsing dylibs with bare Mach-O IDs.
export ac_cv_lib_soname_gnutls='@loader_path/../../libgnutls.30.dylib'
export ac_cv_lib_soname_freetype='@loader_path/../../libfreetype.6.dylib'
cd "$BUILD"
"$SOURCE/configure" --host=x86_64-apple-darwin24 \
  --prefix="$PREFIX" --enable-win64 \
  --with-mingw=/opt/homebrew/opt/llvm/bin/clang --disable-tests \
  --without-x --with-freetype --with-gnutls --without-vulkan \
  --without-gstreamer --without-ffmpeg > "$BUILD/configure.log" 2>&1
make -j"$JOBS" > "$BUILD/build.log" 2>&1
python3 "$ROOT/tools/verify-wine-source.py" --source "$SOURCE" --check-receipt "$BUILD/source-verification.json"
make install > "$BUILD/install.log" 2>&1
python3 "$ROOT/tools/verify-wine-source.py" --source "$SOURCE" --check-receipt "$BUILD/source-verification.json"
python3 - "$ROOT" "$PREFIX" "$SOURCE" <<'PYMANIFEST'
import hashlib, json, pathlib, subprocess, sys
root, prefix, source = map(pathlib.Path, sys.argv[1:])
manifest = {
    "wine_source_repository": "https://github.com/Sightem/WineGDK",
    "wine_source_revision": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
    "wine_version": subprocess.check_output([str(prefix / "bin/wine"), "--version"], text=True).strip(),
    "architecture": "x86_64",
    "source_verification": json.loads((source.parent / "source-verification.json").read_text()),
    "native_dependency_manifest": json.loads((prefix / "native-dependency-manifest.json").read_text()),
    "patches": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "patches").glob("standalone-wine*.patch")},
    "required_portable_libraries": sorted(p.name for p in (prefix / "lib").glob("*.dylib")),
    "capabilities": {"win64": True, "win32": False, "macdriver": True, "coreaudio": True,
                     "gnutls": True, "freetype": True, "gstreamer": False, "vulkan": False},
    "graphics": "Run tools/build-standalone-graphics.sh --wine-runtime with this prefix after rebuilding Wine; validate graphics before gameplay."
}
(prefix / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PYMANIFEST
/bin/sh "$ROOT/native/file-pickers/build.sh" --wine-build "$BUILD" \
  --output "$ROOT/build/file-pickers" --stage-runtime "$PREFIX"
printf 'Built standalone Wine: %s\n' "$PREFIX/bin/wine"
