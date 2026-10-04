import os
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

from keep_alive import keep_alive

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

keep_alive()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


async def load_extensions():
    await bot.load_extension("cogs.general")
    await bot.load_extension("cogs.moderation")
    await bot.load_extension("cogs.schedule")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Connected to {len(bot.guilds)} server(s)")


async def main():
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)


asyncio.run(main())