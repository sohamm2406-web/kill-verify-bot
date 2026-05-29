import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional

import database as db
from analyzer import load_reference_images, reference_summary
from config import Config

_STATUS = {"approved": "APRV", "rejected": "REJ", "flagged": "FLAG", "tampered": "TAMP", "banned": "BAN"}


def _format_date(value) -> str:
    if not value:
        return "N/A"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %I:%M %p")
    except ValueError:
        return str(value).replace("T", " ")[:19]

def _truncate_to_width(value, width: int) -> str:
    text = "N/A" if value is None else str(value)
    return text[:width - 1] + "." if len(text) > width else text.ljust(width)

def _format_row(table: str, row: dict) -> str:
    if table == "verifications":
        return (
            f"`#{row['id']}` {row['username']} | `{_STATUS.get(row['status'], row['status'])}` | "
            f"KD `{_truncate_to_width(row['kd'], 6).strip()}` | "
            f"tag `{_truncate_to_width(row['tag_found'], 1).strip()}` | "
            f"{_format_date(row['submitted_at'])}"
        )
    if table == "cooldowns":
        return f"`{row['user_id']}` | attempts `{row['attempt_count']}` | {_format_date(row['last_attempt'])}"
    if table == "verified_users":
        return f"`{row['user_id']}` {row['username']} | KD `{_truncate_to_width(row['kd'], 6).strip()}` | {_format_date(row['verified_at'])}"
    return str(row)

def _build_table_embeds(table: str, rows: list[dict]) -> list[discord.Embed]:
    if not rows:
        return [discord.Embed(title=f"DB: {table}", description="No records.", color=discord.Color.blurple())]
    all_embeds, current_page_lines, page_length, page_number = [], [], 0, 1
    for line in (_format_row(table, row) for row in rows):
        if current_page_lines and page_length + len(line) + 1 > 3600:
            all_embeds.append(discord.Embed(
                title=f"DB: {table} | p{page_number}",
                description="\n".join(current_page_lines),
                color=discord.Color.blurple()
            ))
            current_page_lines, page_length, page_number = [], 0, page_number + 1
        current_page_lines.append(line)
        page_length += len(line) + 1
    if current_page_lines:
        all_embeds.append(discord.Embed(
            title=f"DB: {table} | p{page_number}",
            description="\n".join(current_page_lines),
            color=discord.Color.blurple()
        ))
    return all_embeds

def _build_history_embed(title: str, rows: list[dict]) -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.blurple())
    embed.description = "\n".join(
        f"`#{row['id']}` **{row['username']}** | `{row['status']}` | KD:`{row['kd'] or 'N/A'}` | {row['submitted_at'][:19]}"
        for row in rows
    ) if rows else "No records found."
    return embed


class AdminCog(commands.Cog):
    db_group = app_commands.Group(name="db", description="View and edit verification database records.")

    def __init__(self, bot):
        self.bot = bot

    async def _check_channel(self, interaction: discord.Interaction) -> bool:
        if interaction.channel and interaction.channel.name == Config.LOG_CHANNEL_NAME:
            return True
        await interaction.response.send_message(f"Use in #{Config.LOG_CHANNEL_NAME}.", ephemeral=True)
        return False

    async def _send_tables(self, interaction: discord.Interaction, tables: list[str]):
        counts = db.get_db_counts()
        summary_embed = discord.Embed(title="Database", color=discord.Color.blurple())
        summary_embed.description = "\n".join(f"**{table}:** `{count}` row(s)" for table, count in counts.items())
        await interaction.followup.send(embed=summary_embed)
        for table in tables:
            for page_embed in _build_table_embeds(table, db.get_table_rows(table)):
                await interaction.followup.send(embed=page_embed)

    # ── Slash commands ────────────────────────────────────────────────────────

    @app_commands.command(name="verifystatus", description="Check a user's verification status.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def verify_status(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._check_channel(interaction):
            return
        cooldown_record = db.get_cooldown(str(member.id))
        recent_rows     = db.get_verifications_for_user(str(member.id), limit=5)
        status_embed    = discord.Embed(title=f"Verification Status — {member}", color=discord.Color.blurple())
        status_embed.add_field(name="Verified",      value="Yes" if db.is_already_verified(str(member.id)) else "No", inline=True)
        status_embed.add_field(name="Attempts",      value=str(db.get_attempt_count(str(member.id))),                  inline=True)
        status_embed.add_field(name="Last Attempt",  value=cooldown_record["last_attempt"] if cooldown_record else "Never", inline=True)
        if recent_rows:
            status_embed.add_field(
                name="Recent",
                value="\n".join(f"`#{row['id']}` {row['status']} | KD `{row['kd']}`" for row in recent_rows),
                inline=False
            )
        await interaction.response.send_message(embed=status_embed)

    @app_commands.command(name="recentverify", description="Show recent verification attempts.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def recent_verifications(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 20] = 10):
        if not await self._check_channel(interaction):
            return
        await interaction.response.send_message(
            embed=_build_history_embed("Recent Verifications", db.get_all_verifications(limit))
        )

    @app_commands.command(name="reloadrefs", description="Reload reference images without restarting.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def reload_refs(self, interaction: discord.Interaction):
        if not await self._check_channel(interaction):
            return
        load_reference_images()
        await interaction.response.send_message(f"References reloaded: **{reference_summary()}**")

    @db_group.command(name="user", description="Show DB records for one user.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def db_user(self, interaction: discord.Interaction, member: discord.Member,
                      limit: app_commands.Range[int, 1, 20] = 10):
        if not await self._check_channel(interaction):
            return
        await interaction.response.send_message(
            embed=_build_history_embed(f"DB — {member}", db.get_verifications_for_user(str(member.id), limit))
        )

    @db_group.command(name="all", description="Show database in Discord.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.choices(table=[
        app_commands.Choice(name="everything",     value="everything"),
        app_commands.Choice(name="verifications",  value="verifications"),
        app_commands.Choice(name="cooldowns",      value="cooldowns"),
        app_commands.Choice(name="verified_users", value="verified_users"),
    ])
    async def db_all(self, interaction: discord.Interaction, table: Optional[app_commands.Choice[str]] = None):
        if not await self._check_channel(interaction):
            return
        await interaction.response.defer()
        table_value = table.value if table else "everything"
        tables = ["verifications", "cooldowns", "verified_users"] if table_value == "everything" else [table_value]
        await self._send_tables(interaction, tables)

    @db_group.command(name="verify", description="Manually mark a user verified.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def db_verify(self, interaction: discord.Interaction, member: discord.Member,
                        kd: Optional[float] = None, give_role: bool = True):
        if not await self._check_channel(interaction):
            return
        db.mark_verified(str(member.id), str(member), kd)
        db.log_verification(str(member.id), str(member), "approved", kd=kd, reviewed_by=str(interaction.user.id))
        role_added = False
        if give_role:
            killers_role = discord.utils.get(interaction.guild.roles, name=Config.KILLERS_ROLE_NAME)
            if killers_role:
                await member.add_roles(killers_role, reason=f"Manually verified by {interaction.user}")
                role_added = True
        await interaction.response.send_message(
            f"{member.mention} marked verified.{' Role added.' if role_added else ''}"
        )

    @db_group.command(name="unverify", description="Remove a user from verified_users.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def db_unverify(self, interaction: discord.Interaction, member: discord.Member, remove_role: bool = True):
        if not await self._check_channel(interaction):
            return
        removed_count = db.unmark_verified(str(member.id))
        db.log_verification(str(member.id), str(member), "rejected", reviewed_by=str(interaction.user.id))
        role_removed = False
        if remove_role:
            killers_role = discord.utils.get(interaction.guild.roles, name=Config.KILLERS_ROLE_NAME)
            if killers_role and killers_role in member.roles:
                await member.remove_roles(killers_role, reason=f"Manually unverified by {interaction.user}")
                role_removed = True
        await interaction.response.send_message(
            f"{member.mention} unverified. Rows removed: `{removed_count}`.{' Role removed.' if role_removed else ''}"
        )

    @db_group.command(name="resetcd", description="Reset a user's cooldown.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def db_reset_cooldown(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._check_channel(interaction):
            return
        await interaction.response.send_message(
            f"Cooldown reset for {member.mention}. Rows removed: `{db.reset_cooldown(str(member.id))}`."
        )

    @db_group.command(name="attempts", description="Set a user's attempt count.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def db_attempts(self, interaction: discord.Interaction, member: discord.Member,
                          count: app_commands.Range[int, 0, 999]):
        if not await self._check_channel(interaction):
            return
        db.set_attempt_count(str(member.id), count)
        await interaction.response.send_message(f"Attempts for {member.mention} set to `{count}`.")

    @db_group.command(name="update", description="Edit a verification record by ID.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.choices(
        status=[app_commands.Choice(name=s, value=s) for s in ("approved", "rejected", "flagged", "tampered", "banned")],
        tamper_score=[app_commands.Choice(name=s, value=s) for s in ("clean", "suspicious", "tampered")],
    )
    async def db_update(self, interaction: discord.Interaction, verification_id: int,
                        status: Optional[app_commands.Choice[str]] = None, kd: Optional[float] = None,
                        tag_found: Optional[bool] = None,
                        tamper_score: Optional[app_commands.Choice[str]] = None,
                        tamper_reason: Optional[str] = None):
        if not await self._check_channel(interaction):
            return
        fields = {key: value for key, value in {
            "status":       status.value if status else None,
            "kd":           kd,
            "tag_found":    int(tag_found) if tag_found is not None else None,
            "tamper_score": tamper_score.value if tamper_score else None,
            "tamper_reason": tamper_reason,
        }.items() if value is not None}
        if not fields:
            await interaction.response.send_message("Choose at least one field.", ephemeral=True)
            return
        fields["reviewed_by"] = str(interaction.user.id)
        if not db.update_verification(verification_id, **fields):
            await interaction.response.send_message(f"No record `#{verification_id}`.", ephemeral=True)
            return
        row = db.get_verification(verification_id)
        await interaction.response.send_message(
            embed=_build_history_embed(f"Updated #{verification_id}", [row] if row else [])
        )

    @db_group.command(name="delete", description="Delete a verification record by ID.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def db_delete(self, interaction: discord.Interaction, verification_id: int):
        if not await self._check_channel(interaction):
            return
        if not db.delete_verification(verification_id):
            await interaction.response.send_message(f"No record `#{verification_id}`.", ephemeral=True)
            return
        await interaction.response.send_message(f"Deleted `#{verification_id}`.")

    @db_group.command(name="delete-member", description="Delete a member's DB records.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def db_delete_member(self, interaction: discord.Interaction, member: discord.Member,
                               include_history: bool = False, remove_role: bool = True):
        if not await self._check_channel(interaction):
            return
        counts = db.delete_member_records(str(member.id), include_history=include_history)
        role_removed = False
        if remove_role:
            killers_role = discord.utils.get(interaction.guild.roles, name=Config.KILLERS_ROLE_NAME)
            if killers_role and killers_role in member.roles:
                await member.remove_roles(killers_role, reason=f"DB delete by {interaction.user}")
                role_removed = True
        deletion_embed = discord.Embed(title=f"Deleted — {member}", color=discord.Color.orange())
        for field_name, field_value in counts.items():
            deletion_embed.add_field(name=field_name, value=str(field_value), inline=True)
        deletion_embed.add_field(name="Role Removed", value="Yes" if role_removed else "No", inline=True)
        if not include_history:
            deletion_embed.set_footer(text="History kept. Use include_history=True to delete it.")
        await interaction.response.send_message(embed=deletion_embed)

    # ── Leaderboard ───────────────────────────────────────────────────────────

    @app_commands.command(name="leaderboard", description="Show top verified members ranked by K/D.")
    async def leaderboard(self, interaction: discord.Interaction,
                          limit: app_commands.Range[int, 1, 25] = 10):
        rows = db.get_leaderboard(limit)
        if not rows:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🏆 Leaderboard",
                    description="No verified members yet.",
                    color=discord.Color.gold()
                )
            )
            return

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for rank, row in enumerate(rows, 1):
            medal = medals.get(rank, f"`#{rank}`")
            kd_str = f"{row['kd']:.2f}" if row['kd'] is not None else "N/A"
            lines.append(f"{medal} **{row['username']}** — K/D `{kd_str}`")

        leaderboard_embed = discord.Embed(
            title="🏆 KILL Clan Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        leaderboard_embed.set_footer(text=f"Top {len(rows)} verified member(s)")
        await interaction.response.send_message(embed=leaderboard_embed)

    # ── Stats Dashboard ───────────────────────────────────────────────────────

    @app_commands.command(name="stats", description="Show verification stats dashboard.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def stats_dashboard(self, interaction: discord.Interaction):
        if not await self._check_channel(interaction):
            return

        stats = db.get_verification_stats()
        status_counts = stats["status_counts"]
        total = stats["total_submissions"] or 1  # avoid division by zero

        approved_count = status_counts.get("approved", 0)
        rejected_count = status_counts.get("rejected", 0)
        flagged_count  = status_counts.get("flagged", 0)

        stats_embed = discord.Embed(
            title="📊 Verification Stats Dashboard",
            color=discord.Color.blue()
        )
        stats_embed.add_field(
            name="👥 Verified Members",
            value=f"**{stats['total_verified']}**",
            inline=True
        )
        stats_embed.add_field(
            name="📈 Average K/D",
            value=f"**{stats['avg_kd']:.2f}**",
            inline=True
        )
        stats_embed.add_field(
            name="📋 Total Submissions",
            value=f"**{stats['total_submissions']}**",
            inline=True
        )
        stats_embed.add_field(
            name="📅 Activity",
            value=f"Today: **{stats['today']}**\nThis week: **{stats['this_week']}**",
            inline=True
        )
        stats_embed.add_field(
            name="✅ Approved",
            value=f"**{approved_count}** ({approved_count * 100 // total}%)",
            inline=True
        )
        stats_embed.add_field(
            name="❌ Rejected",
            value=f"**{rejected_count}** ({rejected_count * 100 // total}%)",
            inline=True
        )
        if flagged_count:
            stats_embed.add_field(
                name="🔍 Flagged",
                value=f"**{flagged_count}** ({flagged_count * 100 // total}%)",
                inline=True
            )
        stats_embed.set_footer(text="Stats pulled from the verification database")
        await interaction.response.send_message(embed=stats_embed)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            message = "You need Manage Roles permission."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        raise error


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
