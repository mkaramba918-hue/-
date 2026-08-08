import sqlite3
import discord
from discord.ext import commands


class Logger(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  # Инициализация таблицы для логов при необходимости
  def get_log_channel(self, guild_id):
    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT value FROM settings WHERE key = ?", (f"log_channel_{guild_id}",)
    )
    row = cursor.fetchone()
    conn.close()
    return int(row[0]) if row else None

  @commands.command(name="setlog")
  @commands.has_permissions(administrator=True)
  async def setlog(self, ctx, channel: discord.TextChannel):
    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value"
        " TEXT)"
    )
    cursor.execute(
        "REPLACE INTO settings (key, value) VALUES (?, ?)",
        (f"log_channel_{ctx.guild.id}", str(channel.id)),
    )
    conn.commit()
    conn.close()
    await ctx.send(f"✅ Канал для логов успешно установлен: {channel.mention}")


async def setup(bot):
  await bot.add_cog(Logger(bot))
