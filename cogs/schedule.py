import aiohttp
import asyncio
import json
import re
import unicodedata
from urllib.parse import urljoin
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks


class Schedule(commands.Cog):

    BASE_URL = "https://lqddn-tkb.vercel.app/"
    CACHE_MINUTES = 10

    DAY_NAMES = [
        "Chủ Nhật",
        "Thứ Hai",
        "Thứ Ba",
        "Thứ Tư",
        "Thứ Năm",
        "Thứ Sáu",
        "Thứ Bảy",
    ]

    PERIODS = [
        "Sáng 1",
        "Sáng 2",
        "Sáng 3",
        "Sáng 4",
        "Sáng 5",
        "Chiều 1",
        "Chiều 2",
        "Chiều 3",
        "Chiều 4",
    ]

    TZ = ZoneInfo("Asia/Ho_Chi_Minh")

    def __init__(self, bot):
        self.bot = bot

        self.all_students = []
        self.classes_data = {}
        self.elective_classes = {}
        self.teachers_data = {}
        self.room_dict = {}

        self.last_loaded = None
        self.version_info = "Đang khởi tạo..."
        self.load_lock = asyncio.Lock()

        self.auto_update.start()

    def cog_unload(self):
        self.auto_update.cancel()

    # ============================================================
    # AUTO UPDATE TASK
    # ============================================================

    @tasks.loop(minutes=30)
    async def auto_update(self):
        """Tự động đồng bộ lại dữ liệu TKB mỗi 30 phút."""
        try:
            await self.load_data(force=True)
            print(f"[TKB] Đã tự động cập nhật dữ liệu lúc {datetime.now(self.TZ).strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[TKB] Lỗi khi tự động cập nhật: {e}")

    @auto_update.before_loop
    async def before_auto_update(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # TEXT HELPERS
    # ============================================================

    @staticmethod
    def normalize(text):
        if not text:
            return ""

        text = str(text).strip().lower()
        text = unicodedata.normalize("NFD", text)
        text = "".join(
            c
            for c in text
            if unicodedata.category(c) != "Mn"
        )
        text = text.replace("đ", "d")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # ============================================================
    # HTTP & JS PARSING HELPERS
    # ============================================================

    async def fetch_text(self, session, url):
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Discord TKB Bot; +https://discord.com)"
                )
            },
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"HTTP {response.status}: {url}"
                )
            return await response.text(encoding="utf-8")

    @staticmethod
    def parse_js_assign(text, var_name):
        """Trích xuất và parse object JSON sau dấu '=' của window.VAR_NAME."""
        pattern = re.compile(
            rf"(?:window\.)?{re.escape(var_name)}\s*=\s*",
            re.MULTILINE,
        )
        matches = list(pattern.finditer(text))
        if not matches:
            return None

        for match in reversed(matches):
            start = match.end()
            while start < len(text) and text[start].isspace():
                start += 1

            if start >= len(text):
                continue

            try:
                decoder = json.JSONDecoder()
                value, _ = decoder.raw_decode(text[start:])
                return value
            except json.JSONDecodeError:
                continue

        return None

    # ============================================================
    # LOAD DATA
    # ============================================================

    async def load_data(self, force=False):
        if not force and self.last_loaded is not None:
            age = (datetime.now(self.TZ) - self.last_loaded).total_seconds()
            if age < self.CACHE_MINUTES * 60:
                return

        async with self.load_lock:
            if not force and self.last_loaded is not None:
                age = (datetime.now(self.TZ) - self.last_loaded).total_seconds()
                if age < self.CACHE_MINUTES * 60:
                    return

            print("[TKB] Đang tải HTML live...")
            async with aiohttp.ClientSession() as session:
                html = await self.fetch_text(session, self.BASE_URL)

                visited_urls = set()
                to_fetch = set()

                # Quét script trong HTML ban đầu
                for js_path in re.findall(r'src=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']', html, re.IGNORECASE):
                    to_fetch.add(urljoin(self.BASE_URL, js_path))

                fetched_scripts = {}

                # Tải toàn bộ các file JS liên quan
                while to_fetch:
                    current_url = to_fetch.pop()
                    if current_url in visited_urls:
                        continue
                    visited_urls.add(current_url)

                    try:
                        js_text = await self.fetch_text(session, current_url)
                        fetched_scripts[current_url] = js_text

                        # Tìm tiếp các file .js hoặc mã phiên bản YYYY-MM-DD...
                        found_paths = re.findall(r'["\']([^"\'\s\?]+\.js)(?:\?[^"\'\s]*)?["\']', js_text, re.IGNORECASE)
                        version_matches = re.findall(r'["\'](\d{4}-\d{2}-\d{2}-v\d+[\w-]*)(?:\.js)?["\']', js_text, re.IGNORECASE)
                        for vm in version_matches:
                            found_paths.append(f"{vm}.js")

                        for raw_path in found_paths:
                            clean_path = raw_path.strip().lstrip('./')
                            filename = clean_path.split('/')[-1]

                            candidates = [
                                urljoin(self.BASE_URL, clean_path),
                                f"{self.BASE_URL.rstrip('/')}/data/timetable/{filename}",
                                f"{self.BASE_URL.rstrip('/')}/data/{filename}",
                            ]

                            for cand_url in candidates:
                                if cand_url.startswith(self.BASE_URL) and cand_url not in visited_urls:
                                    to_fetch.add(cand_url)

                    except Exception:
                        pass

            # ----------------------------------------------------
            # BÓC TÁCH DỮ LIỆU TỪ OBJECT JS
            # ----------------------------------------------------
            tkb_master = None
            timetable_files = []

            for url, content in fetched_scripts.items():
                if not tkb_master:
                    parsed_master = self.parse_js_assign(content, "TKB_MASTER")
                    if parsed_master:
                        tkb_master = parsed_master

                parsed_timetable = self.parse_js_assign(content, "TKB_TIMETABLE")
                if parsed_timetable:
                    # Lấy tên file để sắp xếp theo thời gian mới nhất (VD: 2026-10-05 > 2026-09-07)
                    filename = url.split('/')[-1]
                    timetable_files.append((filename, parsed_timetable))

            if not tkb_master:
                raise RuntimeError("Không thể parse window.TKB_MASTER")

            if not timetable_files:
                raise RuntimeError("Không thể parse window.TKB_TIMETABLE")

            # Ưu tiên lấy file timetable mới nhất theo thứ tự alphabet/ngày tháng
            timetable_files.sort(key=lambda x: x[0], reverse=True)
            latest_filename, latest_timetable = timetable_files[0]

            all_students = tkb_master.get("allStudents") or []
            elective_classes = tkb_master.get("electiveClasses") or {}
            room_dict = tkb_master.get("roomDict") or {}

            classes_data = latest_timetable.get("classesData") or {}
            teachers_data = latest_timetable.get("teachersData") or {}

            # Version
            version_info = (
                latest_timetable.get("version")
                or latest_timetable.get("updateDate")
                or latest_filename.replace(".js", "")
            )

            # ----------------------------------------------------
            # LƯU KẾT QUẢ
            # ----------------------------------------------------
            self.all_students = all_students
            self.classes_data = classes_data
            self.elective_classes = elective_classes
            self.teachers_data = teachers_data
            self.room_dict = room_dict
            self.version_info = str(version_info)
            self.last_loaded = datetime.now(self.TZ)

            print(
                "[TKB] Loaded thành công từ "
                f"[{latest_filename}]: {len(self.all_students)} học sinh, "
                f"{len(self.classes_data)} lớp, "
                f"{len(self.elective_classes)} lớp tự chọn."
            )

    async def cog_load(self):
        try:
            await self.load_data(force=True)
        except Exception as e:
            print(f"[Schedule] Không load được TKB: {e}")

    # ============================================================
    # STUDENT SEARCH & FORMATTING LOGIC
    # ============================================================

    def find_students(self, name, class_name=None):
        query = self.normalize(name)
        class_query = None

        if class_name:
            class_query = self.normalize(class_name)

        exact = []
        partial = []

        for student in self.all_students:
            student_name = student.get("name", "")
            student_class = str(student.get("class", "")).strip()

            if class_query:
                if self.normalize(student_class) != class_query:
                    continue

            normalized_student_name = self.normalize(student_name)

            if normalized_student_name == query:
                exact.append(student)
            elif query in normalized_student_name:
                partial.append(student)

        if exact:
            return exact
        return partial

    def get_schedule_day(self):
        now = datetime.now(self.TZ)
        weekday = now.weekday()
        if weekday >= 5:
            return "Thứ Hai", True
        if now.hour >= 17:
            return (self.DAY_NAMES[weekday + 2], False)
        return (self.DAY_NAMES[weekday + 1], False)

    def get_home_class(self, student):
        class_name = str(student.get("class", "")).strip()
        if class_name in self.classes_data:
            return class_name

        normalized_class = self.normalize(class_name)
        for code in self.classes_data:
            if self.normalize(code) == normalized_class:
                return code
        for code in self.classes_data:
            if normalized_class.startswith(self.normalize(code)):
                return code
        return class_name

    def get_room(self, value):
        if not value:
            return ""
        value = str(value).strip()

        if value in self.room_dict:
            return self.room_dict[value]

        if (value in self.classes_data and self.classes_data[value].get("phong")):
            return self.classes_data[value]["phong"]

        if (value in self.elective_classes and self.elective_classes[value].get("room")):
            return self.elective_classes[value]["room"]

        if ".MT" in value or value.startswith("MT"):
            return "P. MT"

        if any(x in value for x in [".AN1", ".AN3", ".AN5"]):
            return "P. AN1"

        if any(x in value for x in [".AN2", ".AN4", ".AN6"]):
            return "P. AN2"

        if ".Ti" in value or ".TI" in value:
            return "P. Tin"

        if any(x in value for x in [".Ph", ".Anh", ".AnD", "NN2"]):
            return "P. Ngoại ngữ"

        return ""

    def resolve_elective_code(self, code):
        if not code:
            return None
        code = str(code).strip()
        if code in self.elective_classes:
            return code
        code_lower = code.lower()
        for key in self.elective_classes:
            if str(key).lower() == code_lower:
                return key
        return None

    def get_student_elective_codes(self, student):
        codes = []
        mon_lc = student.get("mon_lc")
        if isinstance(mon_lc, list):
            for code in mon_lc:
                if code:
                    codes.append(str(code).strip())
        elif mon_lc:
            codes.append(str(mon_lc).strip())

        tc = student.get("tc")
        if isinstance(tc, list):
            for code in tc:
                if code:
                    codes.append(str(code).strip())
        elif tc:
            codes.append(str(tc).strip())

        result = []
        seen = set()
        for code in codes:
            key = code.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(code)

        return result

    def get_elective_lesson(self, student, day, period):
        codes = self.get_student_elective_codes(student)
        for code in codes:
            code = str(code).strip()
            resolved_code = self.resolve_elective_code(code)

            if resolved_code:
                info = self.elective_classes.get(resolved_code)
                if not isinstance(info, dict):
                    continue

                slots = info.get("slots") or []
                for slot in slots:
                    if not isinstance(slot, dict):
                        continue
                    if (slot.get("day", "") != day or slot.get("period", "") != period):
                        continue

                    subject = slot.get("to") or slot.get("subject") or ""
                    teacher = slot.get("gv") or ""
                    room = info.get("room") or self.get_room(resolved_code)
                    return {
                        "period": period,
                        "subject": subject,
                        "room": room,
                        "teacher": teacher,
                        "type": "Tự chọn",
                    }

            for teacher_name, teacher_info in self.teachers_data.items():
                if not isinstance(teacher_info, dict):
                    continue

                schedule = teacher_info.get("schedule") or {}
                day_schedule = schedule.get(day) or {}
                assigned_code = day_schedule.get(period)

                if assigned_code != code:
                    continue

                subject = teacher_info.get("to") or ""
                if not subject:
                    code_lower = code.lower()
                    if ".ly" in code_lower:
                        subject = "Vật lý"
                    elif ".ho" in code_lower:
                        subject = "Hoá học"
                    elif ".ti" in code_lower:
                        subject = "Tin học"
                    elif ".an" in code_lower:
                        subject = "Ngoại ngữ 1"
                    elif ".kt" in code_lower:
                        subject = "GDKTPL"
                    elif ".cn" in code_lower:
                        subject = "Công nghệ"
                    elif ".mt" in code_lower:
                        subject = "Mỹ thuật"
                    elif ".di" in code_lower:
                        subject = "Địa lý"
                    else:
                        subject = "Tự chọn"

                return {
                    "period": period,
                    "subject": subject,
                    "room": "",
                    "teacher": teacher_name,
                    "type": "Tự chọn",
                }
        return None

    def get_student_day_schedule(self, student, day):
        home_class = self.get_home_class(student)
        class_info = self.classes_data.get(home_class)
        if not class_info:
            return []

        class_schedule = class_info.get("schedule") or {}
        day_schedule = class_schedule.get(day) or {}
        result = []

        for period in self.PERIODS:
            subject = day_schedule.get(period) or ""
            if not subject:
                continue

            subject_string = str(subject).strip()

            if subject_string.upper().startswith("LC"):
                elective = self.get_elective_lesson(student, day, period)
                if elective:
                    result.append(
                        {
                            "period": period,
                            "subject": elective["subject"],
                            "room": elective["room"],
                            "teacher": elective["teacher"],
                            "type": "Tự chọn",
                        }
                    )
                continue

            result.append(
                {
                    "period": period,
                    "subject": subject_string,
                    "class": home_class,
                    "room": class_info.get("phong", ""),
                    "teacher": "",
                    "type": "Môn lớp",
                }
            )
        return result

    @staticmethod
    def period_label(period):
        parts = str(period).split()
        if len(parts) != 2:
            return period
        session = "Sáng" if parts[0] == "Sáng" else "Chiều"
        return f"{session} tiết {parts[1]}"

    def format_schedule(self, student, day, fallback_weekend=False):
        home_class = self.get_home_class(student)
        lessons = self.get_student_day_schedule(student, day)
        lines = []

        if fallback_weekend:
            lines.append("📅 **Lịch Thứ Hai** *(hôm nay là cuối tuần)*")
        else:
            lines.append(f"📅 **Lịch {day}**")

        lines.append(f"👤 **{student.get('name', 'Không rõ')}**")
        lines.append(f"🏫 Lớp **{home_class}**")
        lines.append("")

        if not lessons:
            lines.append("📭 Hôm nay không có tiết học.")
            return "\n".join(lines)

        morning = [lesson for lesson in lessons if lesson["period"].startswith("Sáng")]
        afternoon = [lesson for lesson in lessons if lesson["period"].startswith("Chiều")]

        def add_lesson(lesson):
            period = lesson["period"]
            subject = lesson["subject"]
            room = lesson["room"]
            teacher = lesson["teacher"]
            lesson_type = lesson["type"]
            line = f"`{period}` — **{subject}**"
            extras = []

            if lesson_type == "Tự chọn":
                extras.append("tự chọn")
            if room:
                extras.append(room)
            if teacher:
                extras.append(teacher)
            if extras:
                line += " · " + " · ".join(extras)
            lines.append(line)

        if morning:
            lines.append("🌅 **Buổi sáng**")
            for lesson in morning:
                add_lesson(lesson)

        if afternoon:
            if morning:
                lines.append("")
            lines.append("🌇 **Buổi chiều**")
            for lesson in afternoon:
                add_lesson(lesson)

        return "\n".join(lines)

    # ============================================================
    # COMMANDS
    # ============================================================

    @commands.command(name="schedule", aliases=["tkb"])
    async def schedule_command(self, ctx, *, query: str = None):
        if not query:
            await ctx.send(
                "❌ Cú pháp:\n"
                "`!schedule <tên>`\n"
                "`!schedule <tên> <lớp>`\n\n"
                "Ví dụ:\n"
                "`!schedule Dương Bảo Kha`\n"
                "`!schedule Dương Bảo Kha 10A3`"
            )
            return

        try:
            await self.load_data()
        except Exception as e:
            await ctx.send(f"❌ Không tải được TKB:\n`{e}`")
            return

        name_query = query.strip()
        class_query = None
        match = re.match(r"^(.*?)(?:\s+)(\d{2}[A-Za-z]\d+)$", name_query, flags=re.IGNORECASE)

        if match:
            name_query = match.group(1).strip()
            class_query = match.group(2).upper()

        students = self.find_students(name_query, class_query)

        if not students:
            if class_query:
                await ctx.send(f"❌ Không tìm thấy học sinh **{name_query}** ở lớp `{class_query}`.")
            else:
                await ctx.send(f"❌ Không tìm thấy học sinh **{name_query}**.")
            return

        if len(students) > 1:
            lines = [f"🔎 Tìm thấy **{len(students)}** học sinh:"]
            for i, student in enumerate(students[:15], start=1):
                lines.append(f"`{i}.` **{student.get('name', '?')}** — `{student.get('class', '?')}`")
            if len(students) > 15:
                lines.append(f"... và {len(students) - 15} kết quả khác.")
            lines.append("\n💡 Ghi rõ lớp, ví dụ:\n`!schedule Dương Bảo Kha 10A3`")
            await ctx.send("\n".join(lines))
            return

        student = students[0]
        day, weekend_fallback = self.get_schedule_day()
        text = self.format_schedule(student, day, weekend_fallback)
        await ctx.send(text)
        
    @commands.command(name="schedule-full", aliases=["tkb-full", "tkbfull", "tkbcatuan"])
    async def schedule_full_command(self, ctx, *, query: str = None):
        if not query:
            await ctx.send(
                "❌ Cú pháp:\n"
                "`!schedule-full <tên>`\n"
                "`!schedule-full <tên> <lớp>`\n\n"
                "Ví dụ:\n"
                "`!schedule-full Dương Bảo Kha`\n"
                "`!schedule-full Dương Bảo Kha 10A3`"
            )
            return

        try:
            await self.load_data()
        except Exception as e:
            await ctx.send(f"❌ Không tải được TKB:\n`{e}`")
            return

        # Tách tên và lớp giống hệt logic cũ
        name_query = query.strip()
        class_query = None
        match = re.match(r"^(.*?)(?:\s+)(\d{2}[A-Za-z]\d+)$", name_query, flags=re.IGNORECASE)

        if match:
            name_query = match.group(1).strip()
            class_query = match.group(2).upper()

        students = self.find_students(name_query, class_query)

        if not students:
            if class_query:
                await ctx.send(f"❌ Không tìm thấy học sinh **{name_query}** ở lớp `{class_query}`.")
            else:
                await ctx.send(f"❌ Không tìm thấy học sinh **{name_query}**.")
            return

        # Xử lý trường hợp trùng tên
        if len(students) > 1:
            lines = [f"🔎 Tìm thấy **{len(students)}** học sinh:"]
            for i, student in enumerate(students[:15], start=1):
                lines.append(f"`{i}.` **{student.get('name', '?')}** — `{student.get('class', '?')}`")
            if len(students) > 15:
                lines.append(f"... và {len(students) - 15} kết quả khác.")
            lines.append("\n💡 Ghi rõ lớp, ví dụ:\n`!schedule-full Dương Bảo Kha 10A3`")
            await ctx.send("\n".join(lines))
            return

        student = students[0]
        home_class = self.get_home_class(student)

        # Khởi tạo Embed hiển thị toàn bộ tuần
        embed = discord.Embed(
            title="📅 Lịch học cả tuần",
            description=f"👤 **{student.get('name', 'Không rõ')}** - 🏫 Lớp **{home_class}**",
            color=0x2ecc71
        )

        days = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"]
        has_any_lesson = False

        for day in days:
            lessons = self.get_student_day_schedule(student, day)
            if not lessons:
                continue

            has_any_lesson = True
            morning = [l for l in lessons if l["period"].startswith("Sáng")]
            afternoon = [l for l in lessons if l["period"].startswith("Chiều")]

            day_str = []
            
            # Format siêu gọn: 🌅 Sáng: 1.Toán, 2.Lý, 3.Tin (TC)
            if morning:
                m_str = ", ".join([f"`T{l['period'][-1]}` {l['subject']}{' *(TC)*' if l['type'] == 'Tự chọn' else ''}" for l in morning])
                day_str.append(f"🌅 **Sáng:** {m_str}")
                
            if afternoon:
                a_str = ", ".join([f"`T{l['period'][-1]}` {l['subject']}{' *(TC)*' if l['type'] == 'Tự chọn' else ''}" for l in afternoon])
                day_str.append(f"🌇 **Chiều:** {a_str}")

            # Thêm thông tin của ngày đó vào Embed
            embed.add_field(name=f"▶️ {day}", value="\n".join(day_str), inline=False)

        if not has_any_lesson:
            embed.description += "\n\n📭 Tuần này không có dữ liệu tiết học nào."
            
        embed.set_footer(text="*(TC)* = Tiết Tự Chọn")

        await ctx.send(embed=embed)

    @commands.command(name="version-schedule", aliases=["tkb-version", "vstkb"])
    async def version_schedule_command(self, ctx):
        if not self.last_loaded:
            await ctx.send("⏳ Đang kéo dữ liệu TKB... Cậu chờ một chút nhé.")
            return

        embed = discord.Embed(
            title="ℹ️ Thông tin phiên bản Thời Khóa Biểu",
            color=0x3498db
        )
        embed.add_field(name="🌐 Nguồn Web", value=self.BASE_URL, inline=False)
        embed.add_field(name="🏷️ Phiên bản hiện tại", value=f"`{self.version_info}`", inline=False)
        embed.add_field(name="🔄 Đồng bộ lần cuối lúc", value=f"`{self.last_loaded.strftime('%d/%m/%Y %H:%M:%S')}`", inline=False)
        embed.add_field(
            name="📊 Thống kê dữ liệu", 
            value=f"• **{len(self.all_students)}** Học sinh\n• **{len(self.classes_data)}** Lớp học", 
            inline=False
        )
        embed.set_footer(text="Tự động cập nhật mỗi 30 phút.")

        await ctx.send(embed=embed)


# ================================================================
# SETUP
# ================================================================

async def setup(bot):
    await bot.add_cog(Schedule(bot))