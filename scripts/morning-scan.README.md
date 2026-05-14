# morning-scan

A 2-minute pre-market scan for an active US-equity trader. Replaces the
original "Horizon finance profile" plan with a **single standalone
script** that pulls three high-signal feeds, prints them as plain text,
and exits. No LLM spend, no blocking infra, no background scheduler.

This script is **private** to the `config/personal-finance` branch. It
deliberately lives outside `src/` so it never ships upstream.

---

## Quick start

```bash
cd /opt/workspace/personal/stock/Horizon
uv run scripts/morning-scan.py
```

That's it. Output is ~45 lines of plain text: three sections, one
header, readable before the market opens.

---

## What it shows

### Section 1 — OpenInsider cluster buys (`http://openinsider.com/latest-cluster-buys`)

Cluster buys = multiple *different* insiders at the same company buying
open-market (P-code, not option exercise) within a short window. This
is the academically strongest insider-trading signal: Cohen, Malloy &
Pomorski (*Journal of Finance*, 2012, "Decoding Inside Information")
show that clustered, open-market purchases by officers and directors
predict abnormal returns over the following 6 months, while routine
trades do not. OpenInsider aggregates SEC Form 4 filings and tags these
cluster buys in one feed.

Default filter: `min-insiders=3`, `min-value=$500,000`, purchases only,
max 20 rows. Rows matching your watchlist get a `*` marker.

### Section 2 — Watchlist earnings (yfinance)

For every ticker in your watchlist, yfinance's `Ticker.calendar`
returns the next scheduled report date plus analyst EPS/revenue
consensus. We filter to earnings within the next `--earnings-days`
(default 7) so you don't accidentally hold into a print.

ETFs in the watchlist (SPY/QQQ/DIA/IWM) return 404 from Yahoo because
they have no fundamentals. yfinance prints that to stdout by default,
which clobbers a plain-text report, so the script suppresses it.

### Section 3 — Macro calendar (Forex Factory weekly JSON)

`https://nfs.faireconomy.media/ff_calendar_thisweek.json` is a public
feed Forex Factory publishes for their own site. It includes the US
scheduled releases (FOMC, CPI, NFP, retail sales, claims, PMI, ...)
with impact ratings and consensus forecasts. Script filters to the
next 48 hours, High+Medium impact, USD country by default.

---

## CLI flags

| Flag | Default | Meaning |
| --- | --- | --- |
| `--watchlist SYM [SYM ...]` | 17 mega-cap tech + indexes | Tickers for earnings section and `*` marker |
| `--min-insiders N` | `3` | Minimum distinct insiders for a cluster-buy row |
| `--min-value USD` | `500000` | Minimum aggregate purchase value |
| `--insider-limit N` | `20` | Max cluster-buy rows shown after filtering |
| `--earnings-days N` | `7` | Forward window for earnings section |
| `--impacts LEVEL [...]` | `High Medium` | Forex Factory impact levels to include |
| `--countries CODE [...]` | `USD` | Forex Factory country codes (USD, EUR, CNY, ...) |
| `--no-insider` | off | Skip OpenInsider section |
| `--no-earnings` | off | Skip yfinance earnings section |
| `--no-macro` | off | Skip Forex Factory macro section |
| `--timeout SEC` | `20.0` | Per-request HTTP timeout |

Examples:

```bash
# Only earnings for a custom watchlist
uv run scripts/morning-scan.py --no-insider --no-macro \
    --watchlist AAPL MSFT NVDA TSLA AMD

# Stricter cluster-buy conviction
uv run scripts/morning-scan.py --min-insiders 5 --min-value 2000000

# Add Europe / China macro releases
uv run scripts/morning-scan.py --countries USD EUR CNY
```

---

## Changing the watchlist

Either pass `--watchlist` at the command line, or edit
`DEFAULT_WATCHLIST` at the top of `scripts/morning-scan.py`. Uppercase
tickers only; the script upper-cases them anyway before comparison.

---

## Known limitations

1. **Small-cap skew.** OpenInsider cluster buys are dominated by
   small-caps and REITs; mega-cap insider trades rarely cluster.
   Treat Section 1 as a deep-value / regional-bank / biotech scout,
   not a mega-cap signal.
2. **Academic alpha decay.** The Cohen-Malloy result is 12+ years old
   and widely published. Expected excess return has compressed. Use
   this as a starting point for deeper due diligence, not a standalone
   entry.
3. **No options flow, no short interest, no dark-pool prints.** Those
   require paid feeds.
4. **Not real-time.** OpenInsider updates throughout the day as Form 4
   filings post. Forex Factory JSON updates on their own cadence. If
   you run at 6 AM ET you will see yesterday's filings and today's
   pre-open releases — which is exactly what this tool is for.
5. **Earnings date volatility.** yfinance occasionally lags the
   officially-announced report date by a day. Cross-check on the
   company's IR page before sizing into a print.

---

## Troubleshooting

### "no IPv4 address for openinsider.com" / connect timeouts

AL2 hosts frequently have broken IPv6 egress. The script already
forces `AF_INET` via a custom `IPv4OnlyTransport`. If you still see
this, your DNS resolver isn't returning A records — check
`/etc/resolv.conf` or try from a different network.

### OpenInsider returns 0 rows

The parser looks for the `<table>` with > 50 `<tr>` elements (the data
table). If OpenInsider changes its markup the parser silently returns
`[]`. Inspect `curl -A 'Mozilla/5.0' http://openinsider.com/latest-cluster-buys`
and adjust `fetch_cluster_buys` in `scripts/morning-scan.py`. Don't
switch to a paid provider — the whole point of this script is zero
recurring cost.

### yfinance returns `?` for every estimate

Yahoo occasionally rate-limits anonymous clients. Wait a few minutes
and re-run, or narrow the watchlist. yfinance also stops returning
consensus for some tickers days before their report — that's upstream,
not a bug here.

### Forex Factory returns 403

The `nfs.faireconomy.media` host blocks some user agents. The script
sends a browser-like UA; if it breaks in future, try fetching with
`curl -A 'Mozilla/5.0 ...'` to confirm, then adjust `USER_AGENT`.

---

## Relationship to Horizon's news profile

`morning-scan` is **complementary**, not a replacement. The `news`
profile (`src/profiles/news.ts` etc.) produces an LLM-summarised macro
/ geopolitics brief that runs on a different clock and costs money per
run. `morning-scan`:

- runs in < 3 seconds,
- costs nothing,
- answers "what specifically should I look at when the market opens",
- lives on a private branch so it doesn't interfere with upstream
  Horizon's generic mandate.

Run both. News brief before coffee, `morning-scan` after.
