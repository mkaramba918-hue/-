import os
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

# ---------------------------------------------------------
# 4. МАГАЗИН РОЛЕЙ (UI)
# ---------------------------------------------------------
class RoleShopView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)
        self.guild = guild
        self.update_components()

    def update_components(self):
        self.clear_items()
        conn = sqlite3.connect('economy.db')
        cursor = conn.cursor()
        cursor.execute('SELECT role_id, price FROM shop_roles')
        items = cursor.fetchall()
        conn.close()

        if not items:
            return

        options = []
        for role_id, price in items:
            role = self.guild.get_role(role_id)
            if role:
                options.append(
                    discord.SelectOption(
                        label=role.name,
                        value=str(role_id),
                        description=f"Стоимость: {price} баллов",
                        emoji="🏷️"
                    )
                )

        if options:
            select = discord.Select(placeholder="Выберите роль для покупки...", options=options[:25])
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        role_id = int(interaction.data["values"][0])
        role = interaction.guild.get_role(role_id)
        
        if not role:
            await interaction.response.send_message("❌ Эта роль была удалена на сервере.", ephemeral=True)
            return

        conn = sqlite3.connect('economy.db')
        cursor = conn.cursor()
        cursor.execute('SELECT price FROM shop_roles WHERE role_id = ?', (role_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            await interaction.response.send_message("❌ Роль не найдена в магазине.", ephemeral=True)
            return
        price = row[0]

        cursor.execute('SELECT points FROM users WHERE user_id = ?', (interaction.user.id,))
        user_row = cursor.fetchone()
        user_points = user_row[0] if user_row else 0

        if user_points < price:
            conn.close()
            await interaction.response.send_message(f"❌ Недостаточно баллов! У вас **{user_points}**, а нужно **{price}**.", ephemeral=True)
            return

        cursor.execute('UPDATE users SET points = points - ? WHERE user_id = ?', (price, interaction.user.id))
        conn.commit()
        conn.close()

        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"🎉 Вы успешно купили роль **{role.name}** за **{price}** баллов!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав на выдачу этой роли (проверьте иерархию ролей!).", ephemeral=True)

# ---------------------------------------------------------
# 5. КОМАНДЫ ЭКОНОМИКИ, НАГРАД И МАГАЗИНА
# ---------------------------------------------------------

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

    await interaction.response.send_message(f"🎁 Вы успешно получили ежедневную награду — **100 баллов**!\n💎 Ваш текущий баланс: **{new_balance}** баллов.")

@bot.tree.command(name="bal", description="Проверить свой баланс баллов")
@app_commands.describe(member="Участник (необязательно)")
async def bal_command(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (target.id,))
    row = cursor.fetchone()
    points = row[0] if row else 0
    conn.close()
    await interaction.response.send_message(f"💎 У пользователя **{target.display_name}** баланс: **{points} баллов**.")

@bot.tree.command(name="shop", description="Открыть магазин ролей")
async def shop_command(interaction: discord.Interaction):
    view = RoleShopView(interaction.guild)
    if not view.children:
        await interaction.response.send_message("🛒 Магазин ролей пока пуст! Администратор может добавить роли через текстовую команду `!addshop`.", ephemeral=True)
    else:
        await interaction.response.send_message("🛒 **Магазин ролей сервера**\nВыберите нужную роль в меню ниже, чтобы приобрести её за баллы:", view=view, ephemeral=True)

@bot.command(name='addshop')
@commands.has_permissions(administrator=True)
async def add_shop_role(ctx, role: discord.Role, price: int):
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO shop_roles (role_id, price) VALUES (?, ?)', (role.id, price))
    conn.commit()
    conn.close()
    await ctx.send(f'🛒 Роль {role.mention} добавлена в магазин за **{price}** баллов.')

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
    await ctx.send(f'✅ Администратор выдал {amount} баллов пользователю {member.mention}. Новый баланс: **{new_balance}**.')
@bot.command(name="setup_settings")
@commands.has_permissions(administrator=True)
async def setup_settings(ctx):
    embed = discord.Embed(
        title="Настройка приватной комнаты",
        description="Вы можете **настроить** созданную **приватную комнату** в соответствии с доступным функционалом. Чтобы это сделать воспользуйтесь меню под сообщением.",
        color=discord.Color.from_rgb(40, 40, 40)
    )
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
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ Ошибка: Не найден токен бота в переменных окружения (DISCORD_TOKEN).")
    else:
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
            bot.run(TOKEN)
        
