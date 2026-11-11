# Local development

Start with [CONTEXT.md](../CONTEXT.md) for component ownership and
[CONTRIBUTING.md](../CONTRIBUTING.md) for the review workflow. All commands here
run from the repository root on the local Mac. The standalone build does not
require CrossOver or an Apple Developer membership.

## Build and play from source

For the automated source setup, clone or extract the repository into a permanent
folder and run `./Start.command`. It installs missing tools, builds the runtime,
validates/stages the graphics memory fixes, downloads the owned game, and launches
it. Reopen it to retry or play; use `--setup-only` to stop before launch and
`--check` for read-only readiness. See [the README](../README.md#start-from-source).
This path stores game data and worlds in the checkout. Keep it when updating
source; it does not automatically update a completed runtime or game. Source
setup always uses the checkout, including when `BEDROCK_HOME` or `BEDROCK_BUNDLE`
was inherited from a packaged-app command. Lower-level CLI commands still honor
`BEDROCK_HOME` when explicitly selected.

The manual recipe below builds a **separate, self-contained app**, with a data
root under Application Support. It does not import source-run worlds or game
files. Source setup and packaging use separate commands and validation records.

### Refresh a generated source checkout after a dependency update

An update to the reviewed `patches/Cargo.lock` can make an older generated Xodus
checkout fail source verification. Keep the check enabled. Save and quit Minecraft
normally, then move only `sources/xodus` into a new backup directory under
`sources/`. Preserve that backup, including any local changes. With the original
`sources/xodus` path now absent, run:

```sh
python3 tools/bootstrap-sources.py --project xodus
./Start.command
```

Leave `game/`, `bottles/`, settings and saves where they are. Bootstrap creates
only the new source checkout and refuses to overwrite an existing destination.
The normal startup flow then rebuilds changed helper inputs. Keep the old source
backup until the updated setup works.

## Prerequisites

The documented build host is Apple Silicon. Swift/DXMT target macOS 15, but the
minimum OS of an assembled app depends on every native binary, including Python
and Wine dependencies. Local 0.3.0 RC4 has an inspected macOS 15.0 floor;
the old macOS 26 statement does not apply to it. Inspect each later candidate
independently. See [release readiness](RELEASE.md).

Install Apple's Command Line Tools and Rosetta, Git, a Python 3.12+ interpreter
for dependency builds, source checks and packaging, Rust/rustup, and Homebrew
under `/opt/homebrew`. CI exercises Python 3.12 and 3.14. Homebrew's LLVM,
Bison, pkg-config and Protocol Buffers are build dependencies. GnuTLS and
FreeType are built from pinned sources by the dependency builder. The scripts
use their `/opt/homebrew/opt/...` paths; an Intel Homebrew installation is not a
drop-in replacement.

If these tools are not installed yet, start with the official
[Homebrew installation guide](https://brew.sh/) and
[Rust/rustup installation guide](https://rust-lang.org/tools/install/). Reopen
Terminal after configuring their PATH entries. A Homebrew Python can provide
the packaging interpreter (`brew install python@3.14`); check which `python3`
your shell selects before creating the venv.

With Homebrew and rustup already installed:

```sh
xcode-select --install  # only if Command Line Tools are missing
brew install llvm bison pkgconf protobuf
rustup toolchain install 1.98.0 --profile minimal
```

Check the selected tools before a long build:

```sh
uname -m
sw_vers -productVersion
xcrun --find clang
xcrun --find swiftc
python3 --version
rustup run 1.98.0 rustc --version
protoc --version
pkg-config --version
/usr/bin/arch -x86_64 /usr/bin/true
```

The last command must exit successfully for the Intel runtime to work. If
Rosetta is missing, follow [Apple's instructions](https://support.apple.com/en-us/102527).
The native app only checks for Rosetta. `Start.command` can request Apple’s
Rosetta installer during source setup; the user handles its license prompt.

### Build paths

Native dependency and Wine compilation require checkout, build, dependency
prefix, SDK and compiler/tool paths containing only **ASCII letters, digits,
`/`, `.`, `_`, `+` and `-`**. Spaces, other punctuation and non-ASCII names are
not supported by the underlying Autoconf/make flag handling. Symlink targets
must satisfy the same restriction; a short alias does not make an unsupported
location safe. Builders reject these paths before downloads or output changes.
Choose a location such as `~/git/bedrock-mac` with a compatible home-directory
path. This build restriction does not require moving or renaming installed
apps, game data or saves, whose paths can still contain spaces.

Building Wine and Rust uses much more storage than the player's 8 GB setup
check. Inspect `df -h .`, leave room for source, compiler output, archives, and
both app/DMG copies, and use a separate backup location for worlds. No measured
minimum build-space requirement or build-time guarantee is established.

## Build a launcher for this checkout

For a native launcher tied to this checkout, run `./Start.command --runtime-only`
and `./tools/build-launcher.sh`. Move the resulting `build/Bedrock for Mac.app`
to Applications and keep the checkout at the same path. Open the app and choose
**Install & Play** to sign in and acquire the game. The runtime build leaves
game acquisition to Play, so the launcher keeps one helper through first setup
and gameplay. The app stores its game and worlds in the checkout.

### Offline license diagnostic

The online content-license flow reports `BEDROCK_OFFLINE_LICENSE:candidate`
when Microsoft's response includes an unexpired offline lease matching the
machine-bound content key. Otherwise it reports `unavailable`. The diagnostic
does not expose or store license data and does not change the launch decision.
It does not verify a lease signature, designate an offline PC, or establish
that Wine can start Minecraft and load the expected profile offline.

The device, lease type and expiry checks follow the response fields documented
in the [Xodus Nexus offline licensing patches](https://github.com/domsvoboda/xodus-nexus/tree/backend-v0.2.13/assets).
Microsoft's [PC licensing model](https://learn.microsoft.com/en-us/gaming/gdk/docs/store/commerce/fundamentals/xstore-product-sharing-model-for-games)
requires a designated offline PC, initial online acquisition and periodic
renewal. A future launch path also needs secure storage bound to the local
account, device and content, revocation on explicit refusal, and native tests
with a disposable world and the connection unavailable.

## Build a complete local app

Clone the repository into a directory you control, then run:

```sh
git clone https://github.com/1JRobertson/bedrock-mac.git
cd bedrock-mac
python3 tools/bootstrap-sources.py
python3 tools/build-native-dependencies.py --destination "$PWD/build/native-dependencies" --jobs 3
STANDALONE_DEPENDENCY_PREFIX="$PWD/build/native-dependencies/prefix" \
  STANDALONE_JOBS=3 ./tools/build-standalone-wine.sh
./tools/build-standalone-graphics.sh --wine-runtime "$PWD/runtime/standalone/wine"
python3 client/standalone-setup.py --build-helper --jobs 4
python3 -m venv build/packaging-env
build/packaging-env/bin/python -m pip install -r tools/packaging-requirements.txt
python3 tools/package-launcher.py
python3 tools/build-dmg.py
```

Use Python 3.12+ throughout this recipe. The native dependency destination must
be new or empty; the builder refuses to reuse compiled outputs. Its `prefix/`
contains the libraries, matching headers, notices and verified receipt required
by the Wine builder. It does not install dependencies into Homebrew or the system.

Use a Python 3.12+ `python3` when creating `build/packaging-env`. If the venv
already uses an older Python, preserve/move it and create a new one with the
intended interpreter. Installing a newer system Python does not upgrade an
existing venv.

| Step | Result and behavior |
| --- | --- |
| Bootstrap | Fetches pinned WineGDK, Xodus and DXMT into `sources/`, applies tracked patches and Cargo lockfile; refuses an existing destination |
| Native dependencies | Downloads hash-pinned source archives and builds an isolated x86-64 prefix with matching headers and a verified receipt |
| Wine build | Compiles WineGDK in `build/standalone-wine`, installs to `runtime/standalone/wine`; requires `STANDALONE_DEPENDENCY_PREFIX` and copies its verified source-built dependencies |
| Graphics staging | Downloads/verifies pinned DXMT, installs its Wine overlay, and records original DLL backups |
| Helper build | Copies `client/standalone-helper.rs` into Xodus and builds its release example with the locked dependencies |
| Package | Builds Swift/icon and frozen Python worker; copies runtime/helper, signs locally, records resource hashes and actual OS requirement |
| DMG | Creates `build/Bedrock for Mac.dmg` containing the app and an Applications shortcut; verifies the image |

The complete app is `build/packaged/Bedrock for Mac.app`. It includes build
outputs for the open-source runtime but no game, Microsoft DLLs, Keychain data,
worlds, or development checkout. First Play obtains the required Microsoft
component and owned game. Build scripts never imply that a binary is cleared for
public redistribution; see [THIRD_PARTY.md](../THIRD_PARTY.md).

Do not run the Wine/graphics builds or replace an app while a game uses those
components. Quit Minecraft normally and let its account helper finish first.
The Wine and helper builders have active-process guards; still check which app
copy and runtime you are testing.

### Wine source verification failures

If setup stops with **Unexpected untracked or ignored Wine source inputs**, the
error lists up to five unexpected relative paths and the total count. Recheck the
actual build copy without compiling or installing:

```sh
python3 tools/verify-wine-source.py --source build/standalone-wine/source
```

Files added by reviewed patches, including the GDK Store/save files, normally
appear as untracked in the checkout's ordinary Git index. The verifier replays
the patches into a temporary index and accepts those exact additions. It still
rejects extra files, including ignored headers, and edits to reviewed files.
Regular `.DS_Store` files created by Finder are allowed and preserved. Symlinks
with that name and other unexpected source files are still rejected.
The check preserves the source files and real index. Keep existing files while
investigating the reported paths; manually staging the GDK files does not repair
a source mismatch. Report only reviewed path names, source release and Git
version, rather than full setup logs. See [issue #18](https://github.com/1JRobertson/bedrock-mac/issues/18).

For a candidate assembled from reviewed isolated inputs, the packager accepts
explicit runtime/helper and packaging-tool paths. Choose fresh output and work
directories; the packager refuses existing ones:

```sh
python3 tools/package-launcher.py \
  --wine /path/to/reviewed/wine --dxmt /path/to/reviewed/dxmt \
  --helper /path/to/reviewed/standalone_helper \
  --pyinstaller /path/to/packaging-env/bin/pyinstaller \
  --work-dir /path/to/new/package-work \
  --output '/path/to/new/Bedrock for Mac.app' \
  --version 0.1.0 --build-number 1
```

The version above is an example, not an announced release. Record the actual
version, complete resource manifest, DMG checksum and whole-bundle minimum OS.
These options do not qualify untested runtime profiles or authorize distribution.

The optional memory-lifetime bridge can be built and validated following
[the graphics notes](research/GRAPHICS.md) before packaging. Packaging
retains and verifies its provenance; see [stability notes](STABILITY.md).

## Reconstruct the selected release profile

[tools/build-release-runtime.py](../tools/build-release-runtime.py) and
[config/release-runtime-profile.json](../config/release-runtime-profile.json) pin the selected
WineGDK/DXMT sources, local patches and tool versions. They target the same
functional profile, not byte-identical binaries. The profile's validation/status
fields describe the recipe's initial qualification state; dated observations
live in [release readiness](RELEASE.md), and each new workspace needs its own
build and validation record. **The October 7 v4 source replay passed ten build steps and two exact-bridge
graphics validation steps.** RC4 packages that runtime. This establishes a
recorded source build and graphics probes, not byte-identical reproducibility,
gameplay, or successful fresh acquisition.

Start with a read-only plan, then prepare a fresh workspace whose parent exists:

```sh
python3 tools/build-release-runtime.py plan --workspace /absolute/new-build
python3 tools/build-release-runtime.py prepare --workspace /absolute/new-build
```

Before `build`, supply the profile's hash-verified LLVM-MinGW archive, a separate
venv with its exact Meson/Ninja versions, and a source-built x86-64 dependency
prefix with `dependency-manifest.json` and matching headers/libraries. The v4 replay used the audited source-built native dependency prefix;
the driver refuses binary-only fallback. See `python3 tools/build-release-runtime.py --help` for the
explicit input, jobs and shared-lock options.

The build records commands and logs without running a game or account probe.
After Minecraft has exited normally, `validate` uses a private prefix to check
the exact graphics bridge before staging it. Preserve the source inventory,
notices, dependency receipt, `release-runtime-state.json`, build/graphics logs
and component manifests. Package the workspace's explicit Wine/DXMT inputs
with the separately rebuilt helper, then qualify that new artifact for gameplay,
M1, updates and multiplayer. Graphics probes do not pass those gates.

## Iterate without losing a working build

`./tools/build-launcher.sh` creates `build/Bedrock for Mac.app`, a development front end
that points at this checkout and uses `/usr/bin/python3`. It is useful for Swift
and worker changes after preparing the local runtime, but is not a portable app.
`python3 launcher/setup.py --status` inspects its installation without sign-in.

The packager refuses to overwrite an existing output. Use a new output name:

```sh
python3 tools/package-launcher.py --output 'build/iteration-2/Bedrock for Mac.app'
python3 tools/build-dmg.py --app 'build/iteration-2/Bedrock for Mac.app' \
  --output 'build/Bedrock for Mac-iteration-2.dmg'
```

A failed DMG creation or verification leaves the chosen final output absent,
so that output can be retried. An existing output is preserved, including one
created by another build during packaging. Atomic DMG publication requires a
filesystem with hard-link support, such as APFS or HFS+. Build locally there,
then copy the verified DMG and its receipt to an exFAT/FAT volume if needed.

Choose a fresh suffix for each retained build. Launcher, frozen worker and
PyInstaller intermediates live in the isolated work directory, which defaults
to `<output-parent>/<app-stem>-build`. Reusing that parent and stem also reuses
the default work path; choose a fresh `--work-dir` if it already exists. Keep
heavy builds serial during qualification. A packaged app copies its components;
subsequent checkout edits do not update it. Repackage to test them.

After a Wine rebuild, rerun graphics staging with `--wine-runtime`: Wine's
installed D3D DLLs otherwise shadow DXMT. For helper source changes, use
`client/standalone-setup.py --build-helper`; `legacy/build-helper.sh` compiles the historical
`bedrock_helper`, not the native launcher's `standalone_helper`.

Rebuilding an ad-hoc helper can change Keychain authorization. To test remembered
access, launch the same helper bytes twice after the user authorizes it; do not
rebuild between attempts. Never change Keychain permissions just to force a pass.

## Command-line setup and diagnostics

The source CLI works in the checkout by default. Do not use it to infer the state
of a packaged app's separate data directory. To read that installation's status:

```sh
BEDROCK_HOME="$HOME/Library/Application Support/Bedrock for Mac" \
  python3 client/standalone-setup.py --check
```

`--check` is local and returns nonzero when installation is incomplete. It does
not access Microsoft or Keychain. `--dry-run` prints requested actions without
performing them. For a source installation, these are the actual setup stages:

```sh
python3 client/standalone-setup.py --threading
python3 client/standalone-setup.py --download-game --game-dir "$PWD/game" --market CA
python3 client/standalone.py prepare
python3 client/standalone.py launch --market CA
```

Download and launch can sign in and contact Microsoft; they are not offline
checks. The separate CLI invocations also use separate helper sessions. Use the
native launcher when testing its single-session onboarding UX. A custom
`--game-dir` must be supplied consistently to setup and runtime commands. A
different game directory cannot silently replace an existing `G:` drive mapping
in the same prepared prefix.

For optional probes, after installing the owned game and runtime:

```sh
./tools/build-standalone-probes.sh
python3 client/standalone.py probe graphics
```

The graphics probe exercises the local Wine prefix. The `account`, `store`, and
`privileges` probes also use the account helper and may prompt/contact Microsoft.
See [CLI reference](CLI.md),
[graphics notes](research/GRAPHICS.md), and [testing](TESTING.md).

## Build failures

| Failure | Check |
| --- | --- |
| Bootstrap destination exists | Run `python3 tools/bootstrap-sources.py --check`; preserve local changes before preparing a new source tree. Do not fetch a different branch into the pinned checkout to silence a mismatch. |
| Cargo lock or source patch mismatch | Compare tracked patches, `patches/Cargo.lock`, and the pinned source check. Keep `--locked`; update provenance and checksums intentionally. |
| Missing native dependency prefix | Build a fresh prefix with `tools/build-native-dependencies.py`, then set `STANDALONE_DEPENDENCY_PREFIX` to its `prefix/` directory. Homebrew dylibs or a binary-only archive do not satisfy the receipt check. |
| `protoc` missing | Check the `protobuf` installation and PATH, or the intended `PROTOC` executable. |
| Wine configure/compile/install failure | Read `build/standalone-wine/configure.log`, `build.log`, or `install.log`; confirm the required Homebrew paths and Rust toolchain. |
| DXMT mismatch after runtime rebuild | Reapply the graphics overlay with `--wine-runtime` before preparing/launching. |
| Package dependency missing | Build Wine, stage DXMT, build the standalone helper, and install the packaging requirements into the expected venv. |
| Package/DMG destination exists | Choose a new output path; keep the running or last working copy. |
| New bundle needs a newer macOS | Inspect its `Contents/Info.plist` and native dependency targets. Lowering the plist alone does not make it compatible. |

Validate the appropriate boundaries in [TESTING.md](TESTING.md), then update the
[source inventory](PUBLISHING.md#update-the-source-inventory). A successful build
is not evidence of a fresh-account download, gameplay, or a clean-Mac install.

The launcher builder handles duplicate legacy `SwiftBridging` module maps in
some Command Line Tools installations with a build-local VFS overlay. It does
not edit the system toolchain. Keep the generated build logs when reporting a
remaining Swift compile failure.
