import random
import discord
from discord.ext import commands


class General(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx):
        await ctx.send(
            "**📖 Danh sách lệnh**\n\n"

            "**=====General - Chung=====**\n"
            "`!help` — Hiện danh sách lệnh\n"
            "`!ban @member <lý do>` — Tạo vote ban thành viên\n"
            "`!members` - Xem toàn bộ thành viên server\n\n" 

            "**=====Chức năng xem thời khóa biểu=====**\n"
            "`!schedule <Tên> <Lớp>` - Tra xem ngày hôm đó học môn gì\n"
            "`!version-schedule` Kiểm tra phiên bản của thời khóa biểu\n\n"

            "**=====Giải trí=====**\n"
            "`!roulette` hoặc `!quay` hoặc `slap` - pick random một người trong server\n"
        )

    @commands.Cog.listener()
    async def on_message(self, message):

        if message.author.bot:
            return

        content = message.content.lower()

        BAD_WORDS = [
            "suck",
            "dick",
            "pussy",
            "cặc",
            "buồi",
            "đụ",
            "địt"
            "dcmm",
            "fuck",
            "nứng",
            "nigger",
            "niger",
            "nigga",
            "niga",
            "nichga",
            "ních ga"
        ]

        BANNED_WORDS = [
            "pinky", "pink" , "hồng"
        ]

        for bw in BAD_WORDS:
            if bw in content:
                await message.channel.send(
                    f"Ê {message.author.mention}, Nói tục là gay."
                )
                return
        for w in BANNED_WORDS:
            if w in content and not "!schedule" in content: #Make sure the schedule command is not banned
                await message.channel.send(
                    f"Ê {message.author.mention}, Thông tin nhạy cảm, vui lòng không nói!(Phúc buồn đó!)"
                )
                return

        if self.bot.user in message.mentions:
            await message.channel.send(
                f"Ê {message.author.mention}, gọi tôi đấy à? :)))"
            )
    
    @commands.command(name="members")
    async def members_command(self, ctx):
        members = ctx.guild.members

        if not members:
            await ctx.send("Server chưa có thành viên nào 💀")
            return

        lines = [
            f"👥 **Danh sách thành viên — {len(members)} người**",
            ""
        ]

        for i, member in enumerate(members, start=1):
            # Không dùng member.mention => không ping
            name = member.display_name.replace("@", "@\u200b")
            lines.append(f"`{i}.` {name}")

        # Discord giới hạn 2000 ký tự/message
        chunks = []
        current = ""

        for line in lines:
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = line
            else:
                current += ("\n" if current else "") + line

        if current:
            chunks.append(current)

        for chunk in chunks:
            await ctx.send(chunk)

    @commands.command(name="roulette", aliases=["quay", "slap"])
    async def roulette_command(self, ctx):
        # Lọc lấy tất cả member trong server ngoại trừ bot
        members = [m for m in ctx.guild.members if not m.bot]

        if not members:
            await ctx.send("❌ Server không có ai (trừ bot) để quay cả!")
            return

        # Pick ngẫu nhiên 1 người
        victim = random.choice(members)

        await ctx.send(f"🎯 Vòng quay tử thần đã xướng tên: {victim.mention}! 💥")

async def setup(bot):
    await bot.add_cog(General(bot))

