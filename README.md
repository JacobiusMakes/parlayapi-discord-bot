# parlayapi-discord-bot

A self-hostable Discord bot that answers odds questions in your server: live moneylines, spreads and totals across 30+ sportsbooks, the biggest line moves, and a parlay price checker. Powered by [ParlayAPI](https://parlay-api.com), bring your own free API key.

No picks, no predictions, no "locks". The bot reports market prices and does math. What you do with that is up to you.

## Commands

| Command | What it does | API cost |
|---|---|---|
| `/odds <team or matchup>` | Moneyline snapshot across top books, best price flagged | 1 credit per uncached call |
| `/line <team>` | Spread and total across top books | 2 credits per uncached call |
| `/moves` | Biggest moneyline moves in the last hour, sharp-anchor view | free (public endpoint) |
| `/parlaycheck <prices>` | Combined price of comma-separated American odds | free (pure math) |

`/odds` and `/line` take an optional sport dropdown (NFL, NCAAF, NBA, WNBA, MLB, NHL, EPL, MMA); the default sport is configurable. Matchup queries like `chiefs vs bills` or `chiefs @ bills` work too.

`/parlaycheck -110, -110, -110` returns combined decimal 6.96, combined American +596, implied probability 14.4%, using exactly the same math as the [parlay calculator](https://parlay-api.com/tools/parlay-calculator) on the site, down to the rounding convention.

Every response is a tidy embed with a "via ParlayAPI" footer and a title link to [parlay-api.com](https://parlay-api.com).

## Quick start

### 1. Get a free ParlayAPI key

Sign up at [parlay-api.com/signup](https://parlay-api.com/signup). The free tier includes 1,000 credits per month with no credit card. With the default cache settings below, that comfortably runs a small server; paid tiers are on the live [pricing page](https://parlay-api.com/pricing).

The bot also runs with no key at all in a clearly-labeled demo mode (see below), but a key is what unlocks all 90+ sport keys, spreads and totals, and all 30+ books.

### 2. Create the Discord bot

1. Go to the [Discord developer portal](https://discord.com/developers/applications), create an application, then in **Bot** create a bot and copy the token.
2. No privileged intents are needed. The bot uses slash commands only and never reads message content.
3. Invite it with the **bot** and **applications.commands** scopes and the Send Messages and Embed Links permissions:

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_APP_ID&permissions=18432&scope=bot%20applications.commands
```

### 3. Run it

With Python 3.9+:

```bash
pip install -r requirements.txt
export DISCORD_TOKEN=your-discord-bot-token
export PARLAY_API_KEY=your-parlayapi-key
python3 bot.py
```

Or with Docker:

```bash
docker build -t parlayapi-discord-bot .
docker run -e DISCORD_TOKEN=... -e PARLAY_API_KEY=... parlayapi-discord-bot
```

Slash commands sync on startup; they can take a minute to appear the first time.

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | required | Discord bot token |
| `PARLAY_API_KEY` | unset | ParlayAPI key. Unset = keyless demo mode |
| `PARLAY_BOT_DEFAULT_SPORT` | `americanfootball_nfl` | Sport used when the dropdown is left empty |
| `PARLAY_BOT_COOLDOWN_SECONDS` | `15` | Per-channel cooldown for API-backed commands |
| `PARLAY_BOT_CACHE_SECONDS` | `60` | Response cache TTL (floor of 60, cannot be lowered) |
| `PARLAY_API_BASE` | `https://parlay-api.com` | API base URL |

## Credit courtesy: how the bot protects your allowance

Two layers keep one spammy channel from burning your monthly credits:

1. **Per-channel cooldown.** `/odds`, `/line`, and `/moves` allow one call per channel every 15 seconds (configurable via `PARLAY_BOT_COOLDOWN_SECONDS`). Users on cooldown get a private nudge, not an API call.
2. **Shared 60 second cache.** Identical requests (same sport, same markets) within 60 seconds are served from memory and cost zero credits. The floor is 60 seconds and cannot be configured lower.

Worst case with defaults: one sport being hammered around the clock costs at most one `/odds` call per minute, or about 60 credits per hour of continuous spam, and `/moves` and `/parlaycheck` never touch your allowance. The per-endpoint credit schedule is public at [`/v1/meta/credit-costs`](https://parlay-api.com/v1/meta/credit-costs).

## Keyless demo mode

If `PARLAY_API_KEY` is not set, the bot falls back to ParlayAPI's free no-auth demo endpoints (`/v1/try/...`). Honest limits, honestly labeled in every embed:

- 6 sports only (NFL, MLB, NBA, NHL, EPL, MMA)
- moneylines only: `/line` explains that spreads and totals need a key
- first 5 events per sport, a few major books
- 60 requests per hour per IP, enforced server-side

`/moves` and `/parlaycheck` work fully in either mode. Demo embeds say they are demo data and link the signup page.

## Dry run without a Discord token

`oddscore.py` (standard library only, no dependencies) renders the same embeds as text, so you can try everything before creating a bot:

```bash
python3 oddscore.py odds "lions" --sport americanfootball_nfl
python3 oddscore.py line "yankees" --sport baseball_mlb
python3 oddscore.py moves --sport americanfootball_nfl
python3 oddscore.py parlaycheck "-110,-110,-110"
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The test suite pins the parlay math to the exact vectors from the site calculator's self-test (including the JavaScript rounding convention, where 3x -110 must come out to +596), plus formatting, event matching, price parsing, and the `/v1/try` envelope convention (events nested under an `events` key).

## Responsible gambling

This bot provides market data and arithmetic, not betting advice, and nothing in it should be read as encouragement to bet. If gambling stops being fun, help is free and confidential: in the US call or text 1-800-GAMBLER, or visit [ncpgambling.org](https://www.ncpgambling.org/).

## License

MIT. Not affiliated with Discord or any sportsbook. Odds data via [ParlayAPI](https://parlay-api.com).

---

Part of the [ParlayAPI](https://parlay-api.com) ecosystem: a real-time sports odds API with a free tier of 1,000 credits per month, no card required. Explore all the tools at [github.com/JacobiusMakes](https://github.com/JacobiusMakes).
