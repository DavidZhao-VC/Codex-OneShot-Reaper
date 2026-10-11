"""Portability regressions: shell selection and registration discovery."""
import importlib.util
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows Job Objects')
class PortabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (BASE / 'test_runs').mkdir(exist_ok=True)

    def load_manager(self):
        spec = importlib.util.spec_from_file_location('portable_manager', BASE / 'manager.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_explicit_shell_override_runs_real_command(self):
        # Ignoring the override must fail even on machines with a bundled shell.
        with tempfile.TemporaryDirectory(prefix='portable-', dir=BASE / 'test_runs') as folder:
            shell = shutil.which('pwsh') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe')
            env = dict(os.environ, CODEX_LIFECYCLE_PWSH=shell)
            payload = {'cwd':folder, 'tool_name':'Bash', 'tool_input':{'command':'# codex-lifecycle: oneshot\nWrite-Output portable-ok'}}
            result = subprocess.run([sys.executable, str(BASE / 'manager.py'), 'execute'], env=env,
                                    input=json.dumps(payload).encode(), capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(b'portable-ok', result.stdout)
            env['CODEX_LIFECYCLE_PWSH'] = str(Path(folder) / 'missing-shell.exe')
            result = subprocess.run([sys.executable, str(BASE / 'manager.py'), 'execute'], env=env,
                                    input=json.dumps(payload).encode(), capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0, 'Explicit missing shell was silently ignored')

    def test_configured_workspace_is_discovered_under_custom_codex_home(self):
        # A hardcoded user config would miss this registered pending task.
        with tempfile.TemporaryDirectory(prefix='config-', dir=BASE / 'test_runs') as folder:
            root = Path(folder)
            home = root / 'codex-home'
            workspace = root / 'project'
            home.mkdir()
            workspace.mkdir()
            (home / 'config.toml').write_text('[projects.' + json.dumps(str(workspace)) + ']\ntrust_level = "trusted"\n', encoding='utf-8')
            m = self.load_manager()
            with patch.object(m, 'CATALOG', root / 'catalog'), patch.object(m, 'EVENTS', root / 'events'):
                result = m.prepare({'cwd':str(workspace), 'tool_name':'Bash', 'tool_input':{'command':'# codex-lifecycle: oneshot\nWrite-Output pending'}})
                record = json.loads(Path(result['record_path']).read_text(encoding='utf-8'))
                # Remove only this test's catalog file to force configured-root discovery.
                (m.CATALOG / (record['run_id'] + '.json')).unlink()
                with patch.dict(os.environ, {'CODEX_HOME':str(home)}), contextlib.chdir(root):
                    results = m.sweep()
                self.assertIn({'run_id':record['run_id'], 'decision':'keep_pending'}, results)

    def test_missing_config_allows_direct_workspace_sweep(self):
        with tempfile.TemporaryDirectory(prefix='no-config-', dir=BASE / 'test_runs') as folder:
            root = Path(folder)
            m = self.load_manager()
            with patch.object(m, 'CATALOG', root / 'catalog'), patch.object(m, 'EVENTS', root / 'events'), patch.dict(os.environ, {'CODEX_HOME':str(root / 'absent')}), contextlib.chdir(root):
                # No user installation is required for standalone maintenance.
                results = m.sweep()
                self.assertEqual(results, [])

    def test_generated_hook_config_runs_without_editing_user_settings(self):
        with tempfile.TemporaryDirectory(prefix='hook-config-', dir=BASE / 'test_runs') as folder:
            env = dict(os.environ, CODEX_HOME=str(Path(folder) / 'codex-home'))
            result = subprocess.run([sys.executable, str(BASE / 'print_hooks.py')],
                                    env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            config = tomllib.loads(result.stdout.decode('utf-8'))
            self.assertEqual(set(config['hooks']), {'PreToolUse','PostToolUse','Stop','SessionEnd'})
            self.assertFalse(Path(env['CODEX_HOME']).exists(), 'Generator edited user settings')
            handler = config['hooks']['PreToolUse'][0]['hooks'][0]['command']
            m = self.load_manager()
            payload = {'cwd':folder, 'tool_name':'Bash', 'tool_input':{'command':'# codex-lifecycle: oneshot\nWrite-Output generated-config-ok'}}
            result = subprocess.run([str(m.PWSH), '-NoProfile', '-Command', handler],
                                    env=env, input=json.dumps(payload).encode(), capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            response = json.loads(result.stdout)
            self.assertIn('updatedInput', response['hookSpecificOutput'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
