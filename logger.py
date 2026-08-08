import logging
import discord
from discord.ext import commands

class DiscordLogHandler(logging.Handler):
    """Обработчик, который перехватывает логи Python/хостинга и отправляет их в Discord моментально."""
    def __init__(self, bot, channel_id: int):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    def emit(self, record):
        log_entry = self.format(record)
        # Запускаем отправку в фоновой задаче бота без блокировки потока
        self.bot.loop.create_task(self.send_log(log_entry))

    async def send_log(self, message: str):
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                # Обрезаем сообщение под лимит Discord (2000 символов)
                if len(message) > 1900:
                    message = message[:1900] + "..."
                await channel.send(f"```ini\n{message}\n```")
            except Exception as e:
                print(f"Ошибка отправки лога в канал: {e}")


class HostLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ID вашего канала для логов (замените на нужный ID)
        self.LOG_CHANNEL_ID = 123456789012345678 

        # Подключаем перехватчик к системе логирования Python
        self.handler = DiscordLogHandler(self.bot, self.LOG_CHANNEL_ID)
        self.handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
        
        root_logger = logging.getLogger()
        root_logger.addHandler(self.handler)
        root_logger.setLevel(logging.INFO)

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Система логов успешно активирована. Бот {self.bot.user} в сети.")

    # Пример удобной функции для отправки кастомных логов (например, о покупках)
    async def send_custom_log(self, text: str):
        channel = self.bot.get_channel(self.LOG_CHANNEL_ID)
        if channel:
            await channel.send(f"📢 {text}")


async def setup(bot):
  await bot.add_cog(HostLogger(bot))
  
