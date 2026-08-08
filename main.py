import os
import discord
from discord.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
import discord
from discord.ext import commands

# Указываем префикс "!" для текстовых команд вроде !getlogs
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
import asyncio
import datetime
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
from threading import Thread
from flask import Flask

# Импортируем функционал приваток из privates.py
from privates import CreateRoomButtonView, on_voice_state_update

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
# 1. БАЗА ДАННЫХ (ЭКОНОМИКА, ЕЖЕДНЕВНЫЕ НАГРАДЫ И МАГАЗИН)
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            last_reward TEXT DEFAULT "2000-01-01"
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shop_roles (
            role_id INTEGER PRIMARY KEY,
            price INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# 2. Настройки Intents и Инициализация
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

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
# 3. Настройки yt-dlp и Музыки
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
    bot.add_view(CreateRoomButtonView())
    try:
        synced = await bot.tree.sync()
        print(f"🌲 Синхронизировано слэш-команд: {len(synced)}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации слэш-команд: {e}")
    print("--------------------------------------------------")

bot.add_listener(on_voice_state_update, 'on_voice_state_update')

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

async def load_extensions():
  await bot.load_extension("cogs.shop")
  await bot.load_extension("logger")
  await bot.load_extension("cogs.console_logger")

@bot.event
async def on_ready():
  print(f"Logged in as {bot.user}")
  await load_extensions()
  try:
    guild = discord.Object(id=890471319815192597)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    print(f"Synced {len(synced)} slash commands.")
  except Exception as e:
    print(f"Ошибка синхронизации: {e}")
      
@bot.event
async def on_ready():
  await bot.tree.sync()  # Принудительно синхронизирует все слэш-команды с серверами
  print(f"Бот {bot.user} запущен и команды синхронизированы!")
    

# --------------------------------------------------------#
# 5. КОМАНДЫ ЭКОНОМИКИ, НАГРАД И МАГАЗИНА                  #
# ---------------------------------------------------------#

@bot.tree.command(name="reward", description="Получить ежедневную награду (раз в сутки)")
async def reward_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    today = datetime.date.today().isoformat()

    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('SELECT last_reward, points FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()

    if row:
        last_reward_date = row[0]
        if last_reward_date == today:
            conn.close()
            await interaction.response.send_message("⏳ Вы уже получали ежедневную награду сегодня! Приходите завтра.", ephemeral=True)
            return
        
        cursor.execute('UPDATE users SET points = points + 100, last_reward = ? WHERE user_id = ?', (today, user_id))
    else:
        cursor.execute('INSERT INTO users (user_id, points, last_reward) VALUES (?, 100, ?)', (user_id, today))

    conn.commit()
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
    new_balance = cursor.fetchone()[0]
    conn.close()

    await interaction.response.send_message(f"🎁 Вы успешно получили ежедневную награду — **100 монет**!\n💎 Ваш текущий баланс: **{new_balance}** монет.")

@bot.tree.command(name="bal", description="Проверить свой баланс монет")
@app_commands.describe(member="Участник (необязательно)")
async def bal_command(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (target.id,))
    row = cursor.fetchone()
    points = row[0] if row else 0
    conn.close()
    await interaction.response.send_message(f"💎 У пользователя **{target.display_name}** баланс: **{points} монет**.")

@bot.command(name='addshop')
@commands.has_permissions(administrator=True)
async def add_shop_role(ctx, role: discord.Role, price: int):
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO shop_roles (role_id, price) VALUES (?, ?)', (role.id, price))
    conn.commit()
    conn.close()
    await ctx.send(f'🛒 Роль {role.mention} добавлена в магазин за **{price}** монет.')

@bot.command(name='addpoints')
@commands.has_permissions(administrator=True)
async def add_points(ctx, member: discord.Member, amount: int):
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, points) VALUES (?, 0)', (member.id,))
    cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (amount, member.id))
    conn.commit()
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (member.id,))
    new_balance = cursor.fetchone()[0]
    conn.close()
    await ctx.send(f'✅ Администратор выдал {amount} монет пользователю {member.mention}. Новый баланс: **{new_balance}**.')
    # Отправляем сообщение вместе с вашим выпадающим списком (RoomSettingsView)
    await ctx.send(embed=embed, view=RoomSettingsView())
    try:
        await ctx.message.delete()
    except:
        pass
        
    
    await ctx.send(embed=embed, view=CreateRoomButtonView())
    try:
        await ctx.message.delete()
    except:
        pass

# ---------------------------------------------------------
# 6. СЛЭШ-КОМАНДЫ ДОЛЖНОСТЕЙ И МОДЕРАЦИИ
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

@bot.tree.command(name="role", description="Создать личную роль с указанием названия и цвета (Стоимость: 10000 монет)")
@app_commands.describe(
    name="Название будущей роли",
    color="Цвет роли в HEX формате (например: #FF0000 или FF0000)"
)
async def role_command(interaction: discord.Interaction, name: str, color: str):
    clean_color = color.strip("#")
    try:
        role_color = discord.Color(int(clean_color, 16))
    except ValueError:
        await interaction.response.send_message("❌ Неверный формат цвета! Используйте HEX формат, например: `#FF0000`.", ephemeral=True)
        return

    user_id = interaction.user.id
    role_price = 10000

    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    user_points = row[0] if row else 0

    if user_points < role_price:
        conn.close()
        await interaction.response.send_message(f"❌ У вас недостаточно средств! Создание личной роли стоит **{role_price} монет**, а у вас всего **{user_points} монет**.", ephemeral=True)
        return

    try:
        guild = interaction.guild
        new_role = await guild.create_role(
            name=name, 
            color=role_color, 
            reason=f"Личная роль создана пользователем {interaction.user}"
        )
        
        cursor.execute('UPDATE users SET points = points - ? WHERE user_id = ?', (role_price, user_id))
        conn.commit()
        conn.close()

        await interaction.user.add_roles(new_role)
        await interaction.response.send_message(f"✅ Вы успешно создали личную роль {new_role.mention} за **{role_price} монет**!", ephemeral=True)
    except discord.Forbidden:
        conn.close()
        await interaction.response.send_message("❌ У бота нет прав на создание или выдачу ролей! Проверьте иерархию ролей бота.", ephemeral=True)
    except Exception as e:
        conn.close()
        await interaction.response.send_message(f"❌ Произошла ошибка: {e}", ephemeral=True)

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
async def mute(interaction: discord.Interaction, member: discord.Member, duration_minutes: int, reason: str = "Причина не указана"):
    try:
        duration = datetime.timedelta(minutes=duration_minutes)
        await member.timeout(duration, reason=reason)
        await interaction.response.send_message(f"🔇 Участник **{member.name}** получил мут на {duration_minutes} мин. Причина: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Не удалось выдать мут: {e}", ephemeral=True)

# ---------------------------------------------------------
# ЗАПУСК БОТА И WEB-СЕРВЕРА
# ---------------------------------------------------------
    import discord
from discord.ext import commands

# Словарь для хранения баланса пользователей: {user_id: amount}
user_balances = {}

# --- Модуль создания приватной комнаты ---

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
        category = interaction.channel.category  # Создаем в том же разделе
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            author: discord.PermissionOverwrite(connect=True, manage_channels=True, mute_members=True, deafen_members=True, move_members=True)
        }
        
        try:
            channel = await guild.create_voice_channel(
                name=self.room_name.value, 
                overwrites=overwrites, 
                category=category
            )
            
            if author.voice:
                await author.move_to(channel)
                
            await interaction.followup.send(f"✅ Ваша приватная комната **{self.room_name.value}** успешно создана!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка при создании комнаты: {e}", ephemeral=True)

class CreateRoomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать приватную комнату", style=discord.ButtonStyle.green, custom_id="create_room_btn", emoji="➕")
    async def create_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateRoomModal())

@bot.command(name="setup_create")
@commands.has_permissions(administrator=True)
async def setup_create(ctx):
    embed = discord.Embed(
        title="Создание приватной комнаты",
        description="Вы можете **создать** собственную **приватную комнату** с необходимым названием, а впоследствии **гибко настроить** в соответствии с имеющимся функционалом.",
        color=discord.Color.from_rgb(217, 78, 47)
    )
    await ctx.send(embed=embed, view=CreateRoomView())
    try:
        await ctx.message.delete()
    except:
        pass


# --- Модуль настройки приватной комнаты ---

class RenameModal(discord.ui.Modal, title="Изменить название комнаты"):
    new_name = discord.ui.TextInput(
        label="Новое название",
        placeholder="Введите название...",
        max_length=50,
    )

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
    new_limit = discord.ui.TextInput(
        label="Лимит пользователей (0-99)",
        placeholder="Например: 5",
        max_length=2,
    )

    def __init__(self, voice_channel: discord.VoiceChannel):
        super().__init__()
        self.voice_channel = voice_channel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            limit = int(self.new_limit.value)
            if 0 <= limit <= 99:
                await self.voice_channel.edit(user_limiTOKENt)
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
                await interaction.followup.send(f"🚫 Пользователь {target.mention} больше не может заходить в комнату.", ephemeral=True)
            elif self.action == "grant":
                await self.voice_channel.set_permissions(target, connect=True)
                await interaction.followup.send(f"✅ Пользователю {target.mention} разрешен вход в комнату.", ephemeral=True)
            elif self.action == "mute":
                member = interaction.guild.get_member(target.id)
                if member and member.voice:
                    await member.edit(mute=True)
                    await interaction.followup.send(f"🔇 Пользователь {target.mention} заглушен.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Пользователь не находится в голосовом канале.", ephemeral=True)
            elif self.action == "unmute":
                member = interaction.guild.get_member(target.id)
                if member and member.voice:
                    await member.edit(mute=False)
                    await interaction.followup.send(f"🎙️ С пользователя {target.mention} снят мут.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Пользователь не находится в голосовом канале.", ephemeral=True)
            elif self.action == "kick":
                member = interaction.guild.get_member(target.id)
                if member and member.voice and member.voice.channel == self.voice_channel:
                    await member.move_to(None)
                    await interaction.followup.send(f"🚪 Пользователь {target.mention} выгнан из комнаты.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Пользователь не найден в вашей комнате.", ephemeral=True)
            elif self.action == "transfer":
                await self.voice_channel.set_permissions(target, connect=True, manage_channels=True, mute_members=True, deafen_members=True, move_members=True)
                await self.voice_channel.set_permissions(interaction.user, manage_channels=False)
                await interaction.followup.send(f"👑 Права владельца комнаты переданы пользователю {target.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Произошла ошибка: {e}", ephemeral=True)

class RoomSettingsSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Изменить название", description="Изменить название вашей комнаты", emoji="✏️", value="rename"),
            discord.SelectOption(label="Установить лимит", description="Ограничить количество мест в комнате", emoji="👥", value="limit"),
            discord.SelectOption(label="Забрать доступ", description="Запретить пользователю заходить в комнату", emoji="➖", value="revoke"),
            discord.SelectOption(label="Выдать доступ", description="Разрешить пользователю вход в комнату", emoji="➕", value="grant"),
            discord.SelectOption(label="Закрыть комнату для всех", description="Сделать комнату закрытой", emoji="🔒", value="lock"),
            discord.SelectOption(label="Открыть комнату для всех", description="Сделать комнату открытой", emoji="🔓", value="unlock"),
            discord.SelectOption(label="Отключить микрофон", description="Заглушить пользователя в комнате", emoji="🔇", value="mute"),
            discord.SelectOption(label="Включить микрофон", description="Включить звук пользователю", emoji="🎙️", value="unmute"),
            discord.SelectOption(label="Выгнать пользователя", description="Кикнуть участника из комнаты", emoji="🚪", value="kick"),
            discord.SelectOption(label="Назначить владельца", description="Передать права на комнату другому", emoji="👑", value="transfer"),
            discord.SelectOption(label="Удалить приватную комнату", description="Полностью удалить канал", emoji="❌", value="delete"),
        ]
        super().__init__(placeholder="Настроить приватную комнату", min_values=1, max_values=1, options=options, custom_id="room_settings_select")

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        user = interaction.user
        
        voice_channel = user.voice.channel if user.voice else None

        if not voice_channel:
            await interaction.response.send_message("❌ Вы должны находиться в голосовом канале, чтобы управлять им!", ephemeral=True)
            return
        
        # Проверка прав (создатель канала имеет manage_channels)
        if not voice_channel.permissions_for(user).manage_channels and not user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Вы не являетесь владельцем этой комнаты!", ephemeral=True)
            return

        if choice == "rename":
            await interaction.response.send_modal(RenameModal(voice_channel))
        elif choice == "limit":
            await interaction.response.send_modal(LimitModal(voice_channel))
        elif choice == "lock":
            await interaction.response.defer(ephemeral=True)
            try:
                await voice_channel.set_permissions(interaction.guild.default_role, connect=False)
                await interaction.followup.send("🔒 Комната закрыта для всех.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)
        elif choice == "unlock":
            await interaction.response.defer(ephemeral=True)
            try:
                await voice_channel.set_permissions(interaction.guild.default_role, connect=True)
                await interaction.followup.send("🔓 Комната открыта для всех.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)
        elif choice == "delete":
            await interaction.response.defer(ephemeral=True)
            try:
                await voice_channel.delete()
                await interaction.followup.send("❌ Приватная комната успешно удалена.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Не удалось удалить комнату: {e}", ephemeral=True)
        elif choice in ["revoke", "grant", "mute", "unmute", "kick", "transfer"]:
            view = TargetUserSelectView(voice_channel, choice)
            await interaction.response.send_message("Выберите пользователя из списка ниже:", view=view, ephemeral=True)

class RoomSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoomSettingsSelect())

@bot.command(name="setup_settings")
@commands.has_permissions(administrator=True)
async def setup_settings(ctx):
    embed = discord.Embed(
        title="Настройка приватной комнаты",
        description="Вы можете **настроить** созданную **приватную комнату** в соответствии с доступным функционалом. Чтобы это сделать воспользуйтесь меню под сообщением.",
        color=discord.Color.from_rgb(40, 40, 40)
    )
    await ctx.send(embed=embed, view=RoomSettingsView())
    try:
        await ctx.message.delete()
    except:
        pass

# --- Автоматическое удаление пустых комнат ---
@bot.event
async def on_voice_state_update(member, before, after):
    # Если человек вышел из канала, и в этом канале больше никого нет
    if before.channel and before.channel != after.channel:
        # Проверяем, является ли канал созданными приватным (например, если он находится в категории с созданием или пуст)
        # Здесь условие проверяет, что в канале 0 участников и название/права указывают на то, что это пустой войс (можно настроить проверку по категории)
        if len(before.channel.members) == 0:
            # Убедитесь, что это именно динамическая комната (например, проверяем по префиксу или категории)
            try:
                # Если хотите удалять только те каналы, которые создавались ботом, можно добавить проверку по категории
                await before.channel.delete()
            except:
                pass
    
# --- Команда для выдачи монет (с сохранением баланса) ---

@bot.command(name="add_money")
@commands.has_permissions(administrator=True)
async def add_money(ctx, member: discord.Member, amount: int):
    # Добавляем монеты в словарь по ID пользователя
    current_balance = user_balances.get(member.id, 0)
    user_balances[member.id] = current_balance + amount
    
    await ctx.send(f"Успешно выдано **{amount}** монет пользователю {member.mention}! (Баланс: {user_balances[member.id]})")


# --- Запуск бота ---

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ Ошибка: Не найден токен бота в переменных окружения (DISCORD_TOKEN).")
    else:
        bot.run(DISCORD_TOKEN)
        
