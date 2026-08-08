import sqlite3
import discord
from discord.ext import commands


class RoleSelect(discord.ui.Select):

  def __init__(self, options):
    super().__init__(
        placeholder="Выберите роль для покупки...",
        min_values=1,
        max_values=1,
        options=options,
    )

  async def callback(self, interaction: discord.Interaction):
    role_id = int(self.values[0])
    guild = interaction.guild
    role = guild.get_role(role_id)

    if not role:
      await interaction.response.send_message(
          "❌ Эта роль больше не существует на сервере.", ephemeral=True
      )
      return

    # Проверка и списание валюты из базы данных, выдача роли
    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()

    # Проверяем баланс пользователя (предполагаем таблицу users с полями user_id и balance)
    cursor.execute(
        "SELECT balance FROM users WHERE user_id = ?", (interaction.user.id,)
    )
    user_row = cursor.fetchone()
    user_balance = user_row[0] if user_row else 0

    # Проверяем цену роли (предполагаем таблицу shop_roles с полями role_id и price)
    cursor.execute(
        "SELECT price FROM shop_roles WHERE role_id = ?", (role_id,)
    )
    role_row = cursor.fetchone()

    if not role_row:
      conn.close()
      await interaction.response.send_message(
          "❌ Этот товар не найден в базе данных.", ephemeral=True
      )
      return

    price = role_row[0]

    if user_balance < price:
      conn.close()
      await interaction.response.send_message(
          f"❌ У вас недостаточно средств! Нужно: {price}, а у вас:"
          f" {user_balance}.",
          ephemeral=True,
      )
      return

    # Списываем баланс и выдаем роль
    cursor.execute(
        "UPDATE users SET balance = balance - ? WHERE user_id = ?",
        (price, interaction.user.id),
    )
    conn.commit()
    conn.close()

    try:
      await interaction.user.add_roles(role)
      await interaction.response.send_message(
          f"✅ Вы успешно купили роль {role.mention} за {price} валюты!",
          ephemeral=True,
      )
    except discord.Forbidden:
      await interaction.response.send_message(
          "❌ У бота нет прав на выдачу этой роли (проверьте иерархию ролей).",
          ephemeral=True,
      )


class RoleShopView(discord.ui.View):

  def __init__(self):
    super().__init__()
    conn = sqlite3.connect("economy.db")
    cursor = conn.cursor()

    # Подгружаем все роли из базы данных магазина
    cursor.execute("SELECT role_id, price FROM shop_roles")
    roles_data = cursor.fetchall()
    conn.close()

    options = []
    for role_id, price in roles_data:
      # Добавляем каждую роль в селект-меню (название можно подтягивать или ставить дефолтное)
      options.append(
          discord.SelectOption(
              label=f"Роль ID: {role_id}",
              value=str(role_id),
              description=f"Цена: {price} валюты",
          )
      )

    if not options:
      options.append(
          discord.SelectOption(
              label="Нет доступных ролей", value="none", description="Пусто"
          )
      )

    self.add_item(RoleSelect(options))


class Shop(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @discord.app_commands.command(
      name="shop", description="Открыть магазин ролей"
  )
  async def shop(self, interaction: discord.Interaction):
    view = RoleShopView()
    await interaction.response.send_message(
        "🛒 **Магазин ролей:** Выберите роль для покупки ниже:",
        view=view,
        ephemeral=True,
    )


async def setup(bot):
  await bot.add_cog(Shop(bot))
  
