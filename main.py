import os
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List

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

team_cache: Dict[str, List[dict]] = {}


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


async def team_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    if len(current) < 2:
        return [
            app_commands.Choice(name="Type at least 2 characters...", value="none")
        ]
    
    cache_key = current.lower()
    if cache_key in team_cache:
        teams = team_cache[cache_key]
    else:
        async with aiohttp.ClientSession() as session:
            data = await api_request(session, "teams", {"search": current})
        teams = data.get("response", [])
        team_cache[cache_key] = teams
    
    if not teams:
        return [
            app_commands.Choice(name="No teams found", value="none")
        ]
    
    choices = []
    for team in teams[:25]:
        team_name = team["team"]["name"]
        choices.append(app_commands.Choice(name=team_name, value=team_name))
    
    return choices


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
    match_date = format_time_bd(fixture["fixture"]["date"])
    embed.set_footer(text=f"{league_name} • {match_date}")
    
    return embed


@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot ready! No automatic messages will be sent.")
    print(f"Logged in as: {bot.user}")


@tree.command(name="live", description="Show live match for a specific team")
@app_commands.describe(team_name="Team name to check live match")
@app_commands.autocomplete(team_name=team_autocomplete)
async def live_matches(interaction: discord.Interaction, team_name: str):
    await interaction.response.defer()
    
    if team_name == "none":
        embed = discord.Embed(
            title="❌ Invalid Selection",
            description="Please type a valid team name.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
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
        data = await api_request(session, "fixtures", {"live": "all", "team": team_id})
    
    fixtures = data.get("response", [])
    
    if not fixtures:
        embed = discord.Embed(
            title="⚽ No Live Match",
            description=f"{team_full_name} is not playing right now.",
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed)
        return
    
    embeds = []
    for fixture in fixtures:
        embed = create_fixture_embed(fixture, f"⚽ LIVE - {team_full_name}")
        embeds.append(embed)
    
    await interaction.followup.send(embeds=embeds[:10])


@tree.command(name="last", description="Show the last match result for a specific team")
@app_commands.describe(team_name="Team name to check last match")
@app_commands.autocomplete(team_name=team_autocomplete)
async def last_match(interaction: discord.Interaction, team_name: str):
    await interaction.response.defer()
    
    if team_name == "none":
        embed = discord.Embed(
            title="❌ Invalid Selection",
            description="Please type a valid team name.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
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
    
    # Search last 30 days for finished matches
    today = datetime.now(BD_TZ).date()
    all_fixtures = []
    
    for days_ago in range(30):
        check_date = today - timedelta(days=days_ago)
        async with aiohttp.ClientSession() as session:
            data = await api_request(session, "fixtures", {
                "team": team_id,
                "date": str(check_date)
            })
        
        fixtures = data.get("response", [])
        finished = [f for f in fixtures if f["fixture"]["status"]["short"] == "FT"]
        
        if finished:
            all_fixtures.extend(finished)
            break
    
    if not all_fixtures:
        embed = discord.Embed(
            title="❌ No Recent Match",
            description=f"No finished match found for {team_full_name} in the last 30 days",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
    # Sort by date and get most recent
    all_fixtures.sort(key=lambda x: x["fixture"]["date"], reverse=True)
    fixture = all_fixtures[0]
    embed = create_fixture_embed(fixture, f"📊 Last Match - {team_full_name}")
    
    await interaction.followup.send(embed=embed)


@tree.command(name="upcoming", description="Show upcoming matches for a team or all matches (today + tomorrow)")
@app_commands.describe(team_name="Team name (optional - leave empty for all matches)")
@app_commands.autocomplete(team_name=team_autocomplete)
async def upcoming_matches(interaction: discord.Interaction, team_name: str = None):
    await interaction.response.defer()
    
    # If team name is provided
    if team_name and team_name != "none":
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
                "next": 5
            })
        
        fixtures = data.get("response", [])
        
        if not fixtures:
            embed = discord.Embed(
                title="📅 No Upcoming Matches",
                description=f"No upcoming matches found for {team_full_name}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return
        
        embeds = []
        for fixture in fixtures[:5]:
            embed = create_fixture_embed(fixture, f"📅 Upcoming - {team_full_name}")
            embeds.append(embed)
        
        await interaction.followup.send(embeds=embeds)
        return
    
    # If no team name - show all matches (today + tomorrow)
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
@app_commands.autocomplete(team_name=team_autocomplete)
async def team_fixtures(interaction: discord.Interaction, team_name: str):
    await interaction.response.defer()
    
    if team_name == "none":
        embed = discord.Embed(
            title="❌ Invalid Selection",
            description="Please type a valid team name.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
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


bot.run(DISCORD_TOKEN)
