# parlayapi-discord-bot

A self-hostable personal Discord assistant for one configured owner: moneyline, spread and total snapshots, line moves, and a parlay price checker. Powered by [ParlayAPI](https://parlay-api.com), using your own API key or the limited keyless demo.

Every slash command checks your Discord user ID before reading cached data or calling a provider. Replies are ephemeral, visible only to the person who invoked the command. Other users receive a private refusal, including server administrators. A missing or malformed owner ID prevents startup.

This version supports personal use only and does not offer a shared community feed. Installing MIT software grants no data distribution rights; applicable [Terms](https://parlay-api.com/terms) and any written agreement govern data use. These tool defaults do not amend existing customer agreements. Private replies limit channel exposure; they do not prevent screenshots, copying or forwarding by the owner.

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

Data and calculator replies are private embeds with a "via ParlayAPI" footer and a title link to [parlay-api.com](https://parlay-api.com).

## Quick start

### 1. Get a free ParlayAPI key

Sign up at [parlay-api.com/signup](https://parlay-api.com/signup?utm_source=github&utm_medium=example&utm_campaign=discord_personal). Current credits, rates and paid tiers are on the [pricing page](https://parlay-api.com/pricing). Your usage depends on requested markets and refresh frequency; the cache does not guarantee a monthly allowance will cover your workload.

The bot also runs without a key in the limited demo mode below. A key enables account requests for supported sports and markets. Actual event, book and market availability varies; a key does not guarantee complete coverage.

### 2. Create the Discord bot

1. Go to the [Discord developer portal](https://discord.com/developers/applications), create an application, then in **Bot** create a bot and copy the token.
2. No privileged intents are needed. The bot uses slash commands only and never reads message content.
3. In Discord, enable **User Settings > Advanced > Developer Mode**, then right-click your own profile and choose **Copy User ID**. Use that numeric user ID for `PARLAY_BOT_OWNER_ID`, not the application, server or channel ID. The configured account must be you, the API account holder.
4. Invite it with the **bot** and **applications.commands** scopes and the Send Messages and Embed Links permissions. Installing it in a server does not grant its members access:

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_APP_ID&permissions=18432&scope=bot%20applications.commands
```

### 3. Run it

With Python 3.9+:

```bash
pip install -r requirements.txt
export DISCORD_TOKEN=your-discord-bot-token
export PARLAY_BOT_OWNER_ID=your-numeric-discord-user-id
export PARLAY_API_KEY=your-parlayapi-key
python3 bot.py
```

Or with Docker:

```bash
docker build -t parlayapi-discord-bot .
docker run -e DISCORD_TOKEN=... -e PARLAY_BOT_OWNER_ID=... -e PARLAY_API_KEY=... parlayapi-discord-bot
```

Slash commands sync on startup; they can take a minute to appear the first time.

## Personal-mode migration

This is a breaking configuration change for existing installations. Before restarting the updated bot, set `PARLAY_BOT_OWNER_ID` to your own Discord user ID. Startup now stops if it is missing or invalid. Only that account can invoke commands, including `/parlaycheck`, and every reply is private. Server roles and administrator permissions do not override the owner check. Existing customer agreements are unchanged.

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | required | Discord bot token |
| `PARLAY_BOT_OWNER_ID` | required | Your numeric Discord user ID; the only account allowed to use commands |
| `PARLAY_API_KEY` | unset | ParlayAPI key. Unset = keyless demo mode |
| `PARLAY_BOT_DEFAULT_SPORT` | `americanfootball_nfl` | Sport used when the dropdown is left empty |
| `PARLAY_BOT_COOLDOWN_SECONDS` | `15` | Per-owner, per-command cooldown for API-backed commands, across channels |
| `PARLAY_BOT_CACHE_SECONDS` | `60` | Response cache TTL (floor of 60, cannot be lowered) |
| `PARLAY_API_BASE` | `https://parlay-api.com` | API base URL |

## Credit courtesy: how the bot protects your allowance

After the owner check, two layers reduce repeated requests:

1. **Owner-wide cooldown.** `/odds`, `/line`, and `/moves` each allow one call every 15 seconds (configurable via `PARLAY_BOT_COOLDOWN_SECONDS`). Changing channels does not reset it. The cooldown reply is private.
2. **60 second cache.** Repeated requests with the same sport and markets within 60 seconds can be served from memory. Other users cannot access this cache through Discord commands. The floor is 60 seconds and cannot be configured lower.

Different sports or markets use separate cache entries. Concurrent requests can arrive before a cache entry is populated, so this cache is not a hard monthly budget or request cap. The per-endpoint credit schedule is public at [`/v1/meta/credit-costs`](https://parlay-api.com/v1/meta/credit-costs).

## Keyless demo mode

If `PARLAY_API_KEY` is not set, the bot falls back to ParlayAPI's free no-auth demo endpoints (`/v1/try/...`). Honest limits, honestly labeled in every embed:

- 6 sports only (NFL, MLB, NBA, NHL, EPL, MMA)
- moneylines only: `/line` explains that spreads and totals need a key
- first 5 events per sport, a few major books
- 60 requests per hour per IP, enforced server-side

The owner restriction and private replies apply in demo mode too. `/moves` uses its public endpoint and can return empty data or an error; `/parlaycheck` is local arithmetic. Demo embeds label their limited scope and link the signup page.

## Terminal preview without a Discord token

`oddscore.py` (standard library only, no dependencies) renders embeds in your own terminal. Odds, line and moves commands make API requests; only parlaycheck is fully offline. These local commands do not connect to Discord or need a Discord owner ID. Do not republish their feed output:

```bash
python3 oddscore.py odds "lions" --sport americanfootball_nfl
python3 oddscore.py line "yankees" --sport baseball_mlb
python3 oddscore.py moves --sport americanfootball_nfl
python3 oddscore.py parlaycheck "-110,-110,-110"
```

## Tests

```bash
pip install -r requirements.txt
python3 -m unittest discover -s tests -v
```

The test suite pins the parlay math to the exact vectors from the site calculator's self-test (including the JavaScript rounding convention, where 3x -110 must come out to +596), plus formatting, event matching, price parsing, and the `/v1/try` envelope convention (events nested under an `events` key).

Owner/privacy tests use mocked Discord interactions and provider functions. They verify startup validation, non-owner rejection before provider/cache access, and private success, empty, error, math and cooldown replies. They never connect to Discord or the API.

## Responsible gambling

This bot provides market data and arithmetic, not betting advice, and nothing in it should be read as encouragement to bet. If gambling stops being fun, help is free and confidential: in the US call or text 1-800-GAMBLER, or visit [ncpgambling.org](https://www.ncpgambling.org/).

## License

MIT applies to this repository's code, not a license to redistribute API data. Data use remains subject to [ParlayAPI's terms](https://parlay-api.com/terms) and any explicit distribution agreement. Not affiliated with Discord or any sportsbook.

---

Part of the [ParlayAPI](https://parlay-api.com) ecosystem: a real-time sports odds API with a free tier of 1,000 credits per month, no card required. Explore all the tools at [github.com/JacobiusMakes](https://github.com/JacobiusMakes).
