import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import asyncio
import os
import logging
from datetime import datetime, timedelta, timezone

# =========================================================
# CONFIG
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPORTS_API_KEY = os.getenv("SPORTS_API_KEY")

API_BASE = "https://v1.football.sportsapipro.com"
HEADERS = {"x-api-key": SPORTS_API_KEY}

TARGET_TEAMS = ["Real Madrid", "Barcelona", "FC Barcelona"]

POLL_INTERVAL = 90  # seconds (safe for free plans)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("football-bot")

# =========================================================
# DISCORD SETUP
# =========================================================

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# =========================================================
# STATE
# =========================================================

previous_scores = {}      # match_id -> (home, away)
announced_ft = set()
session: aiohttp.ClientSession | None = None

# =========================================================
# HELPERS
# =========================================================

def is_target_match(home: str, away: str) -> bool:
    return any(t in home for t in TARGET_TEAMS) or any(t in away for t in TARGET_TEAMS)

def today_tomorrow_range():
    now = datetime.now(timezone.utc)
    return now.date(), (now + timedelta(days=1)).date()

async def api_get(endpoint: str, params: dict | None = None):
    global session
    if not session or session.closed:
        session = aiohttp.ClientSession(headers=HEADERS)

    async with session.get(f"{API_BASE}{endpoint}", params=params) as r:
        if r.status != 200:
            raise RuntimeError(f"API error {r.status}")
        return await r.json()

async def find_announce_channel():
    for guild in client.guilds:
        for ch in guild.text_channels:
            perms = ch.permissions_for(guild.me)
            if perms.send_messages and perms.embed_links:
                return ch
    return None

# =========================================================
# BOT READY
# =========================================================

@client.event
async def on_ready():
    log.info(f"Logged in as {client.user}")

    for guild in client.guilds:
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)

    match_monitor.start()
    log.info("Bot fully operational")

# =========================================================
# SLASH COMMANDS
# =========================================================

@tree.command(name="ping", description="Check bot status")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"🏓 Pong! `{round(client.latency*1000)}ms`"
    )

@tree.command(name="live", description="Show live matches (Real Madrid / Barcelona)")
async def live(interaction: discord.Interaction):
    await interaction.response.defer()

    data = await api_get("/games/current")
    games = data.get("data", [])

    live_games = []
    for g in games:
        home = g["home_team"]["name"]
        away = g["away_team"]["name"]
        if is_target_match(home, away):
            live_games.append(g)

    if not live_games:
        await interaction.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")
        return

    embed = discord.Embed(title="🔴 Live Matches", color=discord.Color.red())

    for g in live_games:
        embed.add_field(
            name=f'{g["league"]["name"]}',
            value=f'**{g["home_team"]["name"]} {g["scores"]["home"]} - '
                  f'{g["scores"]["away"]} {g["away_team"]["name"]}**',
            inline=False
        )

    await interaction.followup.send(embed=embed)

@tree.command(name="upcoming", description="আজ ও আগামীকালের ম্যাচ")
async def upcoming(interaction: discord.Interaction):
    await interaction.response.defer()

    today, tomorrow = today_tomorrow_range()

    data = await api_get(
        "/games/fixtures",
        {
            "dateFrom": today.isoformat(),
            "dateTo": tomorrow.isoformat(),
        }
    )

    fixtures = []
    for g in data.get("data", []):
        home = g["home_team"]["name"]
        away = g["away_team"]["name"]
        if is_target_match(home, away):
            fixtures.append(g)

    if not fixtures:
        await interaction.followup.send("ℹ️ আজ/কাল কোনো ম্যাচ নেই")
        return

    embed = discord.Embed(title="📅 Upcoming Matches", color=discord.Color.green())

    for g in fixtures:
        kick = g["starting_at"]
        embed.add_field(
            name=f'{g["home_team"]["name"]} vs {g["away_team"]["name"]}',
            value=f'🏆 {g["league"]["name"]}\n⏰ {kick}',
            inline=False
        )

    await interaction.followup.send(embed=embed)

# =========================================================
# BACKGROUND TASK (GOAL + FT)
# =========================================================

@tasks.loop(seconds=POLL_INTERVAL)
async def match_monitor():
    try:
        channel = await find_announce_channel()
        if not channel:
            return

        data = await api_get("/games/current")
        games = data.get("data", [])

        for g in games:
            home = g["home_team"]["name"]
            away = g["away_team"]["name"]

            if not is_target_match(home, away):
                continue

            match_id = g["id"]
            score = (g["scores"]["home"], g["scores"]["away"])

            if match_id in previous_scores:
                if score != previous_scores[match_id]:
                    embed = discord.Embed(
                        title="⚽ GOAL!",
                        description=f"**{home} {score[0]} - {score[1]} {away}**",
                        color=discord.Color.green()
                    )
                    await channel.send(embed=embed)

            previous_scores[match_id] = score

            if g["status"] == "finished" and match_id not in announced_ft:
                embed = discord.Embed(
                    title="⚪ FULL TIME",
                    description=f"**{home} {score[0]} - {score[1]} {away}**",
                    color=discord.Color.blue()
                )
                await channel.send(embed=embed)
                announced_ft.add(match_id)

    except Exception as e:
        log.error(f"Monitor error: {e}")

# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    if not DISCORD_TOKEN or not SPORTS_API_KEY:
        raise RuntimeError("DISCORD_TOKEN or SPORTS_API_KEY missing")

    client.run(DISCORD_TOKEN)
