import sys
import sqlite3
import discord
from discord.ext import commands

# Общий буфер для хранения последних логов (например, последние 20 строк)
LOG_BUFFER = []
MAX_BUFFER_SIZE = 20


class OutputInterceptor:

  def __init__(self, bot):
    self.bot = bot
    self.original_stdout = sys.stdout
    self.original_stderr = sys.stderr

  def write(self, message):
    self.original_stdout.write(message)
    self.original_stdout.flush()

    cleaned = message.strip()
    if cleaned:
      # Сохраняем в буфер
      LOG_BUFFER.append(cleaned)
      if len(LOG_BUFFER) > MAX_BUFFER_SIZE:
        LOG_BUFFER.pop(0)

      # Отправляем в сохраненный канал логов
      self.bot.loop.create_task(self.send_log_to_discord(cleaned))

  def flush(self):
    self.original_stdout.flush()
    self.original_stderr.flush()

  async def send_log_to_discord(self, message):
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
          clean_msg = message[:1900]
          await channel.send(f"🖥️ `LOG:` ```{clean_msg}```")
    except Exception:
      pass


class ConsoleLogger(commands.Cog):

  def __init__(self, bot):
    self.bot = bot
    # Перехватываем вывод только один раз, чтобы не было дублей
    if not isinstance(sys.stdout, OutputInterceptor):
      self.interceptor = OutputInterceptor(bot)
      sys.stdout = self.interceptor
      sys.stderr = self.interceptor

  @commands.command(name="getlogs", description="Скинуть накопленные логи")
  async def getlogs(self, ctx):
    if not LOG_BUFFER:
      await ctx.send("📭 Буфер логов пока пуст.")
      return

    # Собираем то, что уже накопилось, в одно или несколько сообщений
    logs_text = "\n".join(LOG_BUFFER)
    # Если текста слишком много, обрезаем под лимит Discord
    if len(logs_text) > 1900:
      logs_text = logs_text[-1900:]

    await ctx.send(
        f"📜 **Последние логи из буфера:**\n```py\n{logs_text}\n```"
    )

    # Также автоматически сохраняем текущий чат как канал для будущих логов
    try:
      conn = sqlite3.connect("economy.db")
      cursor = conn.cursor()
      cursor.execute(
          "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
          (f"log_channel_{ctx.guild.id}", str(ctx.channel.id)),
      )
      conn.commit()
      conn.close()
      await ctx.send(
          f"✅ Этот канал ({ctx.channel.mention}) успешно установлен для"
          " получения будущих логов!"
      )
    except Exception as e:
      await ctx.send(f"⚠️ Ошибка при сохранении канала: {e}")


async def setup(bot):
  await bot.add_cog(ConsoleLogger(bot))
  
