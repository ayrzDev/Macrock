# Architecture

Bedrock for Mac opens the owner's **Windows Minecraft Bedrock** game on Apple
Silicon through WineGDK, DXMT and Rosetta. The native launcher handles setup,
Microsoft sign-in, updates and recovery; Minecraft keeps its vanilla menus for
worlds, packs, settings and friends.

The public project is a source preview. `Start.command` builds and plays from the
checkout; a separately packaged native app uses its own data root. No public
notarized installer is available. See [setup](README.md#start-from-source),
[build instructions](docs/DEVELOPMENT.md) and [release readiness](docs/RELEASE.md).

## Components

| Component | Responsibility | Source |
| --- | --- | --- |
| Native interface | Play/Cancel, retry, menus and worker lifetime | `launcher/BedrockLauncher.swift` |
| App worker | Bundle wiring, setup state, one account session and journaled updates | `launcher/setup.py` |
| Session runtime | Prefix preparation, account-helper ownership and game launch | `client/standalone.py` |
| Account helper | Keychain, real ownership, verified acquisition and Xbox IPC | `client/standalone-helper.rs`, `client/standalone-xvd.rs` |
| Game preparation | Microsoft threading component, helper build and GameInput extraction | `client/standalone-setup.py`, `client/standalone-gameinput.py` |
| File picker | PNG/world dialogs, verified provider and guarded registration | `client/standalone-pickers.py`, `native/file-pickers/` |
| Compatibility and graphics | Pinned WineGDK/DXMT builds, patches and graphics probes | `tools/`, `patches/`, `native/` |
| Packaging | Swift app, frozen Python worker, resource/native inventories and DMG | `tools/package-launcher.py`, `tools/build-dmg.py` |
| Source setup and export | Local build/retry entry point and explicit source boundary | `tools/start.py`, `tools/bootstrap-sources.py`, `tools/export-source.py` |

The [repository map](docs/README.md#repository-map) identifies supported code,
build tools, default-off experiments and legacy CrossOver work. Upstream trees
under ignored `sources/` are generated from tracked pins and patches.

## Launch sequence

1. Native status reads existing state without sign-in, download or prefix setup.
2. Play acquires the setup lock, wires bundled inputs and checks the Mac, Rosetta,
   runtime and free space. Source startup instead owns the checkout's data root.
3. One helper authenticates the account and checks the actual Microsoft license.
   A new game uses `--download --serve-after`; an existing game uses `--serve`.
4. Changed runtime setup obtains the verified Microsoft threading component and
   prepares the separate Wine prefix. An unchanged setup signature is reusable.
5. The game starts through Direct3D 11/DXMT while the same account helper lives.
6. Normal exit returns to Play and stops owned processes. Failure/cancellation
   unwinds owned work; interrupted game downloads restart rather than resume.

The worker emits newline-delimited JSON with `state`, `title`, `detail` and nullable
`progress`. Only known progress lines and safe `BEDROCK_ERROR` codes reach the UI.
Arbitrary account/service output must not become interface text.

The native Settings window stores a two-letter Store country code in the
launcher's preferences (default `CA`). Each operation passes that selection via
`--market` to the worker, acquisition/account helper and game-launch command.
Changes are blocked during an active operation; retries use the current saved
selection without starting an additional account session.

**Update Minecraft…** downloads separately, preserves the previous game and
prefix, and journals activation. A pending journal blocks ordinary launch until
recovery. Recovery retains displaced newer data under `game-backups`. Live
packaged upgrade/recovery remains a release check; fixtures are not that evidence.

## Data and process ownership

| Item | Packaged app | Source checkout |
| --- | --- | --- |
| Data root (`BEDROCK_HOME`) | `~/Library/Application Support/Bedrock for Mac` | Checkout root |
| Components | App `Contents/Resources` | `runtime/standalone/`, `sources/xodus/target/` |
| Game | `<root>/game` | Same, or explicit CLI `--game-dir` |
| Prefix/worlds | `<root>/bottles/Bedrock-Standalone` | Same relative path |
| Logs/session record | `<root>/logs/standalone`, `<root>/runtime/standalone/helper-session.json` | Same relative paths |

`BEDROCK_BUNDLE` selects shipped scripts/components for the frozen worker. Source
`Start.command` pins its flow to the checkout and clears inherited bundle/data
variables; lower-level CLI commands still accept an explicitly chosen data root.
Wine maps `G:` to the game and `R:` to that root. Source, packaged-app and historical
CrossOver data are not migrated automatically.

Credentials stay in Keychain service `Minecraft Bedrock Standalone`, item
`account-v1`. One helper process caches one read. Sign-out removes user identity
and tokens while retaining device identity, game files and worlds. Changed
ad-hoc helper signatures may require new Keychain authorization.

Game acquisition uses a client-bound Xbox Token Broker ticket and retains a
validated STS renewal in the same helper session, selecting responses by type.

The user-owned mode-0600 `/tmp/xodus.sock` admits one helper. PID/executable records,
locks and private parent-written session receipts govern reuse and cleanup.
New helpers stop if their parent disappears. Lock-file presence alone does not
prove ownership. Unknown or live endpoints are preserved; never kill another
session to force startup. See [shared safety rules](CONTRIBUTING.md#protect-game-data-and-credentials).

## Build and trust boundaries

The launcher is arm64; Wine/DXMT and the Windows game use the Intel/Rosetta path.
Each packaged app needs a complete native minimum-OS audit. Its Swift deployment
target alone cannot establish platform support.

Account/catalog/license traffic uses verified HTTPS. Public package bytes enter
private quarantine and pass catalog identity, production-signature and complete
hash-tree/payload verification before parsing/extraction. Real ownership remains
required. [SECURITY.md](SECURITY.md) is the detailed trust-boundary reference.

Source/resource checksums, ad-hoc signing, notarization, fixture tests and actual
gameplay establish different properties. Retain exact dependency pins, notices,
source materials and artifact identity. [Publishing](docs/PUBLISHING.md) describes
exports; [release readiness](docs/RELEASE.md) tracks uncompleted binary work.

## Research and historical evidence

Default-off performance tools live in `experiments/`; their measurements and
limits are indexed under [research](docs/research/README.md). They are not native
ARM game support or a candidate-wide FPS guarantee. [History](docs/history/README.md)
retains dated gameplay, test, artifact and CrossOver records, including the
[previous context snapshot](docs/history/CONTEXT-2026-10-21.md).
