# Personal Finance Configuration

This branch carries the private Horizon configuration for a personal
**finance + AI + tech** daily digest. It is **never pushed to upstream
`Thysrael/Horizon`** and lives only on the fork.

## What's different from `main`

- `data/config.json` — opus-4.7 via the AWS API Gateway proxy, ZH+EN
  summaries, ai_score_threshold=6.0.
- `data/config.json` sources — SEC 8-K, Federal Reserve, BLS, Seeking
  Alpha, OpenAI blog, Simon Willison (AI), OpenBB watchlists for
  megacaps / AI-semis / broad-index. Reddit/Telegram/Twitter disabled.
- `.env.personal-finance.example` — template for the `.env` you need
  locally (the real `.env` stays `.gitignore`'d).

## Day-to-day usage

```bash
# One-time: point this branch at upstream main whenever you want fixes
git checkout config/personal-finance
git fetch origin
git merge origin/main          # or rebase, up to you

# Regenerate today's digest
uv run horizon                 # last 24h
uv run horizon --hours 48      # last 48h
```

Output lands in `data/summaries/horizon-YYYY-MM-DD-{zh,en}.md` and is
copied into `docs/_posts/` for the GitHub Pages site.

## Switching machines

1. Clone this fork and check out `config/personal-finance`
2. `cp .env.personal-finance.example .env` and fill in real keys
3. `uv sync`
4. Optional (for the OpenBB source):
   `uv pip install --only-binary=:all: openbb openbb-benzinga`

## What to change (and what NOT to change) on this branch

- ✅ edit watchlist tickers, RSS URLs, AI model/concurrency, thresholds,
  Feishu/webhook body templates
- ✅ add personal cron/systemd units under `scripts/` if you want
- ❌ do **not** modify `src/` here — keep generic code changes on `main`
  so they can be PR'd upstream
- ❌ do **not** commit `.env` — it carries live API keys
