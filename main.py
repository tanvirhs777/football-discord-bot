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
# Ensure there is NO trailing slash here
BASE_URL = "https://api.sportsapipro.com/v1/football"
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Asia/Dhaka"))

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json"
}

# Spam control
LAST_GOALS = {}

# ================= BOT CLASS =================
class FootballBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.session = None

    async def setup_hook(self):
        # Initialize the session once when the bot starts
        self.session = aiohttp.ClientSession(headers=HEADERS)
        self.goal_monitor.start()

    async def on_ready(self):
        await self.tree.sync()
        print(f"✅ {self.user} is online")

    # Move the monitor inside the class for better session access
    @tasks.loop(seconds=60)
    async def goal_monitor(self):
        data = await self.api_get("/livescores")
        if not data: return

        matches = self.parse_matches(data)
        # Broadcast logic: you can refine this to a specific channel ID
        for guild in self.guilds:
            channel = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
            if not channel: continue

            for m in matches:
                key = m["id"]
                score = f"{m['hs']}-{m['as']}"
                
                if LAST_GOALS.get(key) and LAST_GOALS.get(key) != score:
                    LAST_GOALS[key] = score
                    await channel.send(f"⚽ **GOAL!**\n**{m['home']} {m['hs']} - {m['as']} {m['away']}**\n⏱ {m['minute']}'")
                elif not LAST_GOALS.get(key):
                    LAST_GOALS[key] = score

    async def api_get(self, endpoint):
        try:
            async with self.session.get(f"{BASE_URL}{endpoint}") as r:
                if r.status != 200:
                    print(f"API Error: {r.status}")
                    return None
                return await r.json()
        except Exception as e:
            print(f"Connection Error: {e}")
            return None

    def parse_matches(self, data):
        # Most SportsAPIs wrap their response in a 'data' or 'items' key
        items = data.get("data", []) if isinstance(data, dict) else []
        parsed = []
        for m in items:
            try:
                parsed.append({
                    "id": str(m.get("id")),
                    # Handling different possible key names for team names
                    "home": m.get("home_team", {}).get("name") or m.get("home", {}).get("name") or "Unknown",
                    "away": m.get("away_team", {}).get("name") or m.get("away", {}).get("name") or "Unknown",
                    "hs": m.get("scores", {}).get("home_score", 0),
                    "as": m.get("scores", {}).get("away_score", 0),
                    "minute": m.get("time", {}).get("minute", 0),
                    "state": m.get("status", "NS"),
                    "start": m.get("starting_at")
                })
            except Exception as e:
                print(f"Parsing error for match: {e}")
                continue
        return parsed

client = FootballBot()

# ================= COMMANDS =================

@client.tree.command(name="live", description="সব লাইভ ম্যাচের আপডেট")
async def live(i: discord.Interaction):
    await i.response.defer()
    data = await client.api_get("/livescores")
    matches = client.parse_matches(data)
    
    if not matches:
        await i.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")
        return

    e = discord.Embed(title="🔴 Live Matches", color=0xff0000)
    for m in matches:
        e.add_field(
            name=f"{m['home']} vs {m['away']}",
            value=f"Score: **{m['hs']} - {m['as']}** | ⏱ {m['minute']}'",
            inline=False
        )
    await i.followup.send(embed=e)

# Simple helper for time formatting
def fmt_time(utc):
    if not utc: return "TBD"
    dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
    return dt.astimezone(TIMEZONE).strftime("%d %b %I:%M %p")

@client.tree.command(name="upcoming", description="আজ ও আগামীকালের ম্যাচ")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    # Check if your API uses /fixtures or /matches
    data = await client.api_get("/fixtures?date=today,tomorrow")
    matches = client.parse_matches(data)
    
    if not matches:
        await i.followup.send("ℹ️ আজ/কাল কোনো ম্যাচ নেই")
        return

    e = discord.Embed(title="📅 Upcoming Matches", color=0x3498db)
    for m in matches:
        e.add_field(
            name=f"{m['home']} vs {m['away']}",
            value=f"🕒 {fmt_time(m['start'])}",
            inline=False
        )
    await i.followup.send(embed=e)

# ================= RUN =================
if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
