import discord  # <--- Вот этого импорта не хватает в privates.py

# Хранилище активных приваток: {voice_channel_id: owner_id}
active_private_channels = {}

# 1. Модальное окно ввода названия приватки (как на скриншоте 13271.jpg)
class CreateRoomModal(discord.ui.Modal, title="Настройка приватной комнаты"):
    room_name = discord.ui.TextInput(
        label="Название приватной комнаты *",
        placeholder="Введите название...",
        max_length=50,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        
        # Ищем категорию, где находится канал с панелью, либо создаем без категории
        category = interaction.channel.category

        # Настраиваем права: владелец получает полный контроль, остальные могут заходить
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            member: discord.PermissionOverwrite(manage_channels=True, connect=True, mute_members=True, deafen_members=True)
        }

        # Создаем голосовой канал с введенным пользователем названием
        channel_name = f"🔒 {self.room_name.value}"
        try:
            voice_channel = await guild.create_voice_channel(
                name=channel_name, 
                category=category, 
                overwrites=overwrites
            )
            active_private_channels[voice_channel.id] = member.id

            # Пытаемся перекинуть пользователя в созданную комнату
            if member.voice:
                await member.move_to(voice_channel)

            await interaction.response.send_message(f"✅ Ваша приватная комната **{channel_name}** успешно создана!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав на создание голосовых каналов в этой категории!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка при создании комнаты: {e}", ephemeral=True)

# 2. Кнопка вызова модального окна в канале `#создать-комнату` (как на скриншоте 13270.jpg)
class CreateRoomButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать приватную комнату", style=discord.ButtonStyle.success, emoji="✨", custom_id="persistent_create_room_btn")
    async def create_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Открываем модальное окно для ввода названия
        await interaction.response.send_modal(CreateRoomModal())

# 3. Команда для отправки этой панели в нужный текстовый канал (чтобы администратор мог её разместить)
@bot.command(name='setup_panel')
@commands.has_permissions(administrator=True)
async def setup_panel(ctx):
    embed = discord.Embed(
        title="✨ Создание приватной комнаты",
        description="Вы можете **создать** собственную приватную комнату с необходимым названием, а впоследствии **гибко настроить** в соответствии с имеющимся функционалом.",
        color=discord.Color.dark_embed()
    )
    # Отправляем сообщение с постоянной кнопкой
    await ctx.send(embed=embed, view=CreateRoomButtonView())
    await ctx.message.delete() # Удаляем команду администратора для красоты

# 4. Автоматическое удаление пустых приваток
@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel and before.channel.id in active_private_channels:
        if len(before.channel.members) == 0:
            room_id = before.channel.id
            del active_private_channels[room_id]
            try:
                await before.channel.delete()
            except:
                pass
                
