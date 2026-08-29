"""ParlayAPI Discord odds bot.

Slash commands: /odds, /line, /moves, /parlaycheck.
All odds math and formatting lives in oddscore.py (stdlib only); this
file is just the discord.py glue.

Run:
    export DISCORD_TOKEN=...          # required
    export PARLAY_API_KEY=...         # recommended; keyless demo mode without it
    python3 bot.py

Dry-run without any Discord token:
    python3 oddscore.py odds "celtics" --sport basketball_nba
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import discord
from discord import app_commands

import oddscore

log = logging.getLogger("parlayapi-discord-bot")
logging.basicConfig(level=logging.INFO)

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
PARLAY_API_KEY = os.environ.get("PARLAY_API_KEY") or None
DEFAULT_SPORT = os.environ.get("PARLAY_BOT_DEFAULT_SPORT", "americanfootball_nfl")

# Per-channel courtesy cooldown (seconds) for commands that can hit the
# API. One spammy channel cannot burn the owner's credits: at most one
# API-backed command per channel per cooldown window, and responses are
# additionally cached for PARLAY_BOT_CACHE_SECONDS (min 60).
COOLDOWN_SECONDS = float(os.environ.get("PARLAY_BOT_COOLDOWN_SECONDS", "15"))
CACHE_SECONDS = max(60.0, float(os.environ.get("PARLAY_BOT_CACHE_SECONDS", "60")))

SPORT_CHOICES = [app_commands.Choice(name=n, value=v)
                 for n, v in oddscore.SPORT_CHOICES]


def to_embed(payload: dict) -> discord.Embed:
    e = discord.Embed(
        title=payload.get("title"),
        url=payload.get("url"),
        description=payload.get("description"),
        color=0x7C5CFC,
    )
    e.set_footer(text=payload.get("footer", oddscore.FOOTER_TEXT))
    return e


def channel_cooldown(interaction: discord.Interaction) -> Optional[app_commands.Cooldown]:
    return app_commands.Cooldown(1, COOLDOWN_SECONDS)


def cooldown_key(interaction: discord.Interaction):
    return interaction.channel_id


class OddsBot(discord.Client):
    def __init__(self):
        # Slash commands only: no privileged intents, no message content.
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        log.info("Slash commands synced.")


bot = OddsBot()


async def _fetch_odds(sport: str, markets: str):
    return await asyncio.to_thread(
        oddscore.fetch_odds, sport, markets, PARLAY_API_KEY, CACHE_SECONDS)


async def _reply_events(interaction: discord.Interaction, sport: str,
                        query: str, markets: str, builder):
    try:
        events, notice = await _fetch_odds(sport, markets)
    except oddscore.ApiError as e:
        await interaction.followup.send(
            embed=to_embed(oddscore.build_error_embed(str(e))))
        return
    hits = oddscore.match_events(events, query)[:oddscore.MAX_EVENTS_SHOWN]
    if not hits:
        msg = "No upcoming %s event matched %r." % (sport, query)
        if not PARLAY_API_KEY:
            msg += (" Keyless demo mode only sees the first 5 events per "
                    "sport. Free key: %s" % oddscore.SIGNUP_URL)
        await interaction.followup.send(
            embed=to_embed(oddscore.build_error_embed(msg)))
        return
    await interaction.followup.send(
        embeds=[to_embed(builder(ev, notice)) for ev in hits])


@bot.tree.command(name="odds", description="Moneyline snapshot across top sportsbooks")
@app_commands.describe(query="Team or matchup, e.g. 'chiefs' or 'chiefs vs bills'",
                       sport="Sport (default: NFL)")
@app_commands.choices(sport=SPORT_CHOICES)
@app_commands.checks.dynamic_cooldown(channel_cooldown, key=cooldown_key)
async def odds(interaction: discord.Interaction, query: str,
               sport: Optional[app_commands.Choice[str]] = None):
    await interaction.response.defer()
    sport_key = sport.value if sport else DEFAULT_SPORT
    await _reply_events(interaction, sport_key, query, "h2h",
                        oddscore.build_odds_embed)


@bot.tree.command(name="line", description="Spread and total across top sportsbooks")
@app_commands.describe(query="Team or matchup, e.g. 'chiefs' or 'chiefs vs bills'",
                       sport="Sport (default: NFL)")
@app_commands.choices(sport=SPORT_CHOICES)
@app_commands.checks.dynamic_cooldown(channel_cooldown, key=cooldown_key)
async def line(interaction: discord.Interaction, query: str,
               sport: Optional[app_commands.Choice[str]] = None):
    await interaction.response.defer()
    sport_key = sport.value if sport else DEFAULT_SPORT
    await _reply_events(interaction, sport_key, query, "spreads,totals",
                        oddscore.build_line_embed)


@bot.tree.command(name="moves", description="Biggest moneyline moves (sharp-anchor view)")
@app_commands.describe(sport="Optional sport filter",
                       window_minutes="Lookback window in minutes (5 to 360)")
@app_commands.choices(sport=SPORT_CHOICES)
@app_commands.checks.dynamic_cooldown(channel_cooldown, key=cooldown_key)
async def moves(interaction: discord.Interaction,
                sport: Optional[app_commands.Choice[str]] = None,
                window_minutes: app_commands.Range[int, 5, 360] = 60):
    await interaction.response.defer()
    sport_key = sport.value if sport else None
    try:
        movers = await asyncio.to_thread(
            oddscore.fetch_movers, sport_key, window_minutes, 5)
    except oddscore.ApiError as e:
        # Degrade gracefully: movers is a public endpoint today, but if
        # it ever errors or moves behind a tier, say so plainly.
        await interaction.followup.send(
            embed=to_embed(oddscore.build_error_embed(str(e))))
        return
    await interaction.followup.send(
        embed=to_embed(oddscore.build_moves_embed(movers, sport_key, window_minutes)))


@bot.tree.command(name="parlaycheck",
                  description="Combined price of comma-separated American odds")
@app_commands.describe(prices="Comma-separated American prices, e.g. -110, -110, +150",
                       stake="Stake for the payout line (default 100)")
async def parlaycheck(interaction: discord.Interaction, prices: str,
                      stake: app_commands.Range[float, 0.01, 1000000.0] = 100.0):
    # Pure math, no API call, no cooldown needed.
    try:
        parsed = oddscore.parse_american_prices(prices)
        payload = oddscore.build_parlaycheck_embed(parsed, stake=stake)
    except ValueError as e:
        await interaction.response.send_message(
            embed=to_embed(oddscore.build_error_embed(str(e))), ephemeral=True)
        return
    await interaction.response.send_message(embed=to_embed(payload))


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction,
                               error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            "Easy there: this channel can run one odds command every %d "
            "seconds so the server owner's API credits last. Try again in "
            "%.0fs." % (int(COOLDOWN_SECONDS), error.retry_after),
            ephemeral=True)
        return
    log.exception("Command error", exc_info=error)
    msg = "Something went wrong on my end. Try again in a minute."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


def main():
    if not DISCORD_TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. See the README for setup, or use the "
            "no-token dry run: python3 oddscore.py odds 'chiefs'")
    if not PARLAY_API_KEY:
        log.warning(
            "PARLAY_API_KEY is not set: running in keyless demo mode "
            "(moneylines only, 6 sports, first 5 events). Get a free key "
            "with 1,000 credits/month at %s", oddscore.SIGNUP_URL)
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
