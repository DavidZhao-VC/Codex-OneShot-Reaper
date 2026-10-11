"""Print a host-specific TOML snippet; never edit config or hook trust."""
import json
from pathlib import Path
import sys


def main():
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    command = '& ' + quote(sys.executable) + ' ' + quote(Path(__file__).resolve().parent / 'manager.py') + ' '
    print('# Merge into your Codex config; review and enable the hooks in Codex.\n')
    for event, mode, matcher, timeout in (
        ('PreToolUse', 'pre', '^Bash$', 15),
        ('PostToolUse', 'maintenance', '^Bash$', 15),
        ('Stop', 'maintenance', None, 15),
        ('SessionEnd', 'maintenance', None, 3),
    ):
        print('[[hooks.' + event + ']]')
        if matcher:
            print('matcher = ' + json.dumps(matcher))
        print('[[hooks.' + event + '.hooks]]')
        print('type = "command"')
        print('command = ' + json.dumps(command + mode))
        print('timeout = ' + str(timeout) + '\n')


if __name__ == '__main__':
    main()
