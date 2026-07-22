"""Local, X11-only: translate spoken phrases into shell commands when the
focused window is a terminal, instead of typing the dictated prose.

Opt-in via the `terminal_commands` config flag. Detection and cwd
resolution are both best-effort and fail silently, matching the pattern
in feedback.py for optional external CLI tools. This never *executes*
anything -- translate() only returns text for app.py to type, exactly
like normal dictation; the user still reviews and presses Enter.
"""

import os
import re
import shutil
import subprocess

# ponytail: fixed list, extend if a terminal emulator is missing.
TERMINAL_CLASSES = {
    "gnome-terminal-server", "konsole", "xterm", "alacritty", "kitty",
    "xfce4-terminal", "terminator", "foot", "tilix", "urxvt",
}


def _run(cmd) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def is_terminal_focused() -> bool:
    if not shutil.which("xdotool"):
        return False
    cls = _run(["xdotool", "getactivewindow", "getwindowclassname"])
    return bool(cls) and cls.lower() in TERMINAL_CLASSES


def _foreground_pid(pid: int) -> int:
    """Walk /proc for the deepest live descendant of pid (stdlib only,
    no psutil). ponytail: single deepest-child heuristic -- doesn't
    disambiguate multiple tabs/panes, good enough for "the terminal
    I'm looking at right now"."""
    by_ppid: dict[int, list[int]] = {}
    try:
        pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return pid
    for p in pids:
        try:
            with open(f"/proc/{p}/stat") as f:
                stat = f.read()
            # comm field can contain spaces/parens; ppid follows the last ')'.
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
            by_ppid.setdefault(ppid, []).append(p)
        except (OSError, IndexError, ValueError):
            continue
    cur = pid
    while by_ppid.get(cur):
        cur = by_ppid[cur][-1]
    return cur


def terminal_cwd() -> str | None:
    win_pid = _run(["xdotool", "getactivewindow", "getwindowpid"])
    if not win_pid or not win_pid.isdigit():
        return None
    shell_pid = _foreground_pid(int(win_pid))
    try:
        return os.readlink(f"/proc/{shell_pid}/cwd")
    except OSError:
        return None


def _git(cwd, *args) -> str | None:
    return _run(["git", "-C", cwd, *args])


def _is_git_repo(cwd) -> bool:
    return _git(cwd, "rev-parse", "--is-inside-work-tree") == "true"


# ponytail: small fixed git grammar; extend via a user rules file if
# requested later. Dynamic values (branch, remote) are resolved live
# from git, never spoken -- Whisper never has to transcribe a branch name.
_RULES = [
    (re.compile(r"^push(?: to)?(?: the)? remote(?: (\w+))?$", re.I),
     lambda m, cwd: f"git push {m.group(1) or 'origin'} "
                    f"{_git(cwd, 'branch', '--show-current')}"),
    (re.compile(r"^pull(?: from)?(?: the)? remote(?: (\w+))?$", re.I),
     lambda m, cwd: f"git pull {m.group(1) or 'origin'} "
                    f"{_git(cwd, 'branch', '--show-current')}"),
    (re.compile(r"^(?:git )?status$", re.I),
     lambda m, cwd: "git status"),
    (re.compile(r"^check ?out (.+)$", re.I),
     lambda m, cwd: f"git checkout {m.group(1).strip().replace(' ', '-')}"),
    (re.compile(r"^(?:stage|add) all$", re.I),
     lambda m, cwd: "git add ."),
    (re.compile(r"^(?:show )?(?:the )?log$", re.I),
     lambda m, cwd: "git log --oneline -10"),
]


def resolve(text: str, cwd: str) -> str | None:
    stripped = text.strip().rstrip(".")
    for pattern, build in _RULES:
        m = pattern.match(stripped)
        if m:
            return build(m, cwd)
    return None


def translate(text: str) -> str | None:
    """None if not applicable; else the shell command string to type."""
    if not is_terminal_focused():
        return None
    cwd = terminal_cwd()
    if not cwd or not _is_git_repo(cwd):
        return None
    return resolve(text, cwd)


if __name__ == "__main__":
    # Grammar-only checks -- no live xdotool/git needed, runs anywhere.
    m = _RULES[0][0].match("push to remote")
    assert m and m.group(1) is None
    m = _RULES[0][0].match("push to remote origin")
    assert m and m.group(1) == "origin"
    m = _RULES[3][0].match("checkout main")
    assert m and m.group(1) == "main"
    assert _RULES[2][0].match("status")
    assert _RULES[4][0].match("add all")
    assert _RULES[5][0].match("show the log")
    assert resolve("not a command", "/tmp") is None
    print("terminal_commands self-check OK")
