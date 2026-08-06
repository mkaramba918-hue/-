import discord
from discord.ext import commands
from discord.ui import Button, View, Select

# Словарь для отслеживания созданных комнат: {voice_channel_id: owner_id}
active_private_channels = {}

class PrivateControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Название", style=discord.ButtonStyle.secondary, emoji="✏️", row=0)
    async def change_name(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RenameModal())

    @discord.ui.button(label="Лимит", style=discord.ButtonStyle.secondary, emoji="👥", row=0)
    async def change_limit(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(LimitModal())

    @discord.ui.button(label="Закрыть", style=discord.ButtonStyle.danger, emoji="🔒", row=1)
    async def lock_room(self, interaction: discord.Interaction, button: Button):
        vc = interaction.user.voice.channel
        if vc and active_private_channels.get(vc.id) == interaction.user.id:
            await vc.set_permissions(interaction.guild.default_role, connect=False)
            await interaction.response.send_message("🔒 Комната закрыта для всех.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Вы не владелец этой комнаты!", ephemeral=True)

    @discord.ui.button(label="Открыть", style=discord.ButtonStyle.success, emoji="🔓", row=1)
    async def unlock_room(self, interaction: discord.Interaction, button: Button):
        vc = interaction.user.voice.channel
        if vc and active_private_channels.get(vc.id) == interaction.user.id:
            await vc.set_permissions(interaction.guild.default_role, connect=True)
            await interaction.response.send_message("🔓 Комната открыта для всех.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Вы не владелец этой комнаты!", ephemeral=True)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger, emoji="❌", row=2)
    async def delete_room(self, interaction: discord.Interaction, button: Button):
        vc = interaction.user.voice.channel
        if vc and active_private_channels.get(vc.id) == interaction.user.id:
            del active_private_channels[vc.id]
            await vc.delete()
            await interaction.response.send_message("🗑️ Комната удалена.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Вы не владелец этой комнаты!", ephemeral=True)

class RenameModal(discord.ui.Modal, title="Изменить название комнаты"):
    new_name = discord.ui.TextInput(label="Новое название", placeholder="Введи название...", max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel
        if vc and active_private_channels.get(vc.id) == interaction.user.id:
            await vc.edit(name=self.new_name.value)
            await interaction.response.send_message(f"✅ Название изменено на: **{self.new_name.value}**", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ошибка: вы не в своей комнате.", ephemeral=True)

class LimitModal(discord.ui.Modal, title="Изменить лимит пользователей"):
    new_limit = discord.ui.TextInput(label="Лимит от 0 до 99", placeholder="0 — без лимита", max_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel
        if vc and active_private_channels.get(vc.id) == interaction.user.id:
            try:
                limit = int(self.new_limit.value)
                await vc.edit(user_limit=limit)
                await interaction.response.send_message(f"✅ Лимит изменен: **{limit}**", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Введите число!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ошибка: вы не в своей комнате.", ephemeral=True)

# Событие отслеживания захода в канал-триггер
def setup_private_rooms(bot):
    @bot.event
    async def on_voice_state_update(member, before, after):
        # ЗАМЕНИТЕ ID_КАНАЛА_СОЗДАТЕЛЯ на ID вашего голосового канала создания приваток
        CREATOR_CHANNEL_ID = 123456789012345678  

        if after.channel and after.channel.id == CREATOR_CHANNEL_ID:
            guild = member.guild
            category = after.channel.category  # Создает в той же категории
            
            # Создаем приватный канал
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=True),
                member: discord.PermissionOverwrite(manage_channels=True, connect=True, mute_members=True, deafen_members=True)
            }
            
            channel_name = f"🔊 │ Приватка {member.display_name}"
            voice_channel = await guild.create_voice_channel(name=channel_name, category=category, overwrites=overwrites)
            
            active_private_channels[voice_channel.id] = member.id
            
            # Перемещаем пользователя в его новую комнату
            try:
                await member.move_to(voice_channel)
            except:
                pass

        # Удаление пустых приваток
        if before.channel and before.channel.id in active_private_channels:
            if len(before.channel.members) == 0:
                room_id = before.channel.id
                del active_private_channels[room_id]
                await before.channel.delete()
      
