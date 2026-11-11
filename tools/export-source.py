#!/usr/bin/env python3
"""Export reviewed source files only; never walk the private working tree."""

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile


# Add individually reviewed source files here. Directories and globs are forbidden.
# Both runtime paths and the source clones are deliberately absent.
ALLOWED_FILES = (
    "tests/test_mullion_staging.py",
    "tests/test_mullion_experiment.py",
    'tools/qa_resource_guard.py',
    'LICENSES/Mullion-LGPL-2.1-or-later.txt',
    'experiments/mullion/.gitignore',
    'experiments/mullion/README.md',
    'experiments/mullion/RESULTS.md',
    'experiments/mullion/SOAK.md',
    'experiments/mullion/Launch Bedrock Experiment.command',
    'experiments/mullion/Run Ray Probe.command',
    'experiments/mullion/run.py',
    'experiments/mullion/stage.py',
    'experiments/mullion/soak_report.py',
    'experiments/mullion/soak_watch.py',
    'experiments/mullion/versions.json',
    'experiments/mullion/mullion.conf',
    'experiments/mullion/compat/.gitignore',
    'experiments/mullion/compat/README.txt',
    'experiments/mullion/compat/build-loader.sh',
    'experiments/mullion/compat/build.sh',
    'experiments/mullion/compat/diagnostic-loader.c',
    'experiments/mullion/compat/diagnostic-loader.md',
    'experiments/mullion/compat/diagnostic-loader.spec',
    'experiments/mullion/compat/inline_command.py',
    'experiments/mullion/compat/level-profile.inc',
    'experiments/mullion/compat/metal32_fallback.m',
    'experiments/mullion/compat/ray-trace.inc',
    'experiments/mullion/compat/sparse-backport-notes.md',
    'experiments/mullion/probes/LICENSE-BedrockOnLinux.txt',
    'experiments/mullion/probes/README.txt',
    'experiments/mullion/probes/build.sh',
    'experiments/mullion/probes/dxr-render-probe.c',
    'experiments/mullion/probes/inline.hlsl',
    'experiments/mullion/probes/render.inc',
    'experiments/mullion/probes/triangle.hlsl',
    'experiments/mullion/fixture/.gitignore',
    'experiments/mullion/fixture/README.md',
    'experiments/mullion/fixture/build_fixture.py',
    'experiments/mullion/fixture/behavior_pack/manifest.json',
    'experiments/mullion/fixture/behavior_pack/functions/tick.json',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/bootstrap.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/off.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/on.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/room.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/view.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/tick.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/soak_start.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/soak_tick.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/soak_stop.mcfunction',
    'experiments/mullion/fixture/behavior_pack/functions/rayproof/soak_complete.mcfunction',
    'experiments/mullion/fixture/resource_pack/manifest.json',
    'experiments/mullion/fixture/resource_pack/textures/blocks/iron_block.texture_set.json',
    'experiments/mullion/fixture/resource_pack/textures/blocks/lapis_block.texture_set.json',
    'experiments/mullion/fixture/resource_pack/textures/blocks/redstone_block.texture_set.json',
    ".gitignore",
    ".gitattributes",
    "README.md",
    "AGENTS.md",
    "CONTEXT.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "tools/packaging-requirements.txt",
    ".github/workflows/checks.yml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/ROADMAP.md",
    "docs/SOURCE_PREVIEW.md",
    "docs/assets/README.md",
    "docs/assets/social-preview.svg",
    "docs/RELEASE.md",
    "docs/COMPATIBILITY.md",
    "docs/PERFORMANCE.md",
    "docs/RELEASE_NOTES.md",
    "docs/USER_GUIDE.md",
    "docs/DEVELOPMENT.md",
    "docs/TESTING.md",
    "docs/CLEAN_INSTALL.md",
    "docs/history/XBOX-AUTH-ISSUE-12.md",
    "docs/history/DEPENDENCY-AUDIT-2026-11-02.md",
    "docs/README.md",
    "client/README.md",
    "tools/README.md",
    "native/README.md",
    "legacy/README.md",
    "experiments/README.md",
    "config/README.md",
    "docs/history/README.md",
    "docs/research/README.md",
    "docs/research/BUFFERS.md",
    "docs/research/ALLOCATORS.md",
    "docs/research/PRESENTATION.md",
    "docs/research/ARM-BATCH.md",
    "docs/history/CONTEXT-2026-10-21.md",
    "docs/history/RELEASE-2026-10-07.md",
    "docs/history/TESTING.md",
    "docs/history/GAMEPLAY.md",
    "docs/history/AUDIT-2026-10-21.md",
    "docs/research/m4-architecture-results.json",
    "docs/STABILITY.md",
    "docs/history/CROSSOVER.md",
    "launcher/Icon.swift",
    "LICENSE",
    "THIRD_PARTY.md",
    "LICENSES/Wine-LGPL-2.1-or-later.txt",
    "LICENSES/Wine-NOTICE.txt",
    "LICENSES/dxmt-LICENSE.txt",
    "LICENSES/dxmt-DXVK-LICENSE.txt",
    "LICENSES/dxmt-LLVM-LICENSE.txt",
    "LICENSES/dxmt-MinGW-LICENSE.txt",
    "LICENSES/DXMT-embedded-NOTICES.txt",
    "LICENSES/XVD-GreenGamesPublicKey.rsa",
    "LICENSES/XVD-PUBLIC-KEY-PROVENANCE.txt",
    "legacy/Launch Bedrock.command",
    "client/Launch Standalone.command",
    "Start.command",
    "tools/start.py",
    "tools/install-build-tools.sh",
    "client/Mark Problem.command",
    "client/Stop Monitor.command",
    "client/bedrock-monitor.py",
    "legacy/launch.py",
    "client/standalone.py",
    "client/standalone-setup.py",
    "client/standalone-gameinput.py",
    "client/standalone-pickers.py",
    "native/file-pickers/README.md",
    "native/file-pickers/build.sh",
    "native/file-pickers/check-windows.cmd",
    "native/file-pickers/pickers.c",
    "native/file-pickers/ids.h",
    "native/file-pickers/pickers.spec",
    "tests/file-picker-contract.c",
    "tests/test_standalone_pickers.py",
    "tools/standalone-dxmt-unix.py",
    "experiments/standalone-dxmt-shared.py",
    "experiments/standalone-wine-heap.py",
    "experiments/standalone-bedrock-refmove.py",
    "experiments/standalone-bedrock-allocator.py",
    "experiments/standalone-bedrock-frame-slab.py",
    "experiments/standalone-bedrock-frame-control.py",
    "experiments/standalone-bedrock-frame-profile.py",
    "experiments/frame-slab-control.c",
    "experiments/clone-recurrence-control.c",
    "experiments/binding-recurrence-control.c",
    "patches/experimental-bedrock-binding-recurrence.patch",
    "tests/bedrock-binding-recurrence.c",
    "tests/test_bedrock_binding_recurrence.py",
    "patches/experimental-bedrock-clone-recurrence.patch",
    "tests/m4-native-batch.cpp",
    "tests/run-m4-native-batch.py",
    "experiments/build-standalone-frame-pacing.py",
    "experiments/build-standalone-metrics-hud.py",
    "experiments/standalone-dxmt-present-pacer.m",
    "experiments/standalone-dxmt-present-trace.h",
    "experiments/standalone-dxmt-present-trace.m",
    "experiments/standalone-metrics-hud.h",
    "experiments/standalone-metrics-hud.m",
    "docs/CLI.md",
    "legacy/run-windows.sh",
    "legacy/build-helper.sh",
    "tools/build-launcher.sh",
    "tools/package-launcher.py",
    "tools/build-dmg.py",
    "launcher/BedrockLauncher.swift",
    "launcher/setup.py",
    "legacy/build-runtime.sh",
    "legacy/build-probes.sh",
    "tools/build-standalone-wine.sh",
    "tools/verify-wine-source.py",
    "tests/test_wine_source.py",
    "tools/build-native-dependencies.py",
    "tools/collect-helper-licenses.py",
    "tools/collect-python-notices.py",
    "config/native-dependencies.lock.json",
    "tools/build-release-runtime.py",
    "config/release-runtime-profile.json",
    "tools/build-standalone-graphics.sh",
    "experiments/build-standalone-dxmt-pool.sh",
    "tools/build-standalone-dxmt-unix.sh",
    "tools/build-standalone-probes.sh",
    "docs/research/GRAPHICS.md",
    "legacy/stage-runtime.py",
    "tools/bootstrap-sources.py",
    "tools/export-source.py",
    "legacy/bedrock-helper.rs",
    "client/standalone-helper.rs",
    "client/standalone-xvd.rs",
    "legacy/prepare-owned-game.rs",
    "native/probes/runtime-auth-probe.c",
    "native/probes/runtime-privilege-probe.c",
    "native/probes/graphics-probe.c",
    "native/probes/standalone-graphics-probe.c",
    "native/probes/standalone-graphics-shader-probe.c",
    "experiments/standalone-dxmt-autorelease-shim.m",
    "native/graphics/standalone-dxmt-display-trace.c",
    "native/probes/standalone-dxmt-display-probe.m",
    "native/probes/store-callback-probe.c",
    "legacy/gameinput.reg",
    "client/winrt.reg",
    "patches/Cargo.lock",
    "patches/xodus-real-store-license.patch",
    "patches/winegdk-macos-local.patch",
    "patches/minecraft-store-callback.patch",
    "patches/standalone-wine-dxmt-abi.patch",
    "patches/standalone-dxmt-memory-lifetime.patch",
    "patches/standalone-dxmt-shared-buffers.patch",
    "patches/standalone-dxmt-packed-constants.patch",
    "patches/standalone-dxmt-input-layout-reuse.patch",
    "patches/standalone-dxmt-borrow-constant-buffers.patch",
    "patches/standalone-dxmt-frame-latency.patch",
    "patches/experimental-wine-heap-reuse.patch",
    "patches/experimental-bedrock-refmove.patch",
    "patches/experimental-bedrock-exact-current.patch",
    "patches/experimental-bedrock-frame-slab.patch",
    "patches/standalone-wine-macrock-name.patch",
    "patches/standalone-wine-storage-linkage.patch",
    "patches/standalone-wine-idl-list.patch",
    "patches/standalone-wine-user-privileges.patch",
    "patches/standalone-wine-winhttp-write-callbacks.patch",
    "patches/standalone-wine-xuser-realms.patch",
    "patches/standalone-wine-xuser-token-refresh.patch",
    "patches/standalone-wine-xuser-z-device-auth.patch",
    "patches/standalone-wine-xuser-zz-switch-account.patch",
    "patches/keychain-cache.patch",
    "patches/unified-helper.patch",
    "patches/standalone-signin-window.patch",
    "patches/standalone-keychain-write.patch",
    "patches/standalone-account-transport.patch",
    "patches/standalone-account-switch.patch",
    "patches/standalone-helper-dependencies.patch",
    "patches/xbox-auth-errors.patch",
    "patches/standalone-package-ticket.patch",
    "patches/standalone-xvd-preparation-length.patch",
    "patches/standalone-offline-license-diagnostic.patch",
    "patches/standalone-license-ticket.patch",
    "docs/PUBLISHING.md",
    "docs/research/dxmt-shared-buffers-results.json",
    "tests/dxmt-shared-buffers.cpp",
    "tests/dxmt-constant-buffers.cpp",
    "tests/wine-heap-reuse.c",
    "tests/dxmt-input-layout.cpp",
    "tests/dxmt-constant-buffer-lifetime.cpp",
    "tests/test_standalone_dxmt_shared.py",
    "tests/test_standalone_wine_heap.py",
    "tests/test_standalone_bedrock_refmove.py",
    "tests/test_standalone_bedrock_allocator.py",
    "tests/bedrock-exact-current.c",
    "tests/run-bedrock-exact-differential.py",
    "tests/bedrock-exact-differential.cpp",
    "tests/bedrock-frame-slab.cpp",
    "tests/test_bedrock_frame_control.py",
    "tests/test_standalone_bedrock_frame_slab.py",
    "tests/test_standalone_bedrock_frame_profile.py",
    "docs/research/dxmt-packed-constants-results.json",
    "docs/research/wine-heap-reuse-results.json",
    "docs/research/dxmt-input-layout-results.json",
    "docs/research/bedrock-refmove-results.json",
    "docs/research/render-redesign-results.json",
    "tests/test_export_source.py",
    "tests/test_repository_layout.py",
    "native/file-pickers/provenance/build-v1.sh.txt",
    "tests/test_bootstrap_sources.py",
    "tests/test_standalone.py",
    "tests/test_onboarding.py",
    "tests/test_packaging.py",
    "tests/check-launcher-lifecycle.py",
    "tests/test_release_runtime.py",
    "tests/test_collect_helper_licenses.py",
    "tests/test_collect_python_notices.py",
    "tests/native-dependency-probe.c",
    "tests/test_threading_download.py",

    "tests/test_start.py",
    "tests/test_bedrock_monitor.py",
    "tests/test_standalone_setup.py",
    "tests/test_standalone_dxmt_unix.py",
    "tests/xuser-claims.c",
    "tests/xuser-realms.c",
    "tests/xuser-refresh.c",
    "tests/xuser-refresh-live.c",
    "tests/xuser-rta-live.c",
    "tests/run-xuser-refresh-live.sh",
    "tests/run-xuser-rta-live.sh",
    "tests/run-xuser-tests.sh",
    "tests/winhttp-write-callbacks.c",
    "tests/run-winhttp-write-tests.py",
    "docs/history/PARTY-WINHTTP-2026-10-25.md",
    "tests/XUSER.md",
)
PRIVATE_ROOTS = frozenset({
    "sources", "downloads", "runtime", "logs", "bottles", "build", "game",
    ".git", "__pycache__", "exports", "game-backups", ".minecraft-update",
})

# This reviewed production PUBLIC verification key is the only binary source
# input. Pin its bytes so an allowlisted name cannot export arbitrary payloads.
PUBLIC_BINARY_INPUTS = {
    "LICENSES/XVD-GreenGamesPublicKey.rsa": (
        539, "183f0ae05431e4ad91554e88946967c872997227dbe6c85116f5fd2fd2d1229e"
    ),
}


def checked_relative(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or str(path) != name
            or any(part in (".", "..") for part in path.parts)
            or path.parts[0] in PRIVATE_ROOTS
            or path.parts[0].startswith((".minecraft-update-staging-", ".minecraft-discard-"))
            or "\\" in name
            or "\n" in name or "\r" in name):
        raise ValueError("Unsafe export entry: " + repr(name))
    return path


def read_source(root, name):
    """Reject symlinks in every component, not just symlinks at the leaf."""
    relative = checked_relative(name)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Refusing symlink in export path: " + name)
    if not current.is_file() or not current.resolve().is_relative_to(root):
        raise ValueError("Missing regular source file: " + name)
    # Open each directory relative to its validated descriptor. O_NOFOLLOW on
    # every component also closes a parent-symlink swap between check and read.
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW,
                             dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Refusing non-regular source file: " + name)
        content = stream.read()
    if name in PUBLIC_BINARY_INPUTS:
        expected_size, expected_digest = PUBLIC_BINARY_INPUTS[name]
        if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError("Refusing changed public binary source input: " + name)
        return content, 0o644
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Refusing non-text source file: " + name) from exc
    if b"\0" in content:
        raise ValueError("Refusing binary source file: " + name)
    return content, 0o755 if info.st_mode & 0o111 else 0o644


def collect_sources(root, allowlist=ALLOWED_FILES):
    root = Path(root)
    if root.is_symlink():
        raise ValueError("The source root must not be a symlink")
    root = root.resolve(strict=True)
    if len(set(allowlist)) != len(allowlist):
        raise ValueError("Duplicate source export entry")
    return [(name, *read_source(root, name)) for name in allowlist]


def export_sources(root, destination, allowlist=ALLOWED_FILES):
    files = collect_sources(root, allowlist)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination already exists; choose a new directory")
    # Require an existing parent: do not silently create paths outside user intent.
    parent = destination.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("Destination parent is not a directory")
    destination = parent / destination.name
    stage = Path(tempfile.mkdtemp(prefix=".bedrock-source-", dir=parent))
    try:
        digest_lines = []
        for name, content, mode in files:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode)
            digest_lines.append(f"{hashlib.sha256(content).hexdigest()}  {name}\n")
        (stage / "SOURCE-SHA256.txt").write_text("".join(digest_lines), encoding="utf-8")
        # Rename is atomic on this volume. Never merge into an existing directory.
        if destination.exists() or destination.is_symlink():
            raise ValueError("Destination appeared during export")
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", type=Path,
                        help="new output directory (its parent must exist)")
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--list", action="store_true", help="print the reviewed allowlist")
    args = parser.parse_args()
    if args.list:
        print("\n".join(ALLOWED_FILES))
        return 0
    if args.check and args.destination:
        parser.error("--check does not take a destination")
    if not args.check and not args.destination:
        parser.error("provide a destination or --check")
    root = Path(__file__).resolve().parents[1]
    try:
        if args.check:
            count = len(collect_sources(root))
            print(f"Validated {count} allowlisted source files; no runtime data read.")
        else:
            count = export_sources(root, args.destination)
            print(f"Exported {count} source files to {args.destination.absolute()}")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Source export refused: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
