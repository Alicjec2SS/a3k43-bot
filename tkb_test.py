import asyncio
import aiohttp
import os
import re
from urllib.parse import urljoin

BASE_URL = "https://lqddn-tkb.vercel.app/"
DUMP_DIR = "debug_dump"

# Các URL đã biết từ log của cậu
KNOWN_URLS = [
    "https://lqddn-tkb.vercel.app/data/versions.js?v=6.15",
    "https://lqddn-tkb.vercel.app/data/master-v6-12.js?v=6.15",
    "https://lqddn-tkb.vercel.app/data/timetable/2026-10-05-v6-10.js",
    "https://lqddn-tkb.vercel.app/data/timetable/2026-09-07-v6-9.js",
]

async def fetch_text(session, url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    async with session.get(url, headers=headers) as resp:
        if resp.status == 200:
            return await resp.text(encoding="utf-8")
        print(f"❌ Lỗi HTTP {resp.status}: {url}")
        return ""

async def main():
    os.makedirs(DUMP_DIR, exist_ok=True)
    
    async with aiohttp.ClientSession() as session:
        print(f"🔍 1. Tải HTML chính từ {BASE_URL}...")
        html = await fetch_text(session, BASE_URL)
        
        with open(os.path.join(DUMP_DIR, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
            
        urls_to_check = list(KNOWN_URLS)
        
        # Tìm thêm script từ HTML
        for script_src in re.findall(r'src=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']', html, re.IGNORECASE):
            full_url = urljoin(BASE_URL, script_src)
            if full_url not in urls_to_check:
                urls_to_check.append(full_url)
                
        print(f"📦 Tìm thấy tổng cộng {len(urls_to_check)} URL script cần kiểm tra.\n")
        print("=" * 70)
        
        for url in urls_to_check:
            clean_filename = url.split("?")[0].split("/")[-1]
            if not clean_filename.endswith(".js"):
                clean_filename += ".js"
                
            print(f"🌐 Tải: {url}")
            content = await fetch_text(session, url)
            
            if not content:
                continue
                
            # Lưu file ra đĩa
            file_path = os.path.join(DUMP_DIR, clean_filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"   💾 Đã lưu vào: {file_path} ({len(content)} bytes)")
            
            # Soi từ khóa
            target_vars = ["allStudents", "classesData", "electiveClasses", "teachersData"]
            for var_name in target_vars:
                matches = [m.start() for m in re.finditer(re.escape(var_name), content)]
                if matches:
                    print(f"   ✅ Tìm thấy biến '{var_name}' ({len(matches)} lần xuất hiện):")
                    for pos in matches[:3]: # In 3 vị trí đầu tiên
                        start_pos = max(0, pos - 30)
                        end_pos = min(len(content), pos + 120)
                        snippet = content[start_pos:end_pos].replace("\n", " ")
                        print(f"      📍 Pos {pos}: ...{snippet}...")
                else:
                    print(f"   ❌ Không thấy '{var_name}'")
            print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
