#!/usr/bin/env python3
"""Set up owned Windows Bedrock and launch it; --check is strictly read-only."""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
STAGE_NAMES = ('wine', 'graphics', 'helper', 'probes', 'bridge')


def module(name):
    directory = 'client' if name in ('standalone', 'standalone-setup', 'standalone-pickers') else 'tools'
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / directory / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(value)
    finally:
        sys.dont_write_bytecode = previous
    return value


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def installed():
    """Reuse a complete local installation; Start is not a game/runtime updater."""
    try:
        launcher = module('standalone')
        launcher.prerequisites(ROOT / 'game')
        launcher.verify_unix_bridge()
        if not launcher.HELPER.is_file():
            return False
        setup = module('standalone-setup')
        status = setup.game_status(ROOT / 'game')
        return all(status[key] for key in ('prepared_windows_x64_game',
                   'minecraft_store_product', 'package_metadata_present', 'gameinput_installer_present'))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return False


def native_dependencies(python, jobs):
    """Reuse only verified outputs; preserve interrupted builds in private attempts."""
    dependencies = module('build-native-dependencies')
    selected = os.environ.get('STANDALONE_DEPENDENCY_PREFIX')
    if selected:
        prefix = Path(selected).expanduser().absolute()
        dependencies.verify(prefix)
        return prefix
    inputs = ('tools/build-native-dependencies.py', 'config/native-dependencies.lock.json')
    identity = hashlib.sha256(''.join(digest(ROOT / name) for name in inputs).encode()).hexdigest()
    directory = ROOT / 'build/start-native-dependencies' / identity
    checked = directory
    while checked != ROOT.parent:
        if checked.is_symlink():
            raise RuntimeError('The native dependency build directory must not be a symbolic link.')
        checked = checked.parent
    directory.mkdir(parents=True, exist_ok=True)
    for attempt in sorted(directory.glob('attempt-*')):
        if attempt.is_symlink():
            raise RuntimeError('A native dependency build attempt is a symbolic link; it was kept.')
        prefix = attempt / 'prefix'
        if os.path.lexists(prefix / 'dependency-manifest.json'):
            dependencies.verify(prefix)
            print('Native source dependencies — already verified.', flush=True)
            return prefix
    # The builder refuses existing compiled outputs. A retry gets one fresh
    # attempt, while earlier source, archives and diagnostics remain available.
    attempt = Path(tempfile.mkdtemp(prefix='attempt-', dir=directory))
    run([python, str(ROOT / 'tools/build-native-dependencies.py'), '--destination', str(attempt),
         '--jobs', str(min(jobs, 8))], 'Building native source dependencies',
        ROOT / 'logs/standalone/setup/native-dependencies.log')
    prefix = attempt / 'prefix'
    dependencies.verify(prefix)
    return prefix


@contextlib.contextmanager
def lock(name):
    directory = ROOT / 'runtime/standalone'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / name).open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Minecraft or another setup is already running. Let it finish first.')
        yield


def run(command, label, log=None):
    print('\n' + label, flush=True)
    if log is None:
        subprocess.run(command, cwd=ROOT, check=True)
        return
    log.parent.mkdir(parents=True, exist_ok=True)
    print('Details: ' + str(log), flush=True)
    with log.open('wb') as output:
        process = subprocess.Popen(command, cwd=ROOT, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        started = time.monotonic()
        try:
            while True:
                try:
                    code = process.wait(timeout=20)
                    break
                except subprocess.TimeoutExpired:
                    print(f'  Still working ({int(time.monotonic() - started)}s).', flush=True)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
        if code:
            raise RuntimeError(f'{label} failed. Details: {log}')


class Steps:
    """Record successes only; validate input and output bytes before reusing work."""
    def __init__(self):
        self.path = ROOT / 'runtime/standalone/start-state.json'
        try:
            self.state = json.loads(self.path.read_text())
            if not isinstance(self.state, dict):
                self.state = {}
        except (OSError, ValueError):
            self.state = {}
        self.previous = ''

    def step(self, name, label, commands, inputs, outputs):
        signature = hashlib.sha256(json.dumps({
            'previous': self.previous, 'commands': commands,
            'inputs': {p: digest(ROOT / p) for p in sorted(inputs)},
        }, sort_keys=True).encode()).hexdigest()
        receipt = self.state.get(name, {})
        if isinstance(receipt, dict) and receipt.get('signature') == signature:
            try:
                current = {p: digest(ROOT / p) for p in outputs}
                if current == receipt.get('outputs'):
                    print(label + ' — already done.', flush=True)
                    self.previous = signature
                    return
            except OSError:
                pass
        # Invalidate downstream receipts before changing any files. A failed
        # rebuild must never make an older downstream success reusable.
        for downstream in STAGE_NAMES[STAGE_NAMES.index(name):]:
            self.state.pop(downstream, None)
        self.save()
        for i, command in enumerate(commands):
            run(command, label, ROOT / 'logs/standalone/setup' / f'{name}-{i + 1}.log')
        self.state[name] = {'signature': signature,
                            'outputs': {p: digest(ROOT / p) for p in outputs}}
        self.save()
        self.previous = signature

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            # Create exclusively in the destination directory. A predictable
            # .tmp path can be a stale link to unrelated recovery data.
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    prefix='.start-state-', suffix='.tmp',
                    dir=self.path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(self.state, output, indent=2)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def setup(jobs, market, *, runtime_only=False):
    dependencies_builder = module('build-native-dependencies')
    dependencies_builder.require_build_path(ROOT, 'Source checkout')
    if os.environ.get('STANDALONE_DEPENDENCY_PREFIX'):
        dependencies_builder.require_build_path(
            Path(os.environ['STANDALONE_DEPENDENCY_PREFIX']).expanduser(), 'Dependency prefix')
    run(['/bin/bash', str(ROOT / 'tools/install-build-tools.sh')], 'Preparing build tools')
    # Start.command deliberately bootstraps with Apple's Python. Use the modern
    # source-build interpreter installed above for extraction and subprocesses.
    python = '/opt/homebrew/opt/python@3.13/bin/python3.13'
    run([python, '-c', 'import sys; assert sys.version_info >= (3, 12)'], 'Checking source-build Python')
    os.environ['PATH'] = '/opt/homebrew/opt/python@3.13/libexec/bin:' + os.environ.get('PATH', '')
    dependencies = native_dependencies(python, jobs)
    bootstrap = module('bootstrap-sources')
    for name, project in bootstrap.PROJECTS.items():
        if (ROOT / 'sources' / name).exists():
            if name == 'xodus':
                # These examples are generated copies of this checkout's
                # authoritative helper inputs. Refresh them before verifying a
                # previously prepared tree after a source update.
                bootstrap.copy_helper_inputs(ROOT / 'sources' / name, ROOT)
            bootstrap.verify_project(ROOT / 'sources' / name, name, project)
        else:
            bootstrap.bootstrap(ROOT / 'sources', (name,))
    steps = Steps()
    wine = ROOT / 'runtime/standalone/wine'
    wine_inputs = ['tools/build-standalone-wine.sh', 'tools/verify-wine-source.py', 'tools/bootstrap-sources.py',
                   'tools/build-native-dependencies.py', 'config/native-dependencies.lock.json',
                   str(dependencies / 'dependency-manifest.json')]
    wine_inputs += [str(p.relative_to(ROOT)) for p in (ROOT / 'patches').glob('*wine*.patch')]
    wine_inputs += ['patches/minecraft-store-callback.patch']
    wine_inputs += list(module('standalone-pickers').SOURCE_INPUTS)
    steps.step('wine', 'Building the Windows compatibility runtime',
        [['/usr/bin/env', 'STANDALONE_DEPENDENCY_PREFIX=' + str(dependencies),
          '/bin/sh', str(ROOT / 'tools/build-standalone-wine.sh')]], wine_inputs,
        ['runtime/standalone/wine/bin/wine', 'runtime/standalone/wine/build-manifest.json',
         'runtime/standalone/wine/lib/wine/x86_64-unix/ntdll.so',
         'runtime/standalone/wine/lib/wine/x86_64-windows/xgameruntime.dll',
         'runtime/standalone/wine/lib/wine/x86_64-windows/bedrock-pickers.dll',
         'runtime/standalone/wine/file-pickers-build.json'])
    graphics = [f'x86_64-windows/{name}.dll' for name in ('d3d11', 'dxgi', 'd3d10core', 'winemetal')]
    steps.step('graphics', 'Installing graphics support',
        [['/bin/sh', str(ROOT / 'tools/build-standalone-graphics.sh'), '--wine-runtime', str(wine)]],
        ['tools/build-standalone-graphics.sh'],
        ['runtime/standalone/dxmt/' + p for p in graphics + ['x86_64-unix/winemetal.so']]
        + ['runtime/standalone/wine/lib/wine/' + p for p in graphics])
    helper_inputs = ['client/standalone-setup.py', 'tools/bootstrap-sources.py', 'patches/Cargo.lock',
                     *bootstrap.HELPER_INPUTS]
    helper_inputs += ['patches/' + name for name in bootstrap.PROJECTS['xodus']['patches']]
    steps.step('helper', 'Building Microsoft sign-in',
        [[python, str(ROOT / 'client/standalone-setup.py'), '--build-helper', '--jobs', str(jobs)]],
        helper_inputs,
        ['sources/xodus/target/release/examples/standalone_helper'])
    probes = ['standalone-graphics-probe', 'standalone-graphics-shader-probe',
              'runtime-auth-probe', 'store-callback-probe', 'runtime-privilege-probe']
    steps.step('probes', 'Building graphics checks',
        [['/bin/sh', str(ROOT / 'tools/build-standalone-probes.sh')]],
        ['tools/build-standalone-probes.sh', 'tests/xuser-claims.c'] + ['native/probes/' + p + '.c' for p in probes],
        ['runtime/standalone/probes/' + p + '.exe' for p in probes + ['xuser-claims-test']])
    bridge = ['/bin/sh', str(ROOT / 'tools/build-standalone-dxmt-unix.sh')]
    steps.step('bridge', 'Building and testing the graphics memory fixes',
        [bridge, bridge + ['--validate'], bridge + ['--stage-existing-runtime', str(wine)]],
        ['tools/build-standalone-dxmt-unix.sh', 'tools/standalone-dxmt-unix.py',
         'native/graphics/standalone-dxmt-display-trace.c', 'native/probes/standalone-dxmt-display-probe.m',
         'patches/standalone-dxmt-memory-lifetime.patch'],
        ['runtime/standalone/wine/dxmt-unix-bridge.json',
         'runtime/standalone/wine/lib/wine/x86_64-unix/winemetal.so',
         'runtime/standalone/wine/lib/wine/x86_64-unix/winemetal-upstream.so'])
    if runtime_only:
        return
    run([python, str(ROOT / 'client/standalone-setup.py'), '--threading'], 'Installing Microsoft game support')
    run([python, str(ROOT / 'client/standalone-setup.py'), '--download-game', '--market', market],
        'Downloading Minecraft — sign in with the Microsoft account that owns the PC game')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Inspect readiness without installing, signing in, or launching')
    mode.add_argument('--setup-only', action='store_true', help='Complete setup without starting Minecraft')
    mode.add_argument('--runtime-only', action='store_true', help='Build the launcher runtime without acquiring or launching Minecraft')
    parser.add_argument('--market', default='CA', help='Two-letter Store country code (default CA)')
    parser.add_argument('--jobs', type=int, default=2, help='Build workers (default 2, suitable for initial M1 Air testing)')
    args = parser.parse_args(argv)
    if len(args.market) != 2 or not args.market.isascii() or not args.market.isupper() or not args.market.isalpha():
        parser.error('--market must be a two-letter uppercase country code')
    if not 1 <= args.jobs <= 12:
        parser.error('--jobs must be between 1 and 12')
    # Source setup owns this checkout's locks, runtime, game and saves. Do not
    # let inherited packaged-worker variables redirect only part of the flow.
    os.environ['BEDROCK_HOME'] = str(ROOT)
    os.environ.pop('BEDROCK_BUNDLE', None)
    if args.check:
        ready = installed()
        print('Ready to launch.' if ready else 'Setup needed. Open Start.command to continue.')
        return 0 if ready else 1
    if sys.platform != 'darwin' or platform.machine() != 'arm64' or int(platform.mac_ver()[0].split('.')[0]) < 15:
        raise RuntimeError('Open Start.command on an Apple Silicon Mac running macOS 15 or later.')
    os.umask(0o077)
    os.environ['STANDALONE_JOBS'] = str(args.jobs)
    os.environ['PATH'] = ':'.join([str(Path(os.environ.get('CARGO_HOME', str(Path.home() / '.cargo'))) / 'bin'),
        '/opt/homebrew/opt/rustup/bin', '/opt/homebrew/bin', '/opt/homebrew/opt/llvm/bin',
        '/opt/homebrew/opt/bison/bin', os.environ.get('PATH', '')])
    with lock('start.lock'):
        launcher = module('standalone')
        if launcher.game_running():
            if args.runtime_only:
                raise RuntimeError('Quit Minecraft before building its runtime.')
            print('Minecraft is already running.')
            return 0
        if args.runtime_only:
            with lock('launcher.lock'):
                launcher.wait_for_idle_prefix()
                setup(args.jobs, args.market, runtime_only=True)
            print('Runtime ready for the native launcher.')
            return 0
        if not installed():
            print('First-time setup downloads several GB and builds the runtime. Keep this window open.', flush=True)
            with lock('launcher.lock'):
                launcher.wait_for_idle_prefix()
                setup(args.jobs, args.market)
            if not installed():
                raise RuntimeError('Installation verification failed. Open Start.command again to retry.')
        if args.setup_only:
            run([sys.executable, str(ROOT / 'client/standalone.py'), 'prepare'], 'Preparing Minecraft')
            print('Ready. Open Start.command when you want to play.')
            return 0
        run([sys.executable, str(ROOT / 'client/bedrock-monitor.py'), 'play', '--', '--market', args.market], 'Starting Minecraft')
    return 0


def interrupted(_signal, _frame):
    # Unwind run() so its separately owned compiler group cannot outlive Start
    # when Terminal closes or the worker receives a termination request.
    raise KeyboardInterrupt


def cli():
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        return main()
    except KeyboardInterrupt:
        print('\nStopped. Open Start.command again to retry.', file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('Start: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(cli())
