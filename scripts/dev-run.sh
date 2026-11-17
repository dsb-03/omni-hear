#!/bin/bash
# Runs omnihear from this checkout (set up by ./scripts/dev-setup.sh) with
# terminal logs on. If the installed omnihear's systemd user service is
# running, it is stopped first (both would grab the hotkey and port 4738)
# and started again when this exits (Ctrl+C).
#
# Usage: ./scripts/dev-run.sh [--isolated] [omnihear options...]
#   --isolated   use a separate config + history (~/.config/omnihear-dev,
#                ~/.local/share/omnihear-dev) instead of the installed one's
#   anything else is passed to omnihear, e.g. --asr-backend indic, --doctor
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python3"
[ -x "$PY" ] || { echo "no .venv — run ./scripts/dev-setup.sh first" >&2; exit 1; }

ARGS=()
for arg in "$@"; do
    if [ "$arg" = --isolated ]; then
        export XDG_CONFIG_HOME="$HOME/.config/omnihear-dev"
        export XDG_DATA_HOME="$HOME/.local/share/omnihear-dev"
        mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME"
    else
        ARGS+=("$arg")
    fi
done

RESTART=0
if systemctl --user is-active --quiet omnihear 2>/dev/null; then
    echo "==> Stopping the installed omnihear (restarted when you quit)"
    systemctl --user stop omnihear
    RESTART=1
fi
restore() {
    if [ "$RESTART" = 1 ]; then
        echo "==> Starting the installed omnihear again"
        systemctl --user start omnihear
    fi
}
trap restore EXIT

cd "$REPO_ROOT/src"
echo "==> omnihear from $(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo checkout) — Ctrl+C to stop"
set +e
"$PY" -m omnihear --verbose "${ARGS[@]}"
