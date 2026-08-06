import os
import threading
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask

# Импортируем логику приваток из вашего отдельного файла (privates.py)
from privates import CreateRoomButtonView, on_voice_state_update

# ---------------------------------------------------------
# 1. НАСТРОЙКА FLASK ДЛЯ RENDER (УДЕРЖАНИЕ СЕРВИСА 24/7)
# ---------------------------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "🤖 Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# ---------------------------------------------------------
# 2. НАСТРОЙКА БАЗЫ ДАННЫХ (ЭКОНОМИКА И МАГАЗИН РОЛЕЙ)
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0
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
# 3. НАСТРОЙКА DISCORD БОТА И ИНТЕНТОВ
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'🤖 Авторизован как {bot.user} (ID: {bot.user.id})')
    # Регистрируем persistent view для кнопки приваток, чтобы она работала после перезагрузки
    bot.add_view(CreateRoomButtonView())
    try:
        synced = await bot.tree.sync()
        print(f"🌲 Синхронизировано слэш-команд: {len(synced)}")
    except Exception as e:
        print(f"Ошибка синхронизации команд: {e}")

# Подключаем событие отслеживания голосовых каналов из приваток
bot.add_listener(on_voice_state_update, 'on_voice_state_update')

# ---------------------------------------------------------
# 4. МАГАЗИН РОЛЕЙ (ВЫПАДАЮЩИЙ СПИСОК)
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
# 5. КОМАНДЫ (БАЛЛЫ, МАГАЗИН И ПАНЕЛЬ ПРИВАТОК)
# ---------------------------------------------------------
@bot.command(name='баллы', aliases=['points', 'bal'])
async def get_points(ctx, member: discord.Member = None):
    member = member or ctx.author
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (member.id,))
    row = cursor.fetchone()
    points = row[0] if row else 0
    conn.close()
    await ctx.send(f'💎 У пользователя **{member.display_name}** баланс: **{points} баллов**.')

@bot.command(name='датьбаллы', aliases=['addpoints'])
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

@bot.command(name='addshop')
@commands.has_permissions(administrator=True)
async def add_shop_role(ctx, role: discord.Role, price: int):
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO shop_roles (role_id, price) VALUES (?, ?)', (role.id, price))
    conn.commit()
    conn.close()
    await ctx.send(f'🛒 Роль {role.mention} добавлена в магазин за **{price}** баллов.')

@bot.command(name='shop', aliases=['магазин'])
async def shop_command(ctx):
    view = RoleShopView(ctx.guild)
    if not view.children:
        await ctx.send("🛒 Магазин ролей пока пуст! Администратор может добавить роли через команду `!addshop`.")
    else:
        await ctx.send("🛒 **Магазин ролей сервера**\nВыберите нужную роль в меню ниже, чтобы приобрести её за баллы:", view=view)

# Команда для вызова панели создания приваток в канале `#создать-комнату`
@bot.command(name='setup_panel')
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    embed = discord.Embed(
        title="✨ Создание приватной комнаты",
        description="Вы можете **создать** собственную приватную комнату с необходимым названием, а впоследствии **гибко настроить** в соответствии с имеющимся функционалом.",
        color=discord.Color.dark_embed()
    )
    await ctx.send(embed=embed, view=CreateRoomButtonView())
    try:
        await ctx.message.delete()
    except:
        pass

# Слэш-команда создания личной роли с названием и цветом (Black Russia style)
@bot.tree.command(name="role", description="Создать личную роль с указанием названия и цвета")
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

    try:
        guild = interaction.guild
        new_role = await guild.create_role(
            name=name, 
            color=role_color, 
            reason=f"Личная роль создана пользователем {interaction.user}"
        )
        await interaction.user.add_roles(new_role)
        await interaction.response.send_message(f"✅ Вы успешно создали и получили личную роль {new_role.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ У бота нет прав на создание или выдачу ролей! Проверьте иерархию ролей бота.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Произошла ошибка: {e}", ephemeral=True)

# ---------------------------------------------------------
# 6. ЗАПУСК БОТА И ВЕБ-СЕРВЕРА
# ---------------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    token = os.getenv("DISCORD_TOKEN")
    
    if not token:
        print("❌ ОШИБКА: Переменная DISCORD_TOKEN не найдена или пуста в Render!")
    else:
        try:
            bot.run(token)
        except Exception as e:
            print(f"❌ Ошибка при запуске бота: {e}")
            
