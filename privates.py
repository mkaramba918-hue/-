import discord
from discord.ext import commands

# Хранилище активных приваток: {voice_channel_id: owner_id}
active_private_channels = {}

# 1. Модальное окно ввода названия приватки
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
        category = interaction.channel.category

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            member: discord.PermissionOverwrite(manage_channels=True, connect=True, mute_members=True, deafen_members=True)
        }

        channel_name = f"🔒 {self.room_name.value}"
        try:
            voice_channel = await guild.create_voice_channel(
                name=channel_name, 
                category=category, 
                overwrites=overwrites
            )
            active_private_channels[voice_channel.id] = member.id

            if member.voice:
                await member.move_to(voice_channel)

            await interaction.response.send_message(f"✅ Ваша приватная комната **{channel_name}** успешно создана!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав на создание голосовых каналов в этой категории!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка при создании комнаты: {e}", ephemeral=True)

# 2. Кнопка вызова модального окна
class CreateRoomButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать приватную комнату", style=discord.ButtonStyle.success, emoji="✨", custom_id="persistent_create_room_btn")
    async def create_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateRoomModal())

# 3. Автоматическое удаление пустых приваток
async def on_voice_state_update(member, before, after):
    if before.channel and before.channel.id in active_private_channels:
        if len(before.channel.members) == 0:
            room_id = before.channel.id
            del active_private_channels[room_id]
            try:
                await before.channel.delete()
            except:
                pass
                
