import os
import sqlite3
import asyncio
import threading
import discord
from discord.ext import commands
from dotenv import load_dotenv
from flask import Flask, request, jsonify

# 1. Load Token
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# 2. Database Setup
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            xp INTEGER DEFAULT 0,
            is_premium INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 3. Flask Webhook Server Setup
app = Flask(__name__)

@app.route('/whop-webhook', methods=['POST'])
def whop_webhook():
    data = request.json or {}
    print(f" Received Webhook Payload: {data}")
    
    event_type = data.get('action') or data.get('event')
    
    if event_type in ['membership.activated', 'membership.went_valid', 'payment.succeeded']:
        discord_id = data.get('user', {}).get('social_accounts', {}).get('discord', {}).get('id')
        if discord_id:
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            # Ensure user exists before setting premium
            cursor.execute("INSERT OR IGNORE INTO users (user_id, username, xp, is_premium) VALUES (?, ?, 0, 1)", (int(discord_id), "Unknown"))
            cursor.execute("UPDATE users SET is_premium = 1 WHERE user_id = ?", (int(discord_id),))
            conn.commit()
            conn.close()
            print(f" User {discord_id} upgraded to Premium!")

    return jsonify({'status': 'received'}), 200

def run_flask():
    app.run(host='0.0.0.0', port=5000)

# 4. Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f" Logged in as: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f" Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f" Sync error: {e}")

# Command: /ping
@bot.tree.command(name="ping", description="Test bot response time")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! Latency: {latency}ms")

# Command: /info
@bot.tree.command(name="info", description="Check devbox bot status")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="DevBox Bot Status",
        description="Bot is running locally on devPC.",
        color=0x3498db
    )
    embed.add_field(name="Owner", value=interaction.user.mention, inline=True)
    embed.add_field(name="Status", value="Online", inline=True)
    await interaction.response.send_message(embed=embed)

# Command: /daily
@bot.tree.command(name="daily", description="Claim daily XP and save to database")
async def daily(interaction: discord.Interaction):
    await interaction.response.defer()

    def db_work():
        conn = sqlite3.connect('database.db', timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT xp FROM users WHERE user_id = ?", (interaction.user.id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO users (user_id, username, xp, is_premium) VALUES (?, ?, 10, 0)", 
                           (interaction.user.id, str(interaction.user)))
            new_xp = 10
        else:
            new_xp = row[0] + 10
            cursor.execute("UPDATE users SET xp = ? WHERE user_id = ?", (new_xp, interaction.user.id))
        conn.commit()
        conn.close()
        return new_xp

    new_xp = await asyncio.to_thread(db_work)
    await interaction.followup.send(f" Daily claimed! **{interaction.user.name}**, your total balance is now **{new_xp} XP**.")

# Command: /status (With Deferral Fix)
@bot.tree.command(name="status", description="Check your current subscription tier")
async def status(interaction: discord.Interaction):
    # 1. Acknowledge Discord immediately to prevent 3-second timeout
    await interaction.response.defer()

    def db_work():
        conn = sqlite3.connect('database.db', timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT is_premium FROM users WHERE user_id = ?", (interaction.user.id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0

    is_premium = await asyncio.to_thread(db_work)

    # 2. Send follow-up message back to user
    if is_premium == 1:
        await interaction.followup.send(" You hold an active **Premium Plan**!")
    else:
        await interaction.followup.send(" You are on the **Free Tier**. Upgrade via Whop to unlock Premium.")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)