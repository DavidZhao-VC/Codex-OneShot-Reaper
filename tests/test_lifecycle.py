"""Real Windows lifecycle tests; all subprocesses belong to this test."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time
import unittest
import uuid

BASE = pathlib.Path(__file__).resolve().parents[1]
MODULE = BASE / 'manager.py'
PWSH = None


@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows Job Objects')
class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global PWSH
        cls.m = None
        if MODULE.exists():
            spec = importlib.util.spec_from_file_location('lifecycle', MODULE)
            cls.m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.m)
            PWSH = str(cls.m.PWSH)
        cls.workspace = BASE / 'test_runs' / str(uuid.uuid4())
        cls.workspace.mkdir(parents=True)
        cls.env_before = {key: os.environ.get(key) for key in ('CODEX_HOME', 'CODEX_LIFECYCLE_PYTHON')}
        os.environ['CODEX_HOME'] = str(cls.workspace / 'isolated-codex-home')
        os.environ['CODEX_LIFECYCLE_PYTHON'] = sys.executable

    @classmethod
    def tearDownClass(cls):
        for key, value in cls.env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def manager(self):
        self.assertIsNotNone(self.m, 'One-shot process manager has not been implemented')
        return self.m

    def hook(self, command):
        return self.manager().prepare({'session_id': 'test-session', 'cwd': str(self.workspace),
            'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
            'tool_use_id': str(uuid.uuid4()), 'tool_input': {'command': command}})

    def launch(self, body):
        result = self.hook('# codex-lifecycle: oneshot\n' + body)
        record = pathlib.Path(result['record_path'])
        proc = subprocess.Popen([sys.executable, str(MODULE), 'run', '--record', str(record)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return proc, record

    def child_body(self, receipt, code=0, delay=0):
        # A real sleeping child, intentionally left behind by a completed root.
        return "$p = Start-Process -WindowStyle Hidden -FilePath '" + PWSH + "' -ArgumentList @('-NoProfile','-Command','Start-Sleep 120') -PassThru\n" + \
            "$p.Id | Set-Content -LiteralPath '" + str(receipt) + "'\n" + \
            f"Write-Output 'output-preserved'\nStart-Sleep {delay}\nexit {code}"

    def wait_file(self, path):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if path.exists():
                try:
                    return int(path.read_text(encoding='utf-8-sig').strip())
                except ValueError:
                    pass
            time.sleep(.1)
        self.fail('Controlled child did not start')

    def test_completed_root_reclaims_child_and_preserves_output(self):
        m = self.manager()
        receipt = self.workspace / 'completed-child.txt'
        proc, record = self.launch(self.child_body(receipt))
        output, error = proc.communicate(timeout=20)
        child = self.wait_file(receipt)
        self.assertEqual(proc.returncode, 0, error.decode(errors='replace'))
        self.assertIn(b'output-preserved', output)
        self.assertIsNone(m.birth(child), 'Child survived completed root')
        self.assertEqual(json.loads(record.read_text())['state'], 'completed')

    def test_failed_root_reclaims_child_and_preserves_exit_code(self):
        m = self.manager()
        receipt = self.workspace / 'failed-child.txt'
        proc, record = self.launch(self.child_body(receipt, code=7))
        output, error = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 7, error.decode(errors='replace'))
        self.assertIsNone(m.birth(self.wait_file(receipt)))
        self.assertEqual(json.loads(record.read_text())['exit_code'], 7)

    def test_sweep_keeps_running_job_even_at_session_end_then_wrapper_crash_cleans(self):
        m = self.manager()
        receipt = self.workspace / 'running-child.txt'
        proc, record = self.launch(self.child_body(receipt, delay=120))
        try:
            child = self.wait_file(receipt)
            child_birth = m.birth(child)
            self.assertIsNotNone(child_birth)
            result = m.sweep_record(record)
            self.assertEqual(result['decision'], 'keep_running')
            self.assertEqual(m.birth(child), child_birth)
            # Kill only this test's wrapper, to reproduce a crashed manager.
            proc.kill()
            proc.communicate(timeout=10)
            deadline = time.monotonic() + 5
            while m.birth(child) is not None and time.monotonic() < deadline:
                time.sleep(.1)
            self.assertIsNone(m.birth(child), 'OS job did not reclaim child on manager crash')
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=10)

    def test_protected_and_unmarked_commands_are_not_rewritten(self):
        for command in ['ssh host', '# codex-lifecycle: persistent\nStart-Process worker',
                        '# codex-lifecycle: oneshot\npython train.py',
                        '# codex-lifecycle: oneshot\npython C:\\work\\research_project\\check.py',
                        '# codex-lifecycle: oneshot\nuvx blender-mcp',
                        '# codex-lifecycle: oneshot\nssh host']:
            with self.subTest(command=command):
                self.assertNotIn('updatedInput', self.hook(command)['hookSpecificOutput'])

    def test_hook_rewrite_is_executable_and_keeps_quoted_chinese_text(self):
        result = self.hook("# codex-lifecycle: oneshot\nWrite-Output '中文与引号 $() ` 正常'")
        rewritten = result['hookSpecificOutput']['updatedInput']['command']
        proc = subprocess.run([PWSH, '-NoProfile', '-Command', rewritten],
            capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode(errors='replace'))
        self.assertIn('中文与引号 $() ` 正常', proc.stdout.decode('utf-8-sig'))

    def test_hook_command_runs_in_powershell(self):
        self.manager()
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        handler = '& ' + quote(sys.executable) + ' ' + quote(MODULE) + ' pre'
        payload = {'session_id':'test-session', 'cwd':str(self.workspace), 'tool_name':'Bash',
                   'tool_input':{'command':"# codex-lifecycle: oneshot\nWrite-Output 'contract-ok'"}}
        result = subprocess.run([PWSH, '-NoProfile', '-Command', handler],
                                input=json.dumps(payload).encode(), capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        response = json.loads(result.stdout)
        self.assertEqual(response['hookSpecificOutput']['permissionDecision'], 'allow')
        self.assertIn('updatedInput', response['hookSpecificOutput'])

    def test_runtime_workdir_override_is_preserved(self):
        self.manager()
        actual = self.workspace / 'explicit_workdir'
        actual.mkdir()
        result = self.hook('# codex-lifecycle: oneshot\n(Get-Location).Path')
        rewritten = result['hookSpecificOutput']['updatedInput']['command']
        proc = subprocess.run([PWSH, '-NoProfile', '-Command', rewritten], cwd=actual,
                              capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode(errors='replace'))
        self.assertEqual(proc.stdout.decode('utf-8-sig').strip(), str(actual))

    def test_rewritten_tool_preserves_nonzero_exit_code(self):
        result = self.hook('# codex-lifecycle: oneshot\nexit 7')
        proc = subprocess.run([PWSH, '-NoProfile', '-Command',
                               result['hookSpecificOutput']['updatedInput']['command']],
                              capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 7)

    def test_direct_entry_reclaims_child_without_loaded_hooks(self):
        m = self.manager()
        helper = BASE / 'Invoke-OneShot.ps1'
        self.assertTrue(helper.exists(), 'Direct entry for existing sessions is missing')
        receipt = self.workspace / 'direct-child.txt'
        script = "& '" + str(helper) + "' -ScriptBlock {\n" + self.child_body(receipt, code=7) + '\n}\nexit $LASTEXITCODE'
        proc = subprocess.run([PWSH, '-NoProfile', '-Command', script],
                              capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 7, proc.stderr.decode(errors='replace'))
        self.assertIsNone(m.birth(self.wait_file(receipt)))

    def test_maintenance_events_keep_unregistered_running_process(self):
        m = self.manager()
        unregistered = subprocess.Popen([PWSH, '-NoProfile', '-Command', 'Start-Sleep 120'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            original = m.birth(unregistered.pid)
            for event in ['PostToolUse', 'Stop', 'SessionEnd']:
                payload = {'session_id':'test-session', 'hook_event_name':event}
                result = subprocess.run([sys.executable, str(MODULE), 'maintenance'],
                    input=json.dumps(payload).encode(), capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                self.assertEqual(m.birth(unregistered.pid), original)
        finally:
            unregistered.terminate()  # Tear down only the process this test owns.
            unregistered.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
