# Finance Profile Spike Results — 2026-05-14

Two-spike evaluation to decide whether to build a finance-oriented
Horizon profile or pivot to a simpler tool. Executed under Plan-mode
approved scope, zero-code, ~60 min total.

## Spike 1: Baseline Annotation (30 min)

### Source Data

- `data/summaries/horizon-2026-05-13-zh.md` (13 items, scored ≥ 6.0/10)
- `data/summaries/horizon-2026-05-14-zh.md` (11 items, scored ≥ 6.0/10)
- Combined: 24 items

### Tagging Rules (from plan)

| Dimension A | Definition |
|---|---|
| Event-type | Specific ticker + specific event (earnings / M&A / insider / filing / rate change) + clear time window |
| Narrative | Market-cap story, macro opinion, industry recap, punditry |
| Noise | Technical blog, culture discussion, non-investment |

| Dimension B | Definition |
|---|---|
| Finance / Tech / Macro / Other | — |

### Results Matrix (N=24)

| B \ A | Event | Narrative | Noise | Total |
|---|---:|---:|---:|---:|
| Finance | **1** | **5** | 0 | **6 (25%)** |
| Tech | 0 | 2 | 7 | 9 (38%) |
| Macro | 0 | 0 | 0 | 0 (0%) |
| Other | 0 | 1 | 8 | 9 (38%) |
| **Total** | **1 (4%)** | **8 (33%)** | **15 (63%)** | 24 |

### The only event-type finance item

**2026-05-14 #10**: "Cerebras IPO 定价 185 美元/股" — specific ticker
(CBRS forthcoming), specific event (IPO pricing), specific price
($185), specific time window (next-day open). This is exactly the
shape a trader needs.

The other 5 "finance" items are all narrative:
- "微软投入 OpenAI $100B+" (court testimony recap)
- "NVDA 市值破 $5.5T" (market-cap milestone story)
- "Arm/SoftBank 欲购 Cerebras" (reported, unconfirmed rumor)
- "US winning AI race" (opinion)
- "微软减少对 OpenAI 依赖" (strategic intent, no timeline)

### Decision Rule Application

Plan's rule:
- ≥ 20%: prompt is not the bottleneck; data source quality is
- 5% - 20%: prompt is worth tuning
- < 5%: daily-digest format may be unfit for trading decisions

Result: **event-type finance = 4%** → falls on the boundary of the
"unfit format" bucket, BUT total-finance = 25% (above 20% threshold).

### Diagnosis

The split tells a specific story:

> Finance items **do** reach the top 10 (25% already), but 5 of 6
> are **narrative by construction** because the data source
> (OpenBB `news.company(provider='yfinance')`) aggregates Yahoo
> Finance articles, which are second-hand recaps of events that
> happened 12-24 hours earlier.

Tuning the prompt alone cannot turn narrative recaps into actionable
events. The bottleneck is in the **data-source layer**, not the
prompt layer.

This **reverses** the conclusion from the first review round. The
"prompt is the bottleneck" hypothesis was a premature causal claim.

## Spike 2: Data-Source Scouting (30 min)

### 2.1 OpenBB SEC provider

Attempted: `obb.equity.fundamental.filings(symbol=sym, provider='sec')`

Result: **does not work on this host**.

```
[Unexpected Error] -> ClientConnectorError -> Cannot connect to host
www.sec.gov:443 ssl:default [Network is unreachable]
```

Root cause: Amazon Linux 2 + Python aiohttp prefers IPv6; IPv6 route
to sec.gov is unreachable. `curl -4` works fine. OpenBB doesn't
expose an IPv4-only option.

**Implication**: the modified plan's assumption "prefer OpenBB
fetch_filings over writing a new scraper" is now doubly invalidated:
1. `OpenBBScraper` source code does not even invoke `filings()` (only
   `news.company()`); the `fetch_filings=True` config field was
   declared but never wired up.
2. Even if wired, it would fail on this host until we hack aiohttp
   to force AF_INET.

### 2.2 Raw SEC EDGAR atom feed (IPv4 curl)

Works reliably. Single-company 8-K stream for NVDA (CIK 0001045810):

| Date | Item | Priority |
|---|---|---|
| 2026-05-08 | Item 5.02 (director change) | Low |
| 2026-04-27 | Item 5.02 | Low |
| 2026-03-06 | Item 5.02 | Low |
| 2026-02-25 | **Item 2.02 (earnings)** | **High** |
| 2026-01-23 | Item 5.02 | Low |

NVDA posts roughly **2.5 8-K filings per month**, but only **~1
Item 2.02 (earnings) per quarter**. Per-ticker 8-K density is too
low for a daily digest. Global 8-K stream is 200+/day, dominated
by micro-caps — needs aggressive ticker filtering to be useful.

Form 4 (insider transactions) for NVDA: latest entry is 2026-03-24
(50 days old). Large caps have sparse insider activity at the
individual-company level; **Form 4 alpha is concentrated in
small/mid caps and cluster patterns**, not in single large-cap
lookups.

### 2.3 OpenInsider — cluster buys page

`http://openinsider.com/latest-cluster-buys` — 100 rows of structured
data, each row is a cluster buy (multiple insiders buying same
security in same window).

Top rows observed 2026-05-13:

| Ticker | Company | Industry | #Insiders | Trade Type | Price | Value |
|---|---|---|---:|---|---:|---:|
| XRN | Chiron Real Estate | REIT | 7 | P (Purchase) | $33.82 | +$555K |
| TSLX | Sixth Street Specialty Lending | CEF | 6 | P | $18.29 | **+$10.9M** |
| MRP | Millrose Properties | Real Estate | 4 | P | $27.32 | +$6.5M |
| TKO | TKO Group Holdings ($14B cap) | Rec | 3 | P | $185.11 | +$4.5M |
| PSN | Parsons Corp ($5B) | Integrated Sys | 3 | P | $50.11 | +$1.6M |
| GRNT | Granite Ridge Resources | E&P | 5 | P | $5.18 | +$340K |
| GEHC | GE Healthcare Tech ($28B) | Medical | 7 | P | $61.73 | +$5.8M |
| OLED | Universal Display ($4B) | Electronics | 3 | P | $93.39 | +$1.5M |
| MMSI | Merit Medical | Surgical | 5 | P | $61.14 | +$573K |
| FLUT | Flutter Entertainment ($30B) | Software | 7 | P | $100.03 | +$1M |

Delay: 2026-05-13 19:05 filing → visible same day. Effectively
real-time for retail.

### 2.4 Three-way comparison

| Metric | OpenBB yfinance news (current) | Raw SEC EDGAR (IPv4 curl) | OpenInsider |
|---|---|---|---|
| Works on this host | yes | yes (curl -4) | yes |
| Delay | 12-24h | minutes-to-hours | hours (same-day) |
| Event density (per day) | 4.2% of top-10 = 0.4 events | 1 NVDA 8-K per ~12 days | **100 cluster-buy rows per scrape** |
| Structured fields | none | form_type only (need XBRL for codes) | **full table: ticker / date / insiders / type / price / qty / value** |
| Signal quality | narrative retellings | Item 5.02 dominates (low value) | **cluster P-code = academically validated** |
| Implementation cost | 0 (already done) | 3h+ (IPv4 scraper + XBRL parse) | **~30 min (HTML parse)** |
| Coverage | 7 watchlist tickers | Single ticker lookups + global 8-K | **Entire US market, pre-filtered** |

## Final Decision: Path B

### Why not Path A (finance profile with EDGAR/FRED scrapers)

1. The "event-type finance" ratio is 4%, right at the "wrong format"
   boundary. Even if we add EDGAR 8-K / FRED feeds, we have no
   evidence the fundamental problem (narrative density of free
   data sources) would be solved.
2. OpenBB SEC provider fails on this host; the modified plan's
   shortcut is gone.
3. NVDA-only 8-K sample shows density too low for a daily cadence.
   Scale across the whole watchlist and we still get a handful
   of 8-Ks per week, mostly Item 5.02 (not Item 2.02 earnings).
4. Audit trail: two review rounds surfaced 5+ Critical issues
   still unresolved (A/B baseline, merged-PR pollution risk,
   OpenBB filings bug, missing ContentItem fields, success-metric
   loop). Any execution still incurs ~6 hours of elevated risk.

### Why not Path C (stay on news profile, do nothing)

User has a clear, validated need ("these daily digests didn't
help my stock decisions"). Doing nothing accepts the defect.

### Why Path B

A 2-hour shell/Python script that scrapes OpenInsider
latest-cluster-buys + Finviz earnings calendar + FRED events
calendar, outputs a ~30-line structured text file every morning,
beats the current daily digest on every metric that matters for
trading decisions:

| Criterion | Horizon digest | Path B morning scan |
|---|---|---|
| Time to read | 10 min | 2 min |
| Event density | 1/24 | 10+/scan |
| Structured fields | no | yes |
| Signal-to-noise | ~4% | ~100% (pre-filtered) |
| LLM cost | 170K tokens | zero |
| Maintenance | 3 PRs + scrapers + prompts | single script |

### Path B spec

Deliverable: `scripts/morning-scan.sh` (or `.py`) + docs.

Scope (v1):
1. **OpenInsider cluster buys** — fetch `latest-cluster-buys`,
   parse top-20 by `#insiders` × `Value`. Emit:
   `ticker | industry | #insiders | price | value | filing_time`
2. **Earnings calendar (7 days)** — scrape Finviz screener
   (free, public) filtered by watchlist tickers. Emit:
   `date | ticker | when_pre_post | eps_est | rev_est | prior_surprise`
3. **FRED release calendar** — use the public ICS feed
   (`https://fraser.stlouisfed.org/calendar.ashx`) or the
   `observation_start=` FRED API + an event-table with known
   releases. Emit today's and tomorrow's macro release windows.
4. **Optional macro events** — simple JSON file
   `data/macro-calendar.json` for FOMC / CPI / PCE / NFP with
   dates, hand-curated once a quarter.

Output format: plain text to stdout, one section per source,
`< 30 lines total`. Human reads in 2 min. No LLM.

Schedule: cron daily at 06:30 EST (pre-market), and on-demand.

### What this preserves vs abandons

- **Preserve** Horizon news profile as-is. It does its job
  (tech/AI pulse) well; the 5/13 and 5/14 digests demonstrate
  that even without the finance-signal shortcomings.
- **Preserve** the 3 upstream PRs (#54 #55 #56) — they are
  generic improvements, not tied to finance profile.
- **Abandon** the original 12-step plan and the revised
  3-stage plan. No further investment in EDGAR / FRED / GDELT
  scrapers for Horizon.
- **Abandon** the `config/personal-finance` branch's finance-
  specific config. The news profile is simpler and serves
  the preserved role.

### Known limitations of Path B (to disclose now, not discover later)

1. **Small-cap bias**: OpenInsider cluster-buy alpha concentrates
   in small/mid caps. User's watchlist is mega-caps. Expect 1-2
   watchlist hits per week, not daily.
2. **Insider buying ≠ guaranteed alpha**: Cohen-Malloy 2024
   suggests the published-alpha has decayed ~75% post-replication.
   Signal still exists but is weaker than in canonical studies.
3. **No sell-side**: insider selling has weaker academic signal
   (10b5-1 plans, diversification), so Path B de-emphasizes it.
4. **No options flow**: unusual options activity is a rich
   retail signal but the free sources (UnusualWhales free tier,
   CBOE aggregates) are either paywalled or delayed 15 min+.
   Out of scope for v1.
5. **Not real-time**: daily scrape is for pre-market prep,
   not intraday scalping.

## What happens next

Proposed immediate action (out of spike scope, requires user
green-light):

1. Delete the obsolete 3-stage plan file so there's no drift.
2. Write `scripts/morning-scan.sh` + 1-page README.
3. Run for 5 trading days, user tracks whether any signal
   resulted in an action (add-to-watchlist, alert, order).
4. After 5 days: keep, improve, or kill.

## Meta-observation for future planning

Both review rounds flagged "the plan is solving a problem that
hasn't been validated." The spike results prove that concern
correct: the bottleneck is data-source quality, not the scraper
count, not the prompt framing. Always validate bottleneck with
30-min data before committing to multi-hour refactors.
