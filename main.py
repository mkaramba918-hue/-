import os
import asyncio
import datetime
import discord
from discord.ext import commands
import yt_dlp

# ---------------------------------------------------------
# 1. Настройки Intents и Инициализация
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------------------------------------
# 2. Опции yt-dlp с полной защитой от блокировок и DRM
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
    'source_address': '0.0.0.0',  # Принудительно использовать IPv4

    # ⚡️ ОБХОД КАПЧИ И АВТОРИЗАЦИИ YOUTUBE ("Sign in to confirm you're not a bot")
    'extractor_args': {
        'youtube': {
            'player_client': ['tv', 'android'],
            'skip': ['hls', 'dash']
        }
    },
    
    # ⚡️ Обход геоблоков и подмена браузера
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
        
        # Перехват текста, Spotify, Apple Music и поиск через YouTube
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
            # Если прямой доступ заблокирован (DRM/Гео), просим YouTube найти трек по названию
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

# ---------------------------------------------------------
# 3. События Бота
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"🤖 Авторизован как: {bot.user.name} (ID: {bot.user.id})")
    print("--------------------------------------------------")

# ---------------------------------------------------------
# 4. Команды Модерации
# ---------------------------------------------------------
@bot.command(name="clear", help="Удаляет указанное количество сообщений")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Удалено сообщений: **{amount}**", delete_after=3)

@bot.command(name="kick", help="Кикает участника с сервера")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "Причина не указана"):
    await member.kick(reason=reason)
    await ctx.send(f"🚪 Участник **{member.name}** был кикнут. Причина: {reason}")

@bot.command(name="ban", help="Банит участника на сервере")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Причина не указана"):
    await member.ban(reason=reason)
    await ctx.send(f"⛔️ Участник **{member.name}** был забанен. Причина: {reason}")

@bot.command(name="mute", help="Выдает таймаут (мут) участнику в минутах")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, duration_minutes: int = 10, *, reason: str = "Причина не указана"):
    duration = discord.utils.utcnow() + datetime.timedelta(minutes=duration_minutes)
    await member.timeout(duration, reason=reason)
    await ctx.send(f"🔇 **{member.name}** отправлен в мут на {duration_minutes} мин. Причина: {reason}")

# ---------------------------------------------------------
# 5. Музыкальные Команды
# ---------------------------------------------------------
@bot.command(name="play", help="Играет музыку по ссылке или названию")
async def play(ctx, *, url: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Вы должны находиться в голосовом канале!")

    channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        await channel.connect()
    elif ctx.voice_client.channel != channel:
        await ctx.voice_client.move_to(channel)

    async with ctx.typing():
        try:
            player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: print(f'Ошибка плеера: {e}') if e else None)
            await ctx.send(f"🎶 Сейчас играет: **{player.title}**")
        except Exception as e:
            await ctx.send(f"❌ Ошибка воспроизведения: `{str(e)}`")

@bot.command(name="stop", help="Останавливает музыку и отключает бота")
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("⏹ Воспроизведение остановлено, бот отключен.")
    else:
        await ctx.send("❌ Бот не подключен к голосовому каналу.")

@bot.command(name="pause", help="Ставит музыку на паузу")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸ Воспроизведение поставлено на паузу.")

@bot.command(name="resume", help="Продолжает воспроизведение")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Воспроизведение продолжено.")

# ---------------------------------------------------------
# 6. Запуск Бота
# ---------------------------------------------------------
token = os.getenv("DISCORD_TOKEN")
if token:
    bot.run(token)
else:
    print("❌ ОШИБКА: Переменная DISCORD_TOKEN не найдена в окружении!")
    
