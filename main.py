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
    print("--------------------------------------------------")

# ---------------------------------------------------------
# Проверка прав на должности
# ---------------------------------------------------------
def has_role_or_higher(*role_keys):
    async def predicate(ctx):
        if ctx.author == ctx.guild.owner:
            return True
            
        user_role_ids = [r.id for r in ctx.author.roles]
        allowed_ids = [ROLE_IDS[key] for key in role_keys if key in ROLE_IDS]
        
        if any(r_id in user_role_ids for r_id in allowed_ids):
            return True
            
        raise commands.MissingRole("У вас недостаточно прав для использования этой команды!")
    return commands.check(predicate)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole) or isinstance(error, commands.CheckFailure):
        await ctx.send("❌ У вас нет прав для выполнения этой команды!", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Вы указали не все аргументы!", delete_after=5)
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Ошибка в аргументах (проверьте правильность написания чисел или упоминания пользователя).", delete_after=5)
    else:
        print(f"Ошибка в команде: {error}")

# ---------------------------------------------------------
# Функция для назначения/снятия с должности
# ---------------------------------------------------------
async def handle_specific_role(ctx, member: discord.Member, role_key: str, action: str):
    role_id = ROLE_IDS.get(role_key)
    role = ctx.guild.get_role(role_id)
    
    if not role:
        return await ctx.send(f"❌ Должность для `{role_key}` не найдена на сервере (проверьте ID).")
    
    try:
        if action == "add":
            await member.add_roles(role)
            await ctx.send(f"🎖 Участник **{member.display_name}** назначен на должность: **{role.name}**!")
        elif action == "remove":
            await member.remove_roles(role)
            await ctx.send(f"🛡 Участник **{member.display_name}** снят с должности: **{role.name}**.")
    except discord.Forbidden:
        await ctx.send("❌ У бота недостаточно прав (передвиньте роль бота выше в списке ролей сервера).")

# ---------------------------------------------------------
# КОМАНДЫ НАЗНАЧЕНИЯ И СНЯТИЯ С ДОЛЖНОСТЕЙ
# ---------------------------------------------------------

@bot.command(name="gmod")
@has_role_or_higher("gadmin", "gmod")
async def cmd_gmod(ctx, member: discord.Member):
    await handle_specific_role(ctx, member, "gmod", "add")

@bot.command(name="ungmod")
@has_role_or_higher("gadmin", "gmod")
async def cmd_ungmod(ctx, member: discord.Member):
    await handle_specific_role(ctx, member, "gmod", "remove")

@bot.command(name="gadmin")
@has_role_or_higher("gadmin")
async def cmd_gadmin(ctx, member: discord.Member):
    await handle_specific_role(ctx, member, "gadmin", "add")

@bot.command(name="ungadmin")
@has_role_or_higher("gadmin")
async def cmd_ungadmin(ctx, member: discord.Member):
    await handle_specific_role(ctx, member, "gadmin", "remove")

@bot.command(name="admin")
@has_role_or_higher("gadmin")
async def cmd_admin(ctx, member: discord.Member):
    await handle_specific_role(ctx, member, "admin", "add")

@bot.command(name="unadmin")
@has_role_or_higher("gadmin")
async def cmd_unadmin(ctx, member: discord.Member):
    await handle_specific_role(ctx, member, "admin", "remove")

@bot.command(name="mod")
@has_role_or_higher("gadmin", "gmod", "admin")
async def cmd_mod(ctx, member: discord.Member):
    await handle_specific_role(ctx, member, "mod", "add")

@bot.command(name="unmod")
@has_role_or_higher("gadmin", "gmod", "admin")
async def cmd_unmod(ctx, member: discord.Member):
    await handle_specific_role(ctx, member, "mod", "remove")


# ---------------------------------------------------------
# Модерация и Музыка
# ---------------------------------------------------------
@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Удалено сообщений: **{amount}**", delete_after=3)

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "Причина не указана"):
    try:
        await member.send(f"⚠️ Вы были изгнаны с сервера **{ctx.guild.name}**. Причина: {reason}")
    except:
        pass
    await member.kick(reason=reason)
    await ctx.send(f"🚪 Участник **{member.name}** кикнут. Причина: {reason}")

# Команда бана с уведомлением в ЛС и поддержкой количества дней
@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, days: int = 0, *, reason: str = "Причина не указана"):
    # Пытаемся отправить сообщение в ЛС забаненному пользователю
    try:
        if days > 0:
            await member.send(f"⛔️ Вы были забанены на сервере **{ctx.guild.name}** на **{days} дн.** Причина: {reason}")
        else:
            await member.send(f"⛔️ Вы были забанены на сервере **{ctx.guild.name}** навсегда. Причина: {reason}")
    except discord.Forbidden:
        # Если у пользователя закрыты ЛС, бот просто пропустит этот шаг и не выдаст ошибку
        pass

    del_days = min(days, 7) if days > 0 else 0
    await member.ban(reason=reason, delete_message_days=del_days)
    
    if days > 0:
        await ctx.send(f"⛔️ Участник **{member.name}** забанен на **{days} дн.** Причина: {reason}")
    else:
        await ctx.send(f"⛔️ Участник **{member.name}** забанен навсегда. Причина: {reason}")

@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, duration_minutes: int = 10, *, reason: str = "Причина не указана"):
    duration = discord.utils.utcnow() + datetime.timedelta(minutes=duration_minutes)
    await member.timeout(duration, reason=reason)
    await ctx.send(f"🔇 **{member.name}** в муте на {duration_minutes} мин. Причина: {reason}")

@bot.command(name="play")
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

@bot.command(name="stop")
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("⏹ Воспроизведение остановлено, бот отключен.")
    else:
        await ctx.send("❌ Бот не подключен к голосовому каналу.")

token = os.getenv("DISCORD_TOKEN")
if token:
    bot.run(token)
else:
    print("❌ ОШИБКА: Переменная DISCORD_TOKEN не найдена в окружении!")
    
