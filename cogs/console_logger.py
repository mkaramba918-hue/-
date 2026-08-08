import sys
import sqlite3
import discord
from discord.ext import commands, tasks


class StreamRedirector:

  def __init__(self, bot):
    self.bot = bot
    self.buffer = ""

  def write(self, message):
    sys.__stdout__.write(message)  чобы в консоль Railway тоже шло
    if message.strip():
      self.bot.loop.create_task(self.send_to_log_channel(message))

  def flush(self):
    sys.__stdout__.flush()

  async def send_to_log_channel(self, message):
    # Берем первый попавшийся сохраненный канал логов из базы settings
    try:
      conn = sqlite3.connect("economy.db")
      cursor = conn.cursor()
      cursor.execute("SELECT value FROM settings WHERE key LIKE 'log_channel_%'")
      rows = cursor.fetchall()
      conn.close()

      for row in rows:
        channel_id = int(row[0])
        channel = self.bot.get_channel(channel_id)
        if channel:
          # Обрезаем сообщение, если оно слишком длинное для Discord (максимум 2000 символов)
          clean_msg = message.strip()[:1900]
          await channel.send(f"🖥️ `LOG:` ```{clean_msg}```")
    except Exception:
      pass


class ConsoleLogger(commands.Cog):

  def __init__(self, bot):
    self.bot = bot
    # Перенаправляем стандартный вывод ошибок и текста
    sys.stderr = StreamRedirector(bot)


async def setup(bot):
  await bot.add_cog(ConsoleLogger(bot))
  
