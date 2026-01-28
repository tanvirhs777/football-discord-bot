import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import os
import asyncio
from datetime import datetime, timedelta
from dateutil import tz

# ===================== CONFIG =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("API_FOOTBALL_KEY")

API_BASE = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

BD_TZ = tz.gettz("Asia/Dhaka")

# ===================== BOT =====================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ===================== CACHE (ANTI-SPAM) =====================
last_scores = {}  # match_id -> (home, away)
announced_ft = set()

# ===================== API =====================
async def api_get(endpoint, params=None):
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(f"{API_BASE}/{endpoint}", params=params) as r:
            if r.status != 200:
                return []
            data = await r.json()
            return data.get("response", [])

# ===================== HELPERS =====================
def bd_time(utc_str):
    utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return utc.astimezone(BD_TZ).strftime("%d %b %I:%M %p")

def match_embed(match, title, color):
    teams = match["teams"]
    goals = match["goals"]
    fixture = match["fixture"]
    league = match["league"]

    desc = f"**{teams['home']['name']} {goals['home']} - {goals['away']} {teams['away']['name']}**"

    embed = discord.Embed(title=title, description=desc, color=color)
    embed.add_field(name="League", value=league["name"], inline=True)
    embed.add_field(name="Time", value=bd_time(fixture["date"]), inline=True)
    return embed

# ===================== COMMANDS =====================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot online as {client.user}")
    live_monitor.start()

@tree.command(name="ping")
async def ping(i: discord.Interaction):
    await i.response.send_message("🏓 Pong!")

@tree.command(name="live", description="সব লাইভ ম্যাচ")
async def live(i: discord.Interaction):
    await i.response.defer()
    matches = await api_get("fixtures", {"live": "all"})

    if not matches:
        await i.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")
        return

    embed = discord.Embed(title="🔴 Live Matches", color=discord.Color.red())
    for m in matches[:10]:
        t = m["teams"]
        g = m["goals"]
        embed.add_field(
            name=m["league"]["name"],
            value=f"{t['home']['name']} {g['home']} - {g['away']} {t['away']['name']}",
            inline=False
        )
    await i.followup.send(embed=embed)

@tree.command(name="upcoming", description="আজ ও কালকের ম্যাচ")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)

    matches = await api_get("fixtures", {
        "from": today.isoformat(),
        "to": tomorrow.isoformat()
    })

    if not matches:
        await i.followup.send("ℹ️ আজ/কাল কোনো ম্যাচ নেই")
        return

    embed = discord.Embed(title="📅 Upcoming Matches", color=discord.Color.blue())
    for m in matches[:10]:
        embed.add_field(
            name=m["league"]["name"],
            value=f"{m['teams']['home']['name']} vs {m['teams']['away']['name']} — {bd_time(m['fixture']['date'])}",
            inline=False
        )
    await i.followup.send(embed=embed)

@tree.command(name="league", description="লিগ অনুযায়ী ম্যাচ")
@app_commands.describe(name="epl / laliga / ucl")
async def league(i: discord.Interaction, name: str):
    await i.response.defer()
    leagues = {"epl": 39, "laliga": 140, "ucl": 2}
    lid = leagues.get(name.lower())
    if not lid:
        await i.followup.send("❌ লিগ পাওয়া যায়নি")
        return

    matches = await api_get("fixtures", {"league": lid, "season": datetime.utcnow().year})
    if not matches:
        await i.followup.send("ℹ️ কোনো ম্যাচ নেই")
        return

    embed = discord.Embed(title=f"🏆 {name.upper()}", color=discord.Color.green())
    for m in matches[:10]:
        embed.add_field(
            name=m["teams"]["home"]["name"],
            value=f"vs {m['teams']['away']['name']} — {bd_time(m['fixture']['date'])}",
            inline=False
        )
    await i.followup.send(embed=embed)

@tree.command(name="team", description="নির্দিষ্ট দলের ম্যাচ")
async def team(i: discord.Interaction, name: str):
    await i.response.defer()
    teams = await api_get("teams", {"search": name})
    if not teams:
        await i.followup.send("❌ টিম পাওয়া যায়নি")
        return

    team_id = teams[0]["team"]["id"]
    matches = await api_get("fixtures", {"team": team_id, "next": 5})

    embed = discord.Embed(title=f"⚽ {teams[0]['team']['name']}", color=discord.Color.gold())
    for m in matches:
        embed.add_field(
            name=m["league"]["name"],
            value=f"{m['teams']['home']['name']} vs {m['teams']['away']['name']} — {bd_time(m['fixture']['date'])}",
            inline=False
        )
    await i.followup.send(embed=embed)

# ===================== LIVE GOAL MONITOR =====================
@tasks.loop(seconds=60)
async def live_monitor():
    matches = await api_get("fixtures", {"live": "all"})
    if not matches:
        return

    channel = None
    for g in client.guilds:
        for c in g.text_channels:
            if c.permissions_for(g.me).send_messages:
                channel = c
                break
        if channel:
            break

    for m in matches:
        mid = m["fixture"]["id"]
        goals = (m["goals"]["home"], m["goals"]["away"])

        if mid not in last_scores:
            last_scores[mid] = goals
            continue

        if goals != last_scores[mid]:
            embed = match_embed(m, "⚽ GOAL!", discord.Color.green())
            await channel.send(embed=embed)
            last_scores[mid] = goals

        if m["fixture"]["status"]["short"] == "FT" and mid not in announced_ft:
            embed = match_embed(m, "⚪ FULL TIME", discord.Color.blue())
            await channel.send(embed=embed)
            announced_ft.add(mid)

# ===================== RUN =====================
client.run(DISCORD_TOKEN)
