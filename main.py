# main.py
# Discord Football Bot - Production Fixed Version
# Fixes: OAuth scope, sync order, task timing, idempotency, cache handling

import discord
from discord import app_commands
from discord.ext import tasks
import os
import logging
from datetime import datetime
import asyncio
import random

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('football_bot')

# ============================================================================
# BOT SETUP
# ============================================================================

intents = discord.Intents.default()
intents.message_content = False  # Not needed for slash commands

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ============================================================================
# GLOBAL STATE
# ============================================================================

# Prevents duplicate syncs and task starts
_sync_completed = False
_tasks_started = False

# Match tracking
active_matches = {}
previous_scores = {}  # Track score changes to detect goals
announced_ft = set()

# ============================================================================
# MOCK DATA ENGINE
# ============================================================================

def generate_mock_matches():
    """Generate realistic mock football matches"""
    teams = {
        'laliga': ['Real Madrid', 'Barcelona', 'Atletico Madrid', 'Sevilla', 'Real Betis'],
        'epl': ['Manchester City', 'Arsenal', 'Liverpool', 'Chelsea', 'Manchester United'],
        'ucl': ['Real Madrid', 'Barcelona', 'Bayern Munich', 'PSG', 'Man City', 'Inter Milan']
    }
    
    matches = []
    
    for league in ['laliga', 'epl', 'ucl']:
        # 60% chance of Real Madrid or Barcelona match
        if random.random() < 0.6:
            target_team = random.choice(['Real Madrid', 'Barcelona'])
            
            opponent_pool = [t for t in teams[league] if t not in ['Real Madrid', 'Barcelona']]
            if not opponent_pool:
                continue
            
            opponent = random.choice(opponent_pool)
            is_home = random.choice([True, False])
            
            home = target_team if is_home else opponent
            away = opponent if is_home else target_team
            
            # Status: 50% LIVE, 30% FT, 20% scheduled
            rand = random.random()
            if rand < 0.5:
                status = 'LIVE'
                minute = random.randint(1, 90)
                home_score = random.randint(0, 3)
                away_score = random.randint(0, 3)
            elif rand < 0.8:
                status = 'FT'
                minute = 90
                home_score = random.randint(0, 4)
                away_score = random.randint(0, 4)
            else:
                status = 'SCH'
                minute = 0
                home_score = 0
                away_score = 0
            
            match_id = f"{league}_{home}_{away}".replace(' ', '_').lower()
            
            matches.append({
                'id': match_id,
                'league': league,
                'home': home,
                'away': away,
                'home_score': home_score,
                'away_score': away_score,
                'status': status,
                'minute': minute
            })
    
    return matches

def has_target_team(match):
    """Check if Real Madrid or Barcelona is playing"""
    targets = ['Real Madrid', 'Barcelona']
    return match['home'] in targets or match['away'] in targets

# ============================================================================
# BOT EVENTS
# ============================================================================

@client.event
async def on_ready():
    """
    CRITICAL STARTUP SEQUENCE:
    1. Sync commands to ALL guilds (guild-specific for instant availability)
    2. Wait for Discord to confirm sync
    3. Start background tasks ONLY after commands are ready
    4. Use idempotency guards to prevent duplicate runs
    """
    global _sync_completed, _tasks_started
    
    # GUARD: Prevent duplicate sync on reconnects
    if _sync_completed:
        logger.info(f'🔄 Reconnected as {client.user} (skipping re-sync)')
        return
    
    logger.info(f'🤖 Bot logged in as {client.user}')
    logger.info(f'🌐 Connected to {len(client.guilds)} guild(s)')
    
    # List all guilds for debugging
    for guild in client.guilds:
        logger.info(f'   - {guild.name} (ID: {guild.id})')
    
    # ========================================================================
    # CRITICAL: Guild-specific command sync
    # ========================================================================
    
    total_synced = 0
    
    for guild in client.guilds:
        try:
            # STEP 1: Copy global commands to this guild's tree
            tree.copy_global_to(guild=guild)
            
            # STEP 2: Sync guild-specific tree (fast, 1-3 seconds)
            synced_commands = await tree.sync(guild=guild)
            
            logger.info(f'✅ Synced {len(synced_commands)} commands to {guild.name}')
            
            # Debug: Show which commands were synced
            for cmd in synced_commands:
                logger.info(f'   └─ /{cmd.name}')
            
            total_synced += len(synced_commands)
            
        except Exception as e:
            logger.error(f'❌ Failed to sync commands to {guild.name}: {e}')
    
    logger.info(f'📊 Total commands synced: {total_synced}')
    
    # Mark sync as completed
    _sync_completed = True
    
    # ========================================================================
    # CRITICAL: Wait before starting background tasks
    # ========================================================================
    
    logger.info('⏳ Waiting 3 seconds for Discord to process command registration...')
    await asyncio.sleep(3)
    
    # ========================================================================
    # SAFE: Now start background tasks
    # ========================================================================
    
    if not _tasks_started:
        try:
            match_updater.start()
            logger.info('✅ Match updater started')
            
            # Stagger task starts to avoid event loop congestion
            await asyncio.sleep(1)
            
            match_monitor.start()
            logger.info('✅ Match monitor started')
            
            _tasks_started = True
            logger.info('🚀 Bot fully operational')
            
        except Exception as e:
            logger.error(f'❌ Failed to start background tasks: {e}')

# ============================================================================
# SLASH COMMANDS
# ============================================================================

@tree.command(name="ping", description="Check if the bot is responsive")
async def ping(interaction: discord.Interaction):
    """Simple health check"""
    latency = round(client.latency * 1000)
    
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Bot is online and responsive",
        color=discord.Color.green()
    )
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Status", value="✅ Operational", inline=True)
    
    await interaction.response.send_message(embed=embed)
    logger.info(f'📍 Ping command used by {interaction.user} in {interaction.guild.name}')

@tree.command(name="live", description="Show all currently live football matches")
async def live(interaction: discord.Interaction):
    """Display all live matches"""
    await interaction.response.defer()
    
    matches = generate_mock_matches()
    live_matches = [m for m in matches if m['status'] == 'LIVE']
    
    if not live_matches:
        embed = discord.Embed(
            title="❌ No Live Matches",
            description="এখন কোনো লাইভ ম্যাচ নেই",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="🔴 Live Matches",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    
    for match in live_matches:
        match_info = (
            f"**{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**\n"
            f"⏱️ {match['minute']}' | 🏆 {match['league'].upper()}"
        )
        embed.add_field(
            name=f"{match['league'].upper()}",
            value=match_info,
            inline=False
        )
    
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.followup.send(embed=embed)
    logger.info(f'📺 Live command used by {interaction.user}')

@tree.command(name="laliga", description="Show Real Madrid/Barcelona matches in La Liga")
async def laliga(interaction: discord.Interaction):
    """La Liga matches for Real Madrid and Barcelona"""
    await interaction.response.defer()
    
    matches = generate_mock_matches()
    target_matches = [
        m for m in matches 
        if m['league'] == 'laliga' and has_target_team(m)
    ]
    
    if not target_matches:
        embed = discord.Embed(
            title="ℹ️ No Matches Today",
            description="আজ Real Madrid / Barcelona এর ম্যাচ নেই",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="⚽ La Liga - Real Madrid / Barcelona",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    for match in target_matches:
        status_emoji = {'LIVE': '🔴', 'FT': '⚪', 'SCH': '🕐'}.get(match['status'], '⚽')
        match_info = (
            f"{status_emoji} **{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**\n"
            f"Status: {match['status']} | Minute: {match['minute']}'"
        )
        embed.add_field(
            name=f"{match['home']} vs {match['away']}",
            value=match_info,
            inline=False
        )
    
    await interaction.followup.send(embed=embed)
    logger.info(f'🇪🇸 LaLiga command used by {interaction.user}')

@tree.command(name="epl", description="Show Real Madrid/Barcelona matches in Premier League")
async def epl(interaction: discord.Interaction):
    """EPL matches for Real Madrid and Barcelona"""
    await interaction.response.defer()
    
    matches = generate_mock_matches()
    target_matches = [
        m for m in matches 
        if m['league'] == 'epl' and has_target_team(m)
    ]
    
    if not target_matches:
        embed = discord.Embed(
            title="ℹ️ No Matches Today",
            description="আজ Real Madrid / Barcelona এর ম্যাচ নেই",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="⚽ Premier League - Real Madrid / Barcelona",
        color=discord.Color.purple(),
        timestamp=datetime.utcnow()
    )
    
    for match in target_matches:
        status_emoji = {'LIVE': '🔴', 'FT': '⚪', 'SCH': '🕐'}.get(match['status'], '⚽')
        match_info = (
            f"{status_emoji} **{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**\n"
            f"Status: {match['status']} | Minute: {match['minute']}'"
        )
        embed.add_field(
            name=f"{match['home']} vs {match['away']}",
            value=match_info,
            inline=False
        )
    
    await interaction.followup.send(embed=embed)
    logger.info(f'🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL command used by {interaction.user}')

@tree.command(name="ucl", description="Show Real Madrid/Barcelona matches in Champions League")
async def ucl(interaction: discord.Interaction):
    """UCL matches for Real Madrid and Barcelona"""
    await interaction.response.defer()
    
    matches = generate_mock_matches()
    target_matches = [
        m for m in matches 
        if m['league'] == 'ucl' and has_target_team(m)
    ]
    
    if not target_matches:
        embed = discord.Embed(
            title="ℹ️ No Matches Today",
            description="আজ Real Madrid / Barcelona এর ম্যাচ নেই",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="🏆 Champions League - Real Madrid / Barcelona",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    
    for match in target_matches:
        status_emoji = {'LIVE': '🔴', 'FT': '⚪', 'SCH': '🕐'}.get(match['status'], '⚽')
        match_info = (
            f"{status_emoji} **{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**\n"
            f"Status: {match['status']} | Minute: {match['minute']}'"
        )
        embed.add_field(
            name=f"{match['home']} vs {match['away']}",
            value=match_info,
            inline=False
        )
    
    await interaction.followup.send(embed=embed)
    logger.info(f'🏆 UCL command used by {interaction.user}')

# ============================================================================
# BACKGROUND TASKS
# ============================================================================

@tasks.loop(minutes=2)
async def match_updater():
    """Update match state periodically"""
    try:
        global active_matches, previous_scores
        
        matches = generate_mock_matches()
        
        for match in matches:
            if has_target_team(match) and match['status'] in ['LIVE', 'FT']:
                match_id = match['id']
                
                # Store previous score BEFORE updating
                if match_id in active_matches:
                    old_match = active_matches[match_id]
                    previous_scores[match_id] = (old_match['home_score'], old_match['away_score'])
                else:
                    # First time seeing this match
                    previous_scores[match_id] = (match['home_score'], match['away_score'])
                
                active_matches[match_id] = match
        
        # Cleanup finished matches that have been announced
        to_remove = [
            mid for mid, m in active_matches.items()
            if m['status'] == 'FT' and mid in announced_ft
        ]
        
        for mid in to_remove:
            del active_matches[mid]
            if mid in previous_scores:
                del previous_scores[mid]
        
    except Exception as e:
        logger.error(f'❌ Error in match updater: {e}')

@tasks.loop(seconds=45)
async def match_monitor():
    """Monitor matches for goals and full-time results"""
    try:
        if not active_matches:
            return
        
        # Find first available text channel
        channel = None
        for guild in client.guilds:
            for ch in guild.text_channels:
                perms = ch.permissions_for(guild.me)
                if perms.send_messages and perms.embed_links:
                    channel = ch
                    break
            if channel:
                break
        
        if not channel:
            logger.warning('⚠️ No available text channel found')
            return
        
        for match_id, match in list(active_matches.items()):
            
            # ================================================================
            # GOAL DETECTION (only when score increases)
            # ================================================================
            
            if match['status'] == 'LIVE' and match_id in previous_scores:
                old_home, old_away = previous_scores[match_id]
                new_home, new_away = match['home_score'], match['away_score']
                
                # Check if score increased
                if (new_home > old_home) or (new_away > old_away):
                    embed = discord.Embed(
                        title="⚽ GOAL!",
                        description=f"**{match['home']} {new_home} - {new_away} {match['away']}**",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="League", value=match['league'].upper(), inline=True)
                    embed.add_field(name="Time", value=f"{match['minute']}'", inline=True)
                    embed.set_footer(text=f"Today at {datetime.utcnow().strftime('%I:%M %p')}")
                    
                    await channel.send(embed=embed)
                    logger.info(f'⚽ GOAL: {match["home"]} {new_home}-{new_away} {match["away"]}')
                    
                    # Update stored score to prevent duplicate announcement
                    previous_scores[match_id] = (new_home, new_away)
            
            # ================================================================
            # FULL-TIME DETECTION (announce once)
            # ================================================================
            
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
                logger.info(f'⚪ FT: {match["home"]} {match["home_score"]}-{match["away_score"]} {match["away"]}')
        
    except Exception as e:
        logger.error(f'❌ Error in match monitor: {e}')

@match_updater.before_loop
async def before_updater():
    """Wait for bot to be ready before starting updater"""
    await client.wait_until_ready()
    logger.info('✅ Match updater initialized')

@match_monitor.before_loop
async def before_monitor():
    """Wait for bot to be ready before starting monitor"""
    await client.wait_until_ready()
    logger.info('✅ Match monitor initialized')

# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    
    if not token:
        logger.error('❌ DISCORD_TOKEN environment variable not set')
        logger.error('   Set it in Railway dashboard or .env file')
        exit(1)
    
    logger.info('🚀 Starting Football Bot...')
    
    try:
        client.run(token, log_handler=None)
    except KeyboardInterrupt:
        logger.info('⚠️ Bot stopped by user')
    except Exception as e:
        logger.error(f'❌ Fatal error: {e}')
        exit(1)
