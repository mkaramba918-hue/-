import sys
import sqlite3
import discord
from discord.ext import commands

LOG_BUFFER = []
MAX_BUFFER_SIZE = 25


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
      LOG_BUFFER.append(cleaned)
      if len(LOG_BUFFER) > MAX_BUFFER_SIZE:
        LOG_BUFFER.pop(0)
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
    if not isinstance(sys.stdout, OutputInterceptor):
      interceptor = OutputInterceptor(bot)
      sys.stdout = interceptor
      sys.stderr = interceptor

  @discord.app_commands.command(
      name="getlogs", description="Получить последние логи и привязать этот канал"
  )
  async def getlogs_slash(self, interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
      conn = sqlite3.connect("economy.db")
      cursor = conn.cursor()
      cursor.execute(
          "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
          (f"log_channel_{interaction.guild.id}", str(interaction.channel.id)),
      )
      conn.commit()
      conn.close()
    except Exception:
      pass

    if not LOG_BUFFER:
      await interaction.followup.send(
          "📭 Буфер логов пока пуст, но канал успешно привязан!", ephemeral=True
      )
      return

    logs_text = "\n".join(LOG_BUFFER)
    if len(logs_text) > 1900:
      logs_text = logs_text[-1900:]

    await interaction.channel.send(
        f"📜 **Последние логи из буфера:**\n```py\n{logs_text}\n```"
    )
    await interaction.followup.send(
        "✅ Готово! Логи отправлены в чат, а канал привязан для будущих ошибок.",
        ephemeral=True,
    )


# <-- ВОТ СЮДА (в самый конец файла `cogs/console_logger.py`) -->
async def setup(bot):
  print("🔥 КОГ CONSOLE_LOGGER УСПЕШНО ПОДКЛЮЧЕН!")
  await bot.add_cog(ConsoleLogger(bot))
  
