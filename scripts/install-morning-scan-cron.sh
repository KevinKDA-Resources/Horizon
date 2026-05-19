#!/usr/bin/env bash
# Install the morning-scan daily cron entry.
#
# Schedules scripts/morning-scan.py to run every day at 20:30 Asia/Shanghai
# (= ~13:30 UTC = ~08:30 ET pre-market, see README for time-zone notes).
# Output is streamed to logs/morning-scan-YYYY-MM-DD.log so you have a
# timestamped daily artifact you can grep when something interesting
# pops in the digest the next morning.
#
# Why a separate installer instead of reusing scripts/install-cron.sh:
#   - daily-finance.sh runs the *Horizon* pipeline (LLM, big tokens).
#   - morning-scan.py runs the zero-LLM pre-market scan.
#   The two have different schedules, different log paths, and different
#   risk profiles, so they get separate crontab entries.
#
# Usage:
#   ./scripts/install-morning-scan-cron.sh          # default: 30 20 * * *
#   HORIZON_MORNING_CRON="15 9 * * *" ./scripts/install-morning-scan-cron.sh
#   ./scripts/install-morning-scan-cron.sh --remove # uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Branch guard: this installer is private to config/personal-finance and
# uses a watchlist that is institutional information. Refuse to install
# on any other branch so a stray run from main does not silently start
# leaking output through the user's mail or persistent logs.
CURRENT_BRANCH="$(cd "$PROJECT_DIR" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
if [[ "$CURRENT_BRANCH" != "config/personal-finance" ]]; then
    echo "refuse to install on branch '$CURRENT_BRANCH'" >&2
    echo "switch first: git checkout config/personal-finance" >&2
    exit 2
fi

RUN_PY="$PROJECT_DIR/.venv/bin/python"
SCAN_SCRIPT="$PROJECT_DIR/scripts/morning-scan.py"
LOG_DIR="$PROJECT_DIR/logs"
TAG="# horizon-morning-scan-daily"

if [[ ! -x "$RUN_PY" ]]; then
    echo "venv python not found at $RUN_PY" >&2
    echo "did you run 'uv sync' ?" >&2
    exit 3
fi
if [[ ! -f "$SCAN_SCRIPT" ]]; then
    echo "$SCAN_SCRIPT not found" >&2
    exit 4
fi

mkdir -p "$LOG_DIR"

# --remove path
if [[ "${1:-}" == "--remove" ]]; then
    echo "removing existing horizon-morning-scan-daily cron entry..."
    ( crontab -l 2>/dev/null || true ) | grep -v "$TAG" | crontab -
    echo "done; current crontab:"
    crontab -l 2>/dev/null || echo "(empty)"
    exit 0
fi

# Default schedule: 20:30 local (Asia/Shanghai), every day.
# 20:30 CST = 12:30 UTC = 08:30 ET in summer / 07:30 ET in winter, which
# is roughly 1 hour before US cash open and right after Form 4 evening
# filings clear (4pm ET cutoff +/- 30min).
SCHEDULE="${HORIZON_MORNING_CRON:-30 20 * * *}"

# cron's default PATH is `/usr/bin:/bin`, missing uv shims. We hard-code
# the venv python (RUN_PY) so PATH only needs to cover system tools the
# scan calls indirectly (mostly nothing, but include for safety).
CRON_PATH="${HORIZON_PATH:-/usr/local/bin:/usr/bin:/bin}"

# In cron, '%' has special meaning unless escaped. We need %Y-%m-%d in the
# log filename so we escape with backslash.
DATE_TOKEN='$(date +\%Y-\%m-\%d)'

# Build the line:
#   1. cd into the project so relative paths inside the python script work
#   2. set a sane PATH
#   3. invoke the venv python directly with the absolute scan script path
#   4. redirect both stdout and stderr to a per-day log
#   5. prune logs older than 30 days
LOG_PATH="$LOG_DIR/morning-scan-$DATE_TOKEN.log"
PRUNE="find $LOG_DIR -name 'morning-scan-*.log' -mtime +30 -delete"
CRON_LINE="$SCHEDULE cd $PROJECT_DIR && PATH=\"$CRON_PATH\" $RUN_PY $SCAN_SCRIPT > $LOG_PATH 2>&1 ; $PRUNE $TAG"

# Replace any previous occurrence atomically.
NEW_CRONTAB="$( ( crontab -l 2>/dev/null || true ) | grep -v "$TAG" ; echo "$CRON_LINE" )"
echo "$NEW_CRONTAB" | crontab -

echo "installed:"
crontab -l | grep "$TAG"
echo ""
echo "schedule:        $SCHEDULE  (Asia/Shanghai by default)"
echo "log directory:   $LOG_DIR/"
echo "next-day log:    $LOG_DIR/morning-scan-\$(date +%Y-%m-%d).log"
echo ""
echo "tail tonight:    tail -f $LOG_DIR/morning-scan-\$(date +%Y-%m-%d).log"
echo "remove the cron: $0 --remove"
echo ""
echo "smoke-test the cron command body now (recommended):"
echo "    cd $PROJECT_DIR && PATH=\"$CRON_PATH\" $RUN_PY $SCAN_SCRIPT | head -5"
