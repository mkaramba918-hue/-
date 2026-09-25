import os
import sys
import asyncio
import datetime
import sqlite3
import pytz
import random
import discord
from discord.ext import commands
from discord import app_commands
from privates import CreateRoomButtonView, RoomSettingsView

def get_msk_time():
    msk = pytz.timezone('Europe/Moscow')
    return datetime.datetime.now(msk).strftime("%d.%m.%Y %H:%M:%S")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = 1535375319517626448
MUTE_ROLE_ID = 1530607100701442208

WARN_ROLES = {
    1: 1512870192076685442,
    2: 1512870420339101746,
    3: 1512870515960971274
}

DB_NAME = "database.db"

def get_db_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

conn = get_db_conn()
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS warns (
    user_id INTEGER PRIMARY KEY,
    count INTEGER DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS mod_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time_msk TEXT,
    category TEXT,
    target_user TEXT,
    moderator TEXT,
    reason TEXT,
    audio_file TEXT DEFAULT ''
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    points INTEGER DEFAULT 0,
    last_reward TEXT DEFAULT "2000-01-01"
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS shop_roles (
    role_id INTEGER PRIMARY KEY,
    price INTEGER NOT NULL,
    owner_id INTEGER DEFAULT 0,
    purchases INTEGER DEFAULT 0
)
""")
conn.commit()

def add_log_entry(category: str, target: str, moderator: str, reason: str, audio_file: str = ""):
    time_str = get_msk_time()
    try:
        db = get_db_conn()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO mod_logs (time_msk, category, target_user, moderator, reason, audio_file) VALUES (?, ?, ?, ?, ?, ?)",
            (time_str, category, target, moderator, reason, audio_file)
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"[DB LOG ERROR]: {e}")

def get_warns(user_id: int) -> int:
    cursor.execute("SELECT count FROM warns WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def update_warns(user_id: int, delta: int) -> int:
    current = get_warns(user_id)
    new_count = max(0, current + delta)
    cursor.execute("INSERT OR REPLACE INTO warns (user_id, count) VALUES (?, ?)", (user_id, new_count))
    conn.commit()
    return new_count

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 Основной бот запущен: {bot.user.name} (ID: {bot.user.id})")
    
    # Регистрация кнопок приваток
    bot.add_view(CreateRoomButtonView())
    bot.add_view(RoomSettingsView())

    # Загрузка модуля приваток
    try:
        await bot.load_extension("privates")
        print("✅ Модуль приваток (privates.py) успешно загружен!")
    except Exception as e:
        print(f"❌ Ошибка загрузки privates.py: {e}")

    try:
        synced = await bot.tree.sync()
        print(f"🌲 Синхронизировано команд: {len(synced)}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации слэш-команд: {e}")

# --- ПЕРЕХВАТ СОБЫТИЙ (БОТЫ ИСКЛЮЧЕНЫ) ---
@bot.event
async def on_message(message: discord.Message):
    if not message.guild or message.author.bot:
        return

    time_str = get_msk_time()
    add_log_entry("Чат", f"#{message.channel.name}", f"{message.author.name} ({message.author.id})", f"Сообщение: {message.content}")

    if message.channel.id != LOG_CHANNEL_ID:
        log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            text = (
                f"📅 **Время МСК:** `{time_str}`\n"
                f"💬 **Новое сообщение**\n"
                f"• **Автор:** {message.author.mention} (`{message.author.id}`)\n"
                f"• **Канал:** {message.channel.mention}\n"
                f"• **Текст:** {message.content or '*[Вложения/Медиа]*'}"
            )
            files = []
            if message.attachments:
                for a in message.attachments:
                    try:
                        files.append(await a.to_file())
                    except Exception:
                        pass
            if files:
                await log_channel.send(text, files=files)
            else:
                await log_channel.send(text)

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild or message.author.bot:
        return

    mod_str = f"{message.author.name} ({message.author.id})"
    try:
        async for entry in message.guild.audit_logs(limit=2, action=discord.AuditLogAction.message_delete):
            if entry.target.id == message.author.id and not entry.user.bot:
                mod_str = f"{entry.user.name} ({entry.user.id})"
                break
    except Exception:
        pass

    add_log_entry("Удаление сообщений", f"#{message.channel.name}", mod_str, f"Содержимое: {message.content or '*[Пусто/Медиа]*'}")

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not before.guild or before.author.bot or before.content == after.content:
        return

    add_log_entry(
        "Редактирование",
        f"#{before.channel.name}",
        f"{before.author.name} ({before.author.id})",
        f"Было: {before.content} | Стало: {after.content}"
    )

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return

    u_tag = f"{member.name} ({member.id})"
    if before.channel is None and after.channel is not None:
        add_log_entry("Войс", u_tag, member.name, f"Подключился к «{after.channel.name}»")
    elif before.channel is not None and after.channel is None:
        add_log_entry("Войс", u_tag, member.name, f"Покинул «{before.channel.name}»")
    elif before.channel != after.channel:
        add_log_entry("Войс", u_tag, member.name, f"Перешел: «{before.channel.name}» ➔ «{after.channel.name}»")

# --- КОМАНДЫ МОДЕРИРОВАНИЯ ---
@bot.tree.command(name="mute_user", description="Замутить участника на время (в минутах)")
@app_commands.default_permissions(moderate_members=True)
async def mute_cmd(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Не указана"):
    mute_role = interaction.guild.get_role(MUTE_ROLE_ID)
    if mute_role:
        await member.add_roles(mute_role, reason=f"Мут: {reason}")

    duration = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)

    add_log_entry("Мут", f"{member.name} ({member.id})", interaction.user.name, f"Срок: {minutes} мин. | Причина: {reason}")
    await interaction.response.send_message(f"🔇 Участник {member.mention} замучен на {minutes} мин. Инициатор: {interaction.user.mention}")

@bot.tree.command(name="unmute_user", description="Снять мут с участника")
@app_commands.default_permissions(moderate_members=True)
async def unmute_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    mute_role = interaction.guild.get_role(MUTE_ROLE_ID)
    if mute_role and mute_role in member.roles:
        await member.remove_roles(mute_role, reason=f"Снятие мута: {reason}")

    await member.timeout(None, reason=reason)
    add_log_entry("Снятие мута", f"{member.name} ({member.id})", interaction.user.name, reason)
    await interaction.response.send_message(f"🔊 Мут с {member.mention} успешно снят. Инициатор: {interaction.user.mention}")

@bot.tree.command(name="ban_user", description="Забанить участника на сервере")
@app_commands.default_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, member: discord.Member, days: int = 0, reason: str = "Не указана"):
    dur = f"на {days} дн." if days > 0 else "навсегда"
    await member.ban(reason=f"Срок: {dur} | Инициатор: {interaction.user.name} | Причина: {reason}")
    add_log_entry("Бан", f"{member.name} ({member.id})", interaction.user.name, f"{dur} | {reason}")
    await interaction.response.send_message(f"⛔️ Участник {member.mention} забанен ({dur}).")

@bot.tree.command(name="unban_user", description="Разбанить пользователя по ID")
@app_commands.default_permissions(ban_members=True)
async def unban_cmd(interaction: discord.Interaction, user_id: str, reason: str = "Не указана"):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
        add_log_entry("Разбан", f"{user.name} ({user.id})", interaction.user.name, reason)
        await interaction.response.send_message(f"🔓 Пользователь {user.mention} успешно разбанен.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Ошибка разбана: {e}", ephemeral=True)

@bot.tree.command(name="kick", description="Выгнать участника с сервера")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    await member.kick(reason=f"Инициатор: {interaction.user.name} | {reason}")
    add_log_entry("Кик", f"{member.name} ({member.id})", interaction.user.name, reason)
    await interaction.response.send_message(f"👢 Участник {member.mention} был изгнан.")

@bot.tree.command(name="clear", description="Очистить сообщения в чате")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_cmd(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    add_log_entry("Очистка чата", f"#{interaction.channel.name}", interaction.user.name, f"Удалено: {len(deleted)}")
    await interaction.followup.send(f"🧹 Удалено сообщений: **{len(deleted)}**")

@bot.tree.command(name="warn", description="Выдать варн")
@app_commands.default_permissions(manage_roles=True)
async def warn_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    new_count = update_warns(member.id, 1)

    for level, role_id in WARN_ROLES.items():
        role = interaction.guild.get_role(role_id)
        if role:
            if level == new_count:
                await member.add_roles(role)
            elif role in member.roles:
                await member.remove_roles(role)

    add_log_entry("Варн", f"{member.name} ({member.id})", interaction.user.name, f"Варн ({new_count}/3) | {reason}")
    await interaction.response.send_message(f"⚠️ {member.mention} получил варн ({new_count}/3). Причина: {reason}")

    if new_count >= 3:
        cursor.execute("UPDATE warns SET count = 0 WHERE user_id = ?", (member.id,))
        conn.commit()
        await member.ban(reason="Автоматический бан за 3 варна")
        add_log_entry("Бан", f"{member.name} ({member.id})", "Авто-бан (3 варна)", "Превышен лимит варнов")

@bot.tree.command(name="unwarn", description="Снять варн")
@app_commands.default_permissions(manage_roles=True)
async def unwarn_cmd(interaction: discord.Interaction, member: discord.Member):
    new_count = update_warns(member.id, -1)
    for role_id in WARN_ROLES.values():
        role = interaction.guild.get_role(role_id)
        if role and role in member.roles:
            await member.remove_roles(role)

    if new_count > 0 and new_count in WARN_ROLES:
        role_to_give = interaction.guild.get_role(WARN_ROLES[new_count])
        if role_to_give:
            await member.add_roles(role_to_give)

    add_log_entry("Снятие варна", f"{member.name} ({member.id})", interaction.user.name, f"Осталось: {new_count}/3")
    await interaction.response.send_message(f"✅ С {member.mention} снят варн. Всего: {new_count}/3.")

@bot.tree.command(name="slowmode", description="Установить медленный режим в секундах")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int):
    await interaction.channel.edit(slowmode_delay=seconds)
    add_log_entry("Каналы", f"#{interaction.channel.name}", interaction.user.name, f"Медленный режим: {seconds} сек.")
    await interaction.response.send_message(f"⏳ Медленный режим: **{seconds} сек.**" if seconds > 0 else "⏳ Медленный режим отключен.")

@bot.tree.command(name="lock", description="Заблокировать отправку сообщений в канале")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock_channel(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    add_log_entry("Безопасность", f"#{interaction.channel.name}", interaction.user.name, "Канал заблокирован (/lock)")
    await interaction.response.send_message("🔒 Канал закрыт для отправки сообщений.")

@bot.tree.command(name="unlock", description="Открыть канал для общения")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock_channel(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    add_log_entry("Безопасность", f"#{interaction.channel.name}", interaction.user.name, "Канал открыт (/unlock)")
    await interaction.response.send_message("🔓 Канал открыт.")

@bot.tree.command(name="userinfo", description="Посмотреть информацию об участнике")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    roles = [r.mention for r in target.roles if r.name != "@everyone"]
    roles_str = ", ".join(roles) if roles else "Нет ролей"

    created = target.created_at.strftime("%d.%m.%Y %H:%M")
    joined = target.joined_at.strftime("%d.%m.%Y %H:%M") if target.joined_at else "Неизвестно"

    embed = discord.Embed(title=f"Досье: {target.display_name}", color=target.color)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="ID", value=f"`{target.id}`", inline=True)
    embed.add_field(name="Бот?", value="Да" if target.bot else "Нет", inline=True)
    embed.add_field(name="Дата регистрации", value=created, inline=False)
    embed.add_field(name="Присоединился", value=joined, inline=False)
    embed.add_field(name=f"Роли [{len(roles)}]", value=roles_str, inline=False)
    await interaction.response.send_message(embed=embed)

# --- РАЗВЛЕКАТЕЛЬНЫЕ КОМАНДЫ ---
@bot.tree.command(name="coinflip", description="Подбросить монетку (Орёл или Решка)")
async def coinflip(interaction: discord.Interaction):
    await interaction.response.send_message(random.choice(["🪙 Выпал **Орёл**!", "🪙 Выпала **Решка**!"]))

@bot.tree.command(name="roll", description="Случайное число от 1 до указанного максимума")
async def roll(interaction: discord.Interaction, max_val: int = 100):
    if max_val < 1:
        return await interaction.response.send_message("❌ Число должно быть больше 0!", ephemeral=True)
    await interaction.response.send_message(f"🎲 Вам выпало число: **{random.randint(1, max_val)}** (из {max_val})")

@bot.tree.command(name="poll", description="Создать быстрое голосование")
async def poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(title="📊 Голосование", description=question, color=discord.Color.blue())
    embed.set_footer(text=f"Автор: {interaction.user.display_name}")
    await interaction.response.send_message("✅ Голосование создано!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Ошибка: Переменная DISCORD_TOKEN не задана!")
    else:
        bot.run(DISCORD_TOKEN)
