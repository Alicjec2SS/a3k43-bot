import discord
from discord.ext import commands


class Moderation(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(
        self,
        ctx,
        member: discord.Member,
        *,
        reason="No reason provided"
    ):

        # Số thành viên thật trong server, không tính bot
        human_members = [
            m for m in ctx.guild.members
            if not m.bot
        ]

        required_votes = len(human_members) / 4

        # Tạo poll
        poll = await ctx.send(
            f"🔨 **Ban vote for {member.mention}**\n\n"
            f"Reason: {reason}\n\n"
            f"👍 = Ban\n"
            f"👎 = Don't ban\n\n"
            f"Need **{required_votes:.0f} 👍 votes** to ban."
        )

        await poll.add_reaction("👍")
        await poll.add_reaction("👎")

        # Chờ từng vote bằng reaction event
        def check(reaction, user):
            return (
                reaction.message.id == poll.id
                and str(reaction.emoji) in ["👍", "👎"]
                and not user.bot
            )

        while True:

            reaction, user = await self.bot.wait_for(
                "reaction_add",
                check=check
            )

            # Lấy số 👍 hiện tại
            yes_reaction = discord.utils.get(
                poll.reactions,
                emoji="👍"
            )

            yes_votes = yes_reaction.count - 1

            # Đủ 1/4 server đồng ý
            if yes_votes >= required_votes:

                await ctx.send(
                    f"🔨 **Ban vote passed!**\n"
                    f"{yes_votes} people voted 👍.\n"
                    f"{member.mention} has been banned."
                )

                await member.ban(reason=reason)
                break


async def setup(bot):
    await bot.add_cog(Moderation(bot))