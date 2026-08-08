import os
import sys
import asyncio
import datetime
import sqlite3
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands
from discord import app_commands
import logging
# Импортируем функционал приваток из privates.py
from privates import CreateRoomButtonView

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

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


LOG_BUFFER = []
MAX_BUFFER_SIZE = 25


# 1. СНАЧАЛА СОЗДАЕМ БОТА:
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)


# 2. БЕЗОПАСНЫЙ ПЕРЕХВАТЧИК КОНСОЛИ (без вызова бота из потоков):
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


# 3. ВКЛЮЧАЕМ ПЕРЕХВАТ:
if not isinstance(sys.stdout, ConsoleCapture):
  interceptor = ConsoleCapture()
  sys.stdout = interceptor
  sys.stderr = interceptor
 

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

from discord.ext import tasks

# Фоновая задача для автоматической отправки новых логов
@tasks.loop(seconds=30)
async def auto_send_logs():
    if not LOG_BUFFER:
        return
    
    try:
        conn = sqlite3.connect("economy.db")
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key LIKE 'log_channel_%'")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return

        # Берем последние логи из буфера, которые еще не отправлялись
        logs_to_send = "\n".join(LOG_BUFFER)
        LOG_BUFFER.clear() # Очищаем буфер после отправки

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

# Запускаем задачу при старте бота (например, в событии on_ready или прямо здесь)
# auto_send_logs.start()


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

    # Инициализация отправки логов в канал
    
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

  # Сначала загружаем все коги (включая shop и console_logger)
@bot.event
async def on_ready():
    # 1. Загружаем коги
    try:
        await bot.load_extension("cogs.shop")
        print("✅ Коги успешно загружены!")
    except Exception as e:
        print(f"❌ Ошибка загрузки когов: {e}")

    # 2. Синхронизируем слэш-команды на ваш сервер
    try:
        guild = discord.Object(id=890471319815192597)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"🌲 Синхронизировано слэш-команд: {len(synced)}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")

    # 3. Дополнительные вьюхи (если нужны)
    try:
        bot.add_view(CreateRoomButtonView())
    except Exception:
        pass

    print(f"🤖 Бот {bot.user} успешно запущен и готов к работе!")

@bot.command(name="getlogs")
async def getlogs_text(ctx):
    if not LOG_BUFFER:
        await ctx.send("📭 Буфер логов пока пуст.")
        return

    logs_text = "\n".join(LOG_BUFFER)
    if len(logs_text) > 1900:
        logs_text = logs_text[-1900:]

    await ctx.send(
        f"📜 **Последние логи из буфера:**\n```py\n{logs_text}\n```"
    )

    # Сохраняем канал в БД
    try:
        conn = sqlite3.connect("economy.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (f"log_channel_{ctx.guild.id}", str(ctx.channel.id)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

@bot.command(name="fix_db")
@commands.is_owner() # Чтобы только вы могли это запустить
async def fix_db(ctx):
  try:
    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()
    cursor.execute("ALTER TABLE shop_roles ADD COLUMN owner_id INTEGER;")
    cursor.execute("ALTER TABLE shop_roles ADD COLUMN purchases INTEGER DEFAULT 0;")
    conn.commit()
    conn.close()
    await ctx.send("✅ База данных успешно обновлена!")
  except Exception as e:
    await ctx.send(f"❌ Ошибка (возможно, колонки уже есть): {e}")
    
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

#логииииииии#
# --- ЛОГИ ---#
@bot.tree.command(
    name="getlogs", description="Получить последние логи и привязать этот канал"
)
async def getlogs_slash(interaction: discord.Interaction):
  await interaction.response.defer(ephemeral=True)

  try:
    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (f"log_channel_{interaction.guild.id}", str(interaction.channel.id)),
    )
    conn.commit()
    conn.close()
  except Exception:
    pass

  if not LOG_BUFFER:
    await interaction.followup.send(
        "📭 Буфер логов пока пуст, но канал успешно привязан!", ephemeral=True
    )
    return

  logs_text = "\n".join(LOG_BUFFER)
  if len(logs_text) > 1900:
    logs_text = logs_text[-1900:]

  await interaction.channel.send(
      f"📜 **Последние логи из буфера:**\n```py\n{logs_text}\n```"
  )
  await interaction.followup.send(
      "✅ Готово! Логи отправлены в чат, а канал привязан для будущих ошибок.",
      ephemeral=True,
  )
    
    
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
  # 1. Сразу даем понять Discord, что бот думает (убирает ошибку 10062)
  await interaction.response.defer(ephemeral=True)

  # 2. Удаляем сообщения (плюс 1, чтобы удалить саму команду, если нужно)
  deleted = await interaction.channel.purge(limit=amount + 1)

  # 3. Отправляем результат через followup
  await interaction.followup.send(
      f"🧹 Удалено сообщений: **{len(deleted) - 1}**", ephemeral=True
  )
    

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

# --- Команда для выдачи монет (с сохранением баланса) ---

@bot.command(name="add_money")
@commands.has_permissions(administrator=True)
async def add_money(ctx, member: discord.Member, amount: int):
    # Добавляем монеты в словарь по ID пользователя
    current_balance = user_balances.get(member.id, 0)
    user_balances[member.id] = current_balance + amount
    
    await ctx.send(f"Успешно выдано **{amount}** монет пользователю {member.mention}! (Баланс: {user_balances[member.id]})")

# --- 1. Обработчик системных логов Python ---
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
                print(f"Ошибка отправки лога: {e}")


# --- ID канала для логов ---
LOG_CHANNEL_ID = 1535375319517626448

# Подключение системного обработчика к логированию
if not any(
    isinstance(h, DiscordLogHandler) for h in logging.getLogger().handlers
):
    handler = DiscordLogHandler(bot, LOG_CHANNEL_ID)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
        )
    )
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


# --- 2. Событийные логи (действия пользователей) ---
@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(
            f"🗑️ **Сообщение удалено** | В канале {message.channel.mention}\nАвтор: {message.author.mention}\nТекст: {message.content}"
        )


@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(
            f"✏️ **Сообщение изменено** | В канале {before.channel.mention}\nАвтор: {before.author.mention}\nБыло: {before.content}\nСтало: {after.content}"
        )


@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    if before.channel is None and after.channel is not None:
        await channel.send(
            f"🔊 **{member.name}** вошел в голосовой канал **{after.channel.name}**"
        )
    elif before.channel is not None and after.channel is None:
        await channel.send(
            f"🔇 **{member.name}** вышел из голосового канала **{before.channel.name}**"
        )
    elif before.channel != after.channel:
        await channel.send(
            f"🔀 **{member.name}** переместился: **{before.channel.name}** ➡️ **{after.channel.name}**"
        )


@bot.event
async def on_member_ban(guild, user):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(
            f"🚫 **Участник забанен:** {user.name} (ID: {user.id})"
        )
        

# --- Запуск бота ---

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ Ошибка: Не найден токен бота в переменных окружения (DISCORD_TOKEN).")
    else:
        bot.run(DISCORD_TOKEN)
        
