import discord
from discord.ext import commands
from discord import app_commands

active_private_channels = {}

# 1. Модальное окно создания комнаты
class CreateRoomModal(discord.ui.Modal, title="Создание приватной комнаты"):
    room_name = discord.ui.TextInput(
        label="Название комнаты",
        placeholder="Введите название вашей комнаты...",
        max_length=50,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        category = interaction.channel.category

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            member: discord.PermissionOverwrite(
                manage_channels=True, connect=True, mute_members=True, deafen_members=True, move_members=True
            )
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

            await interaction.response.send_message(f"✅ Приватная комната **{channel_name}** создана!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав на создание каналов в этой категории!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка создания комнаты: {e}", ephemeral=True)

# 2. Кнопка создания комнаты
class CreateRoomButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать приватную комнату", style=discord.ButtonStyle.success, emoji="✨", custom_id="persistent_create_room_btn")
    async def create_room_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateRoomModal())

# 3. Модальные окна настройки
class RenameModal(discord.ui.Modal, title="Изменить название комнаты"):
    new_name = discord.ui.TextInput(label="Новое название", placeholder="Введите название...", max_length=50, required=True)

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        await self.channel.edit(name=f"🔒 {self.new_name.value}")
        await interaction.response.send_message(f"✅ Название изменено на **{self.new_name.value}**", ephemeral=True)

class LimitModal(discord.ui.Modal, title="Установить лимит мест"):
    new_limit = discord.ui.TextInput(label="Лимит пользователей (0-99)", placeholder="Например: 4", max_length=2, required=True)

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.new_limit.value)
            if 0 <= val <= 99:
                await self.channel.edit(user_limit=val)
                await interaction.response.send_message(f"✅ Лимит мест установлен: **{val}**", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Лимит должен быть от 0 до 99.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Введите корректное целое число.", ephemeral=True)

# 4. Выбор пользователя для действий
class TargetSelectView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, action: str):
        super().__init__(timeout=60)
        self.channel = channel
        self.action = action

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Выберите участника...")
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        target = select.values[0]
        await interaction.response.defer(ephemeral=True)

        if self.action == "revoke":
            await self.channel.set_permissions(target, connect=False)
            await interaction.followup.send(f"🚫 Доступ закрыт для {target.mention}.", ephemeral=True)
        elif self.action == "grant":
            await self.channel.set_permissions(target, connect=True)
            await interaction.followup.send(f"✅ Доступ выдан {target.mention}.", ephemeral=True)
        elif self.action == "kick":
            member = interaction.guild.get_member(target.id)
            if member and member.voice and member.voice.channel == self.channel:
                await member.move_to(None)
                await interaction.followup.send(f"🚪 {target.mention} выгнан из комнаты.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Участник не находится в вашей комнате.", ephemeral=True)
        elif self.action == "transfer":
            active_private_channels[self.channel.id] = target.id
            await self.channel.set_permissions(target, connect=True, manage_channels=True, mute_members=True, deafen_members=True, move_members=True)
            await self.channel.set_permissions(interaction.user, manage_channels=False)
            await interaction.followup.send(f"👑 Права владельца переданы {target.mention}.", ephemeral=True)

# 5. Меню настроек
class RoomSettingsSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Изменить название", description="Задать новое имя комнате", emoji="✏️", value="rename"),
            discord.SelectOption(label="Установить лимит", description="Ограничить количество мест", emoji="👥", value="limit"),
            discord.SelectOption(label="Забрать доступ", description="Запретить участнику вход", emoji="➖", value="revoke"),
            discord.SelectOption(label="Выдать доступ", description="Разрешить участнику вход", emoji="➕", value="grant"),
            discord.SelectOption(label="Закрыть комнату", description="Сделать закрытой для всех", emoji="🔒", value="lock"),
            discord.SelectOption(label="Открыть комнату", description="Сделать открытой для всех", emoji="🔓", value="unlock"),
            discord.SelectOption(label="Выгнать пользователя", description="Исключить участника из войса", emoji="🚪", value="kick"),
            discord.SelectOption(label="Передать владение", description="Назначить нового владельца", emoji="👑", value="transfer"),
            discord.SelectOption(label="Удалить комнату", description="Удалить канал сейчас", emoji="❌", value="delete"),
        ]
        super().__init__(placeholder="Настроить приватную комнату", min_values=1, max_values=1, options=options, custom_id="persistent_room_settings_select")

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        voice = user.voice

        if not voice or not voice.channel:
            return await interaction.response.send_message("❌ Вы должны находиться в голосовом канале!", ephemeral=True)

        channel = voice.channel
        owner_id = active_private_channels.get(channel.id)

        # Проверка прав: создатель или администратор сервера
        if owner_id != user.id and not channel.permissions_for(user).manage_channels and not user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Вы не являетесь владельцем этой комнаты!", ephemeral=True)

        action = self.values[0]

        if action == "rename":
            await interaction.response.send_modal(RenameModal(channel))
        elif action == "limit":
            await interaction.response.send_modal(LimitModal(channel))
        elif action == "lock":
            await channel.set_permissions(interaction.guild.default_role, connect=False)
            await interaction.response.send_message("🔒 Комната закрыта для всех.", ephemeral=True)
        elif action == "unlock":
            await channel.set_permissions(interaction.guild.default_role, connect=True)
            await interaction.response.send_message("🔓 Комната открыта для всех.", ephemeral=True)
        elif action == "delete":
            active_private_channels.pop(channel.id, None)
            await channel.delete()
            await interaction.response.send_message("❌ Комната успешно удалена.", ephemeral=True)
        elif action in ["revoke", "grant", "kick", "transfer"]:
            await interaction.response.send_message("Выберите участника:", view=TargetSelectView(channel, action), ephemeral=True)

class RoomSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoomSettingsSelect())

# 6. Cog с командами установки
class PrivatesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup_create", description="Отправить кнопку создания приватных комнат")
    @app_commands.checks.has_permissions(administrator=True)
    async def slash_setup_create(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✨ Создание приватной комнаты",
            description="Нажмите на кнопку ниже, чтобы создать собственную приватную комнату.",
            color=discord.Color.from_rgb(217, 78, 47)
        )
        await interaction.channel.send(embed=embed, view=CreateRoomButtonView())
        await interaction.response.send_message("✅ Карточка создания комнат выставлена!", ephemeral=True)

    @app_commands.command(name="setup_settings", description="Отправить панель настроек приватных комнат")
    @app_commands.checks.has_permissions(administrator=True)
    async def slash_setup_settings(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ Управление приватной комнатой",
            description="Используйте меню ниже для изменения названия, лимита и параметров доступа вашей комнаты.",
            color=discord.Color.from_rgb(40, 40, 40)
        )
        await interaction.channel.send(embed=embed, view=RoomSettingsView())
        await interaction.response.send_message("✅ Меню настроек выставлено!", ephemeral=True)

    @commands.command(name="setup_create")
    @commands.has_permissions(administrator=True)
    async def prefix_setup_create(self, ctx):
        embed = discord.Embed(
            title="✨ Создание приватной комнаты",
            description="Нажмите на кнопку ниже, чтобы создать собственную приватную комнату.",
            color=discord.Color.from_rgb(217, 78, 47)
        )
        await ctx.send(embed=embed, view=CreateRoomButtonView())

    @commands.command(name="setup_settings")
    @commands.has_permissions(administrator=True)
    async def prefix_setup_settings(self, ctx):
        embed = discord.Embed(
            title="⚙️ Управление приватной комнатой",
            description="Используйте меню ниже для изменения параметров доступа.",
            color=discord.Color.from_rgb(40, 40, 40)
        )
        await ctx.send(embed=embed, view=RoomSettingsView())

async def setup(bot):
    await bot.add_cog(PrivatesCog(bot))
    
