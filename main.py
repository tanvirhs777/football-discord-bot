import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict
import asyncio

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_BASE_URL = "https://v3.football.api-sports.io"

LEAGUE_MAP = {
    "epl": 39,
    "premier league": 39,
    "laliga": 140,
    "la liga": 140,
    "serie a": 135,
    "bundesliga": 78,
    "ligue 1": 61,
    "ucl": 2,
    "champions league": 2,
    "europa": 3,
    "europa league": 3,
    "world cup": 1,
}

BD_TZ = ZoneInfo("Asia/Dhaka")

intents = discord.Intents.default()
intents.message_content = False

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

announced_goals: Dict[int, set] = {}


async def api_request(session: aiohttp.ClientSession, endpoint: str, params: dict = None) -> dict:
    headers = {
        "x-apisports-key": API_FOOTBALL_KEY,
        "x-rapidapi-key": API_FOOTBALL_KEY,
    }
    url = f"{API_BASE_URL}/{endpoint}"
    try:
        async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status == 200:
                return await response.json()
            return {"response": []}
    except Exception as e:
        print(f"API Error: {e}")
        return {"response": []}


def format_time_bd(utc_time_str: str) -> str:
    try:
        utc_time = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00"))
        bd_time = utc_time.astimezone(BD_TZ)
        return bd_time.strftime("%I:%M %p, %d %b")
    except:
        return "TBA"


def create_fixture_embed(fixture: dict, title: str) -> discord.Embed:
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    home_score = fixture["goals"]["home"]
    away_score = fixture["goals"]["away"]
    status = fixture["fixture"]["status"]["short"]
    elapsed = fixture["fixture"]["status"]["elapsed"]
    
    if status in ["1H", "2H", "HT", "ET", "BT", "P", "LIVE"]:
        score_text = f"⚽ {home_score or 0} - {away_score or 0}"
        if elapsed:
            score_text += f" ({elapsed}')"
        color = discord.Color.green()
    elif status == "NS":
        kick_off = format_time_bd(fixture["fixture"]["date"])
        score_text = f"🕐 {kick_off}"
        color = discord.Color.blue()
    elif status == "FT":
        score_text = f"✅ {home_score} - {away_score} (FT)"
        color = discord.Color.greyple()
    else:
        score_text = f"{home_score or 0} - {away_score or 0}"
        color = discord.Color.orange()
    
    embed = discord.Embed(title=title, color=color)
    embed.add_field(
        name=f"{home} vs {away}",
        value=score_text,
        inline=False
    )
    
    league_name = fixture["league"]["name"]
    embed.set_footer(text=f"{league_name} • ID: {fixture['fixture']['id']}")
    
    return embed


@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ {bot.user} is ready!")
    if not goal_tracker.is_running():
        goal_tracker.start()


@tree.command(name="live", description="Show currently live matches")
async def live_matches(interaction: discord.Interaction):
    await interaction.response.defer()
    
    async with aiohttp.ClientSession() as session:
        data = await api_request(session, "fixtures", {"live": "all"})
    
    fixtures = data.get("response", [])
    
    if not fixtures:
        embed = discord.Embed(
            title="⚽ Live Matches",
            description="No live matches at the moment.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
    embeds = []
    for fixture in fixtures[:10]:
        embed = create_fixture_embed(fixture, "⚽ LIVE MATCH")
        embeds.append(embed)
    
    await interaction.followup.send(embeds=embeds[:10])


@tree.command(name="upcoming", description="Show upcoming matches (today + tomorrow)")
async def upcoming_matches(interaction: discord.Interaction):
    await interaction.response.defer()
    
    today = datetime.now(BD_TZ).date()
    tomorrow = today + timedelta(days=1)
    
    async with aiohttp.ClientSession() as session:
        data_today = await api_request(session, "fixtures", {"date": str(today)})
        data_tomorrow = await api_request(session, "fixtures", {"date": str(tomorrow)})
    
    fixtures = data_today.get("response", []) + data_tomorrow.get("response", [])
    fixtures = [f for f in fixtures if f["fixture"]["status"]["short"] == "NS"]
    
    if not fixtures:
        embed = discord.Embed(
            title="📅 Upcoming Matches",
            description="No upcoming matches found.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
    fixtures = sorted(fixtures, key=lambda x: x["fixture"]["date"])[:10]
    
    embeds = []
    for fixture in fixtures:
        embed = create_fixture_embed(fixture, "📅 Upcoming Match")
        embeds.append(embed)
    
    await interaction.followup.send(embeds=embeds[:10])


@tree.command(name="league", description="Show matches from a specific league")
@app_commands.describe(league_name="League name (e.g., epl, laliga, ucl)")
async def league_matches(interaction: discord.Interaction, league_name: str):
    await interaction.response.defer()
    
    league_id = LEAGUE_MAP.get(league_name.lower())
    
    if not league_id:
        embed = discord.Embed(
            title="❌ League Not Found",
            description=f"Available leagues: {', '.join(LEAGUE_MAP.keys())}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
    today = datetime.now(BD_TZ).date()
    
    async with aiohttp.ClientSession() as session:
        data = await api_request(session, "fixtures", {
            "league": league_id,
            "date": str(today),
            "season": today.year
        })
    
    fixtures = data.get("response", [])
    
    if not fixtures:
        async with aiohttp.ClientSession() as session:
            data = await api_request(session, "fixtures", {
                "league": league_id,
                "next": 10
            })
        fixtures = data.get("response", [])
    
    if not fixtures:
        embed = discord.Embed(
            title=f"❌ No Matches Found",
            description=f"No matches found for {league_name}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
    embeds = []
    for fixture in fixtures[:10]:
        embed = create_fixture_embed(fixture, f"🏆 {league_name.upper()}")
        embeds.append(embed)
    
    await interaction.followup.send(embeds=embeds[:10])


@tree.command(name="team", description="Show fixtures for a specific team")
@app_commands.describe(team_name="Team name to search")
async def team_fixtures(interaction: discord.Interaction, team_name: str):
    await interaction.response.defer()
    
    async with aiohttp.ClientSession() as session:
        search_data = await api_request(session, "teams", {"search": team_name})
    
    teams = search_data.get("response", [])
    
    if not teams:
        embed = discord.Embed(
            title="❌ Team Not Found",
            description=f"No team found matching '{team_name}'",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
    team_id = teams[0]["team"]["id"]
    team_full_name = teams[0]["team"]["name"]
    
    async with aiohttp.ClientSession() as session:
        data = await api_request(session, "fixtures", {
            "team": team_id,
            "next": 10
        })
    
    fixtures = data.get("response", [])
    
    if not fixtures:
        embed = discord.Embed(
            title=f"❌ No Fixtures",
            description=f"No upcoming fixtures for {team_full_name}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
    embeds = []
    for fixture in fixtures[:10]:
        embed = create_fixture_embed(fixture, f"🎯 {team_full_name}")
        embeds.append(embed)
    
    await interaction.followup.send(embeds=embeds[:10])


@tasks.loop(minutes=2)
async def goal_tracker():
    try:
        async with aiohttp.ClientSession() as session:
            data = await api_request(session, "fixtures", {"live": "all"})
        
        fixtures = data.get("response", [])
        
        for fixture in fixtures:
            fixture_id = fixture["fixture"]["id"]
            home_goals = fixture["goals"]["home"] or 0
            away_goals = fixture["goals"]["away"] or 0
            total_goals = home_goals + away_goals
            
            if fixture_id not in announced_goals:
                announced_goals[fixture_id] = set()
            
            current_goals = announced_goals[fixture_id]
            
            if total_goals > len(current_goals):
                async with aiohttp.ClientSession() as session:
                    events_data = await api_request(session, "fixtures/events", {"fixture": fixture_id})
                
                events = events_data.get("response", [])
                goal_events = [e for e in events if e["type"] == "Goal" and e["detail"] != "Missed Penalty"]
                
                for event in goal_events:
                    event_key = f"{event['time']['elapsed']}_{event['team']['name']}_{event['player']['name']}"
                    
                    if event_key not in current_goals:
                        current_goals.add(event_key)
                        
                        home = fixture["teams"]["home"]["name"]
                        away = fixture["teams"]["away"]["name"]
                        scorer = event["player"]["name"]
                        minute = event["time"]["elapsed"]
                        team = event["team"]["name"]
                        
                        embed = discord.Embed(
                            title="⚽ GOAL!",
                            description=f"**{scorer}** scores for **{team}**!",
                            color=discord.Color.gold()
                        )
                        embed.add_field(
                            name="Match",
                            value=f"{home} {home_goals} - {away_goals} {away}",
                            inline=False
                        )
                        embed.add_field(name="Time", value=f"{minute}'", inline=True)
                        
                        for guild in bot.guilds:
                            for channel in guild.text_channels:
                                if channel.permissions_for(guild.me).send_messages:
                                    try:
                                        await channel.send(embed=embed)
                                        break
                                    except:
                                        continue
    except Exception as e:
        print(f"Goal tracker error: {e}")


@goal_tracker.before_loop
async def before_goal_tracker():
    await bot.wait_until_ready()


bot.run(DISCORD_TOKEN)
