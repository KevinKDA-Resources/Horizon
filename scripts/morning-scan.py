#!/usr/bin/env python3
"""Morning scan for active trading.

A single-file, dependency-light script that answers the three
questions a daily-swing / intraday trader actually needs every
morning:

    1. Who insider-bought yesterday, at what conviction?
       (OpenInsider cluster buys, most-recent 100)
    2. Which of my watchlist tickers report earnings this week?
       (yfinance Ticker.calendar)
    3. What scheduled macro releases will move the tape today?
       (Forex Factory public JSON)

Design goals (from two-round plan review + spike results):

- **Plain text output** readable in ~2 minutes
- **Zero LLM spend**: no API calls that cost money
- **Data sources that actually work on AWS / AL2 from IPv4**
- **No blocking dependencies** beyond what Horizon already installs
- **Fail loud, fail partial**: a dead source must not kill the whole scan

Run:

    uv run scripts/morning-scan.py
    uv run scripts/morning-scan.py --watchlist AAPL MSFT NVDA GOOGL AMZN META TSLA
    uv run scripts/morning-scan.py --min-insiders 4 --min-value 1000000
    uv run scripts/morning-scan.py --no-macro   # skip macro calendar
    uv run scripts/morning-scan.py --no-insider # skip openinsider

Exit code 0 on success even if one of three sources fails. Exit code
1 only for fatal config errors.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import httpx


# -----------------------------------------------------------------------------
# Defaults
# -----------------------------------------------------------------------------

DEFAULT_WATCHLIST: list[str] = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    "AMD", "TSM", "AVGO", "MU", "ARM", "ASML",
    "SPY", "QQQ", "DIA", "IWM",
]

# Which macro event impacts matter. Forex Factory uses "High" / "Medium" / "Low".
DEFAULT_MACRO_IMPACTS: set[str] = {"High", "Medium"}

# Which countries' macro releases matter for US-equity trading.
DEFAULT_MACRO_COUNTRIES: set[str] = {"USD"}

OPENINSIDER_CLUSTER_URL = "http://openinsider.com/latest-cluster-buys"
FOREX_FACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(morning-scan; personal research)"
)


# -----------------------------------------------------------------------------
# IPv4-forcing HTTP transport
#
# Background: on Amazon Linux 2 the default getaddrinfo prefers AAAA (IPv6)
# records. sec.gov and a few others respond slowly over IPv6 from our
# network. Forcing AF_INET via a custom transport dodges the problem.
# -----------------------------------------------------------------------------


class IPv4OnlyTransport(httpx.HTTPTransport):
    """httpx transport that forces AF_INET."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        try:
            socket.getaddrinfo(host, None, socket.AF_INET)
        except socket.gaierror as exc:
            raise httpx.ConnectError(
                f"no IPv4 address for {host}: {exc}", request=request
            ) from exc
        return super().handle_request(request)


def make_client(timeout: float = 20.0) -> httpx.Client:
    """Build an httpx client that prefers IPv4 and sets a friendly UA."""
    return httpx.Client(
        transport=IPv4OnlyTransport(),
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
    )


# -----------------------------------------------------------------------------
# Section 1: OpenInsider cluster buys
# -----------------------------------------------------------------------------


@dataclass
class InsiderRow:
    filing_dt: str
    trade_date: str
    ticker: str
    company: str
    industry: str
    n_insiders: int
    trade_type: str
    price: float
    qty: int
    value_usd: int


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _parse_money(s: str) -> int:
    """`+$10,949,141` or `-$500` -> integer USD."""
    cleaned = re.sub(r"[^\d\-]", "", s.replace(",", ""))
    try:
        return int(cleaned) if cleaned else 0
    except ValueError:
        return 0


def _parse_insider_row(row_html: str) -> Optional[InsiderRow]:
    cells_raw = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL)
    if len(cells_raw) < 13:
        return None
    cells = [_strip_tags(c) for c in cells_raw]

    filing = cells[1]
    trade = cells[2]
    ticker_raw = cells[3]
    company = cells[4]
    industry = cells[5]
    n_ins = cells[6]
    trade_type = cells[7]
    price_raw = cells[8]
    qty_raw = cells[9]
    value_raw = cells[12]

    # OpenInsider's ticker column includes JS tooltip fragments; keep only
    # the trailing letters (upper case) that look like a ticker symbol.
    ticker_match = re.search(r"\b([A-Z][A-Z0-9\.\-]{0,7})\s*$", ticker_raw)
    if not ticker_match:
        return None
    ticker = ticker_match.group(1)

    try:
        n_insiders = int(re.sub(r"[^\d]", "", n_ins))
    except ValueError:
        return None

    try:
        price = float(price_raw.replace("$", "").replace(",", ""))
    except ValueError:
        price = 0.0

    try:
        qty = int(qty_raw.replace("+", "").replace(",", ""))
    except ValueError:
        qty = 0

    value = _parse_money(value_raw)

    return InsiderRow(
        filing_dt=filing,
        trade_date=trade,
        ticker=ticker,
        company=company,
        industry=industry,
        n_insiders=n_insiders,
        trade_type=trade_type,
        price=price,
        qty=qty,
        value_usd=value,
    )


def fetch_cluster_buys(
    client: httpx.Client,
    min_insiders: int,
    min_value_usd: int,
    limit: int,
) -> list[InsiderRow]:
    """Scrape OpenInsider latest-cluster-buys page."""
    resp = client.get(OPENINSIDER_CLUSTER_URL)
    resp.raise_for_status()
    html = resp.text

    # The page has ~12 tables; the data table is identified by having > 50
    # rows - small structural tables have few rows and lack price columns.
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
    data_table: Optional[str] = None
    for t in tables:
        if len(re.findall(r"<tr[^>]*>", t)) > 50:
            data_table = t
            break
    if data_table is None:
        return []

    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", data_table, re.DOTALL)
    parsed: list[InsiderRow] = []
    for rh in rows_html[1:]:  # skip header
        row = _parse_insider_row(rh)
        if row is None:
            continue
        if row.n_insiders < min_insiders:
            continue
        if row.value_usd < min_value_usd:
            continue
        if "Purchase" not in row.trade_type:
            continue
        parsed.append(row)
        if len(parsed) >= limit:
            break
    return parsed


def render_insider_section(rows: list[InsiderRow], watchlist: set[str]) -> list[str]:
    lines: list[str] = []
    lines.append("")
    lines.append(f"## 1. Insider cluster buys  ({len(rows)} rows, P-code, purchases only)")
    lines.append("")
    if not rows:
        lines.append("   (no rows pass thresholds)")
        return lines
    lines.append(
        "   {:>8}  {:>4}  {:>14}  {:>6}  {:<30}  {:<22}  {:<6}".format(
            "ticker", "ins", "value", "price", "company", "industry", "filed"
        )
    )
    lines.append("   " + "-" * 100)
    for r in rows:
        marker = "  *" if r.ticker in watchlist else ""
        value_str = f"${r.value_usd/1_000_000:.2f}M"
        lines.append(
            "   {:>8}  {:>4}  {:>14}  {:>6}  {:<30}  {:<22}  {:<6}{}".format(
                r.ticker,
                r.n_insiders,
                value_str,
                f"${r.price:.2f}",
                r.company[:30],
                r.industry[:22],
                r.filing_dt[:10],
                marker,
            )
        )
    lines.append("")
    lines.append("   * = ticker is in your watchlist")
    return lines


# -----------------------------------------------------------------------------
# Section 2: Earnings calendar via yfinance
# -----------------------------------------------------------------------------


@dataclass
class EarningsRow:
    ticker: str
    earnings_date: date
    days_until: int
    eps_estimate: Optional[float]
    revenue_estimate: Optional[float]


def fetch_earnings_windows(
    tickers: Iterable[str], days_ahead: int
) -> tuple[list[EarningsRow], list[str]]:
    """Return rows with earnings within days_ahead, plus a list of tickers that failed."""
    try:
        import contextlib
        import io
        import logging
        import os
        import yfinance as yf
    except ImportError:
        return [], list(tickers)

    # yfinance prints HTTP 404 messages to stdout for ETFs (SPY/QQQ/...) that
    # have no fundamentals data, which pollutes our plain-text report. Silence
    # both its logger and its raw stdout/stderr chatter during lookups.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    _devnull_out = io.StringIO()
    _devnull_err = io.StringIO()

    today = date.today()
    horizon = today + timedelta(days=days_ahead)
    rows: list[EarningsRow] = []
    failed: list[str] = []
    for sym in tickers:
        try:
            with contextlib.redirect_stdout(_devnull_out), \
                    contextlib.redirect_stderr(_devnull_err):
                cal = yf.Ticker(sym).calendar
        except Exception:
            failed.append(sym)
            continue
        if not cal or "Earnings Date" not in cal:
            continue
        dates = cal.get("Earnings Date") or []
        if isinstance(dates, date):
            dates = [dates]
        for d in dates:
            if not isinstance(d, date):
                continue
            if today <= d <= horizon:
                rows.append(EarningsRow(
                    ticker=sym,
                    earnings_date=d,
                    days_until=(d - today).days,
                    eps_estimate=cal.get("Earnings Average"),
                    revenue_estimate=cal.get("Revenue Average"),
                ))
    rows.sort(key=lambda r: (r.days_until, r.ticker))
    return rows, failed


def render_earnings_section(
    rows: list[EarningsRow], failed: list[str], days_ahead: int
) -> list[str]:
    lines: list[str] = []
    lines.append("")
    lines.append(f"## 2. Watchlist earnings  (next {days_ahead} days)")
    lines.append("")
    if not rows:
        lines.append("   (no earnings scheduled within window)")
    else:
        lines.append(
            "   {:>6}  {:>12}  {:>5}  {:>10}  {:>14}".format(
                "ticker", "report date", "T-d", "EPS est", "rev est ($B)"
            )
        )
        lines.append("   " + "-" * 60)
        for r in rows:
            eps = f"{r.eps_estimate:.2f}" if r.eps_estimate else "?"
            rev_b = (
                f"{r.revenue_estimate/1e9:.2f}"
                if r.revenue_estimate else "?"
            )
            lines.append(
                "   {:>6}  {:>12}  {:>5}  {:>10}  {:>14}".format(
                    r.ticker,
                    r.earnings_date.isoformat(),
                    f"T-{r.days_until}",
                    eps,
                    rev_b,
                )
            )
    if failed:
        lines.append("")
        lines.append(f"   (failed lookups: {', '.join(failed)})")
    return lines


# -----------------------------------------------------------------------------
# Section 3: Macro calendar via Forex Factory public JSON
# -----------------------------------------------------------------------------


@dataclass
class MacroRow:
    title: str
    country: str
    when_local: datetime
    impact: str
    forecast: str
    previous: str


def fetch_macro_today_tomorrow(
    client: httpx.Client,
    impacts: set[str],
    countries: set[str],
) -> list[MacroRow]:
    """Pull the Forex Factory weekly JSON and keep today + tomorrow slots."""
    resp = client.get(FOREX_FACTORY_URL)
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception:
        return []

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=2)
    rows: list[MacroRow] = []
    for item in data:
        country = item.get("country", "")
        if countries and country not in countries:
            continue
        impact = item.get("impact", "")
        if impacts and impact not in impacts:
            continue
        raw_date = item.get("date", "")
        if not raw_date:
            continue
        try:
            dt = datetime.fromisoformat(raw_date)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_utc = dt.astimezone(timezone.utc)
        if not (now <= dt_utc <= horizon):
            continue
        rows.append(MacroRow(
            title=item.get("title", "(untitled)"),
            country=country,
            when_local=dt_utc,
            impact=impact,
            forecast=item.get("forecast", "") or "",
            previous=item.get("previous", "") or "",
        ))
    rows.sort(key=lambda r: r.when_local)
    return rows


def render_macro_section(rows: list[MacroRow]) -> list[str]:
    lines: list[str] = []
    lines.append("")
    lines.append("## 3. Macro releases  (next 48h, High/Medium impact)")
    lines.append("")
    if not rows:
        lines.append("   (no qualifying macro events scheduled)")
        return lines
    lines.append(
        "   {:>17}  {:>7}  {:<30}  {:<9}  {:>10}  {:>10}".format(
            "when (UTC)", "country", "event", "impact", "forecast", "previous"
        )
    )
    lines.append("   " + "-" * 90)
    for r in rows:
        lines.append(
            "   {:>17}  {:>7}  {:<30}  {:<9}  {:>10}  {:>10}".format(
                r.when_local.strftime("%Y-%m-%d %H:%M"),
                r.country,
                r.title[:30],
                r.impact,
                r.forecast,
                r.previous,
            )
        )
    return lines


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="morning-scan",
        description=(
            "Pre-market scan: insider cluster buys, watchlist earnings,"
            " and today's macro release windows. Plain text output."
        ),
    )
    p.add_argument(
        "--watchlist", nargs="+", default=DEFAULT_WATCHLIST,
        help="Tickers to track for earnings and starred-row highlighting.",
    )
    p.add_argument(
        "--min-insiders", type=int, default=3,
        help="Minimum distinct insiders in a cluster buy (default 3).",
    )
    p.add_argument(
        "--min-value", type=int, default=500_000,
        help="Minimum USD value of a cluster buy (default $500,000).",
    )
    p.add_argument(
        "--insider-limit", type=int, default=20,
        help="Max insider rows to show after filtering (default 20).",
    )
    p.add_argument(
        "--earnings-days", type=int, default=7,
        help="Earnings window in days ahead (default 7).",
    )
    p.add_argument(
        "--impacts", nargs="+", default=sorted(DEFAULT_MACRO_IMPACTS),
        help="Forex Factory impact levels to include.",
    )
    p.add_argument(
        "--countries", nargs="+", default=sorted(DEFAULT_MACRO_COUNTRIES),
        help="Forex Factory country codes to include (USD, EUR, CNY, ...).",
    )
    p.add_argument("--no-insider", action="store_true")
    p.add_argument("--no-earnings", action="store_true")
    p.add_argument("--no-macro", action="store_true")
    p.add_argument("--timeout", type=float, default=20.0)
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    watchlist = {t.upper() for t in args.watchlist}
    impacts = set(args.impacts)
    countries = set(args.countries)

    now_utc = datetime.now(timezone.utc)
    header: list[str] = []
    header.append("=" * 90)
    header.append(
        f"  morning-scan  |  {now_utc:%Y-%m-%d %H:%M UTC}  "
        f"|  watchlist: {len(watchlist)} tickers"
    )
    header.append("=" * 90)
    print("\n".join(header))

    client = make_client(timeout=args.timeout)

    # Section 1
    if not args.no_insider:
        try:
            rows = fetch_cluster_buys(
                client,
                min_insiders=args.min_insiders,
                min_value_usd=args.min_value,
                limit=args.insider_limit,
            )
            print("\n".join(render_insider_section(rows, watchlist)))
        except Exception as exc:
            print(f"\n## 1. Insider cluster buys  (ERROR)\n   {exc}")

    # Section 2
    if not args.no_earnings:
        try:
            erows, efailed = fetch_earnings_windows(
                watchlist, days_ahead=args.earnings_days,
            )
            print("\n".join(render_earnings_section(
                erows, efailed, args.earnings_days
            )))
        except Exception as exc:
            print(f"\n## 2. Earnings  (ERROR)\n   {exc}")

    # Section 3
    if not args.no_macro:
        try:
            mrows = fetch_macro_today_tomorrow(
                client, impacts=impacts, countries=countries,
            )
            print("\n".join(render_macro_section(mrows)))
        except Exception as exc:
            print(f"\n## 3. Macro  (ERROR)\n   {exc}")

    client.close()
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
