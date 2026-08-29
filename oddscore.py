"""Core logic for the ParlayAPI Discord bot: odds math, formatting,
API client, and embed payload builders.

Standard library only. No discord.py import here, so this module is
unit-testable and runnable as a dry-run CLI without a Discord token:

    python3 oddscore.py parlaycheck "-110,-110,-110"
    python3 oddscore.py odds "celtics" --sport basketball_nba
    python3 oddscore.py line "chiefs" --sport americanfootball_nfl
    python3 oddscore.py moves --sport americanfootball_nfl

The parlay math mirrors the pure functions of
https://parlay-api.com/tools/parlay-calculator exactly, including its
rounding convention (JavaScript Math.round semantics, half away from
negative infinity), so the bot and the site never disagree on a price.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

__version__ = "1.0.0"

BASE_URL = os.environ.get("PARLAY_API_BASE", "https://parlay-api.com")
SITE_URL = "https://parlay-api.com"
SIGNUP_URL = "https://parlay-api.com/signup"
USER_AGENT = "parlayapi-discord-bot/" + __version__ + " (+https://github.com/JacobiusMakes/parlayapi-discord-bot)"

# Sports the keyless /v1/try demo family supports. With an API key any
# of the 90+ sport keys works; see https://parlay-api.com/docs
TRY_DEMO_SPORTS = (
    "americanfootball_nfl",
    "baseball_mlb",
    "basketball_nba",
    "icehockey_nhl",
    "mma_mixed_martial_arts",
    "soccer_epl",
)

# Sport choices offered in the slash-command dropdowns. Any valid
# sport key also works via the free-text sport argument in keyed mode.
SPORT_CHOICES = (
    ("NFL", "americanfootball_nfl"),
    ("College Football", "americanfootball_ncaaf"),
    ("NBA", "basketball_nba"),
    ("WNBA", "basketball_wnba"),
    ("MLB", "baseball_mlb"),
    ("NHL", "icehockey_nhl"),
    ("EPL", "soccer_epl"),
    ("MMA", "mma_mixed_martial_arts"),
)

MAX_PARLAY_LEGS = 20
MAX_BOOKS_SHOWN = 6
MAX_EVENTS_SHOWN = 3

# Server-side /v1/try shared cache is 60s; never cache below that so a
# busy Discord server cannot hammer the API (or burn owner credits).
MIN_CACHE_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Parlay math. Mirrors parlay-api.com/tools/parlay-calculator exactly.
# ---------------------------------------------------------------------------

def js_round(x: float) -> int:
    """JavaScript Math.round semantics: half rounds toward +infinity.

    Python's round() does banker's rounding, which would disagree with
    the site calculator on exact halves. floor(x + 0.5) matches JS.
    """
    return int(math.floor(x + 0.5))


def american_to_decimal(american) -> float:
    """American odds to decimal odds.

    Positive A: A/100 + 1. Negative A: 100/|A| + 1. Zero or
    non-numeric input raises ValueError.
    """
    try:
        a = float(american)
    except (TypeError, ValueError):
        raise ValueError("not a number: %r" % (american,))
    if not math.isfinite(a) or a == 0:
        raise ValueError("invalid American odds: %r" % (american,))
    return (a / 100.0) + 1.0 if a > 0 else (100.0 / abs(a)) + 1.0


def decimal_to_american(decimal_odds) -> int:
    """Decimal odds back to American (display convenience).

    d >= 2 maps to round((d-1)*100); 1 < d < 2 maps to
    round(-100/(d-1)). Same rounding as the site calculator.
    """
    d = float(decimal_odds)
    if not math.isfinite(d) or d <= 1:
        raise ValueError("invalid decimal odds: %r" % (decimal_odds,))
    return js_round((d - 1.0) * 100.0) if d >= 2 else js_round(-100.0 / (d - 1.0))


def combined_decimal(decimals) -> float:
    """Product of leg decimal odds. Raises ValueError on empty input or
    any leg <= 1."""
    decimals = list(decimals)
    if not decimals:
        raise ValueError("no legs")
    product = 1.0
    for d in decimals:
        d = float(d)
        if not math.isfinite(d) or d <= 1:
            raise ValueError("invalid leg decimal odds: %r" % (d,))
        product *= d
    return product


def parlay_payout(stake: float, combined_dec: float) -> float:
    """payout = stake * combined decimal"""
    return float(stake) * combined_dec


def parlay_profit(stake: float, combined_dec: float) -> float:
    """profit = payout - stake"""
    return float(stake) * combined_dec - float(stake)


def combined_implied_prob(combined_dec: float) -> float:
    """implied probability = 1 / combined decimal"""
    return 1.0 / combined_dec


def parse_american_prices(text: str) -> list:
    """Parse a comma or space separated list of American prices.

    Accepts "-110, -110, +150" or "-110 -110 150". Raises ValueError
    with a human-readable message on bad input.
    """
    raw = (text or "").replace(",", " ").split()
    if not raw:
        raise ValueError("No prices given. Example: -110, -110, +150")
    if len(raw) > MAX_PARLAY_LEGS:
        raise ValueError("Too many legs (max %d)." % MAX_PARLAY_LEGS)
    prices = []
    for tok in raw:
        t = tok.strip().lstrip("+")
        try:
            v = int(t)
        except ValueError:
            raise ValueError("Not an American price: %r. Example: -110, -110, +150" % tok)
        if v == 0:
            raise ValueError("0 is not a valid American price.")
        prices.append(v)
    return prices


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_american(price) -> str:
    """+150 / -110 style. Non-numeric input renders as '?'."""
    try:
        return "%+d" % int(round(float(price)))
    except (TypeError, ValueError):
        return "?"


def fmt_decimal(d: float) -> str:
    return "%.2f" % float(d)


def fmt_prob(p: float) -> str:
    return "%.1f%%" % (float(p) * 100.0)


def fmt_money(x: float) -> str:
    return "$%.2f" % float(x)


def fmt_point(point) -> str:
    """Spread/total point: -2.5, +7, 224.5. Trims trailing .0."""
    try:
        f = float(point)
    except (TypeError, ValueError):
        return "?"
    if f == int(f):
        return "%+d" % int(f)
    return "%+.1f" % f


def fmt_total_point(point) -> str:
    """Total line without a sign: 224.5, 47."""
    try:
        f = float(point)
    except (TypeError, ValueError):
        return "?"
    if f == int(f):
        return "%d" % int(f)
    return "%.1f" % f


def fmt_commence(iso_ts) -> str:
    """Compact UTC kickoff string from an ISO timestamp."""
    if not iso_ts:
        return "time TBD"
    s = str(iso_ts).replace("T", " ").replace("Z", "")
    s = s.split("+")[0].split(".")[0].strip()
    return s + " UTC"


# ---------------------------------------------------------------------------
# API client (stdlib urllib; bot.py wraps these in a thread executor)
# ---------------------------------------------------------------------------

class ApiError(Exception):
    """API-level failure with a message safe to show in Discord."""


_cache: dict = {}


def _cache_get(key):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _cache_put(key, value, ttl: float):
    _cache[key] = (time.time() + max(ttl, MIN_CACHE_SECONDS), value)


def api_get(path: str, params: Optional[dict] = None,
            api_key: Optional[str] = None, timeout: float = 15.0):
    url = BASE_URL.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    if api_key:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
            detail = body.get("message") or body.get("detail") or body.get("error") or ""
        except Exception:
            pass
        if e.code == 401:
            raise ApiError("The API rejected the key (401). Check PARLAY_API_KEY. "
                           "Free keys: " + SIGNUP_URL)
        if e.code in (402, 403):
            raise ApiError("This request is not available on the key's current plan (%d). %s "
                           "Plans: %s/pricing" % (e.code, detail, SITE_URL))
        if e.code == 429:
            raise ApiError("Rate limited by the API (429). The bot caches for 60s; "
                           "try again in a minute. %s" % detail)
        raise ApiError("API returned HTTP %d. %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise ApiError("Could not reach %s (%s)." % (BASE_URL, getattr(e, "reason", e)))


def fetch_odds(sport_key: str, markets: str, api_key: Optional[str],
               cache_seconds: float = MIN_CACHE_SECONDS):
    """Fetch events for one sport.

    Keyed mode: /v1/sports/{sport}/odds (any sport key, any market).
    Keyless demo mode: /v1/try/{sport}/odds (6 sports, h2h only, first
    5 events, 60 req/hour per IP, server-side shared cache).

    Returns (events_list, demo_notice_or_None). Responses are cached
    for cache_seconds (never below 60) so a busy channel costs at most
    one API call per sport per minute.
    """
    cache_key = ("odds", sport_key, markets, bool(api_key))
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit

    if api_key:
        data = api_get("/v1/sports/%s/odds" % sport_key,
                       {"regions": "us", "markets": markets,
                        "oddsFormat": "american"},
                       api_key=api_key)
        events = data if isinstance(data, list) else data.get("events", [])
        result = (events or [], None)
    else:
        if sport_key not in TRY_DEMO_SPORTS:
            raise ApiError(
                "Keyless demo mode only covers: %s. Set PARLAY_API_KEY "
                "(free at %s) for all 90+ sport keys."
                % (", ".join(TRY_DEMO_SPORTS), SIGNUP_URL))
        if markets != "h2h":
            raise ApiError(
                "Keyless demo mode serves moneylines only. Set "
                "PARLAY_API_KEY (free at %s) for spreads and totals."
                % SIGNUP_URL)
        payload = api_get("/v1/try/%s/odds" % sport_key)
        # /v1/try envelope: events nested under an "events" key.
        events = payload.get("events", []) if isinstance(payload, dict) else []
        notice = "Keyless demo data: first 5 events, moneyline only, a few major books."
        result = (events or [], notice)

    _cache_put(cache_key, result, cache_seconds)
    return result


def fetch_movers(sport_key: Optional[str] = None, window_minutes: int = 60,
                 limit: int = 5, cache_seconds: float = 90.0):
    """Fetch /v1/meta/movers (public, no auth, no credits, 90s
    server-side cache). Returns the movers list."""
    cache_key = ("movers", sport_key, window_minutes, limit)
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit
    params = {"window_minutes": window_minutes, "limit": limit}
    if sport_key:
        params["sport_key"] = sport_key
    payload = api_get("/v1/meta/movers", params)
    movers = payload.get("movers", []) if isinstance(payload, dict) else []
    _cache_put(cache_key, movers, cache_seconds)
    return movers


# ---------------------------------------------------------------------------
# Event search
# ---------------------------------------------------------------------------

def match_events(events, query: str):
    """Match events by team or matchup.

    "celtics" matches any event where a team name contains it.
    "celtics vs knicks", "celtics @ knicks", "celtics at knicks" match
    events where each side matches a different team.
    """
    q = (query or "").strip().lower()
    if not q:
        return list(events)
    parts = None
    for sep in (" vs ", " vs. ", " @ ", " at "):
        if sep in q:
            parts = [p.strip() for p in q.split(sep, 1)]
            break

    def team_hit(ev, needle):
        home = str(ev.get("home_team", "")).lower()
        away = str(ev.get("away_team", "")).lower()
        return needle in home or needle in away

    out = []
    for ev in events:
        if parts:
            a, b = parts
            names = [str(ev.get("home_team", "")).lower(),
                     str(ev.get("away_team", "")).lower()]
            if any(a in n for n in names) and any(b in n for n in names):
                out.append(ev)
        elif team_hit(ev, q):
            out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Embed payloads. Plain dicts: {"title", "url", "description", "footer"}.
# bot.py converts them to discord.Embed; the dry-run CLI prints them.
# ---------------------------------------------------------------------------

FOOTER_TEXT = "via ParlayAPI"


def _market(bookmaker, key):
    for m in bookmaker.get("markets", []):
        if m.get("key") == key:
            return m
    return None


def _outcome(market, name):
    for o in market.get("outcomes", []):
        if o.get("name") == name:
            return o
    return None


def build_odds_embed(event, demo_notice: Optional[str] = None,
                     max_books: int = MAX_BOOKS_SHOWN) -> dict:
    """Moneyline snapshot across top books for one event."""
    home = event.get("home_team", "?")
    away = event.get("away_team", "?")
    books = event.get("bookmakers", [])[:max_books]

    rows = []
    best_away = None
    best_home = None
    for bm in books:
        m = _market(bm, "h2h")
        if not m:
            continue
        ao = _outcome(m, away)
        ho = _outcome(m, home)
        ap = ao.get("price") if ao else None
        hp = ho.get("price") if ho else None
        rows.append((bm.get("title") or bm.get("key") or "?", ap, hp))
        if isinstance(ap, (int, float)):
            best_away = ap if best_away is None else max(best_away, ap)
        if isinstance(hp, (int, float)):
            best_home = hp if best_home is None else max(best_home, hp)

    name_w = max([len(r[0]) for r in rows] + [4])
    lines = ["%-*s  %6s  %6s" % (name_w, "Book", "Away", "Home")]
    for name, ap, hp in rows:
        lines.append("%-*s  %6s  %6s" % (name_w, name,
                                         fmt_american(ap) if ap is not None else "-",
                                         fmt_american(hp) if hp is not None else "-"))
    if rows:
        lines.append("%-*s  %6s  %6s" % (name_w, "Best",
                                         fmt_american(best_away) if best_away is not None else "-",
                                         fmt_american(best_home) if best_home is not None else "-"))
    table = "```\n" + "\n".join(lines) + "\n```" if rows else "No moneyline quotes right now."

    desc = "Moneyline, %s\n%s" % (fmt_commence(event.get("commence_time")), table)
    if demo_notice:
        desc += "\n" + demo_notice + " Free key: " + SIGNUP_URL
    return {
        "title": "%s @ %s" % (away, home),
        "url": SITE_URL,
        "description": desc,
        "footer": FOOTER_TEXT,
    }


def build_line_embed(event, demo_notice: Optional[str] = None,
                     max_books: int = MAX_BOOKS_SHOWN) -> dict:
    """Spread and total snapshot across top books for one event."""
    home = event.get("home_team", "?")
    away = event.get("away_team", "?")
    books = event.get("bookmakers", [])[:max_books]

    rows = []
    for bm in books:
        name = bm.get("title") or bm.get("key") or "?"
        spread_txt = "-"
        total_txt = "-"
        sm = _market(bm, "spreads")
        if sm:
            ho = _outcome(sm, home)
            if ho and ho.get("point") is not None:
                spread_txt = "%s %s" % (fmt_point(ho.get("point")),
                                        fmt_american(ho.get("price")))
        tm = _market(bm, "totals")
        if tm:
            over = _outcome(tm, "Over")
            under = _outcome(tm, "Under")
            if over and over.get("point") is not None:
                o_price = fmt_american(over.get("price"))
                u_price = fmt_american(under.get("price")) if under else "-"
                total_txt = "%s %s/%s" % (fmt_total_point(over.get("point")),
                                          o_price, u_price)
        if sm or tm:
            rows.append((name, spread_txt, total_txt))

    name_w = max([len(r[0]) for r in rows] + [4])
    lines = ["%-*s  %-11s  %s" % (name_w, "Book", "Home spread", "Total O/U")]
    for name, s, t in rows:
        lines.append("%-*s  %-11s  %s" % (name_w, name, s, t))
    table = ("```\n" + "\n".join(lines) + "\n```") if rows else \
        "No spread or total quotes right now."

    desc = "Spread and total, %s\n%s" % (fmt_commence(event.get("commence_time")), table)
    if demo_notice:
        desc += "\n" + demo_notice + " Free key: " + SIGNUP_URL
    return {
        "title": "%s @ %s" % (away, home),
        "url": SITE_URL,
        "description": desc,
        "footer": FOOTER_TEXT,
    }


def build_moves_embed(movers, sport_key: Optional[str] = None,
                      window_minutes: int = 60) -> dict:
    """Top moneyline movers (sharp-anchor view, implied-probability
    ranked) from /v1/meta/movers."""
    title = "Top line moves, last %d min" % window_minutes
    if sport_key:
        title += " (%s)" % sport_key
    if not movers:
        desc = ("No market has moved more than 1 implied-probability "
                "point in this window.")
    else:
        chunks = []
        for mv in movers:
            matchup = "%s @ %s" % (mv.get("away_team", "?"), mv.get("home_team", "?"))
            line = "**%s**  `%s`\n" % (matchup, mv.get("sport_key", "?"))
            line += "home %s to %s, away %s to %s (max move %.1fpp)" % (
                fmt_american(mv.get("home_ml_first")),
                fmt_american(mv.get("home_ml_last")),
                fmt_american(mv.get("away_ml_first")),
                fmt_american(mv.get("away_ml_last")),
                float(mv.get("abs_max_prob_delta_pp") or 0.0),
            )
            chunks.append(line)
        desc = "\n\n".join(chunks)
        desc += "\n\nSharp-anchor view, ranked by implied-probability shift."
    return {
        "title": title,
        "url": SITE_URL,
        "description": desc,
        "footer": FOOTER_TEXT,
    }


def build_parlaycheck_embed(prices, stake: float = 100.0) -> dict:
    """Combined price of a list of American odds, using the site
    calculator's exact math."""
    decimals = [american_to_decimal(p) for p in prices]
    dec = combined_decimal(decimals)
    american = decimal_to_american(dec)
    prob = combined_implied_prob(dec)
    payout = parlay_payout(stake, dec)
    profit = parlay_profit(stake, dec)

    legs_txt = ", ".join(fmt_american(p) for p in prices)
    lines = [
        "Legs (%d): %s" % (len(prices), legs_txt),
        "",
        "Combined decimal: **%s**" % fmt_decimal(dec),
        "Combined American: **%s**" % fmt_american(american),
        "Implied probability: **%s**" % fmt_prob(prob),
        "%s stake pays %s (profit %s)" % (fmt_money(stake), fmt_money(payout),
                                          fmt_money(profit)),
        "",
        "Book odds include margin; implied probability is what the "
        "combined price says, not the true chance of winning. Math "
        "only, not betting advice.",
    ]
    return {
        "title": "Parlay check",
        "url": SITE_URL + "/tools/parlay-calculator",
        "description": "\n".join(lines),
        "footer": FOOTER_TEXT,
    }


def build_error_embed(message: str) -> dict:
    return {
        "title": "Hmm, that did not work",
        "url": SITE_URL,
        "description": str(message),
        "footer": FOOTER_TEXT,
    }


# ---------------------------------------------------------------------------
# Dry-run CLI: prints embed payloads as text. No Discord token needed.
# Keyless by default (uses /v1/try and /v1/meta/movers).
# ---------------------------------------------------------------------------

def render_embed_text(payload: dict) -> str:
    bar = "=" * 60
    parts = [bar, payload.get("title", ""), payload.get("url", ""), "",
             payload.get("description", ""), "",
             "[footer] " + payload.get("footer", ""), bar]
    return "\n".join(parts)


def _dry_run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Dry-run the bot's embeds as text (no Discord needed).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_odds = sub.add_parser("odds", help="moneyline snapshot")
    p_odds.add_argument("query", help="team or matchup, e.g. 'celtics' or 'celtics vs knicks'")
    p_odds.add_argument("--sport", default="americanfootball_nfl")

    p_line = sub.add_parser("line", help="spread and total")
    p_line.add_argument("query")
    p_line.add_argument("--sport", default="americanfootball_nfl")

    p_moves = sub.add_parser("moves", help="top movers")
    p_moves.add_argument("--sport", default=None)
    p_moves.add_argument("--window", type=int, default=60)

    p_pc = sub.add_parser("parlaycheck", help="combined parlay price")
    p_pc.add_argument("prices", help="comma-separated American prices, e.g. '-110,-110,-110'")
    p_pc.add_argument("--stake", type=float, default=100.0)

    if argv is None:
        import sys
        argv = sys.argv[1:]
    # Let a leading "-110,..." price list through argparse (it would
    # otherwise be read as an option flag).
    import re
    argv = [(" " + a) if re.fullmatch(r"[-+]?\d+([,\s]+[-+]?\d+)*", a) else a
            for a in argv]
    args = ap.parse_args(argv)
    api_key = os.environ.get("PARLAY_API_KEY") or None

    try:
        if args.cmd == "parlaycheck":
            payload = build_parlaycheck_embed(parse_american_prices(args.prices),
                                              stake=args.stake)
            print(render_embed_text(payload))
        elif args.cmd == "moves":
            movers = fetch_movers(args.sport, args.window, limit=5)
            print(render_embed_text(build_moves_embed(movers, args.sport, args.window)))
        else:
            markets = "h2h" if args.cmd == "odds" else "spreads,totals"
            events, notice = fetch_odds(args.sport, markets, api_key)
            hits = match_events(events, args.query)[:MAX_EVENTS_SHOWN]
            if not hits:
                print(render_embed_text(build_error_embed(
                    "No upcoming %s event matched %r. The keyless demo only "
                    "sees the first 5 events per sport." % (args.sport, args.query))))
                return 1
            builder = build_odds_embed if args.cmd == "odds" else build_line_embed
            for ev in hits:
                print(render_embed_text(builder(ev, notice)))
    except (ApiError, ValueError) as e:
        print(render_embed_text(build_error_embed(str(e))))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_dry_run())
