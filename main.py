import discord
from discord import app_commands
import google.generativeai as genai
import os
import asyncio

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("DISCORD_TOKEN or GEMINI_API_KEY missing")

# Gemini setup (NO search tool)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ================= BOT SETUP =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

async def ask_gemini(prompt: str) -> str:
    try:
        response = await asyncio.to_thread(
            model.generate_content,
            prompt
        )
        return response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        return "❌ Gemini থেকে তথ্য আনতে সমস্যা হয়েছে। পরে আবার চেষ্টা করো।"

# ================= EVENTS =================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot online as {client.user}")

# ================= COMMANDS =================

@tree.command(name="ping", description="Bot status check")
async def ping(i: discord.Interaction):
    await i.response.send_message("🏓 Pong! Gemini bot online ✅")

@tree.command(name="live", description="বর্তমান লাইভ ম্যাচ (AI summary)")
async def live(i: discord.Interaction):
    await i.response.defer()
    prompt = (
        "Summarize current major live football matches. "
        "If unsure, say no confirmed live matches. "
        "Reply in short bullet points with emojis."
    )
    answer = await ask_gemini(prompt)
    await i.followup.send(answer)

@tree.command(name="upcoming", description="আজ ও কালকের ম্যাচ (AI summary)")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    prompt = (
        "List major football matches scheduled for today and tomorrow. "
        "Times in Bangladesh (GMT+6). "
        "If none, clearly say no matches."
    )
    answer = await ask_gemini(prompt)
    await i.followup.send(answer)

@tree.command(name="score", description="নির্দিষ্ট ম্যাচের স্কোর")
@app_commands.describe(match="উদাহরণ: Arsenal vs Chelsea")
async def score(i: discord.Interaction, match: str):
    await i.response.defer()
    prompt = f"Give the latest known score for the match {match}."
    answer = await ask_gemini(prompt)
    await i.followup.send(answer)

# ================= RUN =================
client.run(DISCORD_TOKEN)
