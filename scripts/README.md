# Daily scheduling for the personal finance digest

Three scheduling options, from easiest to most robust. **Pick one**.

## What runs

All three options eventually invoke `scripts/daily-finance.sh`, which:

1. Refuses to run unless you are on the `config/personal-finance` branch
   (safety: prevents leaking tickers to a run started against the wrong
   config).
2. Loads `.env` so `HORIZON_AI_BASE_URL` / `OPENAI_API_KEY` / ... are
   available to `uv run horizon`.
3. `flock(.horizon-daily.lock)` to serialize; double-invocations exit
   cleanly instead of burning tokens twice.
4. Streams Horizon's stdout to `logs/horizon-YYYY-MM-DD.log` for easy
   tailing, and to the invoking supervisor's log for alerts.
5. Never pushes to `gh-pages` or any remote (the watchlist is private).

## Option 1: cron (recommended on Amazon Linux 2)

```bash
cd /path/to/Horizon

# Daily at 08:30 local
scripts/install-cron.sh

# Custom schedule (cron syntax)
HORIZON_CRON="15 9 * * *" scripts/install-cron.sh

# Verify
crontab -l | grep horizon-finance
tail -f logs/cron.log

# Undo
scripts/install-cron.sh --remove
```

## Option 2: manual / ad-hoc

```bash
cd /path/to/Horizon
scripts/daily-finance.sh             # last 24h
HORIZON_HOURS=48 scripts/daily-finance.sh
```

## Option 3: systemd --user (for distros with systemd >= 230)

> Amazon Linux 2 ships systemd 219 and has no user bus enabled by
> default, so cron is the practical choice there. The unit files are
> kept for other hosts (Ubuntu 20.04+, Fedora, recent Debian, ...).

```bash
# 1. Install unit files into the user systemd location
mkdir -p ~/.config/systemd/user
cp scripts/systemd/horizon-finance.service ~/.config/systemd/user/
cp scripts/systemd/horizon-finance.timer   ~/.config/systemd/user/

# 2. Edit WorkingDirectory / ExecStart in .service if your clone is not
#    at ~/code/Horizon. The shipped units assume %h/code/Horizon.

# 3. Reload and enable
systemctl --user daemon-reload
systemctl --user enable --now horizon-finance.timer

# 4. Make the timer survive logout
loginctl enable-linger "$USER"   # requires sudo on some distros

# 5. Observe
systemctl --user list-timers | grep horizon-finance
journalctl --user -u horizon-finance -f
```

## Troubleshooting

**"wrong branch: ... expected=config/personal-finance"**
`daily-finance.sh` refuses to run on any other branch. `git checkout
config/personal-finance` before scheduling.

**"required env var HORIZON_AI_BASE_URL is empty"**
`.env` is missing or incomplete. Copy `.env.personal-finance.example`
to `.env` and fill in real values.

**"another horizon run is already holding .horizon-daily.lock"**
Previous run is still in progress. Normal when you stack a manual run
on top of a cron run. Wait or kill the prior `uv run horizon` process.

**OpenAI 413 / timeout**
Token usage per run is ~180k for the default watchlists. If you
consistently time out, reduce `fetch_top_stories` / `fetch_limit` in
`data/config.json`, or drop the `broad-index` watchlist.

**I want to disable a run day**
Edit the cron entry or `OnCalendar=` line to skip weekdays:
`OnCalendar=Mon..Fri 08:30` in the timer.
