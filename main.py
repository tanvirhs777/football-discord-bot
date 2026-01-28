# main.py
# Discord Football Bot - Railway Ready
# Uses discord.py with slash commands only
# No external APIs - uses mock data for demonstration

import discord
from discord import app_commands
from discord.ext import tasks
import os
import logging
from datetime import datetime, timedelta
import asyncio
import random

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('football_bot')

# Bot setup with minimal intents
intents = discord.Intents.default()
intents.message_content = False
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Global state for match tracking
active_matches = {}
announced_goals = {}
announced_ft = set()
last_match_state = {}

# Mock match data - simulates real matches
def generate_mock_matches():
    """Generate realistic mock match data"""
    teams = {
        'laliga': ['Real Madrid', 'Barcelona', 'Atletico Madrid', 'Sevilla', 'Real Betis', 'Valencia'],
        'epl': ['Manchester City', 'Arsenal', 'Liverpool', 'Chelsea', 'Manchester United'],
        'ucl': ['Real Madrid', 'Barcelona', 'Bayern Munich', 'PSG', 'Manchester City', 'Inter Milan']
    }
    
    matches = []
    now = datetime.utcnow()
    
    # Generate matches with Real Madrid or Barcelona
    for league in ['laliga', 'epl', 'ucl']:
        if random.random() > 0.4:  # 60% chance of match
            team_pool = teams[league].copy()
            
            # Higher chance for Real Madrid/Barcelona in LaLiga and UCL
            if league in ['laliga', 'ucl'] and random.random() > 0.3:
                home = random.choice(['Real Madrid', 'Barcelona'])
                if home in team_pool:
                    team_pool.remove(home)
                away = random.choice(team_pool)
            else:
                home = random.choice(team_pool)
                if home in team_pool:
                    team_pool.remove(home)
                if team_pool:
                    away = random.choice(team_pool)
                else:
                    away = 'Opponent'
            
            # Random match state
            status = random.choice(['LIVE', 'LIVE', 'FT', 'SCH'])
            
            if status == 'LIVE':
                minute = random.randint(1, 90)
                home_score = random.randint(0, 3)
                away_score = random.randint(0, 3)
            elif status == 'FT':
                minute = 90
                home_score = random.randint(0, 4)
                away_score = random.randint(0, 4)
            else:
                minute = 0
                home_score = 0
                away_score = 0
            
            match_id = f"{league}_{home}_{away}".replace(' ', '_')
            
            matches.append({
                'id': match_id,
                'league': league,
                'home': home,
                'away': away,
                'home_score': home_score,
                'away_score': away_score,
                'status': status,
                'minute': minute,
                'kickoff': now
            })
    
    return matches

def format_match_display(match):
    """Format match for display"""
    status_emoji = {
        'LIVE': '🔴',
        'FT': '⚪',
        'SCH': '🕐'
    }
    
    emoji = status_emoji.get(match['status'], '⚽')
    
    if match['status'] == 'LIVE':
        return (f"{emoji} **{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**\n"
                f"⏱️ {match['minute']}'")
    elif match['status'] == 'FT':
        return (f"{emoji} **{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**\n"
                f"⏱️ Full Time")
    else:
        time_str = match['kickoff'].strftime('%H:%M UTC')
        return (f"{emoji} **{match['home']} vs {match['away']}**\n"
                f"⏱️ Kickoff: {time_str}")

def has_target_team(match):
    """Check if match has Real Madrid or Barcelona"""
    target_teams = ['Real Madrid', 'Barcelona']
    return match['home'] in target_teams or match['away'] in target_teams

@client.event
async def on_ready():
    """Bot startup"""
    try:
        synced = await tree.sync()
        logger.info(f'✅ Logged in as {client.user}')
        logger.info(f'✅ Synced {len(synced)} slash command(s)')
        
        # Start background tasks
        if not match_monitor.is_running():
            match_monitor.start()
        if not match_updater.is_running():
            match_updater.start()
    except Exception as e:
        logger.error(f'Error in on_ready: {e}')

@tree.command(name="ping", description="Check if bot is alive")
async def ping(interaction: discord.Interaction):
    """Simple ping command"""
    await interaction.response.send_message("🏓 Pong!", ephemeral=False)
    logger.info(f'Ping command used by {interaction.user}')

@tree.command(name="live", description="Show all live football matches")
async def live(interaction: discord.Interaction):
    """Show live matches"""
    await interaction.response.defer()
    
    matches = generate_mock_matches()
    live_matches = [m for m in matches if m['status'] == 'LIVE']
    
    if not live_matches:
        await interaction.followup.send("❌ এখন কোনো লাইভ ম্যাচ নেই")
        return
    
    embed = discord.Embed(
        title="🔴 Live Matches",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    
    for match in live_matches:
        league_name = match['league'].upper()
        embed.add_field(
            name=f"{league_name}",
            value=format_match_display(match),
            inline=False
        )
    
    embed.set_footer(text="Football Bot")
    await interaction.followup.send(embed=embed)
    logger.info(f'Live command used by {interaction.user}')

@tree.command(name="laliga", description="Show Real Madrid/Barcelona matches in La Liga")
async def laliga(interaction: discord.Interaction):
    """Show La Liga matches for target teams"""
    await interaction.response.defer()
    
    matches = generate_mock_matches()
    laliga_matches = [m for m in matches if m['league'] == 'laliga' and has_target_team(m)]
    
    if not laliga_matches:
        await interaction.followup.send("ℹ️ আজ Real Madrid / Barcelona এর ম্যাচ নেই")
        return
    
    embed = discord.Embed(
        title="⚽ La Liga - Real Madrid / Barcelona",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    for match in laliga_matches:
        embed.add_field(
            name=f"{match['home']} vs {match['away']}",
            value=format_match_display(match),
            inline=False
        )
    
    embed.set_footer(text="Football Bot")
    await interaction.followup.send(embed=embed)
    logger.info(f'LaLiga command used by {interaction.user}')

@tree.command(name="epl", description="Show Real Madrid/Barcelona matches in EPL")
async def epl(interaction: discord.Interaction):
    """Show EPL matches for target teams"""
    await interaction.response.defer()
    
    matches = generate_mock_matches()
    epl_matches = [m for m in matches if m['league'] == 'epl' and has_target_team(m)]
    
    if not epl_matches:
        await interaction.followup.send("ℹ️ আজ Real Madrid / Barcelona এর ম্যাচ নেই")
        return
    
    embed = discord.Embed(
        title="⚽ Premier League - Real Madrid / Barcelona",
        color=discord.Color.purple(),
        timestamp=datetime.utcnow()
    )
    
    for match in epl_matches:
        embed.add_field(
            name=f"{match['home']} vs {match['away']}",
            value=format_match_display(match),
            inline=False
        )
    
    embed.set_footer(text="Football Bot")
    await interaction.followup.send(embed=embed)
    logger.info(f'EPL command used by {interaction.user}')

@tree.command(name="ucl", description="Show Real Madrid/Barcelona matches in UCL")
async def ucl(interaction: discord.Interaction):
    """Show UCL matches for target teams"""
    await interaction.response.defer()
    
    matches = generate_mock_matches()
    ucl_matches = [m for m in matches if m['league'] == 'ucl' and has_target_team(m)]
    
    if not ucl_matches:
        await interaction.followup.send("ℹ️ আজ Real Madrid / Barcelona এর ম্যাচ নেই")
        return
    
    embed = discord.Embed(
        title="🏆 Champions League - Real Madrid / Barcelona",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    
    for match in ucl_matches:
        embed.add_field(
            name=f"{match['home']} vs {match['away']}",
            value=format_match_display(match),
            inline=False
        )
    
    embed.set_footer(text="Football Bot")
    await interaction.followup.send(embed=embed)
    logger.info(f'UCL command used by {interaction.user}')

@tasks.loop(minutes=3)
async def match_updater():
    """Update match data periodically"""
    try:
        global active_matches, last_match_state
        matches = generate_mock_matches()
        
        for match in matches:
            if match['status'] == 'LIVE' and has_target_team(match):
                # Store previous state
                if match['id'] in active_matches:
                    last_match_state[match['id']] = active_matches[match['id']].copy()
                active_matches[match['id']] = match
            elif match['id'] in active_matches and match['status'] == 'FT':
                last_match_state[match['id']] = active_matches[match['id']].copy()
                active_matches[match['id']] = match
        
        # Clean up old matches
        to_remove = []
        for match_id, match in active_matches.items():
            if match['status'] == 'FT' and match_id in announced_ft:
                # Keep for 10 minutes after FT
                to_remove.append(match_id)
        
        for match_id in to_remove:
            if match_id in active_matches:
                del active_matches[match_id]
            if match_id in last_match_state:
                del last_match_state[match_id]
            
    except Exception as e:
        logger.error(f'Error in match updater: {e}')

@tasks.loop(seconds=45)
async def match_monitor():
    """Monitor matches and send goal/FT updates to channel where command was used"""
    try:
        if not active_matches:
            return
        
        # Get first available text channel
        channel = None
        for guild in client.guilds:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
            if channel:
                break
        
        if not channel:
            return
        
        for match_id, match in list(active_matches.items()):
            # Goal updates - only if score changed
            if match['status'] == 'LIVE':
                # Check if score changed
                old_match = last_match_state.get(match_id)
                if old_match:
                    old_total = old_match['home_score'] + old_match['away_score']
                    new_total = match['home_score'] + match['away_score']
                    
                    # New goal scored
                    if new_total > old_total:
                        embed = discord.Embed(
                            title="⚽ GOAL!",
                            description=f"**{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**",
                            color=discord.Color.green(),
                            timestamp=datetime.utcnow()
                        )
                        embed.add_field(name="League", value=match['league'].upper(), inline=True)
                        embed.add_field(name="Time", value=f"{match['minute']}'", inline=True)
                        embed.set_footer(text=f"Today at {datetime.utcnow().strftime('%I:%M %p')}")
                        
                        await channel.send(embed=embed)
                        logger.info(f'Goal announced: {match["home"]} {match["home_score"]}-{match["away_score"]} {match["away"]}')
            
            # Full-time updates
            elif match['status'] == 'FT' and match_id not in announced_ft:
                embed = discord.Embed(
                    title="⚪ FULL TIME",
                    description=f"**{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="League", value=match['league'].upper(), inline=True)
                embed.set_footer(text="Match Ended")
                
                await channel.send(embed=embed)
                announced_ft.add(match_id)
                logger.info(f'FT announced: {match["home"]} {match["home_score"]}-{match["away_score"]} {match["away"]}')
                
    except Exception as e:
        logger.error(f'Error in match monitor: {e}')

@match_updater.before_loop
async def before_updater():
    await client.wait_until_ready()
    logger.info('Match updater started')

@match_monitor.before_loop
async def before_monitor():
    await client.wait_until_ready()
    logger.info('Match monitor started')

# Run bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    
    if not token:
        logger.error('❌ DISCORD_TOKEN environment variable not set')
        exit(1)
    
    try:
        client.run(token, log_handler=None)
    except KeyboardInterrupt:
        logger.info('Bot stopped by user')
    except Exception as e:
        logger.error(f'❌ Failed to start bot: {e}')
        exit(1)
