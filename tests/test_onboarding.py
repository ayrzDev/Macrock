"""Exercise the real worker entry point without network, Keychain, or game access."""
import contextlib
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import socket
import os
import signal
import time
import textwrap
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('onboarding', Path(__file__).resolve().parents[1] / 'launcher/setup.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
runtime_spec = importlib.util.spec_from_file_location('session_runtime', Path(__file__).resolve().parents[1] / 'client/standalone.py')
runtime = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime)


class OnboardingTests(unittest.TestCase):
    def test_invalid_market_is_rejected_before_data_or_account_access(self):
        for market in ('', 'T', 'TUR', 'tr', 'T1', 'ＴＲ', '../TR'):
            with self.subTest(market=market), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch.object(worker, 'ROOT', root), patch.object(worker, 'load') as load, \
                        patch('sys.argv', ['setup.py', '--market', market]), \
                        contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        worker.main()
                self.assertEqual(error.exception.code, 2)
                load.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_selected_market_reaches_returning_account_and_game_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'game').mkdir()
            (root / 'game/Minecraft.Windows.exe').write_bytes(b'MZfixture')
            account = unittest.mock.Mock(return_value=contextlib.nullcontext())
            session = SimpleNamespace(account=account, AccountError=runtime.AccountError)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'BUNDLE', None), \
                    patch.object(worker, 'load', return_value=session), \
                    patch.object(worker, 'installed', return_value=True), \
                    patch.object(worker, 'validate_install'), patch.object(worker, 'run') as run, \
                    patch('sys.argv', ['setup.py', '--market', 'TR']), \
                    contextlib.redirect_stdout(io.StringIO()):
                worker.main()
            self.assertEqual(account.call_count, 1)
            self.assertEqual(account.call_args.args, (root / 'game', 'TR'))
            self.assertFalse(account.call_args.kwargs['download'])
            self.assertEqual(run.call_args.args[0][-3:], ['--market', 'TR', 'launch'])

    def test_selected_market_reaches_update_without_a_second_account(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, sessions, _ = self.update_fixture(root)
            original = session.account
            markets = []

            @contextlib.contextmanager
            def account(destination, **kwargs):
                markets.append(kwargs['market'])
                with original(destination, **kwargs):
                    yield

            session.account = account
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                worker.update_minecraft(session, log, 'TR')
            self.assertEqual(markets, ['TR'])
            self.assertEqual(sessions, ['start', 'stop'])

    def test_update_recovers_after_backup_publication_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, sessions, prefix = self.update_fixture(root)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                with patch.object(worker, 'finish_update', side_effect=OSError('fixture backup unavailable')):
                    with self.assertRaisesRegex(OSError, 'backup unavailable'):
                        worker.update_minecraft(session, log)
                record = json.loads((root / '.minecraft-update/transaction.json').read_text())
                self.assertEqual(record['phase'], 'committed')
                backup = worker.recover_update()
                worker.recover_update()
            self.assertEqual(sessions, ['start', 'stop'])
            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZnew')
            self.assertEqual((prefix / 'world').read_bytes(), b'original world')
            self.assertEqual((backup / 'previous-game/Minecraft.Windows.exe').read_bytes(), b'MZold')
            self.assertEqual((backup / 'previous-prefix/world').read_bytes(), b'original world')
            self.assertFalse((root / '.minecraft-update').exists())

    def test_failed_snapshot_keeps_worlds_and_partial_backup_for_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, sessions, prefix = self.update_fixture(root)

            def full_disk(_source, destination, **_kwargs):
                destination.mkdir()
                (destination / 'world').write_bytes(b'partial snapshot')
                raise OSError(28, 'fixture disk full')

            with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    patch.object(worker.shutil, 'copytree', side_effect=full_disk), \
                    tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'previous setup was restored'):
                    worker.update_minecraft(session, log)
            self.assertEqual(sessions, ['start', 'stop'])
            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZold')
            self.assertEqual((prefix / 'world').read_bytes(), b'original world')
            backup, = (root / 'game-backups').iterdir()
            self.assertEqual((backup / 'previous-prefix/world').read_bytes(), b'partial snapshot')
            self.assertFalse((root / '.minecraft-update').exists())

    def test_worker_selects_relocated_source_or_flat_bundle_commands(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary, patch.object(worker, 'ROOT', Path(temporary)):
            with patch.object(worker, 'BUNDLE', None):
                self.assertEqual(worker.script_path('standalone.py'), source / 'client/standalone.py')
                self.assertEqual(Path(worker.load('source_fixture', 'standalone.py').__file__),
                                 source / 'client/standalone.py')
            with patch.object(worker, 'BUNDLE', Path(temporary) / 'app'):
                self.assertEqual(worker.script_path('standalone.py'), Path(temporary) / 'standalone.py')
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_bundle_setup_preserves_existing_staging_files_and_links(self):
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home, bundle = root / 'data', root / 'app'
                home.mkdir()
                (bundle / 'scripts').mkdir(parents=True)
                for name in ('standalone.py', 'standalone-setup.py', 'standalone-gameinput.py', 'standalone-pickers.py', 'winrt.reg'):
                    (bundle / 'scripts' / name).write_bytes(b'current bundled script')
                recovery = root / 'recovery-file'
                recovery.write_bytes(b'preserve recovery bytes')
                staging = home / 'standalone.py.new'
                if linked:
                    staging.symlink_to(recovery)
                else:
                    staging.write_bytes(b'preserve staged bytes')
                with patch.object(worker, 'ROOT', home), patch.object(worker, 'BUNDLE', bundle):
                    worker.initialize_bundle()
                self.assertEqual(recovery.read_bytes(), b'preserve recovery bytes')
                self.assertEqual(staging.is_symlink(), linked)
                self.assertEqual(staging.read_bytes(), b'preserve recovery bytes' if linked else b'preserve staged bytes')
                self.assertFalse((home / 'standalone.py').is_symlink())
                self.assertEqual((home / 'standalone.py').read_bytes(), b'current bundled script')

    def test_update_journal_preserves_existing_staging_files_and_links(self):
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                transaction = root / '.minecraft-update'
                transaction.mkdir()
                recovery = root / 'world-backup'
                recovery.write_bytes(b'preserve world bytes')
                staging = transaction / 'transaction.new'
                if linked:
                    staging.symlink_to(recovery)
                else:
                    staging.write_bytes(b'preserve staged journal')
                record = {'phase': 'preparing'}
                worker.write_update(transaction, record)
                self.assertEqual(json.loads((transaction / 'transaction.json').read_text()), record)
                self.assertEqual(recovery.read_bytes(), b'preserve world bytes')
                self.assertEqual(staging.is_symlink(), linked)
                self.assertEqual(staging.read_bytes(), b'preserve world bytes' if linked else b'preserve staged journal')

    def test_failed_file_replacement_preserves_original_and_cleans_owned_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'transaction.json'
            target.write_bytes(b'previous complete journal')
            with patch.object(worker.os, 'replace', side_effect=OSError('fixture replacement failure')):
                with self.assertRaisesRegex(OSError, 'replacement failure'):
                    worker.replace_bytes(target, b'next complete journal')
            self.assertEqual(target.read_bytes(), b'previous complete journal')
            self.assertEqual(set(root.iterdir()), {target})

    def test_dangling_update_transaction_routes_to_preserving_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transaction = root / '.minecraft-update'
            transaction.symlink_to(root / 'missing-transaction')
            session = SimpleNamespace(game_running=lambda: False, account_pid=lambda: None,
                                      recover_account_socket=lambda: None, wait_for_idle_prefix=lambda: None)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'BUNDLE', None), \
                    patch.object(worker, 'load', return_value=session), \
                    patch.object(worker, 'initialize_bundle') as initialize, \
                    patch('sys.argv', ['setup.py', '--status']), contextlib.redirect_stdout(io.StringIO()) as output:
                worker.main()
                self.assertEqual(json.loads(output.getvalue())['state'], 'update')
                with patch('sys.argv', ['setup.py']):
                    with self.assertRaisesRegex(RuntimeError, 'unexpected link'):
                        worker.main()
            initialize.assert_not_called()
            self.assertTrue(transaction.is_symlink())

    def test_update_parent_guard_environment_is_scoped_even_on_failure(self):
        @contextlib.contextmanager
        def account(_destination, **_kwargs):
            self.assertEqual(os.environ['BEDROCK_HELPER_PARENT_PID'], str(os.getpid()))
            self.assertEqual(os.environ['BEDROCK_HELPER_SESSION_FILE'], '/fixture/session.json')
            yield

        session = SimpleNamespace(STATE=Path('/fixture/session.json'), account=account)
        with patch.dict(os.environ, {'BEDROCK_HELPER_PARENT_PID': 'previous-owner'}, clear=False):
            original_state = os.environ.get('BEDROCK_HELPER_SESSION_FILE')
            with self.assertRaises(worker.Cancelled):
                with worker.update_account(session, Path('/fixture/download')):
                    raise worker.Cancelled()
            self.assertEqual(os.environ['BEDROCK_HELPER_PARENT_PID'], 'previous-owner')
            self.assertEqual(os.environ.get('BEDROCK_HELPER_SESSION_FILE'), original_state)

    def test_killed_update_worker_releases_guarded_helper_and_allows_recovery_retry(self):
        for stage in ('before-session-record', 'preparing'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, _, prefix = self.update_fixture(root)
                helper = root / 'sources/xodus/target/release/examples/standalone_helper'
                helper.parent.mkdir(parents=True)
                state = root / 'runtime/standalone/helper-session.json'
                endpoint = root / 'account.sock'
                spawned, stopped = root / 'helper-spawned', root / 'helper-stopped'
                helper.write_text('#!' + sys.executable + '\n' + textwrap.dedent('''
                    import json, os, pathlib, socket, sys, time
                    root = pathlib.Path(os.environ['BEDROCK_HOME'])
                    parent = int(os.environ['BEDROCK_HELPER_PARENT_PID'])
                    record = pathlib.Path(os.environ['BEDROCK_HELPER_SESSION_FILE'])
                    assert os.getppid() == parent
                    (root / 'helper-spawned').write_text(str(os.getpid()))
                    server = None
                    try:
                        # Mirror the production guardian contract, without
                        # credentials, network access or any real game process.
                        while os.getppid() == parent:
                            try:
                                data = json.loads(record.read_text())
                                if data['pid'] == os.getpid() and pathlib.Path(data['executable']).resolve() == pathlib.Path(sys.argv[0]).resolve():
                                    break
                            except (OSError, ValueError, KeyError):
                                pass
                            time.sleep(0.01)
                        if os.getppid() == parent:
                            destination = pathlib.Path(sys.argv[2])
                            destination.mkdir()
                            (destination / 'Minecraft.Windows.exe').write_bytes(b'MZnew')
                            server = socket.socket(socket.AF_UNIX)
                            server.bind(str(root / 'account.sock'))
                            os.chmod(root / 'account.sock', 0o600)
                            server.listen()
                            while os.getppid() == parent:
                                time.sleep(0.01)
                    finally:
                        if server:
                            server.close()  # Deliberately leave a dead socket.
                        (root / 'helper-stopped').touch()
                '''))
                helper.chmod(0o700)
                wrapper = root / 'fixture-worker.py'
                wrapper.write_text(textwrap.dedent('''
                    import importlib.util, os, pathlib, time, fcntl
                    from types import SimpleNamespace
                    root = pathlib.Path(ROOT_VALUE)
                    os.environ['BEDROCK_HOME'] = str(root)
                    def load(name, path):
                        spec = importlib.util.spec_from_file_location(name, path)
                        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                        return module
                    worker = load('worker', WORKER_VALUE)
                    runtime = load('runtime', RUNTIME_VALUE)
                    runtime.SOCKET = root / 'account.sock'
                    def account_pid():
                        import json
                        try:
                            pid = json.loads(runtime.STATE.read_text())['pid']
                            os.kill(pid, 0)
                            return pid
                        except (OSError, ValueError):
                            return None
                    runtime.account_pid = account_pid
                    runtime.game_running = lambda: False
                    runtime.wait_for_idle_prefix = lambda: None
                    runtime.prerequisites = lambda _: None
                    runtime.setup_signature = lambda _: {}
                    runtime.setup_matches = lambda _: True
                    def prepare(_):
                        (root / 'preparing').touch()
                        time.sleep(60)
                    runtime.prepare = prepare
                    worker.run = lambda *a, **kw: None
                    worker.shutil.disk_usage = lambda _: SimpleNamespace(free=100 * 1024**3)
                    if STAGE_VALUE == 'before-session-record':
                        original = runtime.subprocess.Popen
                        def delayed_popen(*args, **kwargs):
                            process = original(*args, **kwargs)
                            while not (root / 'helper-spawned').exists():
                                time.sleep(0.01)
                            time.sleep(60)  # Kill between spawn and STATE write.
                            return process
                        runtime.subprocess.Popen = delayed_popen
                    with (root / 'onboarding.lock').open('a') as lock, (root / 'fixture.log').open('ab') as log:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        with worker.maintenance_lock(runtime):
                            worker.update_minecraft(runtime, log)
                ''').replace('ROOT_VALUE', repr(str(root))).replace('WORKER_VALUE', repr(worker.__file__))
                   .replace('RUNTIME_VALUE', repr(runtime.__file__)).replace('STAGE_VALUE', repr(stage)))
                process = subprocess.Popen([sys.executable, str(wrapper)], stdout=subprocess.DEVNULL,
                                           stderr=subprocess.PIPE)
                try:
                    marker = spawned if stage == 'before-session-record' else root / 'preparing'
                    deadline = time.monotonic() + 10
                    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(marker.exists(), 'Synthetic worker did not reach kill boundary')
                    process.kill()
                    process.wait(timeout=5)
                    deadline = time.monotonic() + 5
                    while not stopped.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(stopped.exists(), 'Guarded helper did not stop after worker death')
                    helper_pid = int(spawned.read_text())
                    while time.monotonic() < deadline:
                        try:
                            os.kill(helper_pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.02)
                    else:
                        self.fail('Synthetic orphan was not reaped')
                    if stage == 'before-session-record':
                        self.assertFalse(state.exists())
                        self.assertFalse(endpoint.exists())
                    else:
                        # A bypassing entry point writes newer world progress.
                        subprocess.run([sys.executable, '-c', 'from pathlib import Path; Path(' + repr(str(prefix / 'world')) + ').write_bytes(b"newer progress")'], check=True)
                    with patch.object(worker, 'ROOT', root), patch.object(worker, 'BUNDLE', None), \
                            patch.object(runtime, 'ROOT', root), patch.object(runtime, 'STATE', state), \
                            patch.object(runtime, 'HELPER', helper), patch.object(runtime, 'SOCKET', endpoint), \
                            patch.object(runtime, 'game_running', return_value=False), \
                            patch.object(runtime, 'wait_for_idle_prefix'), \
                            patch.object(worker, 'run'), \
                            patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                            tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                        with worker.maintenance_lock(runtime):
                            recovery = worker.recover_update()
                            self.assertFalse(endpoint.exists())
                            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZold')
                            if stage == 'preparing':
                                self.assertEqual((prefix / 'world').read_bytes(), b'original world')
                                self.assertEqual((recovery / 'discarded-prefix/world').read_bytes(), b'newer progress')

                            @contextlib.contextmanager
                            def retry_account(destination, **_kwargs):
                                destination.mkdir()
                                (destination / 'Minecraft.Windows.exe').write_bytes(b'MZretry')
                                yield
                            retry = SimpleNamespace(STATE=state, account=retry_account, prerequisites=lambda _: None,
                                                    prepare=lambda _: None, setup_signature=lambda _: {}, setup_matches=lambda _: True)
                            worker.update_minecraft(retry, log)
                            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZretry')
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    process.stderr.close()

    def update_fixture(self, root, fail=None):
        game = root / 'game'
        game.mkdir()
        (game / 'Minecraft.Windows.exe').write_bytes(b'MZold')
        prefix = root / 'bottles/Bedrock-Standalone'
        prefix.mkdir(parents=True)
        (prefix / 'world').write_bytes(b'original world')
        (prefix / 'settings').write_bytes(b'original settings')
        sessions = []

        @contextlib.contextmanager
        def account(destination, **kwargs):
            self.assertTrue(kwargs['download'])
            self.assertFalse(destination.exists())
            sessions.append('start')
            try:
                if fail == 'download':
                    raise RuntimeError('download failure')
                if fail == 'cancel-download':
                    raise worker.Cancelled()
                destination.mkdir()
                (destination / 'Minecraft.Windows.exe').write_bytes(b'MZnew')
                yield
            finally:
                sessions.append('stop')

        def prerequisites(destination):
            self.assertEqual((destination / 'Minecraft.Windows.exe').read_bytes(), b'MZnew')
            if fail == 'verification':
                raise RuntimeError('verification failure')

        def prepare(destination):
            self.assertEqual(sessions, ['start'], 'Keep the same account helper through preparation')
            self.assertEqual(destination, game)
            (prefix / 'settings').write_bytes(b'new settings')
            if fail in ('prepare', 'cancel-prepare'):
                # Prove whole-prefix rollback, even if a failing preparation
                # unexpectedly changes world data in addition to settings.
                (prefix / 'world').write_bytes(b'modified world')
                if fail == 'cancel-prepare':
                    raise worker.Cancelled()
                raise RuntimeError('prepare failure')

        return SimpleNamespace(STATE=root / 'runtime/standalone/helper-session.json', account=account, prepare=prepare, prerequisites=prerequisites,
                               setup_signature=lambda _: {}, setup_matches=lambda _: True), sessions, prefix

    def test_update_keeps_previous_game_and_world_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, events, prefix = self.update_fixture(root)
            external = root / 'external'
            external.mkdir()
            (external / 'data').write_bytes(b'external data')
            (prefix / 'external-link').symlink_to(external, target_is_directory=True)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                worker.update_minecraft(session, log)
            self.assertEqual(events, ['start', 'stop'])
            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZnew')
            self.assertEqual((prefix / 'world').read_bytes(), b'original world')
            backup, = (root / 'game-backups').iterdir()
            self.assertEqual((backup / 'previous-game/Minecraft.Windows.exe').read_bytes(), b'MZold')
            self.assertEqual((backup / 'previous-prefix/settings').read_bytes(), b'original settings')
            self.assertTrue((backup / 'previous-prefix/external-link').is_symlink())
            self.assertEqual((external / 'data').read_bytes(), b'external data')
            self.assertFalse((root / '.minecraft-update').exists())

    def test_update_failure_and_cancellation_restore_game_and_entire_prefix(self):
        for failure in ('download', 'cancel-download', 'verification', 'prepare', 'cancel-prepare'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                session, events, prefix = self.update_fixture(root, fail=failure)
                with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
                        patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                        tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(worker.Cancelled if failure.startswith('cancel') else RuntimeError):
                        worker.update_minecraft(session, log)
                self.assertEqual(events, ['start', 'stop'])
                self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZold')
                self.assertEqual((prefix / 'world').read_bytes(), b'original world')
                self.assertEqual((prefix / 'settings').read_bytes(), b'original settings')
                self.assertFalse((root / '.minecraft-update').exists())

    def test_update_retry_after_preparation_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, events, prefix = self.update_fixture(root, fail='prepare')
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'prepare failure'):
                    worker.update_minecraft(session, log)
                session.prepare = lambda _: None
                worker.update_minecraft(session, log)
            self.assertEqual(events, ['start', 'stop', 'start', 'stop'])
            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZnew')
            self.assertEqual((prefix / 'world').read_bytes(), b'original world')

    def test_update_uses_one_real_account_context_for_download_and_prepare(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, _, _ = self.update_fixture(root)
            helper = root / 'helper'
            helper.touch()
            state, endpoint = root / 'session.json', root / 'account.sock'
            started = []

            class Helper:
                pid = 32124
                def __init__(self, command, **kwargs):
                    started.append(command)
                    self.returncode = None
                    destination = Path(command[2])
                    destination.mkdir()
                    (destination / 'Minecraft.Windows.exe').write_bytes(b'MZnew')
                    self.socket = socket.socket(socket.AF_UNIX)
                    self.socket.bind(str(endpoint))
                    endpoint.chmod(0o600)
                    kwargs['stdout'].write(b'Starting Xbox account service.\n')
                    kwargs['stdout'].flush()
                def poll(self): return self.returncode
                def send_signal(self, _):
                    self.socket.close()
                    endpoint.unlink()
                    self.returncode = 0
                def wait(self, **_): return self.returncode

            def account_pid():
                return json.loads(state.read_text())['pid'] if state.exists() else None

            session.account = runtime.account
            session.STATE = state
            session.prepare = lambda _: self.assertTrue(runtime.account_ready())
            with patch.object(worker, 'ROOT', root), patch.object(runtime, 'ROOT', root), \
                    patch.object(runtime, 'HELPER', helper), patch.object(runtime, 'STATE', state), \
                    patch.object(runtime, 'SOCKET', endpoint), patch.object(runtime, 'account_pid', account_pid), \
                    patch.object(runtime.subprocess, 'Popen', Helper), patch.object(worker, 'run'), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                worker.update_minecraft(session, log)
            self.assertEqual(len(started), 1)
            self.assertIn('--download', started[0])
            self.assertIn('--serve-after', started[0])
            self.assertEqual(Path(started[0][2]), root / '.minecraft-update/download')
            self.assertFalse(endpoint.exists())
            self.assertFalse(state.exists())

    def test_cancel_during_prefix_snapshot_keeps_original_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, events, prefix = self.update_fixture(root)

            def partial_copy(_source, destination, **_kwargs):
                destination.mkdir()
                (destination / 'world').write_bytes(b'incomplete snapshot')
                raise worker.Cancelled()

            with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
                    patch.object(worker.shutil, 'copytree', side_effect=partial_copy), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(worker.Cancelled):
                    worker.update_minecraft(session, log)
            self.assertEqual(events, ['start', 'stop'])
            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZold')
            self.assertEqual((prefix / 'world').read_bytes(), b'original world')
            self.assertFalse((root / '.minecraft-update').exists())

    def test_update_repairs_incomplete_game_without_deleting_old_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, _, prefix = self.update_fixture(root)
            (root / 'game/Minecraft.Windows.exe').unlink()
            (root / 'game/partial-file').write_bytes(b'old incomplete download')
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
                worker.update_minecraft(session, log)
            backup, = (root / 'game-backups').iterdir()
            self.assertEqual((backup / 'previous-game/partial-file').read_bytes(), b'old incomplete download')
            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZnew')
            self.assertEqual((prefix / 'world').read_bytes(), b'original world')

    def test_recovery_at_each_activation_and_rollback_rename_boundary(self):
        for boundary in ('before-game', 'after-old-game', 'after-new-game', 'preparing', 'rollback-game', 'rollback-prefix', 'after-prefix-restored'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, _, prefix = self.update_fixture(root)
                transaction = root / '.minecraft-update'
                transaction.mkdir()
                (transaction / 'download').mkdir()
                (transaction / 'download/Minecraft.Windows.exe').write_bytes(b'MZnew')
                import shutil
                shutil.copytree(prefix, transaction / 'previous-prefix')
                record = {'phase': 'activating', 'had_game': True, 'had_prefix': True,
                          'backup': 'minecraft-' + '1' * 32}
                if boundary != 'before-game':
                    (root / 'game').rename(transaction / 'previous-game')
                if boundary not in ('before-game', 'after-old-game'):
                    (transaction / 'download').rename(root / 'game')
                if boundary in ('preparing', 'rollback-game', 'rollback-prefix', 'after-prefix-restored'):
                    record['phase'] = 'preparing'
                    (prefix / 'world').write_bytes(b'changed')
                if boundary in ('rollback-game', 'rollback-prefix', 'after-prefix-restored'):
                    (root / 'game').rename(transaction / 'discarded-game')
                    (transaction / 'previous-game').rename(root / 'game')
                if boundary in ('rollback-prefix', 'after-prefix-restored'):
                    prefix.rename(transaction / 'discarded-prefix')
                if boundary == 'after-prefix-restored':
                    (transaction / 'previous-prefix').rename(prefix)
                worker.write_update(transaction, record)
                with patch.object(worker, 'ROOT', root):
                    worker.recover_update()
                    worker.recover_update()  # Idempotent after completion.
                self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZold')
                self.assertEqual((prefix / 'world').read_bytes(), b'original world')
                self.assertFalse(transaction.exists())

    def test_recovery_finishes_committed_update_without_rolling_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, prefix = self.update_fixture(root)
            transaction = root / '.minecraft-update'
            transaction.mkdir()
            (root / 'game').rename(transaction / 'previous-game')
            (root / 'game').mkdir()
            (root / 'game/Minecraft.Windows.exe').write_bytes(b'MZnew')
            record = {'phase': 'committed', 'had_game': True, 'had_prefix': True,
                      'backup': 'minecraft-' + '2' * 32}
            worker.write_update(transaction, record)
            with patch.object(worker, 'ROOT', root):
                worker.recover_update()
            self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZnew')
            self.assertTrue((root / 'game-backups' / record['backup'] / 'previous-game').is_dir())

    def test_recovery_refuses_unrecognized_journal_without_deleting_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transaction = root / '.minecraft-update'
            transaction.mkdir()
            (transaction / 'transaction.json').write_text('{broken')
            (transaction / 'private-file').write_bytes(b'preserve me')
            with patch.object(worker, 'ROOT', root):
                with self.assertRaisesRegex(RuntimeError, 'record could not be read'):
                    worker.recover_update()
            self.assertEqual((transaction / 'private-file').read_bytes(), b'preserve me')

    def test_update_requires_space_for_prefix_backup_before_starting_account(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session, events, _ = self.update_fixture(root)
            with patch.object(worker, 'ROOT', root), \
                    patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=8 * 1024**3)), \
                    tempfile.TemporaryFile() as log:
                with self.assertRaisesRegex(RuntimeError, 'copy of your worlds'):
                    worker.update_minecraft(session, log)
            self.assertEqual(events, [])
            self.assertFalse((root / '.minecraft-update').exists())

    def test_game_bound_profiles_block_update_before_download_or_data_changes(self):
        for marker, tool in (('bedrock-frame-slab.json', 'standalone-bedrock-frame-profile.py'),
                             ('bedrock-refmove.json', 'standalone-bedrock-refmove.py')):
            for dangling in (False, True):
                with self.subTest(marker=marker, dangling=dangling), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    session, events, prefix = self.update_fixture(root)
                    profile = root / 'runtime/standalone/wine' / marker
                    profile.parent.mkdir(parents=True)
                    if dangling:
                        profile.symlink_to(root / 'missing-profile')
                    else:
                        profile.write_text('{"requested_gate": false}')
                    with patch.object(worker, 'ROOT', root), \
                            patch.object(worker.shutil, 'disk_usage') as disk_usage, \
                            tempfile.TemporaryFile() as log:
                        with self.assertRaisesRegex(RuntimeError, tool + ' restore --wine'):
                            worker.update_minecraft(session, log)
                    disk_usage.assert_not_called()
                    self.assertEqual(events, [])
                    self.assertEqual((root / 'game/Minecraft.Windows.exe').read_bytes(), b'MZold')
                    self.assertEqual((prefix / 'world').read_bytes(), b'original world')
                    self.assertFalse((root / '.minecraft-update').exists())
                    self.assertFalse((root / 'game-backups').exists())

    def test_play_and_signout_preserve_bundle_inputs_while_standalone_lock_is_owned(self):
        for argv in (['setup.py'], ['setup.py', '--sign-out']):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home, old, new = root / 'data', root / 'old-app', root / 'new-app'
                home.mkdir()
                (home / 'standalone.py').write_bytes(b'previous script')
                for relative, bundled in worker.BUNDLE_LINKS.items():
                    link = home / relative
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(old / bundled)
                session = SimpleNamespace(game_running=unittest.mock.Mock())
                with (home / 'runtime/standalone/launcher.lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with patch.object(worker, 'ROOT', home), patch.object(worker, 'BUNDLE', new), \
                            patch.object(worker, 'load', return_value=session), \
                            patch.object(worker, 'initialize_bundle') as initialize, \
                            patch('sys.argv', argv):
                        with self.assertRaisesRegex(RuntimeError, 'Close Minecraft'):
                            worker.main()
                initialize.assert_not_called()
                session.game_running.assert_not_called()
                self.assertEqual((home / 'standalone.py').read_bytes(), b'previous script')
                for relative, bundled in worker.BUNDLE_LINKS.items():
                    self.assertEqual((home / relative).readlink(), old / bundled)

    def test_bundle_refresh_holds_standalone_lock_and_checks_idle_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            order = []
            session = SimpleNamespace(game_running=lambda: False, account_pid=lambda: None,
                                      recover_account_socket=lambda: None,
                                      WINE=root / 'runtime/standalone/wine',
                                      wait_for_idle_prefix=lambda: order.append('idle'))

            def initialize():
                order.append('write')
                with (root / 'runtime/standalone/launcher.lock').open('a') as lock:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

            with patch.object(worker, 'ROOT', root), patch.object(worker, 'BUNDLE', root / 'app'), \
                    patch.object(worker, 'load', return_value=session), \
                    patch.object(worker, 'initialize_bundle', side_effect=initialize):
                worker.initialize_session_bundle()
            self.assertEqual(order, ['idle', 'write'])
            with (root / 'runtime/standalone/launcher.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_maintenance_rejects_live_game_or_account_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(worker, 'ROOT', Path(temporary)):
            for game_active, account_pid in ((True, None), (False, 123)):
                session = SimpleNamespace(game_running=lambda: game_active, account_pid=lambda: account_pid,
                                          wait_for_idle_prefix=unittest.mock.Mock(), recover_account_socket=lambda: None)
                with self.assertRaisesRegex(RuntimeError, 'Close Minecraft|account helper is still running'):
                    with worker.maintenance_lock(session):
                        self.fail('Maintenance cannot reuse a live account')
                session.wait_for_idle_prefix.assert_not_called()
            session = SimpleNamespace(game_running=lambda: False, account_pid=lambda: None,
                                      wait_for_idle_prefix=lambda: None, recover_account_socket=lambda: None)
            with worker.maintenance_lock(session):
                with self.assertRaisesRegex(RuntimeError, 'Close Minecraft'):
                    with worker.maintenance_lock(session):
                        self.fail('Maintenance lock must be exclusive')

    def test_moved_app_maintenance_checks_idle_using_new_runtime_before_relink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / 'new-app'
            old_wine = root / 'runtime/standalone/wine'
            old_wine.parent.mkdir(parents=True)
            old_wine.symlink_to(root / 'deleted-app/runtime/wine')
            checked = []
            session = SimpleNamespace(WINE=old_wine, game_running=lambda: False, account_pid=lambda: None, recover_account_socket=lambda: None)
            session.wait_for_idle_prefix = lambda: checked.append(session.WINE)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'BUNDLE', bundle):
                with worker.maintenance_lock(session):
                    self.assertEqual(session.WINE, old_wine)
            self.assertEqual(checked, [bundle / 'runtime/wine'])
            self.assertEqual(old_wine.readlink(), root / 'deleted-app/runtime/wine')

    def test_install_and_launch_share_one_account_process(self):
        self.run_account_flow()

    def test_first_download_and_launch_share_selected_market_and_account(self):
        self.run_account_flow(market='TR')

    def test_preparation_failure_stops_the_shared_helper_and_never_launches(self):
        self.run_account_flow(fail_prepare=True)

    def run_account_flow(self, fail_prepare=False, market='CA'):
        # Exercise the real worker orchestration and runtime account context.
        # The fake child provides a real private socket and counts each launch.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            helper = root / 'helper'
            helper.touch()
            state, endpoint = root / 'session.json', root / 'account.sock'
            started, commands = [], []

            class Helper:
                pid = 32123
                def __init__(self, command, **kwargs):
                    started.append(command)
                    self.returncode = None
                    (root / 'game').mkdir(exist_ok=True)
                    self.socket = socket.socket(socket.AF_UNIX)
                    self.socket.bind(str(endpoint))
                    endpoint.chmod(0o600)
                    kwargs['stdout'].write(b'Finding the Windows package\nStarting Xbox account service.\n')
                    kwargs['stdout'].flush()
                def poll(self): return self.returncode
                def send_signal(self, _):
                    self.socket.close()
                    endpoint.unlink()
                    self.returncode = 0
                def wait(self, **_): return self.returncode

            def account_pid():
                return json.loads(state.read_text())['pid'] if state.exists() else None

            def command(command, *_args, **_kwargs):
                commands.append(command[-1])
                if command[-1] == 'prepare' and fail_prepare:
                    raise RuntimeError('Preparation failed')
                if command[-1] in ('--download-game', 'launch'):
                    with runtime.account(root / 'game'):
                        self.assertTrue(runtime.account_ready())

            with patch.object(worker, 'ROOT', root), patch.object(runtime, 'ROOT', root), \
                    patch.object(runtime, 'HELPER', helper), patch.object(runtime, 'STATE', state), \
                    patch.object(runtime, 'SOCKET', endpoint), patch.object(runtime, 'account_pid', account_pid), \
                    patch.object(runtime.subprocess, 'Popen', Helper), \
                    patch.object(worker, 'installed', return_value=False), \
                    patch.object(worker, 'load', return_value=runtime), \
                    patch.object(worker, 'validate_install', create=True), \
                    patch.object(worker, 'run', side_effect=command), \
                    patch.object(worker.platform, 'machine', return_value='arm64'), \
                    patch.object(worker.platform, 'mac_ver', return_value=('26.0', (), '')), \
                    patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
                    patch('sys.argv', ['setup.py', '--market', market]), contextlib.redirect_stdout(io.StringIO()):
                for relative in ('runtime/standalone/wine/build-manifest.json',
                                 'runtime/standalone/dxmt/manifest.json',
                                 'sources/xodus/target/release/examples/standalone_helper'):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                if fail_prepare:
                    with self.assertRaisesRegex(RuntimeError, 'Preparation failed'):
                        worker.main()
                else:
                    worker.main()
            self.assertEqual(len(started), 1, 'Setup must not start a second Keychain-reading helper for play')
            self.assertIn('--download', started[0])
            self.assertIn('--serve-after', started[0])
            self.assertEqual(started[0][started[0].index('--market') + 1], market)
            self.assertEqual(commands, ['--threading', 'prepare'] + ([] if fail_prepare else ['launch']))
            self.assertFalse(endpoint.exists())
            self.assertFalse(state.exists())

    def test_keychain_failure_has_actionable_message(self):
        with tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'macOS Keychain prompt'):
                worker.run([sys.executable, '-c', "print('BEDROCK_ERROR:keychain_access'); raise SystemExit(1)"],
                           log, 'Generic failure', account_progress=True)

    def test_account_failure_reports_known_stage_instead_of_blaming_signin(self):
        with tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'download format'):
                worker.run([sys.executable, '-c', "print('BEDROCK_ERROR:package_format'); raise SystemExit(1)"],
                           log, 'Generic failure', account_progress=True)

    def test_unknown_helper_error_never_becomes_ui_text(self):
        with tempfile.TemporaryFile() as log, contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(RuntimeError, '^Generic failure$'):
                worker.run([sys.executable, '-c', "print('BEDROCK_ERROR:private-response'); raise SystemExit(1)"],
                           log, 'Generic failure', account_progress=True)
            self.assertNotIn('private-response', output.getvalue())

    def test_bundle_setup_preserves_worlds_and_relinks_after_app_move(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            home, bundle = folder / 'data', folder / 'app'
            (home / 'game').mkdir(parents=True)
            world = home / 'game/world.save'
            world.write_text('existing world')
            saved_world = home / 'bottles/Bedrock-Standalone/drive_c/users/player/AppData/Roaming/Minecraft Bedrock/account/games/com.mojang/minecraftWorlds/world/db'
            saved_world.mkdir(parents=True)
            (saved_world / 'CURRENT').write_bytes(b'world database')
            (bundle / 'scripts').mkdir(parents=True)
            for name in ('standalone.py', 'standalone-setup.py', 'standalone-gameinput.py', 'standalone-pickers.py', 'winrt.reg'):
                (bundle / 'scripts' / name).write_text('bundled script')
            with patch.object(worker, 'ROOT', home), patch.object(worker, 'BUNDLE', bundle):
                worker.initialize_bundle()
                worker.initialize_bundle()
            moved = folder / 'moved-app'
            bundle.rename(moved)
            with patch.object(worker, 'ROOT', home), patch.object(worker, 'BUNDLE', moved):
                worker.initialize_bundle()
            self.assertEqual(world.read_text(), 'existing world')
            self.assertEqual((saved_world / 'CURRENT').read_bytes(), b'world database')
            self.assertEqual((home / 'runtime/standalone/wine').resolve(), (moved / 'runtime/wine').resolve())

    def test_upgrade_status_requires_this_apps_links_without_changing_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, old, new = root / 'data', root / 'old-app', root / 'new-app'
            home.mkdir()
            (home / 'standalone.py').touch()
            fixture_runtime = SimpleNamespace(prerequisites=lambda _: None, HELPER=home / 'standalone.py',
                                              setup_signature=lambda _: {}, setup_matches=lambda _: True)
            for relative, bundled in worker.BUNDLE_LINKS.items():
                link = home / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(old / bundled)
            with patch.object(worker, 'ROOT', home), patch.object(worker, 'BUNDLE', new), \
                    patch.object(worker, 'load', return_value=fixture_runtime):
                self.assertFalse(worker.installed())
                self.assertEqual((home / 'runtime/standalone/wine').readlink(), old / 'runtime/wine')
                for relative, bundled in worker.BUNDLE_LINKS.items():
                    link = home / relative
                    link.unlink()
                    link.symlink_to(new / bundled)
                self.assertTrue(worker.installed())

    def test_upgrade_preserves_conflicting_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, bundle = root / 'data', root / 'app'
            saved = home / 'runtime/standalone/wine/local-file'
            saved.parent.mkdir(parents=True)
            saved.write_bytes(b'preserve installation')
            (bundle / 'scripts').mkdir(parents=True)
            for name in ('standalone.py', 'standalone-setup.py', 'standalone-gameinput.py', 'standalone-pickers.py', 'winrt.reg'):
                (bundle / 'scripts' / name).write_text('bundled script')
            with patch.object(worker, 'ROOT', home), patch.object(worker, 'BUNDLE', bundle):
                with self.assertRaisesRegex(RuntimeError, 'existing installation blocks'):
                    worker.initialize_bundle()
            self.assertEqual(saved.read_bytes(), b'preserve installation')
            self.assertFalse(saved.parent.is_symlink())

    def test_first_install_uses_only_bundled_components(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(worker, 'ROOT', Path(folder)), \
                patch.object(worker.platform, 'machine', return_value='arm64'), \
                patch.object(worker.platform, 'mac_ver', return_value=('26.0', (), '')), \
                patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=10 * 1024**3)), \
                patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
                patch.object(worker, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            for relative in ('runtime/standalone/wine/build-manifest.json',
                             'runtime/standalone/dxmt/manifest.json',
                             'sources/xodus/target/release/examples/standalone_helper'):
                path = Path(folder) / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with tempfile.TemporaryFile() as log:
                worker.install(log)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual([command[-1] for command in commands], ['--threading', 'prepare'])
            self.assertEqual([Path(command[1]).name for command in commands],
                             ['standalone-setup.py', 'standalone.py'])

    def test_returning_player_skips_installation_and_launches(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(worker, 'ROOT', Path(folder)), \
                patch.object(worker, 'installed', return_value=True), patch.object(worker, 'validate_install'), \
                patch.object(worker, 'load', return_value=SimpleNamespace(
                    account=lambda *a, **kw: contextlib.nullcontext(), AccountError=runtime.AccountError)), \
                patch.object(worker, 'install') as install, patch.object(worker, 'run') as run, \
                patch('sys.argv', ['setup.py']), contextlib.redirect_stdout(io.StringIO()) as output:
            worker.main()
            install.assert_not_called()
            self.assertEqual(run.call_args.args[0][-1], 'launch')
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1])['state'], 'ready')

    def test_failed_setup_never_launches_the_game(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(worker, 'ROOT', Path(folder)), \
                patch.object(worker, 'installed', return_value=False), \
                patch.object(worker, 'validate_install'), \
                patch.object(worker, 'load', return_value=SimpleNamespace(
                    account=lambda *a, **kw: contextlib.nullcontext(), AccountError=runtime.AccountError)), \
                patch.object(worker, 'install', side_effect=RuntimeError('Setup failed')), \
                patch.object(worker, 'run') as run, patch('sys.argv', ['setup.py']):
            with self.assertRaisesRegex(RuntimeError, 'Setup failed'):
                worker.main()
            run.assert_not_called()

    def test_download_progress_advances_and_rejects_invalid_counts(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            worker.account_update(b'Checking the signed Minecraft package header.\n')
            worker.account_update(b"Checking this account's Minecraft ownership.\n")
            worker.account_update(b'Downloading Minecraft into private staging.\n')
            worker.account_update(b"Checking Microsoft's game signature and package integrity.\n")
            worker.account_update(b'Downloading Minecraft 1.26 (1000 files).\n')
            worker.account_update(b'Downloaded 500/1000 files.\n')
            worker.account_update(b'Downloaded 1000/1000 files.\n')
            worker.account_update(b'Downloaded 1/0 files.\n')
            worker.account_update(b'Downloaded 2/1 files.\n')
        statuses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([status['title'] for status in statuses], [
            'Checking download', 'Checking your Minecraft purchase', 'Downloading Minecraft',
            'Checking download', 'Preparing Minecraft', 'Preparing Minecraft', 'Preparing Minecraft'])
        self.assertEqual([status['progress'] for status in statuses], sorted(status['progress'] for status in statuses))
        self.assertTrue(all(0 <= event['progress'] <= 1 for event in statuses))

    def test_cancel_stops_owned_command(self):
        child = unittest.mock.Mock(pid=98765)
        child.wait.side_effect = [worker.Cancelled(), 0]
        child.poll.return_value = None
        with tempfile.TemporaryFile() as log, \
                patch.object(worker.subprocess, 'Popen', return_value=child), \
                patch.object(worker.os, 'killpg') as kill:
            with self.assertRaises(worker.Cancelled):
                worker.run(['fake-download'], log, 'Failed')
        kill.assert_called_once_with(98765, worker.signal.SIGTERM)

    def test_cleanup_accepts_child_exiting_after_timeout(self):
        child = unittest.mock.Mock(pid=98765)
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('fixture', 15), 0]
        with patch.object(worker.os, 'killpg', side_effect=[None, ProcessLookupError]):
            worker.stop_command(child)
        self.assertEqual(child.wait.call_count, 2)

    def test_cancel_releases_setup_lock_and_retry_preserves_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'game').mkdir()
            (root / 'game/Minecraft.Windows.exe').touch()
            world = root / 'bottles/Bedrock-Standalone/fixture-world'
            world.parent.mkdir(parents=True)
            world.write_bytes(b'existing world')
            sessions = []

            @contextlib.contextmanager
            def account(*_args, **_kwargs):
                sessions.append('start')
                try:
                    yield
                finally:
                    sessions.append('stop')

            fixture_runtime = SimpleNamespace(account=account, AccountError=runtime.AccountError)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'BUNDLE', None), \
                    patch.object(worker, 'installed', return_value=False), \
                    patch.object(worker, 'validate_install'), patch.object(worker, 'load', return_value=fixture_runtime), \
                    patch.object(worker, 'install', side_effect=[worker.Cancelled(), None]), \
                    patch.object(worker, 'run') as run, patch('sys.argv', ['setup.py']), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(worker.Cancelled):
                    worker.main()
                run.assert_not_called()
                worker.main()
                self.assertEqual(run.call_args.args[0][-1], 'launch')
            self.assertEqual(sessions, ['start', 'stop', 'start', 'stop'])
            self.assertEqual(world.read_bytes(), b'existing world')
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1])['state'], 'ready')

    def test_failed_setup_can_retry_without_redownloading_existing_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'game').mkdir()
            game = root / 'game/Minecraft.Windows.exe'
            game.write_bytes(b'MZexisting game')
            account = unittest.mock.Mock(side_effect=lambda *a, **kw: contextlib.nullcontext())
            fixture_runtime = SimpleNamespace(account=account, AccountError=runtime.AccountError)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'BUNDLE', None), \
                    patch.object(worker, 'installed', return_value=False), patch.object(worker, 'validate_install'), \
                    patch.object(worker, 'load', return_value=fixture_runtime), \
                    patch.object(worker, 'install', side_effect=[RuntimeError('fixture failure'), None]), \
                    patch.object(worker, 'run') as run, patch('sys.argv', ['setup.py']), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                    worker.main()
                run.assert_not_called()
                worker.main()
            self.assertEqual([call.kwargs['download'] for call in account.call_args_list], [False, False])
            self.assertEqual(game.read_bytes(), b'MZexisting game')

    def test_cancel_terminates_a_real_download_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            pidfile = folder / 'download.pid'
            child_script = folder / 'download.py'
            child_script.write_text("import os, time, pathlib\npathlib.Path(" + repr(str(pidfile)) + ").write_text(str(os.getpid()))\ntime.sleep(60)\n")
            wrapper = folder / 'worker.py'
            wrapper.write_text("import importlib.util, signal\n"
                + "s=importlib.util.spec_from_file_location('worker', " + repr(worker.__file__) + ")\n"
                + "w=importlib.util.module_from_spec(s); s.loader.exec_module(w)\n"
                + "signal.signal(signal.SIGTERM,w.cancel)\n"
                + "try:\n with open(" + repr(str(folder / 'log')) + ", 'wb') as log: w.run("
                + repr([sys.executable, str(child_script)]) + ",log,'failed')\n"
                + "except w.Cancelled: pass\n")
            process = subprocess.Popen([sys.executable, str(wrapper)])
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if pidfile.exists() and pidfile.read_text().strip():
                        break
                    time.sleep(0.02)
                self.assertTrue(pidfile.exists(), 'Fixture download never started')
                pid = int(pidfile.read_text())
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=10), 0)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_upgrade_status_reads_the_new_bundled_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, bundle = root / 'data', root / 'app'
            data.mkdir()
            (bundle / 'scripts').mkdir(parents=True)
            (data / 'standalone.py').write_text("raise RuntimeError('Old installed code must not run')")
            (bundle / 'scripts/standalone.py').write_text("VERSION = 'new'")
            with patch.object(worker, 'ROOT', data), patch.object(worker, 'BUNDLE', bundle):
                self.assertEqual(worker.load('fixture_runtime', 'standalone.py').VERSION, 'new')

    def test_status_does_not_install_or_launch(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(worker, 'ROOT', Path(temporary)), \
                patch.object(worker, 'installed', return_value=False), \
                patch.object(worker, 'install') as install, patch.object(worker, 'run') as run, \
                patch('sys.argv', ['setup.py', '--status']), contextlib.redirect_stdout(io.StringIO()) as output:
            worker.main()
            self.assertEqual(json.loads(output.getvalue())['state'], 'new')
            install.assert_not_called()
            run.assert_not_called()

    def test_status_offers_existing_game_setup_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'game').mkdir()
            (root / 'game/Minecraft.Windows.exe').write_bytes(b'MZfixture')
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'installed', return_value=False), \
                    patch.object(worker, 'initialize_bundle') as initialize, patch.object(worker, 'run') as run, \
                    patch('sys.argv', ['setup.py', '--status']), contextlib.redirect_stdout(io.StringIO()) as output:
                worker.main()
            self.assertEqual(json.loads(output.getvalue())['state'], 'update')
            initialize.assert_not_called()
            run.assert_not_called()
            self.assertFalse((root / 'logs').exists())

    def test_command_failure_does_not_leak_process_output_to_ui(self):
        with tempfile.TemporaryFile() as log, \
                patch.object(worker.subprocess, 'Popen', return_value=unittest.mock.Mock(wait=lambda: 1, poll=lambda: 1)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(RuntimeError, '^Friendly failure$'):
                worker.run(['false'], log, 'Friendly failure')
            self.assertEqual(output.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
