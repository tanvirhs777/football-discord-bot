import discord
from discord import app_commands
import aiohttp
import os
import asyncio
from datetime import datetime, timedelta
from dateutil import tz

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"

BD_TZ = tz.gettz("Asia/Dhaka")

HEADERS = {
    "x-apisports-key": API_KEY
}

# ================= BOT =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ================= CACHE (ANTI-SPAM) =================
last_scores = {}  # fixture_id -> (home, away)

# ================= HELPERS =================
def bd_time(utc_str):
    utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return utc.astimezone(BD_TZ).strftime("%d %b %I:%M %p")

async def api_get(endpoint, params=None):
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(f"{BASE_URL}/{endpoint}", params=params) as r:
            if r.status != 200:
                raise Exception("API Error")
            return await r.json()

def score_changed(fid, h, a):
    old = last_scores.get(fid)
    last_scores[fid] = (h, a)
    return old is not None and old != (h, a)

# ================= EVENTS =================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")

# ================= COMMANDS =================

@tree.command(name="live", description="Show live football matches")
async def live(i: discord.Interaction):
    await i.response.defer()
    try:
        data = await api_get("fixtures", {"live": "all"})
        fixtures = data["response"]

        if not fixtures:
            return await i.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")

        embed = discord.Embed(title="🔴 Live Matches", color=0xff0000)

        for f in fixtures[:10]:
            h = f["teams"]["home"]["name"]
            a = f["teams"]["away"]["name"]
            hs = f["goals"]["home"]
            as_ = f["goals"]["away"]
            minute = f["fixture"]["status"]["elapsed"]

            embed.add_field(
                name=f"{h} vs {a}",
                value=f"⚽ {hs} - {as_} | ⏱ {minute}'",
                inline=False
            )

        await i.followup.send(embed=embed)

    except:
        await i.followup.send("❌ Live matches আনতে সমস্যা হয়েছে")

@tree.command(name="upcoming", description="Today & tomorrow matches")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    try:
        today = datetime.utcnow().date()
        tomorrow = today + timedelta(days=1)

        data = await api_get("fixtures", {
            "from": today.isoformat(),
            "to": tomorrow.isoformat()
        })

        fixtures = data["response"]

        if not fixtures:
            return await i.followup.send("ℹ️ আজ/কাল কোনো ম্যাচ নেই")

        embed = discord.Embed(title="📅 Upcoming Matches", color=0x3498db)

        for f in fixtures[:10]:
            h = f["teams"]["home"]["name"]
            a = f["teams"]["away"]["name"]
            time = bd_time(f["fixture"]["date"])

            embed.add_field(
                name=f"{h} vs {a}",
                value=f"🕒 {time}",
                inline=False
            )

        await i.followup.send(embed=embed)

    except:
        await i.followup.send("❌ Upcoming matches আনতে সমস্যা হয়েছে")

@tree.command(name="league", description="Matches by league")
@app_commands.describe(name="league name (epl, laliga, ucl etc)")
async def league(i: discord.Interaction, name: str):
    await i.response.defer()
    try:
        data = await api_get("leagues", {"search": name})
        league_id = data["response"][0]["league"]["id"]

        data = await api_get("fixtures", {"league": league_id, "season": 2024})
        fixtures = data["response"][:10]

        embed = discord.Embed(title=f"🏆 {name.upper()}", color=0x9b59b6)

        for f in fixtures:
            h = f["teams"]["home"]["name"]
            a = f["teams"]["away"]["name"]
            time = bd_time(f["fixture"]["date"])
            embed.add_field(name=f"{h} vs {a}", value=time, inline=False)

        await i.followup.send(embed=embed)

    except:
        await i.followup.send("❌ League data আনতে সমস্যা হয়েছে")

@tree.command(name="team", description="Matches by team")
@app_commands.describe(name="team name")
async def team(i: discord.Interaction, name: str):
    await i.response.defer()
    try:
        data = await api_get("teams", {"search": name})
        team_id = data["response"][0]["team"]["id"]

        data = await api_get("fixtures", {"team": team_id, "season": 2024})
        fixtures = data["response"][:10]

        embed = discord.Embed(title=f"👕 {name.title()}", color=0x2ecc71)

        for f in fixtures:
            h = f["teams"]["home"]["name"]
            a = f["teams"]["away"]["name"]
            time = bd_time(f["fixture"]["date"])
            embed.add_field(name=f"{h} vs {a}", value=time, inline=False)

        await i.followup.send(embed=embed)

    except:
        await i.followup.send("❌ Team data আনতে সমস্যা হয়েছে")

# ================= RUN =================
client.run(DISCORD_TOKEN)
