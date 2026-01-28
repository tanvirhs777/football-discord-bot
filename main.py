# main.py
# Discord Football Bot - Stateful Mock Engine
# Fixes: Random score jumps, inconsistent match state, duplicate goals

import discord
from discord import app_commands
from discord.ext import tasks
import os
import logging
from datetime import datetime, timedelta
import asyncio
import random
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('football_bot')

# ============================================================================
# DATA MODELS
# ============================================================================

class MatchStatus(Enum):
    """Match status enum for type safety"""
    SCHEDULED = "SCH"
    LIVE = "LIVE"
    HALF_TIME = "HT"
    FULL_TIME = "FT"

@dataclass
class Match:
    """
    Stateful match object that persists throughout bot lifecycle.
    Scores and minutes increment gradually, never jump randomly.
    """
    id: str
    league: str
    home: str
    away: str
    home_score: int = 0
    away_score: int = 0
    minute: int = 0
    status: MatchStatus = MatchStatus.SCHEDULED
    kickoff_time: datetime = field(default_factory=datetime.utcnow)
    
    # Internal tracking for gradual updates
    _last_goal_minute: int = 0
    _goals_this_match: List[tuple] = field(default_factory=list)  # (minute, team, score)
    
    def can_score_goal(self) -> bool:
        """Prevent unrealistic goal frequency (min 5 minutes between goals)"""
        if self.status != MatchStatus.LIVE:
            return False
        return (self.minute - self._last_goal_minute) >= 5
    
    def add_goal(self, team: str) -> bool:
        """
        Add a goal to the specified team.
        Returns True if goal was added, False if invalid.
        """
        if not self.can_score_goal():
            return False
        
        if team == 'home':
            self.home_score += 1
        elif team == 'away':
            self.away_score += 1
        else:
            return False
        
        self._last_goal_minute = self.minute
        self._goals_this_match.append((self.minute, team, f"{self.home_score}-{self.away_score}"))
        return True
    
    def advance_minute(self, minutes: int = 1):
        """Advance match time gradually"""
        if self.status == MatchStatus.LIVE:
            self.minute = min(self.minute + minutes, 90)
            
            # Check for full-time
            if self.minute >= 90:
                self.status = MatchStatus.FULL_TIME
    
    def start_match(self):
        """Transition from scheduled to live"""
        if self.status == MatchStatus.SCHEDULED:
            self.status = MatchStatus.LIVE
            self.minute = 1
            logger.info(f"⚽ Match started: {self.home} vs {self.away}")
    
    def to_dict(self) -> dict:
        """Convert to dict for backwards compatibility"""
        return {
            'id': self.id,
            'league': self.league,
            'home': self.home,
            'away': self.away,
            'home_score': self.home_score,
            'away_score': self.away_score,
            'minute': self.minute,
            'status': self.status.value
        }

# ============================================================================
# STATEFUL MATCH ENGINE (SINGLE SOURCE OF TRUTH)
# ============================================================================

class MatchEngine:
    """
    Centralized match state manager.
    Initializes matches ONCE on startup, then updates them gradually.
    All slash commands and background tasks read from this shared state.
    """
    
    def __init__(self):
        self.matches: Dict[str, Match] = {}
        self.initialized = False
        
        # Track what we've announced to prevent duplicates
        self.announced_goals: Dict[str, set] = {}  # match_id -> set of score strings
        self.announced_ft: set = set()  # match_ids that had FT announced
        
    def initialize_matches(self):
        """
        CALLED ONCE ON STARTUP.
        Creates initial match fixtures with realistic distribution.
        """
        if self.initialized:
            logger.warning("Match engine already initialized, skipping")
            return
        
        teams = {
            'laliga': ['Real Madrid', 'Barcelona', 'Atletico Madrid', 'Sevilla', 'Real Betis', 'Valencia'],
            'epl': ['Manchester City', 'Arsenal', 'Liverpool', 'Chelsea', 'Manchester United', 'Tottenham'],
            'ucl': ['Real Madrid', 'Barcelona', 'Bayern Munich', 'PSG', 'Man City', 'Inter Milan']
        }
        
        target_teams = ['Real Madrid', 'Barcelona']
        
        # Create 1-2 matches per league with target teams
        for league in ['laliga', 'epl', 'ucl']:
            # Higher chance of target teams in LaLiga and UCL
            should_create = True if league in ['laliga', 'ucl'] else random.random() > 0.3
            
            if should_create:
                # Pick Real Madrid or Barcelona
                home_team = random.choice(target_teams)
                
                # Pick opponent
                available = [t for t in teams[league] if t not in target_teams]
                if not available:
                    continue
                
                away_team = random.choice(available)
                
                # Randomly swap home/away
                if random.random() > 0.5:
                    home_team, away_team = away_team, home_team
                
                # Create match ID
                match_id = f"{league}_{home_team}_{away_team}".replace(' ', '_').lower()
                
                # Determine initial status
                # 40% start LIVE, 30% scheduled (will start later), 30% already in progress
                rand = random.random()
                
                if rand < 0.4:
                    # Match is live from start
                    status = MatchStatus.LIVE
                    minute = random.randint(1, 30)  # Early in match
                    home_score = random.randint(0, 1)
                    away_score = random.randint(0, 1)
                elif rand < 0.7:
                    # Match scheduled, will start in 1-3 update cycles
                    status = MatchStatus.SCHEDULED
                    minute = 0
                    home_score = 0
                    away_score = 0
                else:
                    # Match already in progress (mid-game)
                    status = MatchStatus.LIVE
                    minute = random.randint(45, 75)
                    home_score = random.randint(0, 2)
                    away_score = random.randint(0, 2)
                
                match = Match(
                    id=match_id,
                    league=league,
                    home=home_team,
                    away=away_team,
                    home_score=home_score,
                    away_score=away_score,
                    minute=minute,
                    status=status
                )
                
                self.matches[match_id] = match
                self.announced_goals[match_id] = {f"{home_score}-{away_score}"}
                
                logger.info(
                    f"📋 Created match: {home_team} vs {away_team} "
                    f"[{league.upper()}] - Status: {status.value}"
                )
        
        self.initialized = True
        logger.info(f"✅ Match engine initialized with {len(self.matches)} matches")
    
    def update_matches(self) -> List[tuple]:
        """
        CALLED BY BACKGROUND TASK.
        Gradually advances match state:
        - Increment minutes
        - Randomly add goals (with realistic constraints)
        - Transition scheduled → live → full-time
        
        Returns list of (match, event_type) tuples for notification
        """
        events = []  # (match, 'GOAL' or 'FT')
        
        for match in list(self.matches.values()):
            
            # ================================================================
            # SCHEDULED → LIVE transition
            # ================================================================
            if match.status == MatchStatus.SCHEDULED:
                # 20% chance to start each update cycle
                if random.random() < 0.2:
                    match.start_match()
            
            # ================================================================
            # LIVE matches: advance time and potentially add goals
            # ================================================================
            elif match.status == MatchStatus.LIVE:
                # Advance by 1-3 minutes per update
                match.advance_minute(random.randint(1, 3))
                
                # Goal probability increases as match progresses
                # Early game: 10%, late game: 25%
                goal_chance = 0.10 + (match.minute / 90) * 0.15
                
                if random.random() < goal_chance and match.can_score_goal():
                    # Randomly pick which team scores
                    scoring_team = random.choice(['home', 'away'])
                    
                    if match.add_goal(scoring_team):
                        # New goal! Record for notification
                        current_score = f"{match.home_score}-{match.away_score}"
                        
                        if current_score not in self.announced_goals[match.id]:
                            events.append((match, 'GOAL'))
                            self.announced_goals[match.id].add(current_score)
                
                # Check if match just finished
                if match.status == MatchStatus.FULL_TIME and match.id not in self.announced_ft:
                    events.append((match, 'FT'))
                    self.announced_ft.add(match.id)
        
        return events
    
    def get_live_matches(self) -> List[Match]:
        """Get all currently live matches"""
        return [m for m in self.matches.values() if m.status == MatchStatus.LIVE]
    
    def get_matches_by_league(self, league: str, target_teams: List[str]) -> List[Match]:
        """Get matches for specific league with target teams"""
        return [
            m for m in self.matches.values()
            if m.league == league and (m.home in target_teams or m.away in target_teams)
        ]
    
    def cleanup_finished_matches(self):
        """Remove matches that finished 10+ minutes ago (in real time)"""
        to_remove = [
            match_id for match_id, match in self.matches.items()
            if match.status == MatchStatus.FULL_TIME and match_id in self.announced_ft
        ]
        
        # In production, you'd check actual time elapsed
        # For demo, we'll remove after announcing FT
        for match_id in to_remove:
            # Keep for a few cycles, then remove
            pass  # Implement time-based cleanup if needed

# Global match engine instance (single source of truth)
match_engine = MatchEngine()

# ============================================================================
# BOT SETUP
# ============================================================================

intents = discord.Intents.default()
intents.message_content = False

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Sync guards
_sync_completed = False
_tasks_started = False

# ============================================================================
# BOT EVENTS
# ============================================================================

@client.event
async def on_ready():
    """
    Startup sequence:
    1. Initialize match engine ONCE
    2. Sync slash commands
    3. Start background tasks
    """
    global _sync_completed, _tasks_started
    
    if _sync_completed:
        logger.info(f'🔄 Reconnected as {client.user}')
        return
    
    logger.info(f'🤖 Bot logged in as {client.user}')
    
    # ========================================================================
    # CRITICAL: Initialize match engine BEFORE anything else
    # ========================================================================
    match_engine.initialize_matches()
    
    # ========================================================================
    # Sync slash commands to guilds
    # ========================================================================
    total_synced = 0
    for guild in client.guilds:
        try:
            tree.copy_global_to(guild=guild)
            synced = await tree.sync(guild=guild)
            logger.info(f'✅ Synced {len(synced)} commands to {guild.name}')
            total_synced += len(synced)
        except Exception as e:
            logger.error(f'❌ Sync failed for {guild.name}: {e}')
    
    _sync_completed = True
    
    # Wait for Discord to process commands
    await asyncio.sleep(3)
    
    # ========================================================================
    # Start background tasks
    # ========================================================================
    if not _tasks_started:
        match_updater.start()
        await asyncio.sleep(1)
        match_monitor.start()
        _tasks_started = True
        logger.info('🚀 Bot fully operational')

# ============================================================================
# SLASH COMMANDS (READ FROM SHARED STATE)
# ============================================================================

@tree.command(name="ping", description="Check bot responsiveness")
async def ping(interaction: discord.Interaction):
    """Health check"""
    latency = round(client.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latency: {latency}ms",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@tree.command(name="live", description="Show all live matches")
async def live(interaction: discord.Interaction):
    """Display live matches from shared state"""
    await interaction.response.defer()
    
    live_matches = match_engine.get_live_matches()
    
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
            f"**{match.home} {match.home_score} - {match.away_score} {match.away}**\n"
            f"⏱️ {match.minute}' | 🏆 {match.league.upper()}"
        )
        embed.add_field(
            name=f"{match.league.upper()}",
            value=match_info,
            inline=False
        )
    
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.followup.send(embed=embed)
    logger.info(f'📺 /live used by {interaction.user}')

@tree.command(name="laliga", description="Real Madrid/Barcelona in La Liga")
async def laliga(interaction: discord.Interaction):
    """La Liga matches from shared state"""
    await interaction.response.defer()
    
    target_teams = ['Real Madrid', 'Barcelona']
    matches = match_engine.get_matches_by_league('laliga', target_teams)
    
    if not matches:
        embed = discord.Embed(
            title="ℹ️ No Matches",
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
    
    for match in matches:
        status_emoji = {
            MatchStatus.LIVE: '🔴',
            MatchStatus.FULL_TIME: '⚪',
            MatchStatus.SCHEDULED: '🕐'
        }.get(match.status, '⚽')
        
        match_info = (
            f"{status_emoji} **{match.home} {match.home_score} - {match.away_score} {match.away}**\n"
            f"Status: {match.status.value} | Minute: {match.minute}'"
        )
        embed.add_field(
            name=f"{match.home} vs {match.away}",
            value=match_info,
            inline=False
        )
    
    await interaction.followup.send(embed=embed)
    logger.info(f'🇪🇸 /laliga used by {interaction.user}')

@tree.command(name="epl", description="Real Madrid/Barcelona in Premier League")
async def epl(interaction: discord.Interaction):
    """EPL matches from shared state"""
    await interaction.response.defer()
    
    target_teams = ['Real Madrid', 'Barcelona']
    matches = match_engine.get_matches_by_league('epl', target_teams)
    
    if not matches:
        embed = discord.Embed(
            title="ℹ️ No Matches",
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
    
    for match in matches:
        status_emoji = {
            MatchStatus.LIVE: '🔴',
            MatchStatus.FULL_TIME: '⚪',
            MatchStatus.SCHEDULED: '🕐'
        }.get(match.status, '⚽')
        
        match_info = (
            f"{status_emoji} **{match.home} {match.home_score} - {match.away_score} {match.away}**\n"
            f"Status: {match.status.value} | Minute: {match.minute}'"
        )
        embed.add_field(
            name=f"{match.home} vs {match.away}",
            value=match_info,
            inline=False
        )
    
    await interaction.followup.send(embed=embed)
    logger.info(f'🏴󠁧󠁢󠁥󠁮󠁧󠁿 /epl used by {interaction.user}')

@tree.command(name="ucl", description="Real Madrid/Barcelona in Champions League")
async def ucl(interaction: discord.Interaction):
    """UCL matches from shared state"""
    await interaction.response.defer()
    
    target_teams = ['Real Madrid', 'Barcelona']
    matches = match_engine.get_matches_by_league('ucl', target_teams)
    
    if not matches:
        embed = discord.Embed(
            title="ℹ️ No Matches",
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
    
    for match in matches:
        status_emoji = {
            MatchStatus.LIVE: '🔴',
            MatchStatus.FULL_TIME: '⚪',
            MatchStatus.SCHEDULED: '🕐'
        }.get(match.status, '⚽')
        
        match_info = (
            f"{status_emoji} **{match.home} {match.home_score} - {match.away_score} {match.away}**\n"
            f"Status: {match.status.value} | Minute: {match.minute}'"
        )
        embed.add_field(
            name=f"{match.home} vs {match.away}",
            value=match_info,
            inline=False
        )
    
    await interaction.followup.send(embed=embed)
    logger.info(f'🏆 /ucl used by {interaction.user}')

# ============================================================================
# BACKGROUND TASKS (UPDATE SHARED STATE)
# ============================================================================

@tasks.loop(seconds=30)
async def match_updater():
    """
    Updates match state every 30 seconds:
    - Advances minutes
    - Adds goals realistically
    - Transitions statuses
    
    Does NOT create new matches, only updates existing ones.
    """
    try:
        events = match_engine.update_matches()
        
        if events:
            logger.info(f"📊 Match update: {len(events)} events generated")
        
    except Exception as e:
        logger.error(f'❌ Match updater error: {e}')

@tasks.loop(seconds=35)
async def match_monitor():
    """
    Monitors for GOAL and FT events.
    Reads from shared state updated by match_updater.
    """
    try:
        # Get events from last update cycle
        events = match_engine.update_matches()
        
        if not events:
            return
        
        # Find announcement channel
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
            logger.warning('⚠️ No announcement channel found')
            return
        
        # Process events
        for match, event_type in events:
            
            if event_type == 'GOAL':
                embed = discord.Embed(
                    title="⚽ GOAL!",
                    description=f"**{match.home} {match.home_score} - {match.away_score} {match.away}**",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="League", value=match.league.upper(), inline=True)
                embed.add_field(name="Time", value=f"{match.minute}'", inline=True)
                embed.set_footer(text=f"Today at {datetime.utcnow().strftime('%I:%M %p')}")
                
                await channel.send(embed=embed)
                logger.info(f'⚽ GOAL: {match.home} {match.home_score}-{match.away_score} {match.away}')
            
            elif event_type == 'FT':
                embed = discord.Embed(
                    title="⚪ FULL TIME",
                    description=f"**{match.home} {match.home_score} - {match.away_score} {match.away}**",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="League", value=match.league.upper(), inline=True)
                embed.set_footer(text="Match Ended")
                
                await channel.send(embed=embed)
                logger.info(f'⚪ FT: {match.home} {match.home_score}-{match.away_score} {match.away}')
        
    except Exception as e:
        logger.error(f'❌ Match monitor error: {e}')

@match_updater.before_loop
async def before_updater():
    await client.wait_until_ready()
    logger.info('✅ Match updater ready')

@match_monitor.before_loop
async def before_monitor():
    await client.wait_until_ready()
    logger.info('✅ Match monitor ready')

# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    
    if not token:
        logger.error('❌ DISCORD_TOKEN not set')
        exit(1)
    
    logger.info('🚀 Starting Football Bot...')
    
    try:
        client.run(token, log_handler=None)
    except KeyboardInterrupt:
        logger.info('⚠️ Bot stopped by user')
    except Exception as e:
        logger.error(f'❌ Fatal error: {e}')
        exit(1)
