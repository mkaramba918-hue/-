import os
import sys
import asyncio
import datetime
import sqlite3
import random
import logging
from threading import Thread

import discord
from discord.ext import commands, tasks
from discord import app_commands
import yt_dlp

from privates import CreateRoomButtonView, RoomSettingsView

# --- ВРЕМЯ МСК (Без сторонних библиотек pytz) ---
def get_msk_time():
    tz_msk = datetime.timezone(datetime.timedelta(hours=3))
    return datetime.datetime.now(tz_msk).strftime("%d.%m.%Y %H:%M:%S")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = 1535375319517626448
MUTE_ROLE_ID = 1530607100701442208

WARN_ROLES = {
    1: 1512870192076685442,
    2: 1512870420339101746,
    3: 1512870515960971274
}

# --- ПОЛНАЯ ИЕРАРХИЯ РОЛЕЙ STAFF ---
# Укажите реальные ID ролей с вашего сервера
ROLE_IDS = {
    "owner": 1512597517966114946,       # 👑 Owner
    "co_owner": 1512597740494782666,    # ⭐ Co-Owner
    "head_admin": 1512588171756699830,  # 🔷 Head Administrator
    "admin": 1484124657563996170,       # 🛠️ Administrator
    "head_mod": 1512588171756699830,    # 👑 Head Moderator
    "senior_mod": 1554890230270533775,  # ⚖️ Senior Moderator
    "mod": 1530640511420076143,         # 🔨 Moderator
    "support_cur": 1512396871665193076, # 🛡️ Support Curator
    "support": 1530640511420076143      # 👤 Support
}

# Множество всех должностей Staff для контроля ЧСА
STAFF_ROLE_IDS = set(ROLE_IDS.values())

# Группы доступа
LEADERSHIP_ROLES = ["owner", "co_owner", "head_admin"]
ADMIN_ROLES = LEADERSHIP_ROLES + ["admin", "head_mod"]
SENIOR_MOD_ROLES = ADMIN_ROLES + ["senior_mod"]
MOD_ROLES = SENIOR_MOD_ROLES + ["mod", "support_cur"]
ALL_STAFF_ROLES = MOD_ROLES + ["support"]

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS temp_bans (
    user_id INTEGER PRIMARY KEY,
    guild_id INTEGER,
    unban_timestamp REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS csa_list (
    user_id INTEGER PRIMARY KEY,
    reason TEXT,
    moderator TEXT,
    date_msk TEXT
)
""")
conn.commit()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
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

def check_csa(user_id: int):
    db = get_db_conn()
    cur = db.cursor()
    cur.execute("SELECT reason, moderator, date_msk FROM csa_list WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    db.close()
    return row

def get_warns(user_id: int) -> int:
    db = get_db_conn()
    cur = db.cursor()
    cur.execute("SELECT count FROM warns WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    db.close()
    return row[0] if row else 0

def update_warns(user_id: int, delta: int) -> int:
    db = get_db_conn()
    cur = db.cursor()
    cur.execute("SELECT count FROM warns WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    current = row[0] if row else 0
    new_count = max(0, current + delta)
    cur.execute("INSERT OR REPLACE INTO warns (user_id, count) VALUES (?, ?)", (user_id, new_count))
    db.commit()
    db.close()
    return new_count

# --- ПЕРЕХВАТ КОНСОЛИ ---
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
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
user_balances = {}

def has_staff_role(*role_keys):
    async def predicate(interaction: discord.Interaction):
        if interaction.user == interaction.guild.owner or interaction.user.guild_permissions.administrator:
            return True
        user_roles = [r.id for r in interaction.user.roles]
        allowed = [ROLE_IDS[k] for k in role_keys if k in ROLE_IDS]
        if any(r_id in user_roles for r_id in allowed):
            return True
        raise app_commands.CheckFailure("❌ У вашей должности недостаточно прав для этой команды!")
    return app_commands.check(predicate)

async def handle_specific_role_slash(interaction: discord.Interaction, member: discord.Member, role_key: str, action: str):
    role_id = ROLE_IDS.get(role_key)
    role = interaction.guild.get_role(role_id)
    if not role:
        return await interaction.response.send_message(f"❌ Должность для `{role_key}` не найдена на сервере.", ephemeral=True)

    if action == "add" and check_csa(member.id):
        return await interaction.response.send_message(f"❌ Невозможно выдать роль! У участника {member.mention} активен **ЧСА**.", ephemeral=True)

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
        await interaction.response.send_message("❌ У бота недостаточно прав для управления этой ролью.", ephemeral=True)

# --- АВТОМАТИЧЕСКАЯ ОТПРАВКА ЛОГОВ КОНСОЛИ В ДИСКОРД ---
@tasks.loop(seconds=30)
async def auto_send_logs():
    if not LOG_BUFFER:
        return

    try:
        conn_l = get_db_conn()
        cur_l = conn_l.cursor()
        cur_l.execute("SELECT value FROM settings WHERE key LIKE 'log_channel_%'")
        rows = cur_l.fetchall()
        conn_l.close()

        if not rows:
            return

        logs_to_send = "\n".join(LOG_BUFFER)
        LOG_BUFFER.clear()

        if len(logs_to_send) > 1900:
            logs_to_send = logs_to_send[-1900:]

        for row in rows:
            channel_id = int(row[0])
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.send(f"🖥️ **Авто-логи:**\n```py\n{logs_to_send}\n```")
    except Exception:
        pass

@auto_send_logs.before_loop
async def before_auto_send_logs():
    await bot.wait_until_ready()

# --- ФОНОВАЯ ПРОВЕРКА ВРЕМЕННЫХ БАНОВ ---
@tasks.loop(minutes=1)
async def check_temp_bans():
    now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
    conn_b = get_db_conn()
    cur_b = conn_b.cursor()
    cur_b.execute("SELECT user_id, guild_id FROM temp_bans WHERE unban_timestamp <= ?", (now_ts,))
    expired = cur_b.fetchall()

    for uid, gid in expired:
        guild = bot.get_guild(gid)
        if guild:
            try:
                user = await bot.fetch_user(uid)
                await guild.unban(user, reason="Истёк срок временного бана (до 30 дн.)")
                add_log_entry("Разбан", f"{user.name} ({user.id})", "Система", "Истёк срок временного бана")
            except Exception:
                pass
        cur_b.execute("DELETE FROM temp_bans WHERE user_id = ?", (uid,))

    conn_b.commit()
    conn_b.close()

@check_temp_bans.before_loop
async def before_check_temp_bans():
    await bot.wait_until_ready()

# --- ОБРАБОТЧИК СИСТЕМНЫХ ЛОГОВ PYTHON ---
class DiscordLogHandler(logging.Handler):
    def __init__(self, bot, channel_id: int):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    def emit(self, record):
        log_entry = self.format(record)
        self.bot.loop.create_task(self.send_log(log_entry))

    async def send_log(self, message: str):
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                if len(message) > 1900:
                    message = message[:1900] + "..."
                await channel.send(f"```ini\n{message}\n```")
            except Exception as e:
                print(f"Ошибка отправки системного лога: {e}")

if not any(isinstance(h, DiscordLogHandler) for h in logging.getLogger().handlers):
    handler = DiscordLogHandler(bot, LOG_CHANNEL_ID)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

# --- СОБЫТИЕ ЗАПУСКА ON_READY ---
@bot.event
async def on_ready():
    print(f"🤖 Основной бот запущен: {bot.user.name} (ID: {bot.user.id})")

    try:
        bot.add_view(CreateRoomButtonView())
        bot.add_view(RoomSettingsView())
    except Exception as e:
        print(f"[VIEW INIT NOTE]: {e}")

    try:
        await bot.load_extension("cogs.shop")
        print("✅ Коги магазина успешно загружены!")
    except Exception:
        pass

    try:
        await bot.load_extension("privates")
        print("✅ Модуль приваток (privates.py) успешно загружен!")
    except Exception as e:
        print(f"❌ Ошибка загрузки privates: {e}")

    try:
        synced = await bot.tree.sync()
        print(f"🌲 Синхронизировано команд: {len(synced)}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации слэш-команд: {e}")

    if not auto_send_logs.is_running():
        auto_send_logs.start()
    if not check_temp_bans.is_running():
        check_temp_bans.start()

# =========================================================
# СОБЫТИЙНОЕ ЛОГИРОВАНИЕ СЕРВЕРА (БОТЫ ИСКЛЮЧЕНЫ)
# =========================================================

@bot.event
async def on_message(message: discord.Message):
    if not message.guild or message.author.bot:
        return

    time_str = get_msk_time()
    add_log_entry(
        "Чат",
        f"#{message.channel.name}",
        f"{message.author.name} ({message.author.id})",
        f"Сообщение: {message.content or '[Вложения]'}"
    )

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

    time_str = get_msk_time()
    mod_str = f"{message.author.name} ({message.author.id})"
    try:
        async for entry in message.guild.audit_logs(limit=2, action=discord.AuditLogAction.message_delete):
            if entry.target.id == message.author.id and not entry.user.bot:
                mod_str = f"{entry.user.name} ({entry.user.id})"
                break
    except Exception:
        pass

    add_log_entry("Удаление сообщений", f"#{message.channel.name}", mod_str, f"Содержимое: {message.content or '*[Пусто/Медиа]*'}")

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
async def on_raw_message_bulk_delete(payload):
    time_str = get_msk_time()
    target_channel = bot.get_channel(payload.channel_id)
    ch_name = f"#{target_channel.name}" if target_channel else f"<#{payload.channel_id}>"
    count = len(payload.message_ids)

    add_log_entry("Очистка чата", ch_name, "Система (Purge)", f"Массово удалено {count} сообщений")

    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"📅 **Время МСК:** `{time_str}`\n"
            f"🧹 **Массовое удаление сообщений (очистка)**\n"
            f"• **Канал:** {ch_name}\n"
            f"• **Удалено сообщений:** `{count}`"
        )

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not before.guild or before.author.bot or before.content == after.content:
        return

    time_str = get_msk_time()
    add_log_entry(
        "Редактирование",
        f"#{before.channel.name}",
        f"{before.author.name} ({before.author.id})",
        f"Было: {before.content} | Стало: {after.content}"
    )

    log_channel = before.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"📅 **Время МСК:** `{time_str}`\n"
            f"✏️️ **Сообщение отредактировано**\n"
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
    u_tag = f"{member.name} ({member.id})"
    log_channel = member.guild.get_channel(LOG_CHANNEL_ID)

    if before.channel is None and after.channel is not None:
        add_log_entry("Войс", u_tag, member.name, f"Подключился к «{after.channel.name}»")
        if log_channel:
            await log_channel.send(
                f"📅 **Время МСК:** `{time_str}`\n"
                f"🔊 **Подключение к войсу**\n• **Участник:** {member.mention}\n• **Канал:** **{after.channel.name}**"
            )
    elif before.channel is not None and after.channel is None:
        add_log_entry("Войс", u_tag, member.name, f"Покинул «{before.channel.name}»")
        if log_channel:
            await log_channel.send(
                f"📅 **Время МСК:** `{time_str}`\n"
                f"🔇 **Выход из войса**\n• **Участник:** {member.mention}\n• **Канал:** **{before.channel.name}**"
            )
    elif before.channel != after.channel:
        add_log_entry("Войс", u_tag, member.name, f"Перешел: «{before.channel.name}» ➔ «{after.channel.name}»")
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
            if entry.target.id == member.id and not entry.user.bot:
                moderator = entry.user
                reason = entry.reason or "Причина не указана"
                break
    except Exception:
        pass

    log_channel = member.guild.get_channel(LOG_CHANNEL_ID)
    if moderator:
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
async def on_guild_channel_create(channel_obj):
    time_str = get_msk_time()
    mod_name = "Неизвестно"
    try:
        async for entry in channel_obj.guild.audit_logs(limit=2, action=discord.AuditLogAction.channel_create):
            if entry.target.id == channel_obj.id and not entry.user.bot:
                mod_name = entry.user.mention
                break
    except Exception:
        pass

    log_channel = channel_obj.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"📅 **Время МСК:** `{time_str}`\n"
            f"📁 **Создан канал**\n• **Название:** {channel_obj.name}\n• **Создал:** {mod_name}"
        )

@bot.event
async def on_guild_channel_delete(channel_obj):
    time_str = get_msk_time()
    mod_name = "Неизвестно"
    try:
        async for entry in channel_obj.guild.audit_logs(limit=2, action=discord.AuditLogAction.channel_delete):
            if entry.target.id == channel_obj.id and not entry.user.bot:
                mod_name = entry.user.mention
                break
    except Exception:
        pass

    log_channel = channel_obj.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"📅 **Время МСК:** `{time_str}`\n"
            f"🗑️ **Удален канал**\n• **Название:** {channel_obj.name}\n• **Удалил:** {mod_name}"
        )

# Автозащита: снятие стафф-ролей при активном ЧСА + стандартное логирование ролей и мута
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.bot:
        return

    time_str = get_msk_time()
    log_channel = before.guild.get_channel(LOG_CHANNEL_ID)

    # 1. Проверка ЧСА при добавлении ролей
    if len(after.roles) > len(before.roles):
        csa_info = check_csa(after.id)
        if csa_info:
            illegal_roles = [r for r in after.roles if r not in before.roles and r.id in STAFF_ROLE_IDS]
            if illegal_roles:
                for r in illegal_roles:
                    try:
                        await after.remove_roles(r, reason="Запрещено: участник находится в ЧСА")
                    except Exception:
                        pass
                if log_channel:
                    await log_channel.send(
                        f"🚨 **Попытка выдачи роли участнику из ЧСА!**\n"
                        f"• Участник: {after.mention} (`{after.id}`)\n"
                        f"• Роль: {', '.join([r.name for r in illegal_roles])} была **автоматически снята**.\n"
                        f"• Причина ЧСА: `{csa_info[0]}` (Внёс: {csa_info[1]})"
                    )

    # 2. Логирование ролей
    if before.roles != after.roles:
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        mod_name = "Система"
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

    # 3. Логирование таймаута (мута)
    if before.timed_out_until != after.timed_out_until:
        mod_name = "Система"
        mod_mention = "Неизвестно"
        try:
            async for entry in before.guild.audit_logs(limit=2, action=discord.AuditLogAction.member_update):
                if entry.target.id == after.id and not entry.user.bot:
                    mod_name = entry.user.name
                    mod_mention = entry.user.mention
                    break
        except Exception:
            pass

        if after.timed_out_until:
            add_log_entry("Мут", f"{after.name} ({after.id})", mod_name, f"Таймаут до {after.timed_out_until.strftime('%d.%m %H:%M')}")
            if log_channel:
                await log_channel.send(
                    f"📅 **Время МСК:** `{time_str}`\n"
                    f"🤐 **Выдан мут (таймаут)**\n• **Пользователь:** {after.mention}\n• **До:** `{after.timed_out_until}`\n• **Выдал:** {mod_mention}"
                )
        else:
            add_log_entry("Снятие мута", f"{after.name} ({after.id})", mod_name, "Снят таймаут")
            if log_channel:
                await log_channel.send(
                    f"📅 **Время МСК:** `{time_str}`\n"
                    f"🔊 **Мут снят**\n• **Пользователь:** {after.mention}\n• **Снял:** {mod_mention}"
                )

# =========================================================
# КОМАНДЫ МОДЕРАЦИИ ПО ИЕРАРХИИ
# =========================================================

# 1. КОМАНДА /ид (ОТ SUPPORT И ВЫШЕ)
@bot.tree.command(name="ид", description="Просмотреть досье и количество варнов участника")
@app_commands.describe(member="Участник (по умолчанию вы)")
@has_staff_role(*ALL_STAFF_ROLES)
async def cmd_id(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    warns_count = get_warns(target.id)

    roles = [r.mention for r in target.roles if r.name != "@everyone"]
    roles_str = ", ".join(roles) if roles else "Нет ролей"
    created_at = target.created_at.strftime("%d.%m.%Y %H:%M")
    joined_at = target.joined_at.strftime("%d.%m.%Y %H:%M") if target.joined_at else "Неизвестно"

    csa_status = "❌ Активен" if check_csa(target.id) else "✅ Отсутствует"

    embed = discord.Embed(title=f"📋 Досье участника: {target.display_name}", color=discord.Color.blue())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="👤 Никнейм", value=f"{target.mention} (`{target.name}`)", inline=True)
    embed.add_field(name="🆔 Discord ID", value=f"`{target.id}`", inline=True)
    embed.add_field(name="⚠️ Варны", value=f"**{warns_count}/3**", inline=True)
    embed.add_field(name="🚫 ЧСА", value=csa_status, inline=True)
    embed.add_field(name="📅 Регистрация", value=created_at, inline=False)
    embed.add_field(name="📥 Вход на сервер", value=joined_at, inline=False)
    embed.add_field(name=f"🎖️ Роли [{len(roles)}]", value=roles_str, inline=False)
    embed.set_footer(text=f"Запросил сотрудник: {interaction.user.name}")

    await interaction.response.send_message(embed=embed)

# 2. МУТ / СНЯТИЕ МУТА (ОТ MODERATOR И ВЫШЕ)
@bot.tree.command(name="mute_user", description="Выдать таймаут участнику (в минутах)")
@app_commands.describe(member="Участник", minutes="Время в минутах", reason="Причина")
@has_staff_role(*MOD_ROLES)
async def mute_cmd(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message("❌ Нельзя наказать участника с равной или более высокой ролью!", ephemeral=True)

    mute_role = interaction.guild.get_role(MUTE_ROLE_ID)
    if mute_role:
        await member.add_roles(mute_role, reason=f"Мут от {interaction.user.name}: {reason}")

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

    await interaction.response.send_message(f"🔇 {member.mention} замучен на **{minutes} мин.** Инициатор: {interaction.user.mention}")

@bot.tree.command(name="unmute_user", description="Снять таймаут с участника")
@app_commands.describe(member="Участник", reason="Причина снятия")
@has_staff_role(*MOD_ROLES)
async def unmute_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
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

    await interaction.response.send_message(f"🔊 Мут с {member.mention} успешно снят. Инициатор: {interaction.user.mention}")

# 3. ВАРНЫ (ОТ MODERATOR И ВЫШЕ)
@bot.tree.command(name="warn", description="Выдать варн участнику")
@app_commands.describe(member="Участник", reason="Причина")
@has_staff_role(*MOD_ROLES)
async def warn_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message("❌ Нельзя выдать варн участнику с равным или высшим рангом!", ephemeral=True)

    new_count = update_warns(member.id, 1)

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

    await interaction.response.send_message(f"⚠️ {member.mention} получил варн (**{new_count}/3**). Модератор: {interaction.user.mention}")

    if new_count >= 3:
        update_warns(member.id, -3)
        for role_id in WARN_ROLES.values():
            r = interaction.guild.get_role(role_id)
            if r and r in member.roles:
                await member.remove_roles(r)

        await member.ban(reason="Автоматический бан за 3 варна")
        add_log_entry("Бан", f"{member.name} ({member.id})", "Система (3 варна)", "Превышен лимит варнов")

@bot.tree.command(name="unwarn", description="Снять варн с участника")
@app_commands.describe(member="Участник")
@has_staff_role(*MOD_ROLES)
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
    await interaction.response.send_message(f"✅ С {member.mention} снят варн. Текущее количество: **{new_count}/3**.")

# 4. ОБЫЧНЫЙ ВРЕМЕННЫЙ БАН (SENIOR MODERATOR: ОТ 1 ДО 30 ДНЕЙ)
@bot.tree.command(name="ban", description="Забанить участника на время (от 1 до 30 дней)")
@app_commands.describe(member="Участник", days="Срок бана в днях (1-30)", reason="Причина")
@has_staff_role(*SENIOR_MOD_ROLES)
async def ban_temp_cmd(interaction: discord.Interaction, member: discord.Member, days: int, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message("❌ Нельзя наказать участника с равной или более высокой ролью!", ephemeral=True)

    if days < 1 or days > 30:
        return await interaction.response.send_message("❌ Обычный бан выдается на срок от **1** до **30** дней! Для вечного бана используйте `/permban`.", ephemeral=True)

    unban_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    unban_timestamp = unban_time.timestamp()

    conn_b = get_db_conn()
    cur_b = conn_b.cursor()
    cur_b.execute("INSERT OR REPLACE INTO temp_bans (user_id, guild_id, unban_timestamp) VALUES (?, ?, ?)",
                  (member.id, interaction.guild.id, unban_timestamp))
    conn_b.commit()
    conn_b.close()

    try:
        await member.send(f"⛔ Вы были забанены на **{interaction.guild.name}** на **{days} дн.**\nПричина: {reason}")
    except discord.Forbidden:
        pass

    await member.ban(reason=f"Срок: {days} дн. | Модератор: {interaction.user.name} | {reason}")
    add_log_entry("Бан", f"{member.name} ({member.id})", interaction.user.name, f"Бан на {days} дн. | {reason}")

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="🚫 Временный бан", color=discord.Color.red())
        embed.add_field(name="📅 Дата и время (МСК)", value=f"`{get_msk_time()}`", inline=False)
        embed.add_field(name="Пользователь", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Забанил", value=interaction.user.mention, inline=False)
        embed.add_field(name="Срок", value=f"{days} дн.", inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(f"⛔ Участник {member.mention} забанен на **{days} дн.** Старший модератор: {interaction.user.mention}")

# 5. КИК (SENIOR MODERATOR И ВЫШЕ)
@bot.tree.command(name="kick", description="Выгнать участника с сервера")
@app_commands.describe(member="Участник", reason="Причина")
@has_staff_role(*SENIOR_MOD_ROLES)
async def kick_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message("❌ Нельзя кикнуть равного или старшего по должности!", ephemeral=True)

    await member.kick(reason=f"Инициатор: {interaction.user.name} | {reason}")
    add_log_entry("Кик", f"{member.name} ({member.id})", interaction.user.name, reason)
    await interaction.response.send_message(f"👢 Участник {member.mention} был изгнан. Инициатор: {interaction.user.mention}")

# 6. ВЕЧНЫЙ ПЕРМБАН (ADMINISTRATOR И ВЫШЕ)
@bot.tree.command(name="permban", description="Забанить участника навсегда (Пермбан)")
@app_commands.describe(member="Участник", reason="Причина")
@has_staff_role(*ADMIN_ROLES)
async def permban_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Грубое нарушение"):
    if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message("❌ Нельзя забанить администратора или равного по должности!", ephemeral=True)

    try:
        await member.send(f"⛔ Вы получили **Пермбан (навсегда)** на сервере **{interaction.guild.name}**.\nПричина: {reason}")
    except discord.Forbidden:
        pass

    await member.ban(reason=f"ПЕРМБАН | Администратор: {interaction.user.name} | {reason}")
    add_log_entry("Наказания", f"{member.name} ({member.id})", interaction.user.name, f"ПЕРМБАН (Навсегда) | {reason}")

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="🚨 ПЕРМБАН (Навсегда)", color=discord.Color.dark_red())
        embed.add_field(name="📅 Дата и время (МСК)", value=f"`{get_msk_time()}`", inline=False)
        embed.add_field(name="Пользователь", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Администратор", value=interaction.user.mention, inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(f"🚨 Администратор {interaction.user.mention} выдал **ПЕРМБАН** участнику {member.mention}.\nПричина: {reason}")

# 7. РАЗБАН (ADMINISTRATOR И ВЫШЕ)
@bot.tree.command(name="unban_user", description="Разбанить участника по его Discord ID")
@app_commands.describe(user_id="ID пользователя", reason="Причина")
@has_staff_role(*ADMIN_ROLES)
async def unban_cmd(interaction: discord.Interaction, user_id: str, reason: str = "Амнистия"):
    try:
        uid = int(user_id)
        user = await bot.fetch_user(uid)
    except ValueError:
        return await interaction.response.send_message("❌ Укажите корректный числовой ID пользователя.", ephemeral=True)

    try:
        await interaction.guild.unban(user, reason=reason)
    except discord.HTTPException:
        return await interaction.response.send_message("❌ Не удалось разбанить (возможно, пользователь не забанен).", ephemeral=True)

    conn_b = get_db_conn()
    cur_b = conn_b.cursor()
    cur_b.execute("DELETE FROM temp_bans WHERE user_id = ?", (uid,))
    conn_b.commit()
    conn_b.close()

    add_log_entry("Разбан", f"{user.name} ({user.id})", interaction.user.name, reason)

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="🔓 Пользователь разбанен", color=discord.Color.blue())
        embed.add_field(name="📅 Дата и время (МСК)", value=f"`{get_msk_time()}`", inline=False)
        embed.add_field(name="Пользователь", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Разбанил", value=interaction.user.mention, inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(f"🔓 Пользователь {user.mention} (`{user.id}`) успешно разбанен.")

# 8. ОЧИСТКА ЧАТА (ADMINISTRATOR И ВЫШЕ)
@bot.tree.command(name="clear", description="Очистить чат")
@app_commands.describe(amount="Количество сообщений")
@has_staff_role(*ADMIN_ROLES)
async def clear_cmd(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    add_log_entry("Очистка чата", f"#{interaction.channel.name}", interaction.user.name, f"Удалено сообщений: {len(deleted)}")
    await interaction.followup.send(f"🧹 Удалено сообщений: **{len(deleted)}**")

# =========================================================
# СИСТЕМА ЧСА (ЧЁРНЫЙ СПИСОК АДМИНИСТРАЦИИ - РУКОВОДСТВО)
# =========================================================

@bot.tree.command(name="чса_добавить", description="Внести пользователя в Черный Список Администрации")
@app_commands.describe(member="Участник", reason="Причина занесения в ЧСА")
@has_staff_role(*LEADERSHIP_ROLES)
async def csa_add(interaction: discord.Interaction, member: discord.Member, reason: str):
    if member == interaction.guild.owner:
        return await interaction.response.send_message("❌ Нельзя внести в ЧСА владельца сервера!", ephemeral=True)

    time_str = get_msk_time()
    db = get_db_conn()
    cur = db.cursor()
    cur.execute("INSERT OR REPLACE INTO csa_list (user_id, reason, moderator, date_msk) VALUES (?, ?, ?, ?)",
                (member.id, reason, interaction.user.name, time_str))
    db.commit()
    db.close()

    removed = []
    for r in member.roles:
        if r.id in STAFF_ROLE_IDS:
            try:
                await member.remove_roles(r, reason="Внесение в ЧСА")
                removed.append(r.name)
            except Exception:
                pass

    roles_info = f" (Сняты роли: {', '.join(removed)})" if removed else ""
    add_log_entry("ЧСА", f"{member.name} ({member.id})", interaction.user.name, f"Внесен в ЧСА | {reason}")

    await interaction.response.send_message(
        f"⛔ Участник {member.mention} (`{member.id}`) **внесен в Черный Список Администрации**!{roles_info}\n• **Причина:** {reason}\n• **Инициатор:** {interaction.user.mention}"
    )

@bot.tree.command(name="чса_снять", description="Вынести пользователя из Черного Списка Администрации")
@app_commands.describe(user_id="Discord ID участника")
@has_staff_role(*LEADERSHIP_ROLES)
async def csa_remove(interaction: discord.Interaction, user_id: str):
    try:
        uid = int(user_id)
    except ValueError:
        return await interaction.response.send_message("❌ Укажите корректный числовой ID!", ephemeral=True)

    db = get_db_conn()
    cur = db.cursor()
    cur.execute("SELECT user_id FROM csa_list WHERE user_id = ?", (uid,))
    if not cur.fetchone():
        db.close()
        return await interaction.response.send_message("❌ Данный пользователь не состоит в ЧСА.", ephemeral=True)

    cur.execute("DELETE FROM csa_list WHERE user_id = ?", (uid,))
    db.commit()
    db.close()

    add_log_entry("ЧСА", f"ID: {uid}", interaction.user.name, "Вынесен из ЧСА")
    await interaction.response.send_message(f"✅ Пользователь с ID `{uid}` успешно **вынесен из ЧСА**. Инициатор: {interaction.user.mention}")

@bot.tree.command(name="чса_лист", description="Показать актуальный список ЧСА")
@has_staff_role(*LEADERSHIP_ROLES)
async def csa_list_cmd(interaction: discord.Interaction):
    db = get_db_conn()
    cur = db.cursor()
    cur.execute("SELECT user_id, reason, moderator, date_msk FROM csa_list")
    rows = cur.fetchall()
    db.close()

    if not rows:
        return await interaction.response.send_message("📋 Черный список администрации пуст.", ephemeral=True)

    embed = discord.Embed(title="🚫 Черный список администрации (ЧСА)", color=discord.Color.dark_red())
    lines = []
    for uid, reason, mod, date_msk in rows:
        lines.append(f"• <@{uid}> (`{uid}`) — **Причина:** {reason} | **Выдал:** {mod} (`{date_msk}`)")

    embed.description = "\n".join(lines[:20])
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =========================================================
# СКРЫТАЯ ДИНАМИЧЕСКАЯ КОМАНДА /ahelp
# =========================================================

@bot.tree.command(name="ahelp", description="Показать команды модерации по вашему уровню прав")
async def cmd_ahelp(interaction: discord.Interaction):
    user = interaction.user
    user_roles = [r.id for r in user.roles]
    is_owner = (user == interaction.guild.owner) or user.guild_permissions.administrator

    def has_any(keys):
        if is_owner:
            return True
        allowed = [ROLE_IDS[k] for k in keys if k in ROLE_IDS]
        return any(rid in user_roles for rid in allowed)

    embed = discord.Embed(
        title="🛡️ Доступные команды персонала сервера",
        color=discord.Color.from_rgb(43, 45, 49),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"Запросил: {user.display_name}")

    has_any_command = False

    # 1. Support
    if has_any(ALL_STAFF_ROLES):
        has_any_command = True
        embed.add_field(
            name="👤 Support / Поддержка",
            value=(
                "`/ид [участник]` — досье, проверка варнов и ЧСА\n"
                "`/userinfo [участник]` — профиль пользователя"
            ),
            inline=False
        )

    # 2. Moderator
    if has_any(MOD_ROLES):
        has_any_command = True
        embed.add_field(
            name="🔨 Moderator / Модератор",
            value=(
                "`/mute_user <участник> <минуты> [причина]` — таймаут\n"
                "`/unmute_user <участник> [причина]` — снять таймаут\n"
                "`/warn <участник> [причина]` — выдать варн (бан при 3/3)\n"
                "`/unwarn <участник>` — снять варн\n"
                "`/warns_list` — список варнов на сервере\n"
                "`/mutes_list` — список участников в муте"
            ),
            inline=False
        )

    # 3. Senior Moderator
    if has_any(SENIOR_MOD_ROLES):
        has_any_command = True
        embed.add_field(
            name="⚖️ Senior Moderator / Старший Модератор",
            value=(
                "`/ban <участник> <дни (1-30)> [причина]` — временный бан до 30 дней\n"
                "`/kick <участник> [причина]` — изгнать участника\n"
                "`/slowmode <секунды>` — медленный режим"
            ),
            inline=False
        )

    # 4. Administrator
    if has_any(ADMIN_ROLES):
        has_any_command = True
        embed.add_field(
            name="🛠️ Administrator / Администратор",
            value=(
                "`/permban <участник> [причина]` — бессрочный бан (Пермбан)\n"
                "`/unban_user <ID> [причина]` — разбанить участника по ID\n"
                "`/bans_list` — список забаненных\n"
                "`/clear <кол-во>` — очистка сообщений чата\n"
                "`/lock` / `/unlock` — закрыть/открыть текстовый канал\n"
                "`/sync_chat_history [лимит]` — импорт чата на сайт"
            ),
            inline=False
        )

    # 5. Руководство
    if has_any(LEADERSHIP_ROLES):
        has_any_command = True
        embed.add_field(
            name="👑 Руководство (Head Admin / Co-Owner / Owner)",
            value=(
                "`/чса_добавить <участник> <причина>` — внести в ЧСА\n"
                "`/чса_снять <ID>` — вынести из ЧСА\n"
                "`/чса_лист` — список всех участников в ЧСА\n"
                "`/gmod`, `/admin`, `/mod`... — выдача должностей Staff\n"
                "`/setup_create` / `/setup_settings` — меню создания приваток"
            ),
            inline=False
        )

    if not has_any_command:
        await interaction.response.send_message("❌ У вас нет прав для просмотра команд персонала.", ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)

# =========================================================
# СПИСКИ НАКАЗАНИЙ
# =========================================================

@bot.tree.command(name="warns_list", description="Показать список всех участников с активными варнами")
@has_staff_role(*MOD_ROLES)
async def warns_list(interaction: discord.Interaction):
    db = get_db_conn()
    cur = db.cursor()
    cur.execute("SELECT user_id, count FROM warns WHERE count > 0")
    rows = cur.fetchall()
    db.close()

    if not rows:
        return await interaction.response.send_message("На сервере нет пользователей с активными варнами.", ephemeral=True)

    embed = discord.Embed(title="⚠️ Список варнов на сервере", color=discord.Color.gold())
    desc = "".join([f"<@{uid}> — **{c}/3** варнов\n" for uid, c in rows])
    embed.description = desc
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="bans_list", description="Показать список последних забаненных участников")
@has_staff_role(*ADMIN_ROLES)
async def bans_list(interaction: discord.Interaction):
    embed = discord.Embed(title="🚫 Список банов сервера", color=discord.Color.red())
    desc = ""
    async for entry in interaction.guild.bans(limit=25):
        desc += f"• **{entry.user}** (`{entry.user.id}`) — Причина: *{entry.reason or 'Не указана'}*\n"
    embed.description = desc if desc else "Список банов пуст."
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="mutes_list", description="Показать список участников с активным таймаутом")
@has_staff_role(*MOD_ROLES)
async def mutes_list(interaction: discord.Interaction):
    embed = discord.Embed(title="🔇 Список активных мутов", color=discord.Color.dark_grey())
    desc = ""
    now = discord.utils.utcnow()
    for m in interaction.guild.members:
        if m.timed_out_until and m.timed_out_until > now:
            desc += f"• {m.mention} — до {m.timed_out_until.strftime('%d.%m.%Y %H:%M')}\n"
    embed.description = desc if desc else "Активных мутов на сервере нет."
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =========================================================
# КОМАНДЫ РОЛЕЙ РУКОВОДСТВА
# =========================================================

@bot.tree.command(name="gmod", description="Назначить Главного модератора")
@app_commands.describe(member="Участник")
@has_staff_role(*LEADERSHIP_ROLES)
async def cmd_gmod(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "head_mod", "add")

@bot.tree.command(name="ungmod", description="Снять Главного модератора")
@app_commands.describe(member="Участник")
@has_staff_role(*LEADERSHIP_ROLES)
async def cmd_ungmod(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "head_mod", "remove")

@bot.tree.command(name="gadmin", description="Назначить Главного администратора")
@app_commands.describe(member="Участник")
@has_staff_role("owner", "co_owner")
async def cmd_gadmin(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "head_admin", "add")

@bot.tree.command(name="ungadmin", description="Снять Главного администратора")
@app_commands.describe(member="Участник")
@has_staff_role("owner", "co_owner")
async def cmd_ungadmin(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "head_admin", "remove")

@bot.tree.command(name="admin", description="Назначить Администратора")
@app_commands.describe(member="Участник")
@has_staff_role(*LEADERSHIP_ROLES)
async def cmd_admin(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "admin", "add")

@bot.tree.command(name="unadmin", description="Снять Администратора")
@app_commands.describe(member="Участник")
@has_staff_role(*LEADERSHIP_ROLES)
async def cmd_unadmin(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "admin", "remove")

@bot.tree.command(name="mod", description="Назначить Модератора")
@app_commands.describe(member="Участник")
@has_staff_role(*ADMIN_ROLES)
async def cmd_mod(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "mod", "add")

@bot.tree.command(name="unmod", description="Снять Модератора")
@app_commands.describe(member="Участник")
@has_staff_role(*ADMIN_ROLES)
async def cmd_unmod(interaction: discord.Interaction, member: discord.Member):
    await handle_specific_role_slash(interaction, member, "mod", "remove")

# =========================================================
# ЭКОНОМИКА, НАГРАДЫ И МАГАЗИН
# =========================================================

@bot.tree.command(name="reward", description="Получить ежедневную награду (раз в сутки)")
async def reward_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    today = datetime.date.today().isoformat()

    conn_e = get_db_conn()
    cur_e = conn_e.cursor()
    cur_e.execute('SELECT last_reward, points FROM users WHERE user_id = ?', (user_id,))
    row = cur_e.fetchone()

    if row:
        if row[0] == today:
            conn_e.close()
            return await interaction.response.send_message("⏳ Вы уже забирали ежедневную награду сегодня!", ephemeral=True)
        cur_e.execute('UPDATE users SET points = points + 100, last_reward = ? WHERE user_id = ?', (today, user_id))
    else:
        cur_e.execute('INSERT INTO users (user_id, points, last_reward) VALUES (?, 100, ?)', (user_id, today))

    conn_e.commit()
    cur_e.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
    new_bal = cur_e.fetchone()[0]
    conn_e.close()

    await interaction.response.send_message(f"🎁 Вы получили **100 монет**!\n💎 Текущий баланс: **{new_bal}** монет.")

@bot.tree.command(name="bal", description="Проверить свой баланс монет")
@app_commands.describe(member="Участник (необязательно)")
async def bal_command(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    conn_e = get_db_conn()
    cur_e = conn_e.cursor()
    cur_e.execute('SELECT points FROM users WHERE user_id = ?', (target.id,))
    row = cur_e.fetchone()
    pts = row[0] if row else 0
    conn_e.close()
    await interaction.response.send_message(f"💎 Баланс **{target.display_name}**: **{pts} монет**.")

@bot.command(name='addshop')
@commands.has_permissions(administrator=True)
async def add_shop_role(ctx, role: discord.Role, price: int):
    conn_e = get_db_conn()
    cur_e = conn_e.cursor()
    cur_e.execute('INSERT OR REPLACE INTO shop_roles (role_id, price) VALUES (?, ?)', (role.id, price))
    conn_e.commit()
    conn_e.close()
    await ctx.send(f'🛒 Роль {role.mention} добавлена в магазин за **{price}** монет.')

@bot.command(name='addpoints')
@commands.has_permissions(administrator=True)
async def add_points(ctx, member: discord.Member, amount: int):
    conn_e = get_db_conn()
    cur_e = conn_e.cursor()
    cur_e.execute('INSERT OR IGNORE INTO users (user_id, points) VALUES (?, 0)', (member.id,))
    cur_e.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (amount, member.id))
    conn_e.commit()
    cur_e.execute('SELECT points FROM users WHERE user_id = ?', (member.id,))
    nb = cur_e.fetchone()[0]
    conn_e.close()
    await ctx.send(f'✅ Выдано {amount} монет пользователю {member.mention}. Баланс: **{nb}**.')

@bot.command(name="add_money")
@commands.has_permissions(administrator=True)
async def add_money_cmd(ctx, member: discord.Member, amount: int):
    bal = user_balances.get(member.id, 0) + amount
    user_balances[member.id] = bal
    await ctx.send(f"Успешно выдано **{amount}** монет {member.mention}! (Баланс в кэше: {bal})")

@bot.command(name="fix_db")
@commands.is_owner()
async def fix_db(ctx):
    try:
        conn_e = get_db_conn()
        cur_e = conn_e.cursor()
        cur_e.execute("ALTER TABLE shop_roles ADD COLUMN owner_id INTEGER DEFAULT 0;")
        cur_e.execute("ALTER TABLE shop_roles ADD COLUMN purchases INTEGER DEFAULT 0;")
        conn_e.commit()
        conn_e.close()
        await ctx.send("✅ База данных успешно обновлена!")
    except Exception as e:
        await ctx.send(f"❌ Ошибка (возможно, колонки уже есть): {e}")

@bot.tree.command(name="role", description="Создать личную кастомную роль за 10,000 монет")
@app_commands.describe(name="Название роли", color="Цвет в HEX (#FF0000)")
async def role_command(interaction: discord.Interaction, name: str, color: str):
    clean_color = color.strip("#")
    try:
        role_color = discord.Color(int(clean_color, 16))
    except ValueError:
        return await interaction.response.send_message("❌ Неверный формат цвета! Пример: `#38bdf8`", ephemeral=True)

    uid = interaction.user.id
    price = 10000

    conn_e = get_db_conn()
    cur_e = conn_e.cursor()
    cur_e.execute('SELECT points FROM users WHERE user_id = ?', (uid,))
    row = cur_e.fetchone()
    pts = row[0] if row else 0

    if pts < price:
        conn_e.close()
        return await interaction.response.send_message(f"❌ Недостаточно средств! Нужно **{price} монет**, а у вас **{pts}**.", ephemeral=True)

    try:
        new_role = await interaction.guild.create_role(name=name, color=role_color, reason=f"Личная роль {interaction.user}")
        cur_e.execute('UPDATE users SET points = points - ? WHERE user_id = ?', (price, uid))
        conn_e.commit()
        conn_e.close()

        await interaction.user.add_roles(new_role)
        await interaction.response.send_message(f"✅ Создана роль {new_role.mention} за **{price} монет**!", ephemeral=True)
    except discord.Forbidden:
        conn_e.close()
        await interaction.response.send_message("❌ У бота недостаточно прав на создание ролей.", ephemeral=True)
    except Exception as e:
        conn_e.close()
        await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

# =========================================================
# КОМАНДЫ ПРИВЯЗКИ И ПРОСМОТРА ЛОГОВ КОНСОЛИ
# =========================================================

@bot.command(name="getlogs")
async def getlogs_text(ctx):
    if not LOG_BUFFER:
        return await ctx.send("📭 Буфер логов пуст.")
    txt = "\n".join(LOG_BUFFER)[-1900:]
    await ctx.send(f"📜 **Последние логи из буфера:**\n```py\n{txt}\n```")

    conn_s = get_db_conn()
    cur_s = conn_s.cursor()
    cur_s.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"log_channel_{ctx.guild.id}", str(ctx.channel.id)))
    conn_s.commit()
    conn_s.close()

@bot.tree.command(name="getlogs", description="Получить логи из буфера и привязать канал")
async def getlogs_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    conn_s = get_db_conn()
    cur_s = conn_s.cursor()
    cur_s.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"log_channel_{interaction.guild.id}", str(interaction.channel.id)))
    conn_s.commit()
    conn_s.close()

    if not LOG_BUFFER:
        return await interaction.followup.send("📭 Буфер пуст, но канал привязан!", ephemeral=True)

    txt = "\n".join(LOG_BUFFER)[-1900:]
    await interaction.channel.send(f"📜 **Последние логи:**\n```py\n{txt}\n```")
    await interaction.followup.send("✅ Логи отправлены в чат!", ephemeral=True)

# =========================================================
# УТИЛИТЫ И РАЗВЛЕЧЕНИЯ
# =========================================================

@bot.tree.command(name="slowmode", description="Установить медленный режим (в секундах, 0 - выкл)")
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
    await interaction.response.send_message("🔓 Канал открыт для общения.")

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

@bot.tree.command(name="coinflip", description="Подбросить монетку (Орёл или Решка)")
async def coinflip(interaction: discord.Interaction):
    await interaction.response.send_message(random.choice(["🪙 Выпал **Орёл**!", "🪙 Выпала **Решка**!"]))

@bot.tree.command(name="roll", description="Случайное число от 1 до максимума")
async def roll(interaction: discord.Interaction, max_val: int = 100):
    if max_val < 1:
        return await interaction.response.send_message("❌ Число должно быть больше 0!", ephemeral=True)
    await interaction.response.send_message(f"🎲 Выпало число: **{random.randint(1, max_val)}** (из {max_val})")

@bot.tree.command(name="poll", description="Создать опрос с быстрыми реакциями")
async def poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(title="📊 Голосование", description=question, color=discord.Color.blue())
    embed.set_footer(text=f"Автор: {interaction.user.display_name}")
    await interaction.response.send_message("✅ Голосование создано!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")

@bot.tree.command(name="sync_chat_history", description="Импортировать историю сообщений канала на сайт")
@app_commands.describe(limit="Количество сообщений")
@app_commands.checks.has_permissions(administrator=True)
async def sync_history(interaction: discord.Interaction, limit: int = 200):
    await interaction.response.defer(ephemeral=True)
    c = 0
    async for m in interaction.channel.history(limit=limit, oldest_first=True):
        if not m.author.bot and m.content:
            add_log_entry("Чат", f"#{interaction.channel.name}", f"{m.author.name} ({m.author.id})", m.content)
            c += 1
    await interaction.followup.send(f"✅ Импортировано **{c}** сообщений в панель логов!")

# =========================================================
# МУЗЫКАЛЬНЫЙ МОДУЛЬ (YT-DLP)
# =========================================================

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def create_source(cls, search: str, *, loop=None):
        loop = loop or asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url']
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

@bot.tree.command(name="play", description="Воспроизвести музыку в голосовом канале")
async def play_music(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    if not interaction.user.voice:
        return await interaction.followup.send("❌ Вы должны находиться в голосовом канале!")

    channel = interaction.user.voice.channel
    if interaction.guild.voice_client is None:
        await channel.connect()
    elif interaction.guild.voice_client.channel != channel:
        await interaction.guild.voice_client.move_to(channel)

    vc = interaction.guild.voice_client
    try:
        source = await YTDLSource.create_source(query, loop=bot.loop)
        if vc.is_playing():
            vc.stop()
        vc.play(source)
        await interaction.followup.send(f"🎶 Сейчас играет: **{source.title}**")
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка воспроизведения: `{e}`")

@bot.tree.command(name="stop", description="Остановить музыку и выйти из канала")
async def stop_music(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("⏹️ Музыка остановлена.")
    else:
        await interaction.response.send_message("❌ Бот не находится в голосовом канале.", ephemeral=True)

# =========================================================
# ЗАПУСК БОТА
# =========================================================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Ошибка: Переменная DISCORD_TOKEN не задана в Railway!")
    else:
        bot.run(DISCORD_TOKEN)
