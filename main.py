import os
import sys
import asyncio
import datetime
import sqlite3
import pytz
import discord
from discord.ext import commands
from discord import app_commands

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

# --- ИНИЦИАЛИЗАЦИЯ DISCORD БОТА ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- ПРИВАТНЫЕ КОМНАТЫ: МОДАЛЬНЫЕ ОКНА И МЕНЮ ---
class CreateRoomModal(discord.ui.Modal, title="Создание приватной комнаты"):
    room_name = discord.ui.TextInput(
        label="Название комнаты",
        placeholder="Введите название вашей комнаты...",
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        author = interaction.user
        category = interaction.channel.category

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            author: discord.PermissionOverwrite(
                connect=True, manage_channels=True, mute_members=True, deafen_members=True, move_members=True
            )
        }

        try:
            channel = await guild.create_voice_channel(
                name=self.room_name.value,
                overwrites=overwrites,
                category=category
            )
            if author.voice:
                await author.move_to(channel)
            await interaction.followup.send(f"✅ Ваша комната **{self.room_name.value}** успешно создана!", ephemeral=True)
            add_log_entry("Войс", f"#{self.room_name.value}", author.name, "Создана приватная комната")
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка создания комнаты: {e}", ephemeral=True)

class CreateRoomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать приватную комнату", style=discord.ButtonStyle.green, custom_id="create_room_btn_persistent", emoji="➕")
    async def create_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateRoomModal())

class RenameModal(discord.ui.Modal, title="Изменить название комнаты"):
    new_name = discord.ui.TextInput(label="Новое название", placeholder="Введите название...", max_length=50)

    def __init__(self, voice_channel: discord.VoiceChannel):
        super().__init__()
        self.voice_channel = voice_channel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.voice_channel.edit(name=self.new_name.value)
            await interaction.followup.send(f"✅ Название комнаты изменено на: **{self.new_name.value}**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось изменить название: {e}", ephemeral=True)

class LimitModal(discord.ui.Modal, title="Установить лимит мест"):
    new_limit = discord.ui.TextInput(label="Лимит пользователей (0-99)", placeholder="Например: 5", max_length=2)

    def __init__(self, voice_channel: discord.VoiceChannel):
        super().__init__()
        self.voice_channel = voice_channel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            limit = int(self.new_limit.value)
            if 0 <= limit <= 99:
                await self.voice_channel.edit(user_limit=limit)
                await interaction.followup.send(f"✅ Лимит пользователей установлен: **{limit}**", ephemeral=True)
            else:
                await interaction.followup.send("❌ Лимит должен быть от 0 до 99.", ephemeral=True)
        except ValueError:
            await interaction.followup.send("❌ Введите корректное число!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось изменить лимит: {e}", ephemeral=True)

class TargetUserSelectView(discord.ui.View):
    def __init__(self, voice_channel: discord.VoiceChannel, action: str):
        super().__init__(timeout=60)
        self.voice_channel = voice_channel
        self.action = action

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Выберите участника...")
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        target = select.values[0]
        await interaction.response.defer(ephemeral=True)

        try:
            if self.action == "revoke":
                await self.voice_channel.set_permissions(target, connect=False)
                await interaction.followup.send(f"🚫 Пользователю {target.mention} запрещен вход в комнату.", ephemeral=True)
            elif self.action == "grant":
                await self.voice_channel.set_permissions(target, connect=True)
                await interaction.followup.send(f"✅ Пользователю {target.mention} разрешен доступ в комнату.", ephemeral=True)
            elif self.action == "kick":
                member = interaction.guild.get_member(target.id)
                if member and member.voice and member.voice.channel == self.voice_channel:
                    await member.move_to(None)
                    await interaction.followup.send(f"🚪 Пользователь {target.mention} выгнан из комнаты.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Пользователь не находится в этой комнате.", ephemeral=True)
            elif self.action == "transfer":
                await self.voice_channel.set_permissions(target, connect=True, manage_channels=True, mute_members=True, deafen_members=True, move_members=True)
                await self.voice_channel.set_permissions(interaction.user, manage_channels=False)
                await interaction.followup.send(f"👑 Права владельца переданы {target.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка действия: {e}", ephemeral=True)

class RoomSettingsSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Изменить название", description="Задать новое имя комнате", emoji="✏️", value="rename"),
            discord.SelectOption(label="Установить лимит", description="Ограничить количество мест", emoji="👥", value="limit"),
            discord.SelectOption(label="Забрать доступ", description="Запретить конкретному участнику вход", emoji="➖", value="revoke"),
            discord.SelectOption(label="Выдать доступ", description="Разрешить участнику вход", emoji="➕", value="grant"),
            discord.SelectOption(label="Закрыть комнату", description="Сделать закрытой для всех", emoji="🔒", value="lock"),
            discord.SelectOption(label="Открыть комнату", description="Сделать открытой для всех", emoji="🔓", value="unlock"),
            discord.SelectOption(label="Выгнать пользователя", description="Исключить участника из войса", emoji="🚪", value="kick"),
            discord.SelectOption(label="Передать владение", description="Назначить нового владельца комнаты", emoji="👑", value="transfer"),
            discord.SelectOption(label="Удалить комнату", description="Удалить голосовой канал", emoji="❌", value="delete"),
        ]
        super().__init__(placeholder="Управление приватной комнатой", min_values=1, max_values=1, options=options, custom_id="room_settings_select_persistent")

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        user = interaction.user
        voice_channel = user.voice.channel if user.voice else None

        if not voice_channel:
            return await interaction.response.send_message("❌ Вы должны находиться в своем голосовом канале!", ephemeral=True)

        if not voice_channel.permissions_for(user).manage_channels and not user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Вы не являетесь владельцем этой комнаты!", ephemeral=True)

        if choice == "rename":
            await interaction.response.send_modal(RenameModal(voice_channel))
        elif choice == "limit":
            await interaction.response.send_modal(LimitModal(voice_channel))
        elif choice == "lock":
            await interaction.response.defer(ephemeral=True)
            await voice_channel.set_permissions(interaction.guild.default_role, connect=False)
            await interaction.followup.send("🔒 Комната закрыта для всех.", ephemeral=True)
        elif choice == "unlock":
            await interaction.response.defer(ephemeral=True)
            await voice_channel.set_permissions(interaction.guild.default_role, connect=True)
            await interaction.followup.send("🔓 Комната открыта для всех.", ephemeral=True)
        elif choice == "delete":
            await interaction.response.defer(ephemeral=True)
            await voice_channel.delete()
            await interaction.followup.send("❌ Комната удалена.", ephemeral=True)
        elif choice in ["revoke", "grant", "kick", "transfer"]:
            view = TargetUserSelectView(voice_channel, choice)
            await interaction.response.send_message("Выберите пользователя из списка ниже:", view=view, ephemeral=True)

class RoomSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoomSettingsSelect())

# --- ON_READY ---
@bot.event
async def on_ready():
    print(f"🤖 Основной бот запущен как: {bot.user.name} (ID: {bot.user.id})")
    bot.add_view(CreateRoomView())
    bot.add_view(RoomSettingsView())

    try:
        synced = await bot.tree.sync()
        print(f"🌲 Синхронизировано слэш-команд: {len(synced)}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации слэш-команд: {e}")

# --- ПЕРЕХВАТ СОБЫТИЙ СЕРВЕРА (БОТЫ ИГНОРИРУЮТСЯ) ---
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

# --- УСТАНОВКА МЕНЮ ПРИВАТОК ---
@bot.tree.command(name="setup_create", description="Отправить карточку создания приватных комнат")
@app_commands.checks.has_permissions(administrator=True)
async def slash_setup_create(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✨ Создание приватной комнаты",
        description="Нажмите на кнопку ниже, чтобы мгновенно создать свою комнату и гибко управлять ею.",
        color=discord.Color.from_rgb(217, 78, 47)
    )
    await interaction.channel.send(embed=embed, view=CreateRoomView())
    await interaction.response.send_message("✅ Меню создания комнат успешно выставлено!", ephemeral=True)

@bot.tree.command(name="setup_settings", description="Отправить панель управления приватными комнатами")
@app_commands.checks.has_permissions(administrator=True)
async def slash_setup_settings(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Управление приватной комнатой",
        description="Используйте выпадающее меню ниже для изменения названия, лимита и доступов своей комнаты.",
        color=discord.Color.from_rgb(40, 40, 40)
    )
    await interaction.channel.send(embed=embed, view=RoomSettingsView())
    await interaction.response.send_message("✅ Панель настроек комнат успешно выставлена!", ephemeral=True)

@bot.command(name="setup_create")
@commands.has_permissions(administrator=True)
async def prefix_setup_create(ctx):
    embed = discord.Embed(
        title="✨ Создание приватной комнаты",
        description="Нажмите на кнопку ниже, чтобы создать комнату.",
        color=discord.Color.from_rgb(217, 78, 47)
    )
    await ctx.send(embed=embed, view=CreateRoomView())

@bot.command(name="setup_settings")
@commands.has_permissions(administrator=True)
async def prefix_setup_settings(ctx):
    embed = discord.Embed(
        title="⚙️ Управление приватной комнатой",
        description="Используйте меню ниже для изменения параметров.",
        color=discord.Color.from_rgb(40, 40, 40)
    )
    await ctx.send(embed=embed, view=RoomSettingsView())

# --- МОДЕРИРОВАНИЕ: СЛЭШ-КОМАНДЫ С ИНИЦИАТОРОМ ---
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

@bot.tree.command(name="clear", description="Очистить чат")
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

# --- НОВЫЕ ПОЛЕЗНЫЕ КОМАНДЫ МОДЕРАЦИИ ---
@bot.tree.command(name="slowmode", description="Установить медленный режим для текущего канала")
@app_commands.describe(seconds="Задержка между сообщениями в секундах (0 для отключения)")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int):
    await interaction.channel.edit(slowmode_delay=seconds)
    add_log_entry("Каналы", f"#{interaction.channel.name}", interaction.user.name, f"Медленный режим: {seconds} сек.")
    if seconds > 0:
        await interaction.response.send_message(f"⏳ В канале установлен медленный режим: **{seconds} сек.**")
    else:
        await interaction.response.send_message("⏳ Медленный режим отключен.")

@bot.tree.command(name="lock", description="Заблокировать отправку сообщений в текущем канале для всех")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock_channel(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    add_log_entry("Безопасность", f"#{interaction.channel.name}", interaction.user.name, "Канал заблокирован (/lock)")
    await interaction.response.send_message("🔒 Канал закрыт для отправки сообщений.")

@bot.tree.command(name="unlock", description="Открыть канал для отправки сообщений")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock_channel(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    add_log_entry("Безопасность", f"#{interaction.channel.name}", interaction.user.name, "Канал открыт (/unlock)")
    await interaction.response.send_message("🔓 Канал снова открыт для общения.")

@bot.tree.command(name="userinfo", description="Посмотреть информацию об участнике")
@app_commands.describe(member="Участник")
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
    embed.add_field(name="Присоединился к серверу", value=joined, inline=False)
    embed.add_field(name=f"Роли [{len(roles)}]", value=roles_str, inline=False)

    await interaction.response.send_message(embed=embed)

# --- РАЗВЛЕКАТЕЛЬНЫЕ КОМАНДЫ ---
import random

@bot.tree.command(name="coinflip", description="Подбросить монетку (Орёл или Решка)")
async def coinflip(interaction: discord.Interaction):
    res = random.choice(["🪙 Выпал **Орёл**!", "🪙 Выпала **Решка**!"])
    await interaction.response.send_message(res)

@bot.tree.command(name="roll", description="Случайное число от 1 до указанного максимума")
@app_commands.describe(max_val="Максимальное число (по умолчанию 100)")
async def roll(interaction: discord.Interaction, max_val: int = 100):
    if max_val < 1:
        return await interaction.response.send_message("❌ Число должно быть больше 0!", ephemeral=True)
    val = random.randint(1, max_val)
    await interaction.response.send_message(f"🎲 Вам выпало число: **{val}** (из {max_val})")

@bot.tree.command(name="poll", description="Создать голосование в чате с быстрыми реакциями")
@app_commands.describe(question="Тема голосования")
async def poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(
        title="📊 Голосование",
        description=question,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Автор: {interaction.user.display_name}")
    await interaction.response.send_message("✅ Голосование создано!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")

# --- СИНХРОНИЗАЦИЯ ЧАТА В ВЕБ-ПАНЕЛЬ ---
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

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Ошибка: Переменная DISCORD_TOKEN не задана в Railway!")
    else:
        bot.run(DISCORD_TOKEN)
