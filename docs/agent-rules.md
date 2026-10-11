# Suggested agent rules

Adapt the following section into your own global or workspace `AGENTS.md` after
reviewing the repository and replacing `<REPO>` with your clone location.

## Process lifecycle

- For finite local Windows PowerShell commands, prefer the direct entry:
  `& '<REPO>\Invoke-OneShot.ps1' -ScriptBlock { <finite command> }`, followed by
  `exit $LASTEXITCODE` in the calling command.
- A new local chat with verified hook dispatch may instead opt in using the first
  line `# codex-lifecycle: oneshot`. Existing loaded chats must use the direct entry.
- Research, training, data imports, scientific validation, SSH, WSL, rendering,
  downloads, interactive commands and resident MCP/browser/execution services use
  `# codex-lifecycle: persistent` or their original execution path.
- Never label expected background work as one-shot. Do not use WMI, remote launch
  or service launch mechanisms inside a one-shot task.
- A running tool session ID is not completion. Track the command to actual exit.
- Maintenance events and periodic checks only process registered one-shot jobs.
  Living managers, changed identities, denied access and ambiguous ownership are
  retained. Reply completion or chat idle is never a reason to stop background work.
- No stopping by process name, fixed historical PID or arbitrary heuristics. Do
  not restart Codex to clear processes. Unregistered processes receive read-only
  review and logs only. Keep live research, SSH and tool services untouched.
