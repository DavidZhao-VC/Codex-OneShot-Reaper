# Codex-OneShot-Reaper：一次性进程回收

Codex-OneShot-Reaper 用于回收有限 Windows PowerShell 命令留下的子进程。
它会为每个明确选择的一次性命令创建独立的 Windows Job Object；根命令结束或
管理器崩溃后，Windows 会回收该组残留子进程。现有进程不会加入回收组。

## 核心边界

- 管理器还在运行，就保留登记任务；聊天 idle、回复结束和等待审批都不能证明任务已结束。
- 研究、训练、SSH、WSL、下载、渲染、交互命令和常驻工具服务走原有执行方式。
- 维护只检查登记的一次性任务组。进程身份变化、权限不足、归属不明时跳过。
- 不按名称、旧 PID、进程数量、CPU、内存或运行时长猜测清理对象。

命令识别刻意保守，可能拒绝只是提到受保护关键词的有限命令。
这时使用原有执行方式，不把后台或受保护任务伪装成一次性命令。

## 使用

需要 Windows、Python 3.11+、PowerShell 7，不需要第三方 Python 包。
把示例路径替换成你自己的仓库路径：

```powershell
& 'C:\tools\codex-oneshot-lifecycle\Invoke-OneShot.ps1' -ScriptBlock {
    Write-Output '有限的一次性命令'
}
exit $LASTEXITCODE
```

可用 `-Python` 或 `CODEX_LIFECYCLE_PYTHON` 指定解释器；
可用 `CODEX_LIFECYCLE_PWSH` 指定 PowerShell 7 的绝对路径。
已经打开的旧对话优先使用直接入口，不能仅凭注释假定 Hooks 已加载。

运行 `python .\print_hooks.py > hooks.local.toml` 可以生成本机 Hook 配置片段。
它只输出配置，不修改你的配置文件，也不自动写入信任记录。
备份并合并到 Codex 的 `config.toml` 后，通过 Codex 支持的控制方式审核、启用 Hooks，
在新本地对话中验证真实触发。详情见 [英文说明](README.md)。

已验证接入 Hooks 的新对话可用第一行标记：

```powershell
# codex-lifecycle: oneshot
Write-Output '有限命令'
```

长期运行任务使用 `# codex-lifecycle: persistent` 或原有方式。
PostToolUse、Stop、SessionEnd 只维护登记组，不因事件发生而停止仍在运行的任务。

可另行配置每 30 分钟的 Codex 心跳，使用 [定时检查提示词](docs/heartbeat.md)。
检查自身使用 persistent，先执行 `python .\manager.py sweep`。
未登记的进程只读审查、保留；没有变化或正常成功时保持安静。

## 测试与限制

运行 `python -m unittest discover -s tests -v`。测试仅创建并结束自己的测试进程。
它覆盖正常退出、失败退出、崩溃回收、保留活动任务、保留未登记进程、中文与引号、
工作目录、退出码、直接入口、环境变量路径及 Hook 配置生成。

仓库不上传本机配置、聊天记录、进程快照、登记日志或安装备份。
运行生成的记录可能含命令、路径和聊天标识，已加入 `.gitignore`。
代码和登记目录应只允许可信用户写入；登记文件不是防恶意篡改的安全边界。
本工具不回收 WSL 内部、远程 SSH、WMI、服务管理器或现有未登记的进程。
克隆仓库不会自动安装 Hooks 或创建定时任务。
