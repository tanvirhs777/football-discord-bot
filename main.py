import discord
from discord import app_commands
import google.generativeai as genai
import os
import asyncio
import textwrap

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("❌ DISCORD_TOKEN or GEMINI_API_KEY missing")

# ================= GEMINI SETUP =================
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash"
)

# ================= BOT SETUP =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ================= HELPERS =================

async def ask_gemini(prompt: str) -> str:
    try:
        full_prompt = (
            "You are a football assistant.\n"
            "Answer clearly for a Discord message.\n"
            "Use emojis, short paragraphs, and bold team names.\n"
            "Language: Bengali + English mix.\n\n"
            f"Question: {prompt}"
        )

        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, full_prompt),
            timeout=12
        )

        text = response.text.strip()

        # Discord safety (2000 chars)
        return textwrap.shorten(text, width=1800, placeholder="…")

    except asyncio.TimeoutError:
        return "⏳ Gemini একটু বেশি সময় নিচ্ছে, আবার চেষ্টা করো।"
    except Exception as e:
        print("Gemini error:", e)
        return "❌ Gemini থেকে তথ্য আনতে সমস্যা হয়েছে।"

# ================= EVENTS =================

@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Gemini Football Bot online as {client.user}")

# ================= COMMANDS =================

@tree.command(name="ping", description="Bot status check")
async def ping(i: discord.Interaction):
    await i.response.send_message("🏓 Pong! Gemini bot is online.")

@tree.command(name="live", description="বর্তমান লাইভ ম্যাচ (AI summary)")
async def live(i: discord.Interaction):
    await i.response.defer()
    answer = await ask_gemini(
        "Give a summary of current live football matches in major leagues right now."
    )
    await i.followup.send(answer)

@tree.command(name="upcoming", description="আজ ও আগামীকালের ম্যাচ")
async def upcoming(i: discord.Interaction):
    await i.response.defer()
    answer = await ask_gemini(
        "List important football matches for today and tomorrow with Bangladesh time (GMT+6)."
    )
    await i.followup.send(answer)

@tree.command(name="score", description="নির্দিষ্ট ম্যাচের স্কোর")
@app_commands.describe(match="যেমন: Arsenal vs Chelsea")
async def score(i: discord.Interaction, match: str):
    await i.response.defer()
    answer = await ask_gemini(
        f"What is the latest known score or status of this match: {match}?"
    )
    await i.followup.send(answer)

# ================= RUN =================
client.run(DISCORD_TOKEN)
