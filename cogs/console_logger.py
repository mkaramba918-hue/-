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
    # Отправляем в Discord только если сообщение не пустое
    if message.strip():
      self.bot.loop.create_task(self.send_log_to_discord(message))

  def flush(self):
    self.original_stdout.flush()


async def send_log_to_discord(bot, message):
  try:
    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()
    # Ищем сохраненный канал логов
    cursor.execute("SELECT value FROM settings WHERE key LIKE 'log_channel_%'")
    rows = cursor.fetchall()
    conn.close()

    for row in rows:
      channel_id = int(row[0])
      channel = bot.get_channel(channel_id)
      if channel:
        clean_msg = message.strip()[:1900]
        await channel.send(f"🖥️ `LOG:` ```{clean_msg}```")
  except Exception:
    pass


class ConsoleLogger(commands.Cog):

  def __init__(self, bot):
    self.bot = bot
    # Перенаправляем стандартный вывод
    self.interceptor = OutputInterceptor(bot)
    sys.stdout = self.interceptor
    sys.stderr = self.interceptor


async def setup(bot):
  await bot.add_cog(ConsoleLogger(bot))
  
