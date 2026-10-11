# Optional Codex heartbeat prompt

Replace `<PYTHON>` and `<REPO>` with absolute paths before asking Codex to create
a 30-minute heartbeat. Use the app's automation controls; do not hand-edit an
automation file. Scheduling requires a Codex environment that supports it.

> Every 30 minutes, inspect registered local Windows one-shot task groups. First
> execute `<PYTHON> <REPO>\manager.py sweep` on the persistent execution path.
> Only the reviewed manager may reclaim its registered dedicated jobs. A living
> owner, changed PID identity, denied access or uncertain ownership must be skipped.
> Review current local chat metadata and Windows process identities read-only if
> available. Never infer completion from chat idle, CPU, memory, age, names or old
> PIDs. Preserve research, training, SSH, background tasks and in-use MCP, browser
> and execution services. Do not stop unregistered processes, inspect WSL guest or
> remote processes, restart Codex, install dependencies or delete project/chat files.
> Save decisions and observations in a local audit directory outside the public
> repository. Stay quiet for no change, normal success and uncertain ownership.
> Notify only for errors affecting active tasks, repeated cleanup failures or
> permissions requiring user action. Follow the current approval controls.

The native manager logs its own decisions in `events`. Its JSON `results` array
contains per-registration decisions, including `skip_error`; inspect these rather
than relying only on the command's exit code.
