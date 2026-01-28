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

# Gemini setup (টুলস যোগ করা হয়েছে রিয়েল-টাইম ডেটার জন্য)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    tools=[{"google_search_retrieval": {}}] # এটি ইন্টারনেটে সার্চ করতে সাহায্য করবে
)

# ================= BOT SETUP =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

async def ask_gemini(prompt: str) -> str:
    try:
        # প্রম্পটে একটু তথ্য যোগ করে দেওয়া যাতে সে ইন্টারনেটে খুঁজে দেখে
        full_prompt = f"Using Google Search, provide the most current and real-time info: {prompt}"
        
        response = await asyncio.to_thread(
            model.generate_content,
            full_prompt
        )
        return response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        return "❌ Gemini থেকে তথ্য আনতে সমস্যা হয়েছে। পরে আবার চেষ্টা করো।"

# 

# ================= EVENTS =================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot online as {client.user}")

# ================= COMMANDS =================

@tree.command(name="ping", description="বট ঠিক আছে কি না চেক করার জন্য")
async def ping(i: discord.Interaction):
    await i.response.send_message("🏓 Pong! Gemini bot online ✅")

@tree.command(name="live", description="বর্তমান লাইভ ম্যাচ (Real-time summary)")
async def live(i: discord.Interaction):
    await i.response.defer()
    prompt = (
        "Check current live football matches (Premier League, La Liga, UCL, etc.) right now. "
        "List them in bullet points with scores and current minute."
    )
    answer = await ask_gemini(prompt)
    await i.followup.send(answer)

@tree.command(name="upcoming", description="আজ ও কালকের ম্যাচের সময়সূচী")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    prompt = (
        "Search for major football matches today and tomorrow. "
        "Convert all kick-off times to Bangladesh Standard Time (BST/GMT+6)."
    )
    answer = await ask_gemini(prompt)
    await i.followup.send(answer)

@tree.command(name="score", description="নির্দিষ্ট ম্যাচের একদম লেটেস্ট স্কোর")
@app_commands.describe(match="যেমন: Real Madrid vs Barcelona")
async def score(i: discord.Interaction, match: str):
    await i.response.defer()
    prompt = f"Search for the latest live score and key events of {match}."
    answer = await ask_gemini(prompt)
    await i.followup.send(answer)

# ================= RUN =================
client.run(DISCORD_TOKEN)
