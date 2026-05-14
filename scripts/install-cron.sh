#!/usr/bin/env bash
# Install the daily finance digest as a user cron entry.
#
# Rationale over systemd --user timers: systemd 219 on Amazon Linux 2
# has no working user instance (no D-Bus user session out of the box),
# and enabling it would require root to set `loginctl enable-linger`.
# User crontab works without root and survives logout naturally.
#
# Usage:
#   ./scripts/install-cron.sh          # install at 08:30 local every day
#   HORIZON_CRON="15 9 * * *" ./scripts/install-cron.sh
#   ./scripts/install-cron.sh --remove # uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RUN_SCRIPT="$PROJECT_DIR/scripts/daily-finance.sh"
LOG_FILE="$PROJECT_DIR/logs/cron.log"
TAG="# horizon-finance-daily"

SCHEDULE="${HORIZON_CRON:-30 8 * * *}"

mkdir -p "$PROJECT_DIR/logs"

if [[ "${1:-}" == "--remove" ]]; then
    echo "removing existing horizon-finance-daily cron entry..."
    ( crontab -l 2>/dev/null || true ) | grep -v "$TAG" | crontab -
    echo "done; current crontab:"
    crontab -l 2>/dev/null || echo "(empty)"
    exit 0
fi

# Build the cron line. We wrap with flock to serialize, and we cd first
# so that `uv run` resolves the project's venv correctly.
#
# PATH is important: cron's default PATH is minimal and misses ~/.local/bin
# (where uv lives on this box) and the mise shims. We inline enough to
# cover both cases; customize via HORIZON_PATH if your layout differs.
CRON_PATH="${HORIZON_PATH:-$HOME/.local/bin:$HOME/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin}"
CRON_LINE="$SCHEDULE cd $PROJECT_DIR && PATH=\"$CRON_PATH\" $RUN_SCRIPT >> $LOG_FILE 2>&1 $TAG"

# Replace any previous occurrence atomically.
NEW_CRONTAB="$( ( crontab -l 2>/dev/null || true ) | grep -v "$TAG" ; echo "$CRON_LINE" )"
echo "$NEW_CRONTAB" | crontab -

echo "installed:"
crontab -l | grep "$TAG"
echo ""
echo "tail the log with:    tail -f $LOG_FILE"
echo "remove the entry:     $0 --remove"
