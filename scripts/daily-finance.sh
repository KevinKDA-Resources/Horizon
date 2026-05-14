#!/usr/bin/env bash
# Personal finance + AI daily digest runner.
#
# Design goals, relative to the upstream scripts/daily-run.sh:
#   1. Stay on the `config/personal-finance` branch (never switch branches
#      or auto-pull, because the private config lives only here).
#   2. Load .env so HORIZON_AI_BASE_URL, OPENAI_API_KEY, ... are available
#      without the user having to export them in the invoking shell.
#   3. Serialize runs via flock() so overlapping cron / systemd timers
#      can't double-charge the LLM.
#   4. Never push to gh-pages. The private config lists equities we care
#      about - that list is institutional information, it must not leak
#      to a public Pages site even if the fork itself is public today.
#   5. Emit structured log lines that systemd-journald / `journalctl`
#      render well (ISO timestamp, level, message).
#
# Usage:
#   ./scripts/daily-finance.sh            # fetch last 24h
#   HORIZON_HOURS=48 ./scripts/daily-finance.sh
#
# Systemd (user unit; see scripts/horizon-finance.{service,timer}):
#   systemctl --user daemon-reload
#   systemctl --user enable --now horizon-finance.timer
#   journalctl --user -u horizon-finance -f

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOCK_FILE="$PROJECT_DIR/.horizon-daily.lock"
LOG_DIR="$PROJECT_DIR/logs"
HOURS="${HORIZON_HOURS:-24}"

mkdir -p "$LOG_DIR"

log() {
    local level="$1"; shift
    printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$level" "$*"
}

# Serialize: only one run at a time, non-blocking.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log WARN "another horizon run is already holding $LOCK_FILE, exiting"
    exit 0
fi

cd "$PROJECT_DIR"

# Refuse to run on any branch other than the private config branch, to
# stop a future `systemctl --user enable` from silently exfiltrating the
# wrong data when the developer left their shell checked out on main.
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "config/personal-finance" ]]; then
    log ERROR "wrong branch: current=$CURRENT_BRANCH, expected=config/personal-finance"
    log ERROR "switch branches first: git checkout config/personal-finance"
    exit 2
fi

# Load .env so the LLM proxy endpoint and key are available to the process.
# set -a exports every variable defined in the file; we turn it off right
# after so later unset vars don't leak.
if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a
    . ./.env
    set +a
    log INFO "loaded .env"
else
    log WARN ".env not found; relying on inherited environment"
fi

for VAR in OPENAI_API_KEY HORIZON_AI_BASE_URL; do
    if [[ -z "${!VAR:-}" ]]; then
        log ERROR "required env var $VAR is empty after loading .env"
        exit 3
    fi
done

# Pick up only the strictly-required binaries. uv manages the rest.
if ! command -v uv >/dev/null 2>&1; then
    log ERROR "uv not on PATH"
    exit 4
fi

log INFO "starting horizon --hours $HOURS on branch $CURRENT_BRANCH"
START_EPOCH=$(date +%s)

# Run Horizon. Its own output goes to stdout so systemd-journald captures
# it; we mirror to a rolling per-day file for easy human inspection.
TODAY="$(date -u +%Y-%m-%d)"
LOG_FILE="$LOG_DIR/horizon-$TODAY.log"

# tee so we can `journalctl -u horizon-finance` *and* tail a file.
uv run horizon --hours "$HOURS" 2>&1 | tee -a "$LOG_FILE"
RC=${PIPESTATUS[0]}

ELAPSED=$(( $(date +%s) - START_EPOCH ))

if [[ $RC -ne 0 ]]; then
    log ERROR "horizon exited with code $RC after ${ELAPSED}s"
    exit "$RC"
fi

log INFO "horizon completed in ${ELAPSED}s"

SUMMARY_ZH="$PROJECT_DIR/data/summaries/horizon-$TODAY-zh.md"
SUMMARY_EN="$PROJECT_DIR/data/summaries/horizon-$TODAY-en.md"
for f in "$SUMMARY_ZH" "$SUMMARY_EN"; do
    if [[ -f "$f" ]]; then
        log INFO "summary ready: $f ($(wc -c <"$f") bytes)"
    fi
done
