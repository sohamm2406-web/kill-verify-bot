import discord
from discord.ext import commands
from datetime import datetime
import logging

from analyzer import AnalysisResult, analyze_screenshot, evaluate
from config import Config
import database as db

log = logging.getLogger(__name__)

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_NON_STATS = (
    "not a game stats screenshot", "not a stats page", "post-match leaderboard",
    "leaderboard", "not an account profile stats page", "prevents extraction of overall k/d",
)
_COLOR = {
    "approved": discord.Color.green(),   "rejected": discord.Color.red(),
    "flagged":  discord.Color.orange(),  "tampered": discord.Color.dark_red(),
    "invalid":  discord.Color.red(),
}
_VERDICT_EMOJI = {
    "approved": "✅", "rejected": "❌", "flagged": "🔍", "tampered": "🚨", "invalid": "🚫",
}


def _has_review_permission(member: discord.Member) -> bool:
    """Allow staff with Manage Roles OR the Authenticator role."""
    if member.guild_permissions.manage_roles:
        return True
    authenticator_role = discord.utils.get(member.guild.roles, name=Config.AUTHENTICATOR_ROLE_NAME)
    return authenticator_role is not None and authenticator_role in member.roles


def build_result_embed(user: discord.Member, result: AnalysisResult, verdict: str, reasons: list[str]) -> discord.Embed:
    icon = _VERDICT_EMOJI.get(verdict, "")
    embed = discord.Embed(
        title=f"{icon} Verification — {verdict.upper()}",
        color=_COLOR.get(verdict, discord.Color.greyple())
    )
    embed.set_author(name=str(user), icon_url=user.display_avatar.url)
    embed.add_field(name="User ID",          value=str(user.id),                                                    inline=True)
    embed.add_field(name="K/D",              value=str(result.kd) if result.kd is not None else "N/A",             inline=True)
    embed.add_field(name="Tag Found",        value="Yes" if result.tag_found else "No",                             inline=True)
    embed.add_field(name="Account",          value=result.tag_account_name or "—",                                  inline=True)
    embed.add_field(name="Games",            value=str(result.games_played) if result.games_played is not None else "N/A", inline=True)
    embed.add_field(name="Confidence",       value=result.confidence.capitalize(),                                  inline=True)
    if result.visible_kills is not None or result.visible_deaths is not None:
        embed.add_field(name="Kills / Deaths",
                        value=f"{result.visible_kills or 'N/A'} / {result.visible_deaths or 'N/A'}", inline=True)
    embed.add_field(name="Stat Consistency", value=result.stat_consistency.replace("_", " ").capitalize(), inline=True)
    tamper_icon = {"clean": "✅", "suspicious": "⚠️", "tampered": "🚨"}.get(result.tamper_status, "?")
    embed.add_field(
        name=f"Tamper Check {tamper_icon}",
        value="\n".join(result.tamper_reasons) or "No issues detected",
        inline=False
    )
    if result.notes:
        embed.add_field(name="Notes", value=result.notes, inline=False)
    if reasons:
        embed.add_field(name="Verdict Reasons", value="\n".join(f"• {reason}" for reason in reasons), inline=False)
    return embed


class VerifyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        db.init_db()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.name != Config.VERIFY_CHANNEL_NAME:
            return

        image_url = next(
            (attachment.url for attachment in message.attachments
             if any(attachment.filename.lower().endswith(ext) for ext in _IMG_EXTS)),
            None
        )
        if not image_url:
            return

        user = message.author
        user_id = str(user.id)

        if db.is_already_verified(user_id):
            await self._send_temp_message(message, f"{user.mention} You're already verified as a KILLer. ✅")
            return

        if db.get_attempt_count(user_id) >= Config.MAX_ATTEMPTS:
            await message.delete(delay=3)
            await self._send_temp_message(
                message,
                f"{user.mention} You've reached the maximum of **{Config.MAX_ATTEMPTS}** attempts. Contact staff for manual review."
            )
            return

        is_on_cooldown, hours_remaining = db.is_on_cooldown(user_id)
        if is_on_cooldown:
            await message.delete(delay=3)
            await self._send_temp_message(
                message,
                f"{user.mention} You're on cooldown — please wait **{hours_remaining}h** before resubmitting."
            )
            return

        db.set_cooldown(user_id)
        processing_message = await message.reply(f"🔍 {user.mention} Analyzing your screenshot, please wait…")
        result = await analyze_screenshot(image_url)
        await processing_message.delete()

        if not result.success:
            await self._handle_failure(message, result)
            return

        # Not a stats page check
        combined_text = " ".join([result.notes, *result.tamper_reasons, result.raw_response]).lower()
        if any(keyword in combined_text for keyword in _NON_STATS):
            db.rollback_attempt(user_id)
            db.log_verification(user_id, str(user), "rejected", kd=result.kd,
                                tag_found=int(result.tag_found), tamper_score=result.tamper_status,
                                tamper_reason="Not a stats page")
            log_channel = self._get_log_channel(message.guild)
            if log_channel:
                invalid_embed = build_result_embed(user, result, "invalid", ["Not a valid stats page"])
                invalid_embed.set_image(url=image_url)
                await log_channel.send(embed=invalid_embed)
            guidance_embed = discord.Embed(
                title="Wrong Screenshot",
                description=(
                    f"{user.mention}, that doesn't look like your stats page.\n\n"
                    "**How to get the right screenshot:**\n"
                    "1. Go to **deadshot.io**\n"
                    "2. Click **Account** (top right)\n"
                    "3. Take a screenshot of your **stats page** showing K/D, Games Played, etc.\n"
                    "4. Resubmit here. Please try again!"
                ),
                color=discord.Color.orange()
            )
            await message.reply(embed=guidance_embed)
            return

        verdict, reasons = evaluate(result)
        await self._post_staff_log(message, result, verdict, reasons, image_url)

        if verdict == "approved":
            killers_role = discord.utils.get(message.guild.roles, name=Config.KILLERS_ROLE_NAME)
            if killers_role:
                await user.add_roles(killers_role, reason="Verified via bot")
            db.mark_verified(user_id, str(user), result.kd)

            # React with verified emoji (fallback to ✅ if custom emoji not found)
            verified_emoji = discord.utils.get(message.guild.emojis, name=Config.VERIFIED_REACTION_NAME)
            try:
                await message.add_reaction(verified_emoji if verified_emoji else "✅")
            except discord.HTTPException as error:
                log.warning(f"Could not add reaction: {error}")

            # Congratulatory message
            approval_embed = discord.Embed(
                title="Verification Approved",
                description=(
                    f"Welcome to the clan, {user.mention}! "
                    f"You've been verified as a **{Config.KILLERS_ROLE_NAME}** member.\n\n"
                    f"**K/D:** {result.kd:.2f}  |  **Games:** {result.games_played}  |  **Account:** {result.tag_account_name or 'N/A'}"
                ),
                color=discord.Color.green()
            )
            approval_embed.set_author(name=str(user), icon_url=user.display_avatar.url)
            approval_embed.set_footer(text="Verified by KILL Ascension Bot")
            await message.reply(embed=approval_embed)

        elif verdict in ("tampered", "flagged"):
            staff_label = "🚨 TAMPERED FLAG" if verdict == "tampered" else "🔍 Flagged"
            staff_mentions = " ".join(
                role.mention
                for role_name in (*getattr(Config, "MODERATOR_ROLE_NAMES", ()), Config.AUTHENTICATOR_ROLE_NAME)
                if (role := discord.utils.get(message.guild.roles, name=role_name))
            )

            # Concise embed + Approve/Reject buttons → verify channel (public, no internal details)
            flagged_embed = discord.Embed(
                description=(
                    f"{user.mention}, your screenshot has been flagged for review.\n\n"
                    f"**Account:** {result.tag_account_name or '—'}  |  **K/D:** {result.kd or 'N/A'}\n"
                    "Staff will verify shortly."
                ),
                color=discord.Color.dark_red() if verdict == "tampered" else discord.Color.orange()
            )
            flagged_embed.set_footer(text="Staff: use buttons below to approve or reject.")
            await message.reply(
                content=f"{staff_mentions} {staff_label} — {user.mention} needs review.".strip(),
                embed=flagged_embed,
                view=ReviewView(user, message.guild, image_url, result),
                allowed_mentions=discord.AllowedMentions(roles=True, users=True)
            )

        else:  # rejected
            rejection_embed = discord.Embed(
                title="Verification Failed",
                description=f"{user.mention}, your submission did not meet the requirements:",
                color=discord.Color.red()
            )
            rejection_embed.add_field(
                name="Issues",
                value="\n".join(f"• {reason}" for reason in reasons),
                inline=False
            )
            rejection_embed.add_field(
                name="Requirements",
                value=(
                    f"• K/D must be **{Config.MIN_KD}+**\n"
                    f"• Account must show **{Config.REQUIRED_TAG}**\n"
                    f"• Minimum **{Config.MIN_GAMES_PLAYED}** games played"
                ),
                inline=False
            )
            rejection_embed.set_footer(text=f"You can resubmit in {Config.COOLDOWN_HOURS}h.")
            await message.reply(embed=rejection_embed)

        db.log_verification(
            user_id, str(user), verdict,
            kd=result.kd,
            tag_found=int(result.tag_found),
            tamper_score=result.tamper_status,
            tamper_reason=", ".join(result.tamper_reasons)
        )

    async def _handle_failure(self, message: discord.Message, result: AnalysisResult):
        log_channel = self._get_log_channel(message.guild)
        if log_channel:
            failure_embed = discord.Embed(
                title="Analysis Failed",
                description=f"User: {message.author.mention}\n**Error:** {result.error}",
                color=discord.Color.red()
            )
            failure_embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
            if result.error and "quota" in result.error.lower():
                failure_embed.add_field(
                    name="Action Required",
                    value="Gemini API quota exceeded. Check billing.",
                    inline=False
                )
            await log_channel.send(embed=failure_embed)

        if result.error and ("quota" in result.error.lower() or "429" in result.error):
            user_message = f"{message.author.mention} Verification system temporarily overloaded — try again in a few minutes."
        else:
            user_message = f"{message.author.mention} Could not read your screenshot — please resubmit with a clearer image."
        db.rollback_attempt(str(message.author.id))
        await self._send_temp_message(message, user_message)

    async def _post_staff_log(self, message: discord.Message, result: AnalysisResult,
                              verdict: str, reasons: list[str], image_url: str):
        log_channel = self._get_log_channel(message.guild)
        if log_channel:
            staff_embed = build_result_embed(message.author, result, verdict, reasons)
            staff_embed.set_image(url=image_url)
            await log_channel.send(embed=staff_embed)

    def _get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        return discord.utils.get(guild.text_channels, name=Config.LOG_CHANNEL_NAME)

    async def _send_temp_message(self, message: discord.Message, content: str, delay: int = 8):
        temp_message = await message.reply(content)
        await temp_message.delete(delay=delay)


class ReviewView(discord.ui.View):
    def __init__(self, user: discord.Member, guild: discord.Guild, image_url: str, result: AnalysisResult):
        super().__init__(timeout=None)
        self.user      = user
        self.guild     = guild
        self.image_url = image_url
        self.result    = result
        self.resolved  = False

    async def _resolve(self, interaction: discord.Interaction) -> bool:
        if self.resolved:
            await interaction.response.send_message("This review has already been handled.", ephemeral=True)
            return False
        self.resolved = True
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        return True

    async def _post_decision(self, reviewer: discord.Member, decision: str):
        """Send a detailed decision log to the staff log channel."""
        log_channel = discord.utils.get(self.guild.text_channels, name=Config.LOG_CHANNEL_NAME)
        if not log_channel:
            log.warning(f"Log channel '{Config.LOG_CHANNEL_NAME}' not found — cannot post review decision.")
            return

        result = self.result
        color  = discord.Color.green() if decision == "approved" else discord.Color.red()
        icon   = "✅" if decision == "approved" else "❌"

        decision_embed = discord.Embed(
            title=f"{icon} Manual Review — {decision.upper()}",
            color=color,
            timestamp=datetime.utcnow()
        )
        decision_embed.set_author(name=f"Reviewed by {reviewer}", icon_url=reviewer.display_avatar.url)
        decision_embed.add_field(name="User",     value=f"{self.user.mention} (`{self.user.id}`)",  inline=False)
        decision_embed.add_field(name="Reviewer", value=f"{reviewer.mention} (`{reviewer.id}`)",    inline=False)
        decision_embed.add_field(name="Decision", value=decision.upper(),                            inline=True)
        decision_embed.add_field(name="K/D",      value=str(result.kd) if result.kd is not None else "N/A", inline=True)
        decision_embed.add_field(name="Tag Found", value="Yes" if result.tag_found else "No",        inline=True)
        decision_embed.add_field(name="Account",  value=result.tag_account_name or "—",             inline=True)
        decision_embed.add_field(name="Games",    value=str(result.games_played) if result.games_played else "N/A", inline=True)
        decision_embed.add_field(name="Tamper",   value=result.tamper_status.capitalize(),           inline=True)
        if result.tamper_reasons:
            decision_embed.add_field(
                name="Tamper Reasons",
                value="\n".join(f"• {reason}" for reason in result.tamper_reasons),
                inline=False
            )
        decision_embed.add_field(name="Screenshot", value=f"[View Image]({self.image_url})", inline=False)
        decision_embed.set_footer(text=f"Original AI confidence: {result.confidence}")

        await log_channel.send(embed=decision_embed)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="\u2705")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _has_review_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
            return
        if not await self._resolve(interaction):
            return

        killers_role = discord.utils.get(self.guild.roles, name=Config.KILLERS_ROLE_NAME)
        member       = self.guild.get_member(self.user.id)
        if killers_role and member:
            await member.add_roles(killers_role, reason=f"Manually approved by {interaction.user}")
        db.mark_verified(str(self.user.id), str(self.user), kd=self.result.kd)
        db.log_verification(str(self.user.id), str(self.user), "approved",
                            reviewed_by=str(interaction.user.id))

        await self._post_decision(interaction.user, "approved")
        await interaction.followup.send(
            f"✅ {self.user.mention} has been **approved** by {interaction.user.mention} and given the {Config.KILLERS_ROLE_NAME} role!"
        )

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="\u274c")
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _has_review_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
            return
        if not await self._resolve(interaction):
            return

        db.log_verification(str(self.user.id), str(self.user), "rejected",
                            reviewed_by=str(interaction.user.id))

        await self._post_decision(interaction.user, "rejected")
        await interaction.followup.send(
            f"❌ {self.user.mention} has been **rejected** by {interaction.user.mention}."
        )


async def setup(bot):
    await bot.add_cog(VerifyCog(bot))
