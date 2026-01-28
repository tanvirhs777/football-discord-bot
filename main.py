
# main.py
# Discord Football Bot - Real-time data from football-data.org
# Free tier: 10 requests/min, covers La Liga, EPL, UCL

import discord
from discord import app_commands
from discord.ext import tasks
import os
import logging
from datetime import datetime
import asyncio
import aiohttp
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('football_bot')

# ============================================================================
# CONFIGURATION
# ============================================================================

FOOTBALL_API_KEY = os.getenv('FOOTBALL_API_KEY')  # Add to Railway env vars
FOOTBALL_API_BASE = "https://api.football-data.org/v4"

# Competition IDs
COMPETITIONS = {
    'laliga': 'PD',   # Primera División
    'epl': 'PL',      # Premier League
    'ucl': 'CL'       # Champions League
}

# ============================================================================
# DATA MODELS
# ============================================================================
# DATA MODELS
from datetime import datetime, timedelta, timezone

def is_today_or_tomorrow_safe(utc_date: str) -> bool:
    if not utc_date:
        return False
    try:
        match_time = datetime.fromisoformat(utc_date.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return now.date() <= match_time.date() <= (now + timedelta(days=1)).date()
    except Exception:
        return False


@dataclass
class Match:
    """Real match data from API"""
    id: int
    league: str
    home: str
    away: str
    home_score: int
    away_score: int
    minute: int
    status: str  # SCHEDULED, LIVE, IN_PLAY, PAUSED, FINISHED
    utc_date: str
    
    def is_target_match(self) -> bool:
        """Check if Real Madrid or Barcelona is playing"""
        targets = ['Real Madrid', 'Barcelona', 'FC Barcelona']
        return any(team in self.home or team in self.away for team in targets)
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'league': self.league,
            'home': self.home,
            'away': self.away,
            'home_score': self.home_score,
            'away_score': self.away_score,
            'minute': self.minute,
            'status': self.status
        }

# ============================================================================
# FOOTBALL DATA API CLIENT
# ============================================================================

class FootballDataAPI:
    """
    Client for football-data.org API
    Handles rate limiting, error handling, and data parsing
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = FOOTBALL_API_BASE
        self.headers = {
            'X-Auth-Token': api_key
        }
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Cache to track score changes
        self.previous_scores: Dict[int, tuple] = {}  # match_id -> (home, away)
        self.announced_ft: set = set()
    
    async def _ensure_session(self):
        """Create aiohttp session if not exists"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)
    
    async def close(self):
        """Close aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _get(self, endpoint: str) -> dict:
        """Make GET request to API"""
        await self._ensure_session()
        
        url = f"{self.base_url}/{endpoint}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 429:
                    logger.warning("⚠️ Rate limit hit, waiting 60 seconds")
                    await asyncio.sleep(60)
                    return await self._get(endpoint)
                
                if response.status != 200:
                    logger.error(f"API error {response.status}: {await response.text()}")
                    return {}
                
                return await response.json()
        
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return {}
    
    async def get_matches_by_competition(self, competition_code: str, status: str = None) -> List[Match]:
        """
        Get matches for a competition
        status: SCHEDULED, LIVE, IN_PLAY, PAUSED, FINISHED, or None for all
        """
        endpoint = f"competitions/{competition_code}/matches"
        if status:
            endpoint += f"?status={status}"
        
        data = await self._get(endpoint)
        
        if not data or 'matches' not in data:
            return []
        
        matches = []
        
        for match_data in data['matches']:
            try:
                # Parse match status
                status = match_data.get('status', 'SCHEDULED')
                
                # Parse scores
                score = match_data.get('score', {})
                fulltime = score.get('fullTime', {})
                home_score = fulltime.get('home') or 0
                away_score = fulltime.get('away') or 0
                
                # Parse minute (only available during live matches)
                minute = match_data.get('minute') or 0
                
                # Map competition code back to our league names
                league = next(
                    (k for k, v in COMPETITIONS.items() if v == competition_code),
                    competition_code.lower()
                )
                
                match = Match(
                    id=match_data['id'],
                    league=league,
                    home=match_data['homeTeam']['name'],
                    away=match_data['awayTeam']['name'],
                    home_score=home_score,
                    away_score=away_score,
                    minute=minute,
                    status=status,
                    utc_date=match_data.get('utcDate', '')
                )
                
                matches.append(match)
            
            except Exception as e:
                logger.error(f"Failed to parse match: {e}")
                continue
        
        return matches
    
    async def get_live_matches(self) -> List[Match]:
        """Get all live matches across all competitions"""
        all_matches = []
        
        for league, comp_code in COMPETITIONS.items():
            matches = await self.get_matches_by_competition(comp_code, status="IN_PLAY")
            all_matches.extend(matches)
            
            # Small delay to respect rate limits
            await asyncio.sleep(0.5)
        
        return all_matches
    
    async def get_target_team_matches(self, league: str) -> List[Match]:
        """Get Real Madrid/Barcelona matches for specific league"""
        comp_code = COMPETITIONS.get(league)
        if not comp_code:
            return []
        
        matches = await self.get_matches_by_competition(comp_code)
        
        # Filter for target teams
        return [m for m in matches if m.is_target_match()]
    
    def detect_goals(self, match: Match) -> bool:
        """
        Detect if a new goal was scored since last check
        Returns True if score changed
        """
        match_id = match.id
        current_score = (match.home_score, match.away_score)
        
        if match_id not in self.previous_scores:
            # First time seeing this match
            self.previous_scores[match_id] = current_score
            return False
        
        old_score = self.previous_scores[match_id]
        
        if current_score != old_score:
            # Score changed - GOAL!
            self.previous_scores[match_id] = current_score
            return True
        
        return False
    
    def should_announce_ft(self, match: Match) -> bool:
        """Check if FT should be announced"""
        if match.status == 'FINISHED' and match.id not in self.announced_ft:
            self.announced_ft.add(match.id)
            return True
        return False

# Global API client
football_api = FootballDataAPI(FOOTBALL_API_KEY) if FOOTBALL_API_KEY else None

# ============================================================================
# BOT SETUP
# ============================================================================

intents = discord.Intents.default()
intents.message_content = False

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

_sync_completed = False
_tasks_started = False

# ============================================================================
# BOT EVENTS
# ============================================================================

@client.event
async def on_ready():
    global _sync_completed, _tasks_started
    
    if _sync_completed:
        logger.info(f'🔄 Reconnected as {client.user}')
        return
    
    logger.info(f'🤖 Bot logged in as {client.user}')
    
    # Check API key
    if not football_api:
        logger.error('❌ FOOTBALL_API_KEY not set - bot will not work!')
        return
    
    # Sync commands
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
    await asyncio.sleep(3)
    
    # Start background tasks
    if not _tasks_started:
        match_monitor.start()
        _tasks_started = True
        logger.info('🚀 Bot fully operational with real-time data')

# ============================================================================
# SLASH COMMANDS
# ============================================================================
@tree.command(name="upcoming", description="আজ ও আগামীকালের ম্যাচ দেখাও (Real Madrid / Barcelona)")
async def upcoming(interaction: discord.Interaction):
    await interaction.response.defer()

    if not football_api:
        await interaction.followup.send("❌ API key not configured")
        return

    upcoming_matches = []

    try:
        for league, code in COMPETITIONS.items():
            # ⚠️ status filter বাদ
            matches = await football_api.get_matches_by_competition(code)

            for match in matches:
                if not match.is_target_match():
                    continue

                if not is_today_or_tomorrow_safe(match.utc_date):
                    continue

                # Only future / scheduled matches
                if match.status not in ["SCHEDULED", "TIMED"]:
                    continue

                upcoming_matches.append(match)

            await asyncio.sleep(0.4)

        if not upcoming_matches:
            embed = discord.Embed(
                title="ℹ️ Upcoming Matches",
                description="আজ বা আগামীকাল Real Madrid / Barcelona এর কোনো ম্যাচ নেই",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)
            return

        embed = discord.Embed(
            title="📅 Upcoming Matches",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )

        for match in upcoming_matches:
            kickoff = datetime.fromisoformat(
                match.utc_date.replace('Z', '+00:00')
            ).strftime('%d %b, %I:%M %p UTC')

            embed.add_field(
                name=f"{match.home} vs {match.away}",
                value=(
                    f"🏆 {match.league.upper()}\n"
                    f"⏰ {kickoff}\n"
                    f"📌 Status: {match.status}"
                ),
                inline=False
            )

        embed.set_footer(text="Source: football-data.org")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.exception("❌ Upcoming command failed")
        await interaction.followup.send("❌ Upcoming matches আনতে সমস্যা হয়েছে")


@tree.command(name="ping", description="Check bot status")
async def ping(interaction: discord.Interaction):
    latency = round(client.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Bot is online with real-time football data",
        color=discord.Color.green()
    )
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Data Source", value="football-data.org", inline=True)
    await interaction.response.send_message(embed=embed)

@tree.command(name="live", description="Show all live matches")
async def live(interaction: discord.Interaction):
    await interaction.response.defer()
    
    if not football_api:
        await interaction.followup.send("❌ API key not configured")
        return
    
    try:
        live_matches = await football_api.get_live_matches()
        
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
        
        embed.set_footer(text=f"Requested by {interaction.user.name} • Real-time data")
        await interaction.followup.send(embed=embed)
    
    except Exception as e:
        logger.error(f"Error in /live: {e}")
        await interaction.followup.send("❌ Failed to fetch live matches")

@tree.command(name="laliga", description="Real Madrid/Barcelona in La Liga")
async def laliga(interaction: discord.Interaction):
    await interaction.response.defer()
    
    if not football_api:
        await interaction.followup.send("❌ API key not configured")
        return
    
    try:
        matches = await football_api.get_target_team_matches('laliga')
        
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
                'IN_PLAY': '🔴',
                'LIVE': '🔴',
                'FINISHED': '⚪',
                'SCHEDULED': '🕐'
            }.get(match.status, '⚽')
            
            match_info = (
                f"{status_emoji} **{match.home} {match.home_score} - {match.away_score} {match.away}**\n"
                f"Status: {match.status}"
            )
            
            if match.minute > 0:
                match_info += f" | {match.minute}'"
            
            embed.add_field(
                name=f"{match.home} vs {match.away}",
                value=match_info,
                inline=False
            )
        
        embed.set_footer(text="Real-time data from football-data.org")
        await interaction.followup.send(embed=embed)
    
    except Exception as e:
        logger.error(f"Error in /laliga: {e}")
        await interaction.followup.send("❌ Failed to fetch La Liga matches")

@tree.command(name="epl", description="Real Madrid/Barcelona in Premier League")
async def epl(interaction: discord.Interaction):
    await interaction.response.defer()
    
    if not football_api:
        await interaction.followup.send("❌ API key not configured")
        return
    
    try:
        matches = await football_api.get_target_team_matches('epl')
        
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
                'IN_PLAY': '🔴',
                'LIVE': '🔴',
                'FINISHED': '⚪',
                'SCHEDULED': '🕐'
            }.get(match.status, '⚽')
            
            match_info = (
                f"{status_emoji} **{match.home} {match.home_score} - {match.away_score} {match.away}**\n"
                f"Status: {match.status}"
            )
            
            if match.minute > 0:
                match_info += f" | {match.minute}'"
            
            embed.add_field(
                name=f"{match.home} vs {match.away}",
                value=match_info,
                inline=False
            )
        
        embed.set_footer(text="Real-time data from football-data.org")
        await interaction.followup.send(embed=embed)
    
    except Exception as e:
        logger.error(f"Error in /epl: {e}")
        await interaction.followup.send("❌ Failed to fetch EPL matches")

@tree.command(name="ucl", description="Real Madrid/Barcelona in Champions League")
async def ucl(interaction: discord.Interaction):
    await interaction.response.defer()
    
    if not football_api:
        await interaction.followup.send("❌ API key not configured")
        return
    
    try:
        matches = await football_api.get_target_team_matches('ucl')
        
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
                'IN_PLAY': '🔴',
                'LIVE': '🔴',
                'FINISHED': '⚪',
                'SCHEDULED': '🕐'
            }.get(match.status, '⚽')
            
            match_info = (
                f"{status_emoji} **{match.home} {match.home_score} - {match.away_score} {match.away}**\n"
                f"Status: {match.status}"
            )
            
            if match.minute > 0:
                match_info += f" | {match.minute}'"
            
            embed.add_field(
                name=f"{match.home} vs {match.away}",
                value=match_info,
                inline=False
            )
        
        embed.set_footer(text="Real-time data from football-data.org")
        await interaction.followup.send(embed=embed)
    
    except Exception as e:
        logger.error(f"Error in /ucl: {e}")
        await interaction.followup.send("❌ Failed to fetch UCL matches")

# ============================================================================
# BACKGROUND TASKS
# ============================================================================

@tasks.loop(seconds=60)
async def match_monitor():
    """
    Monitor live matches every 60 seconds
    Announce goals and full-time results
    """
    try:
        if not football_api:
            return
        
        # Get all live matches
        live_matches = await football_api.get_live_matches()
        
        # Also check target team matches for FT announcements
        target_matches = []
        for league in ['laliga', 'epl', 'ucl']:
            matches = await football_api.get_target_team_matches(league)
            target_matches.extend(matches)
            await asyncio.sleep(0.5)
        
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
            return
        
        # Check for goals in live matches
        for match in live_matches:
            if not match.is_target_match():
                continue
            
            if football_api.detect_goals(match):
                embed = discord.Embed(
                    title="⚽ GOAL!",
                    description=f"**{match.home} {match.home_score} - {match.away_score} {match.away}**",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="League", value=match.league.upper(), inline=True)
                embed.add_field(name="Time", value=f"{match.minute}'", inline=True)
                embed.set_footer(text="Real-time update")
                
                await channel.send(embed=embed)
                logger.info(f'⚽ GOAL: {match.home} {match.home_score}-{match.away_score} {match.away}')
        
        # Check for full-time
        for match in target_matches:
            if football_api.should_announce_ft(match):
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

@match_monitor.before_loop
async def before_monitor():
    await client.wait_until_ready()
    logger.info('✅ Match monitor ready (60s interval)')

# ============================================================================
# CLEANUP
# ============================================================================

@client.event
async def on_close():
    """Close API session on shutdown"""
    if football_api:
        await football_api.close()
    logger.info('👋 Bot shutting down')

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    
    if not token:
        logger.error('❌ DISCORD_TOKEN not set')
        exit(1)
    
    if not FOOTBALL_API_KEY:
        logger.error('❌ FOOTBALL_API_KEY not set')
        logger.error('   Get one free at: https://www.football-data.org/client/register')
        exit(1)
    
    logger.info('🚀 Starting Football Bot with real-time data...')
    
    try:
        client.run(token, log_handler=None)
    except KeyboardInterrupt:
        logger.info('⚠️ Bot stopped by user')
    except Exception as e:
        logger.error(f'❌ Fatal error: {e}')
        exit(1)
