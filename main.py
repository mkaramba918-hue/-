import os
import sys
import asyncio
import datetime
import sqlite3
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
from privates import CreateRoomButtonView
import yt_dlp
import pytz

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

ROLE_IDS = {
    "gmod": 1512588171756699830,
    "gadmin": 1512588171756699830,
    "admin": 1484124657563996170,
    "mod": 1530640511420076143
}

# --- ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ ---
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
cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
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

# --- ПЕРЕХВАТЧИК КОНСОЛИ ---
LOG_BUFFER = []
MAX_BUFFER_SIZE = 25

class ConsoleCapture:
    def __init__(self):
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

    def flush(self):
        self.original_stdout.flush()
        self.original_stderr.flush()

if not isinstance(sys.stdout, ConsoleCapture):
    interceptor = ConsoleCapture()
    sys.stdout = interceptor
    sys.stderr = interceptor

# --- ИНИЦИАЛИЗАЦИЯ DISCORD БОТА ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- ПРОВЕРКА ПРАВ ---
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

async def handle_specific_role_slash(interaction: discord.Interaction, member: discord.Member, role_key: str, action: str):
    role_id = ROLE_IDS.get(role_key)
    role = interaction.guild.get_role(role_id)
    if not role:
        return await interaction.response.send_message(f"❌ Должность для `{role_key}` не найдена на сервере.", ephemeral=True)
    
    try:
        if action == "add":
            await member.add_roles(role)
            await interaction.response.send_message(f"🎖 Участник **{member.display_name}** назначен на должность: **{role.name}**!")
            add_log_entry("Роли", f"{member.name} ({member.id})", interaction.user.name, f"Назначена роль: {role.name}")
        elif action == "remove":
            await member.remove_roles(role)
            await interaction.response.send_message(f"🛡 Участник **{member.display_name}** снят с должности: **{role.name}**.")
            add_log_entry("Роли", f"{member.name} ({member.id})", interaction.user.name, f"Снята роль: {role.name}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ У бота недостаточно прав для выдачи этой роли.", ephemeral=True)

# --- ON_READY ---
@bot.event
async def on_ready():
    print(f"🤖 Авторизован как: {bot.user.name} (ID: {bot.user.id})")
    try:
        bot.add_view(CreateRoomButtonView())
    except Exception:
        pass
    
    try:
        await bot.load_extension("cogs.shop")
        print("✅ Коги успешно загружены!")
    except Exception:
        pass

    try:
        synced = await bot.tree.sync()
        print(f"🌲 Синхронизировано глобальных слэш-команд: {len(synced)}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации команд: {e}")

# --- СОБЫТИЙНОЕ ЛОГИРОВАНИЕ (БЕЗ УЧЁТА БОТОВ) ---

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # Запись в локальную базу данных
    time_str = get_msk_time()
    add_log_entry("Чат", f"#{message.channel.name}", f"{message.author.name} ({message.author.id})", f"Сообщение: {message.content}")

    # Отправка в Discord-канал логов
    if message.channel.id != LOG_CHANNEL_ID:
        log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            content_text = message.content or "*[Текста нет]*"
            log_text = (
                f"📅 **Время МСК:** `{time_str}`\n"
                f"💬 **Новое сообщение**\n"
                f"• **Автор:** {message.author.mention} (`{message.author.id}`)\n"
                f"• **Канал:** {message.channel.mention}\n"
                f"• **Текст:** {content_text}"
            )
            files = []
            if message.attachments:
                for a in message.attachments:
                    try:
                        files.append(await a.to_file())
                    except Exception:
                        pass
            if files:
                await log_channel.send(log_text, files=files)
            else:
                await log_channel.send(log_text)

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    time_str = get_msk_time()
    add_log_entry("Удаление сообщений", f"#{message.channel.name}", f"{message.author.name} ({message.author.id})", f"Удалено: {message.content or '[Медиа/Файл]'}")
    
    log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"📅 **Время МСК:** `{time_str}`\n"
            f"🗑️ **Сообщение удалено**\n"
            f"• **Автор:** {message.author.mention} (`{message.author.id}`)\n"
            f"• **Канал:** {message.channel.mention}\n"
            f"• **Текст:** {message.content or '*[Пусто / Медиа]*'}"
        )

@bot.event
async def on_raw_message_delete(payload):
    if payload.cached_message and payload.cached_message.author.bot:
        return
    if payload.cached_message:
        return

    time_str = get_msk_time()
    target_channel = bot.get_channel(payload.channel_id)
    ch_name = f"#{target_channel.name}" if target_channel else f"<#{payload.channel_id}>"
    add_log_entry("Удаление сообщений", ch_name, "Система (очистка)", f"Удалено сообщение ID: {payload.message_id}")

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or before.content == after.content or not before.guild:
        return

    time_str = get_msk_time()
    add_log_entry("Редактирование", f"#{before.channel.name}", f"{before.author.name} ({before.author.id})", f"Было: {before.content} | Стало: {after.content}")

    log_channel = before.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"📅 **Время МСК:** `{time_str}`\n"
            f"✏️ **Сообщение отредактировано**\n"
            f"• **Автор:** {before.author.mention}\n"
            f"• **Канал:** {before.channel.mention}\n"
            f"• **Было:** {before.content or '*[Пусто]*'}\n"
            f"• **Стало:** {after.content or '*[Пусто]*'}"
        )

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return

    time_str = get_msk_time()
    log_channel = member.guild.get_channel(LOG_CHANNEL_ID)

    if before.channel is None and after.channel is not None:
        add_log_entry("Войс", f"{member.name} ({member.id})", "Сам участник", f"Подключился к каналу {after.channel.name}")
        if log_channel:
            await log_channel.send(
                f"📅 **Время МСК:** `{time_str}`\n"
                f"🔊 **Подключение к войсу**\n• **Участник:** {member.mention}\n• **Канал:** **{after.channel.name}**"
            )
    elif before.channel is not None and after.channel is None:
        add_log_entry("Войс", f"{member.name} ({member.id})", "Сам участник", f"Покинул канал {before.channel.name}")
        if log_channel:
            await log_channel.send(
                f"📅 **Время МСК:** `{time_str}`\n"
                f"🔇 **Выход из войса**\n• **Участник:** {member.mention}\n• **Канал:** **{before.channel.name}**"
            )
    elif before.channel != after.channel:
        add_log_entry("Войс", f"{member.name} ({member.id})", "Сам участник", f"Перешёл: {before.channel.name} ➔ {after.channel.name}")
        if log_channel:
            await log_channel.send(
                f"📅 **Время МСК:** `{time_str}`\n"
                f"🔀 **Перемещение в войсе**\n• **Участник:** {member.mention}\n• **Маршрут:** **{before.channel.name}** ➡️ **{after.channel.name}**"
            )

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    time_str = get_msk_time()
    add_log_entry("Участники", f"{member.name} ({member.id})", "Система", "Вход на сервер")
    log_channel = member.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"📅 **Время МСК:** `{time_str}`\n"
            f"📥 **Новый участник**\n• **Пользователь:** {member.mention} (`{member.id}`)"
        )

@bot.event
async def on_member_remove(member: discord.Member):
    if member.bot:
        return

    time_str = get_msk_time()
    moderator = None
    reason = "Самостоятельный выход"
    try:
        async for entry in member.guild.audit_logs(limit=2, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                moderator = entry.user
                reason = entry.reason or "Причина не указана"
                break
    except Exception:
        pass

    log_channel = member.guild.get_channel(LOG_CHANNEL_ID)
    if moderator and not moderator.bot:
        add_log_entry("Кик", f"{member.name} ({member.id})", moderator.name, reason)
        if log_channel:
            await log_channel.send(
                f"📅 **Время МСК:** `{time_str}`\n"
                f"👢 **Участник изгнан (Кик)**\n"
                f"• **Пользователь:** {member.mention} (`{member.id}`)\n"
                f"• **Выгнал:** {moderator.mention}\n"
                f"• **Причина:** {reason}"
            )
    else:
        add_log_entry("Участники", f"{member.name} ({member.id})", "Система", "Покинул сервер")
        if log_channel:
            await log_channel.send(
                f"📅 **Время МСК:** `{time_str}`\n"
                f"📤 **Участник покинул сервер**\n• **Пользователь:** {member.mention} (`{member.id}`)"
            )

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.bot:
        return

    time_str = get_msk_time()
    log_channel = before.guild.get_channel(LOG_CHANNEL_ID)

    # Логирование ролей
    if before.roles != after.roles:
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        mod_name = "Система / Бот"
        mod_mention = "Неизвестно"

        try:
            async for entry in before.guild.audit_logs(limit=2, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id and not entry.user.bot:
                    mod_name = entry.user.name
                    mod_mention = entry.user.mention
                    break
        except Exception:
            pass

        for r in added:
            add_log_entry("Роли", f"{after.name} ({after.id})", mod_name, f"Выдана роль: {r.name}")
            if log_channel:
                await log_channel.send(
                    f"📅 **Время МСК:** `{time_str}`\n"
                    f"👑 **Роль назначена**\n• **Участник:** {after.mention}\n• **Роль:** {r.mention}\n• **Выдал:** {mod_mention}"
                )
        for r in removed:
            add_log_entry("Роли", f"{after.name} ({after.id})", mod_name, f"Снята роль: {r.name}")
            if log_channel:
                await log_channel.send(
                    f"📅 **Время МСК:** `{time_str}`\n"
                    f"❌ **Роль снята**\n• **Участник:** {after.mention}\n• **Роль:** {r.mention}\n• **Снял:** {mod_mention}"
                )

# --- СЛЭШ-КОМАНДЫ МОДЕРАЦИИ С ЗАПИСЬЮ ИНИЦИАТОРА ---

@bot.tree.command(name="mute_user", description="Замутить пользователя и выдать роль")
@app_commands.default_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Не указана"):
    mute_role = interaction.guild.get_role(MUTE_ROLE_ID)
    if mute_role:
        await member.add_roles(mute_role, reason=f"Мут: {reason}")
    
    duration = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)

    add_log_entry("Мут", f"{member.name} ({member.id})", interaction.user.name, f"Срок: {minutes} мин. | Причина: {reason}")

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="🔇 Выдан мут (таймаут)", color=discord.Color.dark_grey())
        embed.add_field(name="📅 Дата и время (МСК)", value=f"`{get_msk_time()}`", inline=False)
        embed.add_field(name="Пользователь", value=member.mention, inline=False)
        embed.add_field(name="Выдал", value=interaction.user.mention, inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="До", value=duration.strftime('%d.%m.%Y %H:%M'), inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(f"🔇 Пользователь {member.mention} замучен на {minutes} мин.", ephemeral=True)

@bot.tree.command(name="unmute_user", description="Снять мут с пользователя")
@app_commands.default_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    mute_role = interaction.guild.get_role(MUTE_ROLE_ID)
    if mute_role and mute_role in member.roles:
        await member.remove_roles(mute_role, reason=f"Снятие мута: {reason}")
    
    await member.timeout(None, reason=reason)

    add_log_entry("Снятие мута", f"{member.name} ({member.id})", interaction.user.name, reason)

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="🔊 Снят мут", color=discord.Color.green())
        embed.add_field(name="📅 Дата и время (МСК)", value=f"`{get_msk_time()}`", inline=False)
        embed.add_field(name="Пользователь", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Снял мут", value=interaction.user.mention, inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(f"🔊 С пользователя {member.mention} снят мут.", ephemeral=True)

@bot.tree.command(name="ban_user", description="Забанить участника на сервере")
@app_commands.describe(member="Участник", days="Срок бана в днях (0 - навсегда)", reason="Причина бана")
@app_commands.default_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, days: int = 0, reason: str = "Не указана"):
    duration_text = f"на {days} дн." if days > 0 else "навсегда"
    full_reason = f"Срок: {duration_text} | Причина: {reason}"

    try:
        await member.send(f"⛔️ Вы были забанены на сервере **{interaction.guild.name}** ({duration_text}).\n• Причина: {reason}")
    except discord.Forbidden:
        pass

    await member.ban(reason=full_reason)
    add_log_entry("Бан", f"{member.name} ({member.id})", interaction.user.name, full_reason)

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="🚫 Бан участника", color=discord.Color.red())
        embed.add_field(name="📅 Дата и время (МСК)", value=f"`{get_msk_time()}`", inline=False)
        embed.add_field(name="Пользователь", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Забанил", value=interaction.user.mention, inline=False)
        embed.add_field(name="Срок", value=duration_text, inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(f"⛔️ Пользователь {member.mention} забанен ({duration_text}).", ephemeral=True)

@bot.tree.command(name="unban_user", description="Разбанить пользователя по ID")
@app_commands.default_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "Не указана"):
    try:
        uid = int(user_id)
        user = await bot.fetch_user(uid)
    except Exception:
        return await interaction.response.send_message("❌ Указан некорректный ID пользователя.", ephemeral=True)

    try:
        await interaction.guild.unban(user, reason=reason)
    except discord.HTTPException:
        return await interaction.response.send_message("❌ Не удалось разбанить (возможно, он не забанен).", ephemeral=True)

    add_log_entry("Разбан", f"{user.name} ({user.id})", interaction.user.name, reason)

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="🔓 Пользователь разбанен", color=discord.Color.blue())
        embed.add_field(name="📅 Дата и время (МСК)", value=f"`{get_msk_time()}`", inline=False)
        embed.add_field(name="Пользователь", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Разбанил", value=interaction.user.mention, inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(f"🔓 Пользователь {user.mention} успешно разбанен.", ephemeral=True)

@bot.tree.command(name="kick", description="Изгнать участника с сервера")
@app_commands.describe(member="Участник", reason="Причина кика")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_command(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    await member.kick(reason=reason)
    add_log_entry("Кик", f"{member.name} ({member.id})", interaction.user.name, reason)
    await interaction.response.send_message(f"👢 {member.mention} был изгнан. Причина: {reason}")

@bot.tree.command(name="clear", description="Очистить сообщения")
@app_commands.describe(amount="Количество сообщений для удаления")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_command(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    add_log_entry("Очистка чата", f"#{interaction.channel.name}", interaction.user.name, f"Удалено сообщений: {len(deleted)}")
    await interaction.followup.send(f"🧹 Удалено сообщений: **{len(deleted)}**")

@bot.tree.command(name="warn", description="Выдать варн")
@app_commands.default_permissions(manage_roles=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    user_id = member.id
    new_count = update_warns(user_id, 1)

    for level, role_id in WARN_ROLES.items():
        role = interaction.guild.get_role(role_id)
        if role:
            if level == new_count:
                await member.add_roles(role)
            elif role in member.roles:
                await member.remove_roles(role)

    add_log_entry("Варн", f"{member.name} ({member.id})", interaction.user.name, f"Варн ({new_count}/3) | {reason}")

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="⚠️ Выдан варн", color=discord.Color.gold())
        embed.add_field(name="📅 Дата и время (МСК)", value=f"`{get_msk_time()}`", inline=False)
        embed.add_field(name="Пользователь", value=member.mention, inline=True)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Всего варнов", value=f"{new_count}/3", inline=True)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(f"⚠️ {member.mention} получил варн ({new_count}/3).")

    if new_count >= 3:
        cursor.execute("UPDATE warns SET count = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        for role_id in WARN_ROLES.values():
            r = interaction.guild.get_role(role_id)
            if r and r in member.roles:
                await member.remove_roles(r)
        
        await member.ban(reason="Автоматический бан за 3 варна")
        add_log_entry("Бан", f"{member.name} ({member.id})", "Авто-бан (3 варна)", "Превышен лимит предупреждений")

@bot.tree.command(name="unwarn", description="Снять варн")
@app_commands.default_permissions(manage_roles=True)
async def unwarn(interaction: discord.Interaction, member: discord.Member):
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
    await interaction.response.send_message(f"✅ С пользователя {member.mention} снят варн. Всего: {new_count}/3.")

# --- КОМАНДЫ РОЛЕЙ РУКОВОДСТВА ---
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

# --- СИНХРОНИЗАЦИЯ ЧАТА ---
@bot.tree.command(name="sync_chat_history", description="Импортировать историю сообщений в лог-панель")
@app_commands.describe(limit="Количество сообщений (по умолчанию 300)")
@app_commands.checks.has_permissions(administrator=True)
async def sync_chat_history(interaction: discord.Interaction, limit: int = 300):
    await interaction.response.defer(ephemeral=True)
    count = 0
    async for msg in interaction.channel.history(limit=limit, oldest_first=True):
        if msg.content and not msg.author.bot:
            time_str = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
            add_log_entry("Чат", f"#{interaction.channel.name}", f"{msg.author.name} ({msg.author.id})", f"Сообщение: {msg.content}")
            count += 1
    await interaction.followup.send(f"✅ Успешно импортировано **{count}** сообщений из #{interaction.channel.name}!")

# --- ЗАПУСК БОТА И WEB-ПАНЕЛИ ---
if __name__ == "__main__":
    from web import keep_alive
    keep_alive()

    if not DISCORD_TOKEN:
        print("❌ Ошибка: Переменная DISCORD_TOKEN не задана!")
    else:
        bot.run(DISCORD_TOKEN)
