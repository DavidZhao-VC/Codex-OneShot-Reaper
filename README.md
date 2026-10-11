# Codex-OneShot-Reaper

Codex-OneShot-Reaper reclaims leftover child processes from finite local Windows
PowerShell commands. Each opted-in command starts in a new Windows Job Object.
When its root command finishes, or its manager exits, Windows reclaims the
remaining children of that job. Existing processes are never enrolled.

[中文说明](README.zh-CN.md)

## What it protects

- A running registered manager is retained, including when a chat ends or is idle.
- Research, training, SSH, WSL, downloads, rendering, interactive commands and
  long-lived tool services use their normal lifecycle. A conservative command
  recognizer declines common protected commands.
- Maintenance only opens registered jobs with the expected identity and limits.
  PID creation-time changes, denied access and uncertain ownership cause a skip.
- Unregistered processes are never cleaned up by name, age, CPU, memory or PID.

The protection recognizer is a guardrail, not a complete classifier. Only mark a
command one-shot when its entire local process group should end with its root.

## Requirements

- Windows with Job Object support (tested locally on Windows 11).
- Python 3.11 or later; standard library only.
- PowerShell 7. The manager tries `CODEX_LIFECYCLE_PWSH`, then `pwsh` on PATH,
  then the current user's bundled Codex PowerShell location. Set the environment
  variable to an absolute executable path if discovery does not fit your setup.
- For automatic hooks: a local Codex version supporting the hook format below,
  with its shell tool reported to the hook as `Bash`. Other tool backends need
  their own verified integration. The direct entry works without loaded hooks.

## Start with the direct entry

Clone this repository into a directory your Codex workspace can read. In a
PowerShell command, invoke the entry with the finite command in a script block:

```powershell
& 'C:\tools\codex-oneshot-lifecycle\Invoke-OneShot.ps1' -ScriptBlock {
    Write-Output 'A finite local task'
}
exit $LASTEXITCODE
```

Replace the example path with your clone location. The helper uses `python` on
PATH. You can select an interpreter with `-Python 'C:\path\to\python.exe'` or
the `CODEX_LIFECYCLE_PYTHON` environment variable. Keep the final `exit` when
calling through another PowerShell command so nonzero exit codes are preserved.

For already loaded Codex chats, prefer this explicit entry. A comment alone does
not prove that a hook is active. The hook recognizes the direct entry and avoids
wrapping it twice. Protected commands are rejected by the direct entry.

## Optional Codex hooks

Generate a snippet for the interpreter and clone location on your machine:

```powershell
python .\print_hooks.py > hooks.local.toml
```

The generator prints TOML only. Back up your Codex config and merge the snippet
into `%CODEX_HOME%\config.toml`, or `%USERPROFILE%\.codex\config.toml` when
`CODEX_HOME` is unset. Preserve any existing hook handlers. Review and trust the
hooks through your Codex installation's supported controls; the generator does
not forge trust records or enable hooks itself. Start a fresh local chat and
verify actual hook dispatch before relying on comment-based wrapping.

Once verified, finite commands may opt in with this first line:

```powershell
# codex-lifecycle: oneshot
Write-Output 'A finite local task'
```

Background or protected work uses the original execution path or an explicit
`# codex-lifecycle: persistent` marker. Unmarked commands are left alone.

The four handlers are:

| Event | Action |
| --- | --- |
| PreToolUse (`^Bash$`) | Wrap opted-in commands, retain protected commands |
| PostToolUse (`^Bash$`) | Check this session's registered jobs |
| Stop | Check this session's registered jobs |
| SessionEnd | Check this session's registered jobs |

`Stop` and `SessionEnd` do not stop a still-running manager. A running tool
session ID is not evidence that its command has finished.

## Optional 30-minute fallback

Ask Codex to configure a heartbeat using the [schedule prompt](docs/heartbeat.md).
The repository does not create a schedule merely by being cloned.

The check's own shell invocation should remain on the persistent execution path:

```powershell
# codex-lifecycle: persistent
python 'C:\tools\codex-oneshot-lifecycle\manager.py' sweep
exit $LASTEXITCODE
```

`sweep` uses this clone's catalog, the current directory, and the project roots in
the selected Codex config. It scans only `.codex-process-lifecycle/*.json` under
those roots, never the whole disk. With no config, the catalog and current
workspace still work. It reports a decision for every inspected registration.
Inspect `skip_error` entries even when the CLI itself exits with code zero.

## How reclamation works

1. A registered command receives a random dedicated job name and command hash.
2. The manager creates a new PowerShell process suspended, assigns that new
   process handle to the new job, then resumes it.
3. The job has `KILL_ON_JOB_CLOSE` and no normal breakaway permission. Ordinary
   child processes inherit membership.
4. The manager waits for the root's actual exit, preserves its output and exit
   code, and closes the job handle. Remaining children are reclaimed by Windows.
5. If the manager crashes, closing its handles triggers the same OS cleanup.
   Maintenance checks owner identity again before acting on a registered job.

## Records, permissions and limits

Per-command records are written under the workspace's `.codex-process-lifecycle`.
Shared indexes and event files live in this clone's `catalog` and `events`.
When a workspace sandbox cannot write shared state, local registration and
local events are used. Give the wrapper access to its code, executable and state
paths using your normal workspace permission controls; do not bypass denied
permissions. No administrator requirement is imposed by the code itself.

Records and events may contain commands, paths and chat identifiers. They are
ignored by Git. Keep code and registration directories writable only by trusted
users: this is a lifecycle tool, not a security boundary against forged records.

This tool does not manage existing unregistered leftovers, WSL guest processes,
remote SSH processes, browser-owned work, service-manager launches or processes
created through WMI. Do not mark such work as one-shot. It does not restart Codex
or scan every chat. A separately configured heartbeat can read chat metadata and
log observations, but uncertain unregistered processes remain untouched.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite creates its own test processes and intentionally crashes its own
manager. It checks completed and failed roots, crash reclamation, retention of
running and unregistered processes, Chinese text and quoting, effective working
directories, preserved exit codes, standalone entry, shell discovery, custom
Codex homes and generated hook commands. Test artifacts stay in ignored local
directories. Run on Windows with PowerShell 7; other platforms skip the native
tests. No third-party Python packages are required.

To disable integration, remove only this project's hook handlers and associated
agent-rule section, then pause its heartbeat through Codex. Preserve unrelated
config changes and do not stop active tasks as part of disabling the integration.
