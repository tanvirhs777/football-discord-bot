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

# Gemini setup (Google Search Tool এনাবল করা হয়েছে)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    tools=[{"google_search_retrieval": {}}] # এটি রিয়েল-টাইম ডেটার জন্য অত্যন্ত জরুরি
)

# ================= BOT SETUP =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

async def ask_gemini(prompt: str) -> str:
    try:
        # জেমিনিকে ইন্টারনেটে সার্চ করে উত্তর দিতে বলা হচ্ছে
        full_prompt = f"Provide the most current and real-time info using Google Search: {prompt}"
        response = await asyncio.to_thread(model.generate_content, full_prompt)
        return response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        return "❌ Gemini থেকে তথ্য আনতে সমস্যা হয়েছে। পরে আবার চেষ্টা করো।"

# ================= EVENTS =================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot online as {client.user}")

# ================= COMMANDS =================

@tree.command(name="live", description="বর্তমান লাইভ ম্যাচ (Google Search দ্বারা)")
async def live(i: discord.Interaction):
    # ডিসকর্ড ৩ সেকেন্ডের বেশি সময় নিলে 'Application did not respond' দেখায়। 
    # তাই আমরা defer() ব্যবহার করছি যাতে বট ভাবার সময় পায়।
    await i.response.defer() 
    
    prompt = (
        "Search for major live football matches happening right now. "
        "Include scores, current minute, and league names. "
        "Reply in concise bullet points with emojis."
    )
    answer = await ask_gemini(prompt)
    await i.followup.send(answer) # defer এর পর followup.send ব্যবহার করতে হয়

@tree.command(name="upcoming", description="আজ ও কালকের ম্যাচের সময়সূচী")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    
    prompt = (
        "Search for important football fixtures for today and tomorrow. "
        "Convert kick-off times to Bangladesh Standard Time (BST/GMT+6). "
        "Use a clean list format."
    )
    answer = await ask_gemini(prompt)
    await i.followup.send(answer)

@tree.command(name="score", description="নির্দিষ্ট ম্যাচের স্কোর চেক করুন")
@app_commands.describe(match="উদাহরণ: Arsenal vs Man City")
async def score(i: discord.Interaction, match: str):
    await i.response.defer()
    
    prompt = f"Find the latest live score and goal scorers for the match: {match}."
    answer = await ask_gemini(prompt)
    await i.followup.send(answer)

# ================= RUN =================
client.run(DISCORD_TOKEN)
