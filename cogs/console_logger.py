import sys
import sqlite3
import discord
from discord.ext import commands


class OutputInterceptor:

  def __init__(self, bot):
    self.bot = bot
    self.original_stdout = sys.stdout
    self.original_stderr = sys.stderr

  def write(self, message):
    self.original_stdout.write(message)
    self.original_stdout.flush()
    
    if message.strip():
      # Передаем bot в асинхронную задачу через замыкание или метод
      self.bot.loop.create_task(self.send_log_to_discord(message))

  def flush(self):
    self.original_stdout.flush()
    self.original_stderr.flush()

  async def send_log_to_discord(self, message):
    try:
      conn = sqlite3.connect("economy.db")
      cursor = conn.cursor()
      # Проверяем, сохранился ли канал в базе данных
      cursor.execute("SELECT value FROM settings WHERE key LIKE 'log_channel_%'")
      rows = cursor.fetchall()
      conn.close()

      for row in rows:
        channel_id = int(row[0])
        channel = self.bot.get_channel(channel_id)
        if channel:
          clean_msg = message.strip()[:1900]
          await channel.send(f"🖥️ `LOG:` ```{clean_msg}```")
    except Exception:
      pass


class ConsoleLogger(commands.Cog):

  def __init__(self, bot):
    self.bot = bot
    interceptor = OutputInterceptor(bot)
    sys.stdout = interceptor
    sys.stderr = interceptor


async def setup(bot):
  await bot.add_cog(ConsoleLogger(bot))
  
