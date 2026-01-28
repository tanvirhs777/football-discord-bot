# main.py
# Discord Football Bot - FINAL PRODUCTION VERSION
# Features:
# - /live
# - /upcoming (today + tomorrow)
# - /league <name>
# - /team <name>
# - BD timezone
# - Goal spam control
# - Full-time spam control
# - Railway ready

import discord
from discord import app_commands
from discord.ext import tasks
import os
import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
import pytz

# =========================
# CONFIG
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPORTS_API_KEY = os.getenv("SPORTS_API_KEY")

API_BASE = "https://sportsapipro.com/api/football"

BD_TZ = pytz.timezone("Asia/Dhaka")

# =========================
# LOGGING
# =========================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("football-bot")

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# =========================
# STATE (SPAM CONTROL)
# =========================

last_scores = {}      # match_id -> (home, away)
announced_ft = set() # match_id

# =========================
# HTTP CLIENT
# =========================

async def api_get(endpoint: str, params: dict = None):
    headers = {
        "Authorization": f"Bearer {SPORTS_API_KEY}"
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(f"{API_BASE}/{endpoint}", params=params) as r:
            if r.status != 200:
                raise Exception(f"API error {r.status}")
            return await r.json()

# =========================
# UTIL
# =========================

def bd_time(utc_str: str):
    utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return utc.astimezone(BD_TZ).strftime("%d %b %I:%M %p")

def match_id(m):
    return str(m["id"])

# =========================
# EVENTS
# =========================

@client.event
async def on_ready():
    for g in client.guilds:
        tree.copy_global_to(guild=g)
        await tree.sync(guild=g)
    match_monitor.start()
    log.info("Bot ready")

# =========================
# COMMANDS
# =========================

@tree.command(name="ping")
async def ping(i: discord.Interaction):
    await i.response.send_message("🏓 Pong!")

@tree.command(name="live")
async def live(i: discord.Interaction):
    await i.response.defer()
    try:
        data = await api_get("matches/live")
        matches = data.get("matches", [])
        if not matches:
            await i.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")
            return

        e = discord.Embed(title="🔴 Live Matches", color=discord.Color.red())
        for m in matches:
            e.add_field(
                name=m["league"],
                value=f"**{m['home']} {m['score']['home']} - {m['score']['away']} {m['away']}**\n⏱ {m['minute']}'",
                inline=False
            )
        await i.followup.send(embed=e)
    except:
        await i.followup.send("❌ Live matches আনতে সমস্যা হয়েছে")

@tree.command(name="upcoming")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    try:
        today = datetime.utcnow().date()
        tomorrow = today + timedelta(days=1)

        data = await api_get(
            "matches",
            {
                "from": today.isoformat(),
                "to": tomorrow.isoformat()
            }
        )

        matches = data.get("matches", [])
        if not matches:
            await i.followup.send("ℹ️ আজ/কাল কোনো ম্যাচ নেই")
            return

        e = discord.Embed(title="📅 Upcoming Matches", color=discord.Color.blue())
        for m in matches:
            e.add_field(
                name=m["league"],
                value=f"**{m['home']} vs {m['away']}**\n🕒 {bd_time(m['utc_date'])}",
                inline=False
            )
        await i.followup.send(embed=e)
    except:
        await i.followup.send("❌ Upcoming matches আনতে সমস্যা হয়েছে")

@tree.command(name="league")
@app_commands.describe(name="epl / laliga / ucl etc")
async def league(i: discord.Interaction, name: str):
    await i.response.defer()
    try:
        data = await api_get("matches", {"league": name})
        matches = data.get("matches", [])
        if not matches:
            await i.followup.send("ℹ️ এই league এ কোনো ম্যাচ নেই")
            return

        e = discord.Embed(title=f"🏆 {name.upper()}", color=discord.Color.gold())
        for m in matches:
            e.add_field(
                name=m["status"],
                value=f"{m['home']} {m['score']['home']} - {m['score']['away']} {m['away']}",
                inline=False
            )
        await i.followup.send(embed=e)
    except:
        await i.followup.send("❌ League data আনতে সমস্যা হয়েছে")

@tree.command(name="team")
@app_commands.describe(name="team name")
async def team(i: discord.Interaction, name: str):
    await i.response.defer()
    try:
        data = await api_get("matches", {"team": name})
        matches = data.get("matches", [])
        if not matches:
            await i.followup.send("ℹ️ এই দলের কোনো ম্যাচ নেই")
            return

        e = discord.Embed(title=f"👕 {name}", color=discord.Color.green())
        for m in matches:
            e.add_field(
                name=m["league"],
                value=f"{m['home']} {m['score']['home']} - {m['score']['away']} {m['away']}",
                inline=False
            )
        await i.followup.send(embed=e)
    except:
        await i.followup.send("❌ Team data আনতে সমস্যা হয়েছে")

# =========================
# BACKGROUND GOAL MONITOR
# =========================

@tasks.loop(seconds=60)
async def match_monitor():
    try:
        data = await api_get("matches/live")
        matches = data.get("matches", [])

        channel = None
        for g in client.guilds:
            for c in g.text_channels:
                if c.permissions_for(g.me).send_messages:
                    channel = c
                    break
            if channel:
                break

        if not channel:
            return

        for m in matches:
            mid = match_id(m)
            score = (m["score"]["home"], m["score"]["away"])

            if mid not in last_scores:
                last_scores[mid] = score
                continue

            if score != last_scores[mid]:
                last_scores[mid] = score
                await channel.send(
                    embed=discord.Embed(
                        title="⚽ GOAL!",
                        description=f"**{m['home']} {score[0]} - {score[1]} {m['away']}**",
                        color=discord.Color.green()
                    )
                )

            if m["status"] == "FT" and mid not in announced_ft:
                announced_ft.add(mid)
                await channel.send(
                    embed=discord.Embed(
                        title="⚪ FULL TIME",
                        description=f"**{m['home']} {score[0]} - {score[1]} {m['away']}**",
                        color=discord.Color.blue()
                    )
                )
    except:
        pass

# =========================
# RUN
# =========================

if __name__ == "__main__":
    if not DISCORD_TOKEN or not SPORTS_API_KEY:
        raise RuntimeError("Missing environment variables")

    client.run(DISCORD_TOKEN)
