param(
    [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
    [string]$SessionId = ('direct-' + [guid]::NewGuid().ToString('N')),
    [string]$Python = $(if ($env:CODEX_LIFECYCLE_PYTHON) { $env:CODEX_LIFECYCLE_PYTHON } else { 'python' })
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$request = @{
    session_id = $SessionId
    cwd = (Get-Location).Path
    hook_event_name = 'PreToolUse'
    tool_name = 'Bash'
    tool_use_id = [guid]::NewGuid().ToString('N')
    tool_input = @{ command = "# codex-lifecycle: oneshot`n" + $ScriptBlock.ToString() }
} | ConvertTo-Json -Depth 5 -Compress
$request | & $Python (Join-Path $PSScriptRoot 'manager.py') execute
exit $LASTEXITCODE
