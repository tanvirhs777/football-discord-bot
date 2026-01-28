# =========================
# Discord Football Bot
# SportsAPI Pro – Final
# =========================

import discord
from discord import app_commands
from discord.ext import tasks
import os
import aiohttp
import asyncio
from datetime import datetime, timedelta
import pytz

# =========================
# CONFIG
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPORTS_API_KEY = os.getenv("SPORTS_API_KEY")

API_BASE = "https://api.sportsapipro.com/v1/football"
BD_TZ = pytz.timezone("Asia/Dhaka")

HEADERS = {
    "Authorization": f"Bearer {SPORTS_API_KEY}",
    "Accept": "application/json"
}

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# =========================
# GLOBAL STATE (ANTI-SPAM)
# =========================

last_scores = {}      # match_id -> (home, away)
announced_ft = set()

# =========================
# UTILS
# =========================

def bd_time(utc_str: str) -> str:
    try:
        utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return utc.astimezone(BD_TZ).strftime("%d %b %I:%M %p")
    except:
        return "N/A"

async def api_get(endpoint: str, params: dict = None):
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(f"{API_BASE}/{endpoint}", params=params) as r:
            if r.status != 200:
                raise Exception(f"API Error {r.status}")
            return await r.json()

def parse_matches(data):
    matches = data.get("data", [])
    parsed = []

    for m in matches:
        parsed.append({
            "id": str(m["id"]),
            "league": m.get("league", {}).get("name", "Unknown"),
            "home": m["home_team"]["name"],
            "away": m["away_team"]["name"],
            "home_score": m["scores"]["home_score"],
            "away_score": m["scores"]["away_score"],
            "status": m["status"].upper(),
            "minute": m.get("time", 0),
            "start": m.get("starting_at")
        })
    return parsed

# =========================
# BOT EVENTS
# =========================

@client.event
async def on_ready():
    for g in client.guilds:
        tree.copy_global_to(guild=g)
        await tree.sync(guild=g)
    match_monitor.start()
    print("✅ Bot online & synced")

# =========================
# SLASH COMMANDS
# =========================

@tree.command(name="ping")
async def ping(i: discord.Interaction):
    await i.response.send_message("🏓 Pong! Bot is alive")

# ---------- LIVE ----------
@tree.command(name="live")
async def live(i: discord.Interaction):
    await i.response.defer()
    try:
        raw = await api_get("matches/live")
        matches = parse_matches(raw)

        if not matches:
            await i.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")
            return

        e = discord.Embed(title="🔴 Live Matches", color=discord.Color.red())
        for m in matches:
            e.add_field(
                name=m["league"],
                value=f"**{m['home']} {m['home_score']} - {m['away_score']} {m['away']}**\n⏱ {m['minute']}'",
                inline=False
            )
        await i.followup.send(embed=e)

    except Exception as ex:
        print(ex)
        await i.followup.send("❌ Live matches আনতে সমস্যা হয়েছে")

# ---------- UPCOMING ----------
@tree.command(name="upcoming")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    try:
        today = datetime.utcnow().date()
        tomorrow = today + timedelta(days=1)

        raw = await api_get("matches", {
            "from": today.isoformat(),
            "to": tomorrow.isoformat()
        })

        matches = parse_matches(raw)

        if not matches:
            await i.followup.send("ℹ️ আজ/কাল কোনো ম্যাচ নেই")
            return

        e = discord.Embed(title="📅 Upcoming Matches", color=discord.Color.blue())
        for m in matches:
            e.add_field(
                name=m["league"],
                value=f"**{m['home']} vs {m['away']}**\n🕒 {bd_time(m['start'])}",
                inline=False
            )
        await i.followup.send(embed=e)

    except Exception as ex:
        print(ex)
        await i.followup.send("❌ Upcoming matches আনতে সমস্যা হয়েছে")

# ---------- LEAGUE ----------
@tree.command(name="league")
async def league(i: discord.Interaction, name: str):
    await i.response.defer()
    try:
        raw = await api_get("matches", {"league": name})
        matches = parse_matches(raw)

        if not matches:
            await i.followup.send("ℹ️ এই league এ কোনো ম্যাচ নেই")
            return

        e = discord.Embed(title=f"🏆 {name.upper()}", color=discord.Color.green())
        for m in matches:
            e.add_field(
                name=m["league"],
                value=f"{m['home']} {m['home_score']} - {m['away_score']} {m['away']}",
                inline=False
            )
        await i.followup.send(embed=e)

    except Exception as ex:
        print(ex)
        await i.followup.send("❌ League data আনতে সমস্যা হয়েছে")

# ---------- TEAM ----------
@tree.command(name="team")
async def team(i: discord.Interaction, name: str):
    await i.response.defer()
    try:
        raw = await api_get("matches", {"team": name})
        matches = parse_matches(raw)

        if not matches:
            await i.followup.send("ℹ️ এই দলের কোনো ম্যাচ নেই")
            return

        e = discord.Embed(title=f"👕 {name}", color=discord.Color.orange())
        for m in matches:
            e.add_field(
                name=m["league"],
                value=f"{m['home']} {m['home_score']} - {m['away_score']} {m['away']}",
                inline=False
            )
        await i.followup.send(embed=e)

    except Exception as ex:
        print(ex)
        await i.followup.send("❌ Team data আনতে সমস্যা হয়েছে")

# =========================
# BACKGROUND GOAL MONITOR
# =========================

@tasks.loop(seconds=60)
async def match_monitor():
    try:
        raw = await api_get("matches/live")
        matches = parse_matches(raw)

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
            mid = m["id"]
            score = (m["home_score"], m["away_score"])

            if mid not in last_scores:
                last_scores[mid] = score
                continue

            if score != last_scores[mid]:
                last_scores[mid] = score

                e = discord.Embed(
                    title="⚽ GOAL!",
                    description=f"**{m['home']} {score[0]} - {score[1]} {m['away']}**",
                    color=discord.Color.green()
                )
                await channel.send(embed=e)

    except Exception as e:
        print("Monitor error:", e)

# =========================
# RUN
# =========================

if not DISCORD_TOKEN or not SPORTS_API_KEY:
    raise RuntimeError("❌ Missing ENV variables")

client.run(DISCORD_TOKEN)
