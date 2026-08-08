import sqlite3
import discord
from discord.ext import commands

# --- Авто-инициализация базы данных ---
conn = sqlite3.connect("economy.db")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 0
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS shop_roles (
        role_id INTEGER PRIMARY KEY,
        price INTEGER DEFAULT 0,
        owner_id INTEGER DEFAULT 0,
        purchases INTEGER DEFAULT 0
    )
""")
try:
  cursor.execute("ALTER TABLE users ADD COLUMN points INTEGER DEFAULT 0")
except sqlite3.OperationalError:
  pass
conn.commit()
conn.close()


class RoleBuyButton(discord.ui.Button):

  def __init__(self, role_id, price):
    super().__init__(
        style=discord.ButtonStyle.green, label="Купить роль", emoji="🛒"
    )
    self.role_id = role_id
    self.price = price

  async def callback(self, interaction: discord.Interaction):
    # Сразу защищаем взаимодействие от таймаута
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    role = guild.get_role(self.role_id)

    if not role:
      await interaction.followup.send(
          "❌ Эта роль больше не существует на сервере.", ephemeral=True
      )
      return

    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()

    # Проверяем баланс пользователя
    cursor.execute(
        "SELECT points FROM users WHERE user_id = ?", (interaction.user.id,)
    )
    user_row = cursor.fetchone()
    user_balance = user_row[0] if user_row else 0

    if user_balance < self.price:
      conn.close()
      await interaction.followup.send(
          f"❌ У вас недостаточно средств! Нужно: {self.price} монет, а у вас: {user_balance} монет.",
          ephemeral=True,
      )
      return

    # Списываем points и обновляем счетчик покупок
    cursor.execute(
        "UPDATE users SET points = points - ? WHERE user_id = ?",
        (self.price, interaction.user.id),
    )
    cursor.execute(
        "UPDATE shop_roles SET purchases = purchases + 1 WHERE role_id = ?",
        (self.role_id,),
    )
    conn.commit()
    conn.close()

    # Выдаем роль и отправляем итоговое сообщение через followup
    try:
      await interaction.user.add_roles(role)
      await interaction.followup.send(
          f"✅ Вы успешно купили роль {role.mention} за {self.price} монет!",
          ephemeral=True,
      )
    except discord.Forbidden:
      await interaction.followup.send(
          "❌ У бота нет прав на выдачу этой роли (проверьте иерархию ролей).",
          ephemeral=True,
      )


class RoleShopPaginator(discord.ui.View):

  def __init__(self, roles_data, guild):
    super().__init__(timeout=180)
    self.roles_data = roles_data
    self.current_page = 0
    self.guild = guild
    self.update_buttons()

  def update_buttons(self):
    self.clear_items()
    if not self.roles_data:
      return

    role_id, price, owner_id, purchases = self.roles_data[self.current_page]
    self.add_item(RoleBuyButton(role_id, price))

    if len(self.roles_data) > 1:
      prev_button = discord.ui.Button(
          style=discord.ButtonStyle.secondary, emoji="◀️", disabled=(self.current_page == 0)
      )
      prev_button.callback = self.prev_page
      self.add_item(prev_button)

      next_button = discord.ui.Button(
          style=discord.ButtonStyle.secondary,
          emoji="▶️",
          disabled=(self.current_page == len(self.roles_data) - 1),
      )
      next_button.callback = self.next_page
      self.add_item(next_button)

  def get_embed(self):
    embed = discord.Embed(
        title="📜 Магазин личных ролей", color=discord.Color.from_rgb(43, 45, 49)
    )

    if not self.roles_data:
      embed.description = "В магазине пока нет доступных ролей."
      embed.set_footer(text="Страница 0/0")
      return embed

    role_id, price, owner_id, purchases = self.roles_data[self.current_page]
    role = self.guild.get_role(role_id)
    role_mention = role.mention if role else f"Удаленная роль (ID: {role_id})"
    owner_mention = f"<@{owner_id}>" if owner_id else "Не указан"

    embed.description = (
        f"Страница {self.current_page + 1}/{len(self.roles_data)}\n\n"
        f"**{self.current_page + 1}. Роль**\n"
        f"{role_mention} — {role.name if role else 'Unknown'}\n\n"
        f"**Инфо**\n"
        f"👤 Владелец: {owner_mention}\n"
        f"🪙 Цена: **{price}** монет\n"
        f"🛒 Куплена раз: **{purchases}**"
    )
    return embed

  async def prev_page(self, interaction: discord.Interaction):
    if self.current_page > 0:
      self.current_page -= 1
      self.update_buttons()
      await interaction.response.edit_message(
          embed=self.get_embed(), view=self
      )

  async def next_page(self, interaction: discord.Interaction):
    if self.current_page < len(self.roles_data) - 1:
      self.current_page += 1
      self.update_buttons()
      await interaction.response.edit_message(
          embed=self.get_embed(), view=self
      )


class Shop(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @discord.app_commands.command(
      name="role_shop", description="Открыть магазин личных ролей"
  )
  async def shop(self, interaction: discord.Interaction):
    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role_id, price, owner_id, purchases FROM shop_roles"
    )
    roles_data = cursor.fetchall()
    conn.close()

    if not roles_data:
      await interaction.response.send_message(
          "❌ В магазине пока нет ни одной роли.", ephemeral=True
      )
      return

    view = RoleShopPaginator(roles_data, interaction.guild)
    embed = view.get_embed()
    await interaction.response.send_message(
        embed=embed, view=view, ephemeral=True
    )


async def setup(bot):
  await bot.add_cog(Shop(bot))
    
