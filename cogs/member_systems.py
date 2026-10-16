# Project: 3YZN Discord Bot
# Author: 3YZN (@3yzn)
# Copyright (c) 2026 3YZN
# License: See LICENSE
"""Persistent welcome, leave-message, and automatic-role systems."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import admin_only
from utils.permissions import can_manage_role

log = logging.getLogger("3yzn.member_systems")

PLACEHOLDERS = {
    "{mention}": "member mention",
    "{user}": "member display name",
    "{server}": "server name",
    "{member_count}": "member count",
}


def render_template(template: str, member: discord.Member) -> str:
    """Render only documented placeholders; do not interpret arbitrary format strings."""
    values = {
        "{mention}": member.mention,
        "{user}": discord.utils.escape_mentions(member.display_name),
        "{server}": discord.utils.escape_mentions(member.guild.name),
        "{member_count}": str(member.guild.member_count or len(member.guild.members)),
    }
    rendered = template
    for token, value in values.items():
        rendered = rendered.replace(token, value)
    return rendered[:2000]


class MemberSystems(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _settings(self, guild_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)
        )

    async def _set(self, guild_id: int, column: str, value) -> None:
        allowed = {
            "auto_role_member_id", "auto_role_bot_id",
            "welcome_channel_id", "welcome_message",
            "leave_channel_id", "leave_message",
        }
        if column not in allowed:
            raise ValueError("Unsupported guild setting")
        await self.bot.db.execute(
            f"""INSERT INTO guild_settings(guild_id, {column})
                VALUES(?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET {column}=excluded.{column}""",
            (guild_id, value),
        )

    async def _configure_role(self, interaction: discord.Interaction,
                              role: discord.Role | None, column: str,
                              label: str) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        if role is not None:
            ok, message = can_manage_role(guild, role, guild.me)
            if not ok:
                await interaction.response.send_message(message, ephemeral=True)
                return
        await self._set(guild.id, column, role.id if role else None)
        if role:
            await interaction.response.send_message(
                f"{label} automatic role set to {role.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{label} automatic role disabled.", ephemeral=True
            )

    @app_commands.command(name="autorole-member", description="Set or disable the automatic role for human members.")
    @app_commands.describe(role="Choose a role; leave empty to disable human-member auto-role.")
    @app_commands.guild_only()
    @admin_only()
    async def autorole_member(self, interaction: discord.Interaction,
                              role: discord.Role | None = None) -> None:
        await self._configure_role(interaction, role, "auto_role_member_id", "Human member")

    @app_commands.command(name="autorole-bots", description="Set or disable the automatic role for bot accounts.")
    @app_commands.describe(role="Choose a role; leave empty to disable bot-account auto-role.")
    @app_commands.guild_only()
    @admin_only()
    async def autorole_bots(self, interaction: discord.Interaction,
                            role: discord.Role | None = None) -> None:
        await self._configure_role(interaction, role, "auto_role_bot_id", "Bot account")

    @app_commands.command(name="welcome-set", description="Configure the welcome channel and message.")
    @app_commands.describe(
        channel="Text channel for welcome messages",
        message="Message; placeholders: {mention}, {user}, {server}, {member_count}",
    )
    @app_commands.guild_only()
    @admin_only()
    async def welcome_set(self, interaction: discord.Interaction,
                          channel: discord.TextChannel,
                          message: app_commands.Range[str, 1, 1500]) -> None:
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message("I cannot send messages in that channel.", ephemeral=True)
            return
        await self._set(interaction.guild_id, "welcome_channel_id", channel.id)
        await self._set(interaction.guild_id, "welcome_message", message)
        await interaction.response.send_message(
            f"Welcome messages configured for {channel.mention}. Use `/welcome-preview` to test it.",
            ephemeral=True,
        )

    @app_commands.command(name="welcome-disable", description="Disable welcome messages without deleting the saved template.")
    @app_commands.guild_only()
    @admin_only()
    async def welcome_disable(self, interaction: discord.Interaction) -> None:
        await self._set(interaction.guild_id, "welcome_channel_id", None)
        await interaction.response.send_message("Welcome messages disabled. The saved message is preserved.", ephemeral=True)

    @app_commands.command(name="welcome-preview", description="Preview the current welcome template.")
    @app_commands.guild_only()
    @admin_only()
    async def welcome_preview(self, interaction: discord.Interaction) -> None:
        row = await self._settings(interaction.guild_id)
        if not row or not row["welcome_message"]:
            await interaction.response.send_message("Configure a message first with `/welcome-set`.", ephemeral=True)
            return
        rendered = render_template(row["welcome_message"], interaction.user)
        await interaction.response.send_message(
            f"**Welcome preview**\n{rendered}",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            ephemeral=True,
        )

    @app_commands.command(name="leave-set", description="Configure the channel and message for member departures.")
    @app_commands.describe(
        channel="Text channel for leave messages",
        message="Message; placeholders: {mention}, {user}, {server}, {member_count}",
    )
    @app_commands.guild_only()
    @admin_only()
    async def leave_set(self, interaction: discord.Interaction,
                        channel: discord.TextChannel,
                        message: app_commands.Range[str, 1, 1500]) -> None:
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message("I cannot send messages in that channel.", ephemeral=True)
            return
        await self._set(interaction.guild_id, "leave_channel_id", channel.id)
        await self._set(interaction.guild_id, "leave_message", message)
        await interaction.response.send_message(f"Leave messages configured for {channel.mention}.", ephemeral=True)

    @app_commands.command(name="leave-disable", description="Disable leave messages while preserving the saved template.")
    @app_commands.guild_only()
    @admin_only()
    async def leave_disable(self, interaction: discord.Interaction) -> None:
        await self._set(interaction.guild_id, "leave_channel_id", None)
        await interaction.response.send_message("Leave messages disabled. The saved message is preserved.", ephemeral=True)

    @app_commands.command(name="member-systems-settings", description="Show automatic-role, welcome, and leave settings.")
    @app_commands.guild_only()
    @admin_only()
    async def member_systems_settings(self, interaction: discord.Interaction) -> None:
        row = await self._settings(interaction.guild_id)
        if not row:
            await interaction.response.send_message("No member-system settings configured yet.", ephemeral=True)
            return
        def role_label(key: str) -> str:
            role = interaction.guild.get_role(row[key]) if row[key] else None
            return role.mention if role else "Disabled / not configured"
        def channel_label(key: str) -> str:
            channel = interaction.guild.get_channel(row[key]) if row[key] else None
            return channel.mention if channel else "Disabled / not configured"
        embed = discord.Embed(title="Member systems settings", color=discord.Color.blurple())
        embed.add_field(name="Human auto-role", value=role_label("auto_role_member_id"), inline=False)
        embed.add_field(name="Bot auto-role", value=role_label("auto_role_bot_id"), inline=False)
        embed.add_field(name="Welcome channel", value=channel_label("welcome_channel_id"), inline=False)
        embed.add_field(name="Leave channel", value=channel_label("leave_channel_id"), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _send_template(self, guild: discord.Guild, member: discord.Member,
                             channel_id: int | None, template: str | None,
                             label: str) -> None:
        if not channel_id or not template:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.warning("%s channel is missing or invalid in guild %s", label, guild.id)
            return
        if not channel.permissions_for(guild.me).send_messages:
            log.warning("Missing send_messages permission for %s in guild %s", label, guild.id)
            return
        try:
            await channel.send(
                render_template(template, member),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Could not send %s message in guild %s", label, guild.id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        row = await self._settings(member.guild.id)
        if not row:
            return
        key = "auto_role_bot_id" if member.bot else "auto_role_member_id"
        role_id = row[key]
        if role_id:
            role = member.guild.get_role(role_id)
            if role is None:
                log.warning("Configured auto-role %s no longer exists in guild %s", role_id, member.guild.id)
            elif member.guild.me is None or not member.guild.me.guild_permissions.manage_roles:
                log.warning("Missing manage_roles permission in guild %s", member.guild.id)
            else:
                ok, reason = can_manage_role(member.guild, role, member.guild.me)
                if not ok:
                    log.warning("Auto-role blocked in guild %s: %s", member.guild.id, reason)
                else:
                    try:
                        await member.add_roles(role, reason="3YZN automatic role on member join")
                        log.info("Assigned auto-role %s to member %s in guild %s", role.id, member.id, member.guild.id)
                    except (discord.Forbidden, discord.HTTPException):
                        log.exception("Failed to assign auto-role in guild %s", member.guild.id)
        await self._send_template(
            member.guild, member, row["welcome_channel_id"], row["welcome_message"], "welcome"
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        row = await self._settings(member.guild.id)
        if row:
            await self._send_template(
                member.guild, member, row["leave_channel_id"], row["leave_message"], "leave"
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemberSystems(bot))
