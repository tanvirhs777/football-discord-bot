import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import os
import asyncio
from datetime import datetime
import pytz

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("SPORTSAPI_KEY")
BASE_URL = "https://api.sportsapipro.com/v1/football"
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Asia/Dhaka"))

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json"
}

# ================= BOT CLASS =================
class FootballBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.session = None
        self.last_goals = {}

    async def setup_hook(self):
        # Initialize persistent session
        self.session = aiohttp.ClientSession(headers=HEADERS)
        self.goal_monitor.start()

    async def on_ready(self):
        await self.tree.sync()
        print(f"✅ Logged in as {self.user}")

    async def api_get(self, endpoint):
        try:
            async with self.session.get(f"{BASE_URL}{endpoint}") as r:
                if r.status != 200:
                    print(f"DEBUG: API Status {r.status} for {endpoint}")
                    return None
                return await r.json()
        except Exception as e:
            print(f"DEBUG: Connection Error: {e}")
            return None

    def parse_matches(self, data):
        if not data or "data" not in data:
            return []
        
        parsed = []
        for m in data["data"]:
            try:
                # SportsAPI Pro v1 uses home_team/away_team and scores objects
                parsed.append({
                    "id": str(m.get("id")),
                    "home": m.get("home_team", {}).get("name", "Unknown"),
                    "away": m.get("away_team", {}).get("name", "Unknown"),
                    "hs": m.get("scores", {}).get("home_score", 0),
                    "as": m.get("scores", {}).get("away_score", 0),
                    "minute": m.get("time", {}).get("minute", 0),
                    "status": m.get("status", "NS"),
                    "start": m.get("starting_at")
                })
            except Exception as e:
                print(f"DEBUG: Parse error: {e}")
                continue
        return parsed

    @tasks.loop(seconds=60)
    async def goal_monitor(self):
        data = await self.api_get("/livescores")
        matches = self.parse_matches(data)
        if not matches: return

        for guild in self.guilds:
            channel = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
            if not channel: continue

            for m in matches:
                mid = m["id"]
                score_str = f"{m['hs']}-{m['as']}"
                
                if mid in self.last_goals and self.last_goals[mid] != score_str:
                    self.last_goals[mid] = score_str
                    await channel.send(f"⚽ **GOAL!**\n**{m['home']} {m['hs']} - {m['as']} {m['away']}**\n⏱ {m['minute']}'")
                else:
                    self.last_goals[mid] = score_str

client = FootballBot()

# ================= UTILS =================
def fmt_time(utc):
    if not utc: return "TBD"
    dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
    return dt.astimezone(TIMEZONE).strftime("%d %b %I:%M %p")

# ================= COMMANDS =================

@client.tree.command(name="live", description="Check live football scores")
async def live(i: discord.Interaction):
    await i.response.defer() # Prevents "Application did not respond"
    data = await client.api_get("/livescores")
    matches = client.parse_matches(data)
    
    if not matches:
        return await i.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")

    e = discord.Embed(title="🔴 Live Matches", color=0xff0000)
    for m in matches:
        e.add_field(
            name=f"{m['home']} vs {m['away']}",
            value=f"**{m['hs']} - {m['as']}** | ⏱ {m['minute']}'",
            inline=False
        )
    await i.followup.send(embed=e)

@client.tree.command(name="upcoming", description="Matches for today and tomorrow")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    # SportsAPI Pro filter for today/tomorrow
    data = await client.api_get("/fixtures?date=today,tomorrow")
    matches = client.parse_matches(data)
    
    if not matches:
        return await i.followup.send("ℹ️ আজ/কাল কোনো ম্যাচ নেই")

    e = discord.Embed(title="📅 Upcoming Matches", color=0x3498db)
    for m in matches:
        e.add_field(
            name=f"{m['home']} vs {m['away']}",
            value=f"🕒 {fmt_time(m['start'])}",
            inline=False
        )
    await i.followup.send(embed=e)

# ================= RUN =================
client.run(DISCORD_TOKEN)
