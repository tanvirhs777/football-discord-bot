import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import os
from datetime import datetime
import pytz

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
BD_TZ = pytz.timezone("Asia/Dhaka")

HEADERS = {
    "x-apisports-key": API_KEY
}

# ================= BOT SETUP =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

session: aiohttp.ClientSession | None = None

# Prevent goal spam
last_scores = {}

# ================= UTIL =================
def bd_time(utc_str):
    utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return utc.astimezone(BD_TZ).strftime("%d %b %I:%M %p")

async def api_get(endpoint, params=None):
    async with session.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params) as r:
        return await r.json()

# ================= EVENTS =================
@client.event
async def on_ready():
    global session
    session = aiohttp.ClientSession()
    await tree.sync()
    match_monitor.start()
    print(f"✅ Logged in as {client.user}")

# ================= COMMANDS =================

@tree.command(name="ping")
async def ping(i: discord.Interaction):
    await i.response.send_message("🏓 Pong!")

@tree.command(name="live", description="Show all live matches")
async def live(i: discord.Interaction):
    await i.response.defer()
    data = await api_get("fixtures", {"live": "all"})

    if not data["response"]:
        await i.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")
        return

    embed = discord.Embed(title="🔴 Live Matches", color=discord.Color.red())

    for m in data["response"][:10]:
        f = m["fixture"]
        t = m["teams"]
        g = m["goals"]
        embed.add_field(
            name=f"{t['home']['name']} vs {t['away']['name']}",
            value=f"**{g['home']} - {g['away']}** | ⏱ {f['status']['elapsed']}'",
            inline=False
        )

    await i.followup.send(embed=embed)

@tree.command(name="upcoming", description="Today & tomorrow matches")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    data = await api_get("fixtures", {"date": today})

    if not data["response"]:
        await i.followup.send("ℹ️ আজ/কাল কোনো ম্যাচ নেই")
        return

    embed = discord.Embed(title="📅 Upcoming Matches", color=discord.Color.blue())

    for m in data["response"][:10]:
        f = m["fixture"]
        t = m["teams"]
        embed.add_field(
            name=f"{t['home']['name']} vs {t['away']['name']}",
            value=f"🕒 {bd_time(f['date'])}",
            inline=False
        )

    await i.followup.send(embed=embed)

@tree.command(name="league", description="Matches by league")
@app_commands.describe(name="League name (epl, laliga, ucl etc)")
async def league(i: discord.Interaction, name: str):
    await i.response.defer()
    leagues = await api_get("leagues", {"search": name})

    if not leagues["response"]:
        await i.followup.send("❌ League পাওয়া যায়নি")
        return

    league_id = leagues["response"][0]["league"]["id"]
    data = await api_get("fixtures", {"league": league_id, "season": datetime.utcnow().year})

    if not data["response"]:
        await i.followup.send("❌ কোনো ম্যাচ নেই")
        return

    embed = discord.Embed(title=f"🏆 {name.upper()}", color=discord.Color.purple())

    for m in data["response"][:10]:
        t = m["teams"]
        g = m["goals"]
        embed.add_field(
            name=f"{t['home']['name']} vs {t['away']['name']}",
            value=f"{g['home']} - {g['away']}",
            inline=False
        )

    await i.followup.send(embed=embed)

@tree.command(name="team", description="Matches by team name")
@app_commands.describe(name="Team name (Arsenal, Barcelona etc)")
async def team(i: discord.Interaction, name: str):
    await i.response.defer()
    teams = await api_get("teams", {"search": name})

    if not teams["response"]:
        await i.followup.send("❌ Team পাওয়া যায়নি")
        return

    team_id = teams["response"][0]["team"]["id"]
    data = await api_get("fixtures", {"team": team_id, "season": datetime.utcnow().year})

    if not data["response"]:
        await i.followup.send("❌ কোনো ম্যাচ নেই")
        return

    embed = discord.Embed(title=f"⚽ {name}", color=discord.Color.green())

    for m in data["response"][:10]:
        t = m["teams"]
        g = m["goals"]
        embed.add_field(
            name=f"{t['home']['name']} vs {t['away']['name']}",
            value=f"{g['home']} - {g['away']}",
            inline=False
        )

    await i.followup.send(embed=embed)

# ================= AUTO GOAL UPDATES =================
@tasks.loop(seconds=60)
async def match_monitor():
    data = await api_get("fixtures", {"live": "all"})
    if not data["response"]:
        return

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

    for m in data["response"]:
        f = m["fixture"]
        t = m["teams"]
        g = m["goals"]

        key = f["id"]
        score = f"{g['home']}-{g['away']}"

        if last_scores.get(key) != score:
            last_scores[key] = score
            embed = discord.Embed(
                title="⚽ GOAL!",
                description=f"**{t['home']['name']} {score} {t['away']['name']}**",
                color=discord.Color.green()
            )
            embed.add_field(name="Time", value=f"{f['status']['elapsed']}'")
            await channel.send(embed=embed)

# ================= RUN =================
client.run(DISCORD_TOKEN)
