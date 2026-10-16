# Project: 3YZN Discord Bot
# Author: 3YZN (@3yzn)
# Copyright (c) 2026 3YZN
# License: See LICENSE
"""Persistent free-entry giveaway system with restart-safe buttons and scheduling."""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.checks import admin_only

log = logging.getLogger("3yzn.giveaways")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def giveaway_embed(row, entrant_count: int | None = None, status: str = "active") -> discord.Embed:
    ends = parse_time(row["end_at"])
    color = discord.Color.green() if status == "active" else discord.Color.blurple()
    embed = discord.Embed(title=f"Giveaway: {row['prize']}", color=color)
    embed.add_field(name="Winners", value=str(row["winner_count"]), inline=True)
    embed.add_field(name="Status", value=status.capitalize(), inline=True)
    embed.add_field(name="Ends", value=discord.utils.format_dt(ends, style="R"), inline=True)
    if entrant_count is not None:
        embed.add_field(name="Entries", value=str(entrant_count), inline=True)
    embed.set_footer(text=f"3YZN Discord Bot • Giveaway #{row['id']}")
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self, cog: "Giveaways", giveaway_id: int, disabled: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.giveaway_id = giveaway_id
        button = discord.ui.Button(
            label="Enter giveaway",
            style=discord.ButtonStyle.success,
            custom_id=f"3yzn:giveaway:{giveaway_id}:enter",
            disabled=disabled,
        )
        button.callback = self.enter
        self.add_item(button)

    async def enter(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Giveaways can only be entered in a server.", ephemeral=True)
            return
        row = await self.cog.bot.db.fetchone(
            "SELECT * FROM giveaways WHERE id=? AND guild_id=?",
            (self.giveaway_id, interaction.guild_id),
        )
        if not row or row["status"] != "active":
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return
        if utc_now() >= parse_time(row["end_at"]):
            await interaction.response.send_message("This giveaway has reached its deadline.", ephemeral=True)
            return
        try:
            await self.cog.bot.db.execute(
                "INSERT INTO giveaway_entries(giveaway_id,user_id,entered_at) VALUES(?,?,?)",
                (self.giveaway_id, interaction.user.id, utc_now().isoformat()),
            )
        except Exception as exc:
            import sqlite3
            if isinstance(exc, sqlite3.IntegrityError):
                await interaction.response.send_message("You have already entered this giveaway.", ephemeral=True)
                return
            raise
        await interaction.response.send_message("You are entered in the giveaway.", ephemeral=True)


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._finish_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, message_id FROM giveaways WHERE status='active' AND message_id IS NOT NULL"
        )
        for row in rows:
            self.bot.add_view(GiveawayView(self, row["id"]), message_id=row["message_id"])
        if not self.finish_overdue.is_running():
            self.finish_overdue.start()

    def cog_unload(self) -> None:
        self.finish_overdue.cancel()

    @tasks.loop(seconds=15)
    async def finish_overdue(self) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id FROM giveaways WHERE status='active' AND end_at<=?",
            (utc_now().isoformat(),),
        )
        for row in rows:
            try:
                await self.finish(row["id"])
            except Exception:
                log.exception("Could not finish giveaway %s", row["id"])

    @finish_overdue.before_loop
    async def before_finish_overdue(self) -> None:
        await self.bot.wait_until_ready()

    async def finish(self, giveaway_id: int, cancelled: bool = False) -> str:
        async with self._finish_lock:
            row = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id=?", (giveaway_id,))
            if not row or row["status"] != "active":
                return "This giveaway is not active."
            if not cancelled and utc_now() < parse_time(row["end_at"]):
                return "This giveaway has not reached its deadline yet."
            entrants = await self.bot.db.fetchall(
                "SELECT user_id FROM giveaway_entries WHERE giveaway_id=? ORDER BY entered_at",
                (giveaway_id,),
            )
            status = "cancelled" if cancelled else "ended"
            await self.bot.db.execute("UPDATE giveaways SET status=? WHERE id=?", (status, giveaway_id))
            winners = []
            if not cancelled and entrants:
                winners = random.sample(entrants, min(row["winner_count"], len(entrants)))
                for winner in winners:
                    await self.bot.db.execute(
                        "INSERT OR IGNORE INTO giveaway_winners(giveaway_id,user_id,reroll_no) VALUES(?,?,0)",
                        (giveaway_id, winner["user_id"]),
                    )
            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(row["channel_id"])
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    channel = None
            if channel is not None and row["message_id"] is not None:
                try:
                    message = await channel.fetch_message(row["message_id"])
                    count = len(entrants)
                    await message.edit(
                        embed=giveaway_embed(row, count, status),
                        view=GiveawayView(self, giveaway_id, disabled=True),
                    )
                    if cancelled:
                        await channel.send(f"Giveaway **#{giveaway_id}** was cancelled.")
                    elif winners:
                        mentions = ", ".join(f"<@{item['user_id']}>" for item in winners)
                        await channel.send(
                            f"Congratulations {mentions}! You won **{row['prize']}** (giveaway #{giveaway_id}).",
                            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                        )
                    else:
                        await channel.send(f"Giveaway **#{giveaway_id}** ended with no entries.")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    log.exception("Could not update giveaway message %s", giveaway_id)
            return status

    @app_commands.command(name="giveaway-create", description="Create a free-entry giveaway.")
    @app_commands.describe(
        channel="Channel where the giveaway will be posted",
        prize="Prize description",
        duration_minutes="Duration in minutes (1 to 10080)",
        winners="Number of winners (1 to 20)",
    )
    @app_commands.guild_only()
    @admin_only()
    async def create(self, interaction: discord.Interaction, channel: discord.TextChannel,
                     prize: app_commands.Range[str, 1, 200],
                     duration_minutes: app_commands.Range[int, 1, 10080],
                     winners: app_commands.Range[int, 1, 20] = 1) -> None:
        if not channel.permissions_for(interaction.guild.me).send_messages or not channel.permissions_for(interaction.guild.me).embed_links:
            await interaction.response.send_message("I need Send Messages and Embed Links permissions in that channel.", ephemeral=True)
            return
        end_at = (utc_now() + timedelta(minutes=duration_minutes)).isoformat()
        giveaway_id = await self.bot.db.execute(
            """INSERT INTO giveaways(guild_id,channel_id,prize,winner_count,end_at,status,created_by)
               VALUES(?,?,?,?,?,'active',?)""",
            (interaction.guild_id, channel.id, prize, winners, end_at, interaction.user.id),
        )
        row = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id=?", (giveaway_id,))
        try:
            message = await channel.send(
                embed=giveaway_embed(row, 0),
                view=GiveawayView(self, giveaway_id),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.bot.db.execute("UPDATE giveaways SET message_id=? WHERE id=?", (message.id, giveaway_id))
            self.bot.add_view(GiveawayView(self, giveaway_id), message_id=message.id)
        except (discord.Forbidden, discord.HTTPException):
            await self.bot.db.execute("DELETE FROM giveaways WHERE id=?", (giveaway_id,))
            await interaction.response.send_message("I could not post the giveaway. Check channel permissions.", ephemeral=True)
            return
        await interaction.response.send_message(f"Giveaway **#{giveaway_id}** created in {channel.mention}.", ephemeral=True)

    @app_commands.command(name="giveaway-end", description="End a giveaway early and draw winners.")
    @app_commands.guild_only()
    @admin_only()
    async def end(self, interaction: discord.Interaction, giveaway_id: app_commands.Range[int, 1, 2147483647]) -> None:
        row = await self.bot.db.fetchone("SELECT guild_id FROM giveaways WHERE id=?", (giveaway_id,))
        if not row or row["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("Giveaway not found in this server.", ephemeral=True)
            return
        # Early end is an explicit administrator action. Do not hold the finish
        # lock here: finish() acquires it itself.
        current = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id=?", (giveaway_id,))
        if not current or current["status"] != "active":
            result = "This giveaway is not active."
        else:
            await self.bot.db.execute(
                "UPDATE giveaways SET end_at=? WHERE id=?", (utc_now().isoformat(), giveaway_id)
            )
            result = await self.finish(giveaway_id)
        await interaction.response.send_message(f"Giveaway #{giveaway_id}: {result}", ephemeral=True)

    @app_commands.command(name="giveaway-cancel", description="Cancel a giveaway without drawing winners.")
    @app_commands.guild_only()
    @admin_only()
    async def cancel(self, interaction: discord.Interaction, giveaway_id: app_commands.Range[int, 1, 2147483647]) -> None:
        row = await self.bot.db.fetchone("SELECT guild_id FROM giveaways WHERE id=?", (giveaway_id,))
        if not row or row["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("Giveaway not found in this server.", ephemeral=True)
            return
        result = await self.finish(giveaway_id, cancelled=True)
        await interaction.response.send_message(f"Giveaway #{giveaway_id}: {result}", ephemeral=True)

    @app_commands.command(name="giveaway-list", description="List recent giveaways in this server.")
    @app_commands.guild_only()
    @admin_only()
    async def list_giveaways(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, prize, status, end_at, winner_count FROM giveaways "
            "WHERE guild_id=? ORDER BY id DESC LIMIT 10",
            (interaction.guild_id,),
        )
        if not rows:
            await interaction.response.send_message("No giveaways have been created in this server.", ephemeral=True)
            return
        embed = discord.Embed(title="Recent giveaways", color=discord.Color.blurple())
        for row in rows:
            end_label = discord.utils.format_dt(parse_time(row["end_at"]), style="R")
            embed.add_field(
                name=f"#{row['id']} — {row['prize'][:200]}",
                value=f"Status: {row['status']} • Winners: {row['winner_count']} • Deadline: {end_label}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="giveaway-reroll", description="Select a replacement winner from remaining eligible entrants.")
    @app_commands.guild_only()
    @admin_only()
    async def reroll(self, interaction: discord.Interaction, giveaway_id: app_commands.Range[int, 1, 2147483647]) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id=? AND guild_id=?", (giveaway_id, interaction.guild_id))
        if not row or row["status"] != "ended":
            await interaction.response.send_message("Only an ended giveaway in this server can be rerolled.", ephemeral=True)
            return
        existing = await self.bot.db.fetchall("SELECT user_id FROM giveaway_winners WHERE giveaway_id=?", (giveaway_id,))
        excluded = {item["user_id"] for item in existing}
        entries = await self.bot.db.fetchall("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (giveaway_id,))
        candidates = [item["user_id"] for item in entries if item["user_id"] not in excluded]
        if not candidates:
            await interaction.response.send_message("No remaining eligible entrants are available.", ephemeral=True)
            return
        winner_id = random.choice(candidates)
        reroll_no = max((await self.bot.db.fetchall(
            "SELECT reroll_no FROM giveaway_winners WHERE giveaway_id=?", (giveaway_id,)
        )), key=lambda item: item["reroll_no"], default={"reroll_no": 0})["reroll_no"] + 1
        await self.bot.db.execute(
            "INSERT INTO giveaway_winners(giveaway_id,user_id,reroll_no) VALUES(?,?,?)",
            (giveaway_id, winner_id, reroll_no),
        )
        channel = self.bot.get_channel(row["channel_id"])
        if channel:
            await channel.send(
                f"Replacement winner for giveaway **#{giveaway_id}** ({row['prize']}): <@{winner_id}>",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        await interaction.response.send_message(f"Replacement winner selected: <@{winner_id}>.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaways(bot))
