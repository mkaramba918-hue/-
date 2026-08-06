import os
import asyncio
import datetime
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
from threading import Thread
from flask import Flask

# ---------------------------------------------------------
# 0. ВЕБ-СЕРВЕР ДЛЯ ПРЕДОТВРАЩЕНИЯ ОТКЛЮЧЕНИЯ НА RENDER
# ---------------------------------------------------------
app = Flask("")

@app.route("/")
def home():
    return "Bot is alive and running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# ---------------------------------------------------------
# 1. Настройки Intents и Инициализация
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------------------------------------
# ID РОЛЕЙ НА СЕРВЕРЕ
# ---------------------------------------------------------
ROLE_IDS = {
    "gmod": 1512588171756699830,    # Главный модератор
    "gadmin": 1512588171756699830,  # Главный администратор
    "admin": 1484124657563996170,   # Администратор
    "mod": 1530640511420076143      # Модератор
}

# ---------------------------------------------------------
# 2. Настройки yt-dlp и Музыки
# ---------------------------------------------------------
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extractor_args': {
        'youtube': {
            'player_client': ['tv', 'android'],
            'skip': ['hls', 'dash']
        }
    },
    'geo_bypass': True,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        if not url.startswith("http://") and not url.startswith("https://"):
            search_query = f"ytsearch:{url}"
        elif "spotify.com" in url or "apple.com" in url:
            search_query = f"ytsearch:{url}"
        else:
            search_query = url

        try:
            data = await loop.run_in_executor(
                None, 
                lambda: ytdl.extract_info(search_query, download=not stream)
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "drm" in err_msg or "geo restriction" in err_msg or "confirm" in err_msg:
                data = await loop.run_in_executor(
                    None, 
                    lambda: ytdl.extract_info(f"ytsearch:{url}", download=not stream)
                )
            else:
                raise e

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

@bot.event
async def on_ready():
    print(f"🤖 Авторизован как: {bot.user.name} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"🌲 Синхронизировано слэш-команд: {len(synced)}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации слэш-команд: {e}")
    print("--------------------------------------------------")

# ---------------------------------------------------------
# Проверка прав на должности
# ---------------------------------------------------------
def has_role_or_higher(*role_keys):
    async def predicate(interaction: discord.Interaction):
        if interaction.user == interaction.guild.owner:
            return True
            
        user_role_ids = [r.id for r in interaction.user.roles]
        allowed_ids = [ROLE_IDS[key] for key in role_keys if key in ROLE_IDS]
        
        if any(r_id in user_role_ids for r_id in allowed_ids):
            return True
            
        raise app_commands.CheckFailure("У вас недостаточно прав для использования этой команды!")
    return app_commands.check(predicate)

# ---------------------------------------------------------
# Функция для назначения/снятия с должности
# ---------------------------------------------------------
async def handle_specific_role_slash(interaction: discord.Interaction, member: discord.Member, role_key: str, action: str):
    role_id = ROLE_IDS.get(role_key)
    role = interaction.guild.get_role(role_id)
    
    if not role:
        return await interaction.response.send_message(f"❌ Должность для `{role_key}` не найдена на сервере (проверьте ID).", ephemeral=True)
    
    try:
        if action == "add":
            await member.add_roles(role)
            await interaction.response.send_message(f"🎖 Участник **{member.display_name}** назначен на должность: **{role.name}**!")
        elif action == "remove":
            await member.remove_roles(role)
            await interaction.response.send_message(f"🛡 Участник **{member.display_name}** снят с должности: **{role.name}**.")
    except discord.Forbidden:
        await interaction.response.send_message("❌ У бота недостаточно прав (передвиньте роль бота выше в списке ролей сервера).", ephemeral=True)

# ---------------------------------------------------------
# СЛЭШ-КОМАНДЫ НАЗНАЧЕНИЯ И СНЯТИЯ С ДОЛЖНОСТЕЙ
# ---------------------------------------------------------

@bot.tree.command(name="gmod", description="Назначить Главного модератора")
@app_commands.describe(member="Участник")
@has_role_or_higher("gadmin", "gmod")
async def cmd_gmod(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "gmod", "add")

@bot.tree.command(name="ungmod", description="Снять Главного модератора")
@app_commands.describe(member="Участник")
@has_role_or_higher("gadmin", "gmod")
async def cmd_ungmod(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "gmod", "remove")

@bot.tree.command(name="gadmin", description="Назначить Главного администратора")
@app_commands.describe(member="Участник")
@has_role_or_higher("gadmin")
async def cmd_gadmin(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "gadmin", "add")

@bot.tree.command(name="ungadmin", description="Снять Главного администратора")
@app_commands.describe(member="Участник")
@has_role_or_higher("gadmin")
async def cmd_ungadmin(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "gadmin", "remove")

@bot.tree.command(name="admin", description="Назначить Администратора")
@app_commands.describe(member="Участник")
@has_role_or_higher("gadmin")
async def cmd_admin(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "admin", "add")

@bot.tree.command(name="unadmin", description="Снять Администратора")
@app_commands.describe(member="Участник")
@has_role_or_higher("gadmin")
async def cmd_unadmin(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "admin", "remove")

@bot.tree.command(name="mod", description="Назначить Модератора")
@app_commands.describe(member="Участник")
@has_role_or_higher("gadmin", "gmod", "admin")
async def cmd_mod(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "mod", "add")

@bot.tree.command(name="unmod", description="Снять Модератора")
@app_commands.describe(member="Участник")
@has_role_or_higher("gadmin", "gmod", "admin")
async def cmd_unmod(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "mod", "remove")


# ---------------------------------------------------------
# СЛЭШ-КОМАНДЫ МОДЕРАЦИИ И МУЗЫКИ
# ---------------------------------------------------------

@bot.tree.command(name="clear", description="Очистить сообщения в чате")
@app_commands.describe(amount="Количество сообщений для удаления")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int = 5):
    await interaction.channel.purge(limit=amount + 1)
    await interaction.response.send_message(f"🧹 Удалено сообщений: **{amount}**", ephemeral=True)

@bot.tree.command(name="kick", description="Изгнать участника с сервера")
@app_commands.describe(member="Участник", reason="Причина изгнания")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Причина не указана"):
    try:
        await member.send(f"⚠️ Вы были изгнаны с сервера **{interaction.guild.name}**. Причина: {reason}")
    except:
        pass
    await member.kick(reason=reason)
    await interaction.response.send_message(f"🚪 Участник **{member.name}** кикнут. Причина: {reason}")

@bot.tree.command(name="ban", description="Забанить участника на сервере")
@app_commands.describe(member="Участник", days="Количество дней удаления сообщений (0-7)", reason="Причина бана")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, days: int = 0, reason: str = "Причина не указана"):
    try:
        if days > 0:
            await member.send(f"⛔️ Вы были забанены на сервере **{interaction.guild.name}**. Причина: {reason}")
        else:
            await member.send(f"⛔️ Вы были забанены на сервере **{interaction.guild.name}** навсегда. Причина: {reason}")
    except discord.Forbidden:
        pass

    del_days = min(days, 7) if days > 0 else 0
    await member.ban(reason=reason, delete_message_days=del_days)
    await interaction.response.send_message(f"⛔️ Участник **{member.name}** забанен. Причина: {reason}")

@bot.tree.command(name="mute", description="Выдать мут (тайм-аут) участнику")
@app_commands.describe(member="Участник", duration_minutes="Длительность в минутах", reason="Причина мута")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, duration_minutes: int = 10, reason: str = "Причина не указана"):
    duration = discord.utils.utcnow() + datetime.timedelta(minutes=duration_minutes)
    await member.timeout(duration, reason=reason)
    await interaction.response.send_message(f"🔇 **{member.name}** в муте на {duration_minutes} мин. Причина: {reason}")

@bot.tree.command(name="play", description="Включить музыку из YouTube")
@app_commands.describe(url="Ссылка или название трека")
async def play(interaction: discord.Interaction, url: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ Вы должны находиться в голосовом канале!", ephemeral=True)
    
    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    await interaction.response.defer()

    if voice_client is None:
        await channel.connect()
    elif voice_client.channel != channel:
        await voice_client.move_to(channel)

    try:
        player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
        interaction.guild.voice_client.play(player, after=lambda e: print(f'Ошибка плеера: {e}') if e else None)
        await interaction.followup.send(f"🎶 Сейчас играет: **{player.title}**")
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка воспроизведения: `{str(e)}`")

@bot.tree.command(name="stop", description="Остановить музыку и отключить бота")
async def stop(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹ Воспроизведение остановлено, бот отключен.")
    else:
        await interaction.response.send_message("❌ Бот не подключен к голосовому каналу.", ephemeral=True)

# ---------------------------------------------------------
# ОБРАБОТЧИК ОШИБОК ДЛЯ СЛЭШ-КОМАНД
# ---------------------------------------------------------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ У вас недостаточно прав для выполнения этой команды!", ephemeral=True)
    elif isinstance(error, app_commands.CheckFailure):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
    else:
        print(f"Ошибка в слэш-команде: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Произошла ошибка при выполнении команды.", ephemeral=True)

# ---------------------------------------------------------
# ЗАПУСК БОТА И ВЕБ-СЕРВЕРА
# ---------------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ ОШИБКА: Переменная DISCORD_TOKEN не найдена в окружении!")
    
