import discord
from discord.ext import commands

# Хранилище активных приваток: {voice_channel_id: owner_id}
active_private_channels = {}

# 1. Модальное окно ввода названия приватки
class CreateRoomModal(discord.ui.Modal, title="Создание приватной комнаты"):
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

# 2. Кнопка вызова модального окна создания
class CreateRoomButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать приватную комнату", style=discord.ButtonStyle.success, emoji="✨", custom_id="persistent_create_room_btn")
    async def create_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateRoomModal())

# 3. Выпадающее меню управления комнатой
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
        member = interaction.user
        user_voice = member.voice
        
        # Проверка: находится ли юзер в голосовом канале и владеет ли он им
        if not user_voice or user_voice.channel.id not in active_private_channels:
            return await interaction.response.send_message("❌ Вы должны находиться в своей созданной приватной комнате!", ephemeral=True)
        
        channel_id = user_voice.channel.id
        if active_private_channels[channel_id] != member.id:
            return await interaction.response.send_message("❌ Вы не являетесь владельцем этой приватной комнаты!", ephemeral=True)
            
        channel = user_voice.channel
        val = self.values[0]

        # Базовая логика для основных действий
        if val == "lock":
            await channel.set_permissions(interaction.guild.default_role, connect=False)
            await interaction.response.send_message("🔒 Комната успешно закрыта для всех.", ephemeral=True)
        elif val == "unlock":
            await channel.set_permissions(interaction.guild.default_role, connect=True)
            await interaction.response.send_message("🔓 Комната открыта для всех.", ephemeral=True)
        elif val == "delete":
            if channel_id in active_private_channels:
                del active_private_channels[channel_id]
            await channel.delete()
            await interaction.response.send_message("❌ Комната удалена.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚙️ Вы выбрали опцию: `{val}`. (Модальные окна для ввода параметров подключаются здесь)", ephemeral=True)

# 4. Панель (View) для канала настройки
class RoomSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoomSettingsSelect())

# 5. Команда для развертывания панели настроек
class PrivatesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.has_permissions(administrator=True)
    @commands.command(name="setup_settings_panel")
    async def setup_settings_panel(self, ctx):
        embed = discord.Embed(
            title="Настройка приватной комнаты",
            description="Вы можете **настроить** созданную **приватную комнату** в соответствии с доступным функционалом. Чтобы это сделать **воспользуйтесь меню** под сообщением.",
            color=discord.Color.dark_theme()
        )
        await ctx.send(embed=embed, view=RoomSettingsView())
        try:
            await ctx.message.delete()
        except:
            pass

# 6. Событие автоматического удаления пустых комнат при выходвы#
async def setup(bot):
    await bot.add_cog(PrivatesCog(bot))
    
