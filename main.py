import asyncio
from datetime import timedelta
import os
import sys
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

# ==============================================================================
# 🔑 НАСТРОЙКА И ИНИЦИАЛИЗАЦИЯ
# ==============================================================================
# Токен подтягивается из Environment Variables на хостинге
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Хранилище предупреждений
user_warnings = {}

# Очередь воспроизведения {guild_id: [query_1, query_2, ...]}
queues = {}

# Настройки yt-dlp для извлечения аудио
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "extractflat": False,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}

# Настройки FFmpeg для ровного и стабильного потока
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")

    @classmethod
    async def from_url(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=False)
        )

        if "entries" in data:
            data = data["entries"][0]

        filename = data["url"]
        return cls(
            discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data
        )


@bot.event
async def on_ready():
    print("----------------------------------------")
    print(f"🤖 Авторизован как: {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"✅ Успешно синхронизировано {len(synced)} слэш-команд!")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")

    print("🚀 Бот полностью запущен в облаке и готов к работе 24/7!")
    print("----------------------------------------")


# ==============================================================================
# 🎵 МУЗЫКАЛЬНЫЕ КОМАНДЫ (Direct FFmpeg / yt-dlp)
# ==============================================================================


def play_next(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if guild_id in queues and len(queues[guild_id]) > 0:
        next_track = queues[guild_id].pop(0)
        voice_client = interaction.guild.voice_client

        if voice_client and voice_client.is_connected():

            async def start_play():
                try:
                    player = await YTDLSource.from_url(
                        next_track, loop=bot.loop
                    )
                    voice_client.play(
                        player,
                        after=lambda e: (
                            print(f"Ошибка воспроизведения: {e}")
                            if e
                            else play_next(interaction)
                        ),
                    )
                    if interaction.channel:
                        await interaction.channel.send(
                            f"▶️ Сейчас играет: **{player.title}**"
                        )
                except Exception as ex:
                    print(f"Ошибка воспроизведения трека: {ex}")
                    play_next(interaction)

            asyncio.run_coroutine_threadsafe(start_play(), bot.loop)


@bot.tree.command(
    name="play", description="Включить песню по названию или ссылке"
)
async def play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        await interaction.response.send_message(
            "❌ Сначала зайдите в голосовой канал!", ephemeral=True
        )
        return

    await interaction.response.defer()

    voice_client = interaction.guild.voice_client

    if not voice_client:
        try:
            voice_client = await interaction.user.voice.channel.connect()
        except Exception as e:
            await interaction.followup.send(
                f"❌ Не удалось подключиться к каналу: `{e}`"
            )
            return

    guild_id = interaction.guild_id
    if guild_id not in queues:
        queues[guild_id] = []

    if voice_client.is_playing() or voice_client.is_paused():
        queues[guild_id].append(query)
        await interaction.followup.send(
            f"➕ Добавлено в очередь: `{query}`"
        )
    else:
        try:
            player = await YTDLSource.from_url(query, loop=bot.loop)
            voice_client.play(
                player,
                after=lambda e: (
                    print(f"Ошибка: {e}") if e else play_next(interaction)
                ),
            )
            await interaction.followup.send(
                f"▶️ Сейчас играет: **{player.title}**"
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Ошибка загрузки трека: `{e}`"
            )


@bot.tree.command(name="skip", description="Пропустить текущую песню")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await interaction.response.send_message("⏭️ Трек пропущен.")
    else:
        await interaction.response.send_message(
            "❌ Сейчас ничего не играет.", ephemeral=True
        )


@bot.tree.command(name="pause", description="Поставить песню на паузу")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Воспроизведение приостановлено.")
    else:
        await interaction.response.send_message(
            "❌ Воспроизведение не запущенo или уже на паузе.", ephemeral=True
        )


@bot.tree.command(name="resume", description="Снять песню с паузы")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Воспроизведение продолжено.")
    else:
        await interaction.response.send_message(
            "❌ Музыка не стоит на паузе.", ephemeral=True
        )


@bot.tree.command(name="stop", description="Остановить музыку и отключить бота")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    guild_id = interaction.guild_id

    if guild_id in queues:
        queues[guild_id].clear()

    if vc:
        vc.stop()
        await vc.disconnect()
        await interaction.response.send_message(
            "⏹️ Воспроизведение остановлено, бот отключен."
        )
    else:
        await interaction.response.send_message(
            "❌ Бот не находится в голосовом канале.", ephemeral=True
        )


# ==============================================================================
# 🛡️ КОМАНДЫ МОДЕРАЦИИ
# ==============================================================================


@bot.tree.command(
    name="clear", description="Удалить указанное количество сообщений"
)
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message(
            "❌ Укажите число больше 0.", ephemeral=True
        )
        return

    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(
        f"🧹 Успешно удалено {len(deleted)} сообщений.", ephemeral=True
    )


@bot.tree.command(name="kick", description="Выгнать участника с сервера")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Не указана",
):
    if member == interaction.user:
        await interaction.response.send_message(
            "❌ Вы не можете кикнуть самого себя!", ephemeral=True
        )
        return

    await member.kick(reason=reason)
    await interaction.response.send_message(
        f"👢 {member.mention} был кикнут.\n**Причина:** {reason}"
    )


@bot.tree.command(name="ban", description="Забанить участника на сервере")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Не указана",
):
    if member == interaction.user:
        await interaction.response.send_message(
            "❌ Вы не можете забанить самого себя!", ephemeral=True
        )
        return

    await member.ban(reason=reason)
    await interaction.response.send_message(
        f"🔨 {member.mention} забанен.\n**Причина:** {reason}"
    )


@bot.tree.command(
    name="unban", description="Разбанить пользователя по ID или имени"
)
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_input: str):
    await interaction.response.defer(ephemeral=True)

    banned_users = [entry async for entry in interaction.guild.bans()]
    user_to_unban = None

    for ban_entry in banned_users:
        user = ban_entry.user
        if str(user.id) == user_input or str(user) == user_input:
            user_to_unban = user
            break

    if user_to_unban is None:
        await interaction.followup.send(
            f"❌ Пользователь `{user_input}` не найден в списке банов."
        )
        return

    await interaction.guild.unban(user_to_unban)
    await interaction.followup.send(
        f"🔓 Пользователь **{user_to_unban}** успешно разбанен!"
    )


@bot.tree.command(name="mute", description="Выдать тайм-аут участнику")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: int,
    reason: str = "Не указана",
):
    if minutes <= 0:
        await interaction.response.send_message(
            "❌ Время должно быть больше 0 минут.", ephemeral=True
        )
        return

    time = timedelta(minutes=minutes)
    await member.timeout(time, reason=reason)
    await interaction.response.send_message(
        f"🔇 {member.mention} получил мут на {minutes} мин.\n**Причина:** {reason}"
    )


@bot.tree.command(name="unmute", description="Снять тайм-аут с участника")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(
        f"🔊 Мут с {member.mention} успешно снят!"
    )


@bot.tree.command(
    name="warn", description="Выдать предупреждение пользователю"
)
@app_commands.checks.has_permissions(kick_members=True)
async def warn(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Не указана",
):
    if member.id not in user_warnings:
        user_warnings[member.id] = []

    user_warnings[member.id].append(reason)

    await interaction.response.send_message(
        f"⚠️ {member.mention} получил предупреждение.\n"
        f"**Причина:** {reason}\n"
        f"**Всего предупреждений:** {len(user_warnings[member.id])}"
    )


@bot.tree.command(
    name="unwarn",
    description="Снять предупреждение (номер варна или 0 чтобы снять все)",
)
@app_commands.checks.has_permissions(kick_members=True)
async def unwarn(
    interaction: discord.Interaction,
    member: discord.Member,
    warn_number: int = 0,
):
    if member.id not in user_warnings or not user_warnings[member.id]:
        await interaction.response.send_message(
            f"❌ У {member.mention} нет активных предупреждений.",
            ephemeral=True,
        )
        return

    if warn_number <= 0:
        user_warnings[member.id].clear()
        await interaction.response.send_message(
            f"🧹 Все предупреждения с {member.mention} успешно сняты!"
        )
        return

    if warn_number > len(user_warnings[member.id]):
        await interaction.response.send_message(
            f"❌ У пользователя всего {len(user_warnings[member.id])} варн(а). Укажите правильный номер!",
            ephemeral=True,
        )
        return

    removed_reason = user_warnings[member.id].pop(warn_number - 1)
    await interaction.response.send_message(
        f'✅ Предупреждение №{warn_number} (*"{removed_reason}"*) с {member.mention} снято.\n'
        f"Осталось предупреждений: {len(user_warnings[member.id])}"
    )


@bot.tree.command(
    name="warnings", description="Посмотреть предупреждения пользователя"
)
async def warnings(
    interaction: discord.Interaction, member: discord.Member = None
):
    target = member or interaction.user

    if target.id not in user_warnings or not user_warnings[target.id]:
        await interaction.response.send_message(
            f"✅ У {target.mention} нет активных предупреждений."
        )
        return

    text = "\n".join(
        f"{i+1}. {w}" for i, w in enumerate(user_warnings[target.id])
    )
    await interaction.response.send_message(
        f"⚠️ Предупреждения {target.mention}:\n{text}"
    )


# ==============================================================================
# ⚙️ ОБРАБОТКА ОШИБОК И ЗАПУСК
# ==============================================================================


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ У вас недостаточно прав для использования этой команды!"
    else:
        print(f"Ошибка команды: {error}", file=sys.stderr)
        msg = f"⚠️ Произошла ошибка: `{error}`"

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        print(
            "❌ Ошибка: Переменная DISCORD_TOKEN не найдена! Укажите её в настройках хостинга."
        )
    else:
        bot.run(TOKEN)
      
