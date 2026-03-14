#!/usr/bin/env python3
"""
Telegram Music Channel Auto-Post Bot
"""

import os
import asyncio
import logging
import json
import random
from pathlib import Path
from datetime import datetime
from aiohttp import web

import yt_dlp
from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import requests

# ─── Настройки ────────────────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@your_channel")

POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "3"))

BATCH_MIN = int(os.getenv("BATCH_MIN", "4"))
BATCH_MAX = int(os.getenv("BATCH_MAX", "8"))

PORT = int(os.getenv("PORT", "10000"))

QUEUE_FILE = "queue.json"
POSTED_FILE = "posted.json"
COUNTER_FILE = "counter.json"
COOKIES_FILE = "cookies.txt"

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ─── Логирование ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Счётчик треков ───────────────────────────────────────────────────────────

def get_counter() -> int:
    if Path(COUNTER_FILE).exists():
        with open(COUNTER_FILE, "r") as f:
            return json.load(f).get("count", 1299)
    return 1299

def increment_counter():
    count = get_counter() + 1
    with open(COUNTER_FILE, "w") as f:
        json.dump({"count": count}, f)
    return count


# ─── Очередь ──────────────────────────────────────────────────────────────────

def load_queue() -> list:
    if Path(QUEUE_FILE).exists():
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_queue(queue: list):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

def load_posted() -> list:
    if Path(POSTED_FILE).exists():
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_posted(posted: list):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(posted, f, ensure_ascii=False, indent=2)


# ─── YDL опции с куками ───────────────────────────────────────────────────────

def get_ydl_opts(extra: dict = {}) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
    }
    if Path(COOKIES_FILE).exists():
        opts["cookiefile"] = COOKIES_FILE
        log.info("Используем cookies.txt")
    else:
        log.warning("cookies.txt не найден!")
    opts.update(extra)
    return opts


# ─── Разворачивание плейлиста ─────────────────────────────────────────────────

def expand_playlist(url: str) -> list:
    ydl_opts = get_ydl_opts({"extract_flat": True})
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if "entries" in info:
                urls = []
                for entry in info["entries"]:
                    if entry and entry.get("id"):
                        urls.append(f"https://www.youtube.com/watch?v={entry['id']}")
                log.info("Плейлист развёрнут: %d треков", len(urls))
                return urls
            else:
                return [url]
    except Exception as e:
        log.error("Ошибка разворачивания плейлиста: %s", e)
        return [url]

def expand_queue() -> list:
    queue = load_queue()
    new_queue = []
    changed = False

    for url in queue:
        if "playlist" in url or ("list=" in url and "watch?v=" not in url):
            expanded = expand_playlist(url)
            new_queue.extend(expanded)
            changed = True
            log.info("Плейлист → %d треков", len(expanded))
        else:
            new_queue.append(url)

    if changed:
        save_queue(new_queue)
        log.info("Очередь обновлена: %d треков", len(new_queue))
        return new_queue

    return queue


# ─── Скачивание ───────────────────────────────────────────────────────────────

def download_track(url: str) -> dict | None:
    ydl_opts = get_ydl_opts({
        "format": "bestaudio/best",
        "outtmpl": str(DOWNLOAD_DIR / "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            },
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ],
        "writethumbnail": True,
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "Unknown Title")
            uploader = info.get("uploader", "Unknown Artist")
            duration = info.get("duration", 0)
            thumbnail_url = info.get("thumbnail", "")

            base = Path(ydl.prepare_filename(info)).stem
            mp3_path = DOWNLOAD_DIR / f"{base}.mp3"
            if not mp3_path.exists():
                candidates = list(DOWNLOAD_DIR.glob("*.mp3"))
                mp3_path = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

            if not mp3_path or not mp3_path.exists():
                log.error("MP3 не найден: %s", url)
                return None

            cover_path = None
            if thumbnail_url:
                cover_path = DOWNLOAD_DIR / f"{base}_cover.jpg"
                r = requests.get(thumbnail_url, timeout=10)
                if r.status_code == 200:
                    cover_path.write_bytes(r.content)

            mins = duration // 60
            secs = duration % 60
            duration_str = f"{mins}:{secs:02d}" if duration else "0:00"

            return {
                "file": str(mp3_path),
                "cover": str(cover_path) if cover_path and cover_path.exists() else None,
                "title": title,
                "artist": uploader,
                "duration": duration_str,
                "source_url": url,
            }
    except Exception as e:
        log.error("Ошибка скачивания: %s — %s", url, e)
        return None


# ─── Подпись ──────────────────────────────────────────────────────────────────

def format_caption(track: dict, number: int) -> str:
    duration = track.get("duration", "0:00")
    caption = (
        f"🏆𝐁𝐲 𝐖𝐀𝐑𝐃𝐑𝐄𝐒𝐎𝐍𝐀𝐍𝐂𝐄𝐌𝐔𝐒𝐈𝐂🏆\n"
        f"🌙𝙉𝙤𝙢𝙚𝙧 𝙥𝙤𝙞𝙨𝙠𝙖:{number}№🌙\n"
        f"⭐️𝙬𝙖𝙧𝙙𝙢𝙪𝙨𝙞𝙘⭐️\n"
        f"☁️{duration}☁️"
    )
    return caption


# ─── Постинг ──────────────────────────────────────────────────────────────────

async def post_track(bot: Bot, track: dict, number: int) -> bool:
    audio_path = track.get("file")
    cover_path = track.get("cover")
    caption = format_caption(track, number)

    if not audio_path or not Path(audio_path).exists():
        log.error("Аудиофайл не найден: %s", audio_path)
        return False

    try:
        if cover_path and Path(cover_path).exists():
            with open(cover_path, "rb") as img:
                await bot.send_photo(chat_id=CHANNEL_ID, photo=img)

        with open(audio_path, "rb") as audio:
            await bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=audio,
                title=track.get("title", ""),
                performer=track.get("artist", ""),
                caption=caption,
            )

        log.info("✅ #%d: %s — %s", number, track.get("artist"), track.get("title"))
        return True

    except TelegramError as e:
        log.error("Ошибка Telegram: %s", e)
        return False


# ─── Главная задача ───────────────────────────────────────────────────────────

async def post_batch(bot: Bot):
    queue = expand_queue()

    if not queue:
        log.info("Очередь пуста, нечего постить.")
        return

    available = len(queue)
    batch_min = min(BATCH_MIN, available)
    batch_max = min(BATCH_MAX, available)
    batch_size = random.randint(batch_min, batch_max)

    log.info("Постим %d треков (доступно: %d)...", batch_size, available)

    posted = load_posted()

    for i in range(batch_size):
        queue = load_queue()
        if not queue:
            log.info("Очередь закончилась.")
            break

        url = queue.pop(0)
        save_queue(queue)

        log.info("Скачиваю (%d/%d): %s", i + 1, batch_size, url)
        track = download_track(url)

        if not track:
            log.error("Не удалось скачать, пропускаю: %s", url)
            continue

        number = get_counter()
        success = await post_track(bot, track, number)

        if success:
            increment_counter()
            posted.append({
                "url": url,
                "number": number,
                "title": track.get("title"),
                "posted_at": datetime.now().isoformat(),
            })
            save_posted(posted)

        for f in [track.get("file"), track.get("cover")]:
            if f and Path(f).exists():
                try:
                    Path(f).unlink()
                except Exception:
                    pass

        await asyncio.sleep(3)


# ─── Веб-сервер ───────────────────────────────────────────────────────────────

async def handle(request):
    queue = load_queue()
    posted = load_posted()
    return web.Response(
        text=f"✅ Бот работает!\nТреков в очереди: {len(queue)}\nЗапостено всего: {len(posted)}",
        content_type="text/plain"
    )

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Веб-сервер запущен на порту %d", PORT)


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def main():
    bot = Bot(token=BOT_TOKEN)
    me = await bot.get_me()
    log.info("Бот запущен: @%s", me.username)

    await start_web_server()

    log.info("Разворачиваю плейлисты...")
    queue = expand_queue()
    log.info("Треков в очереди: %d", len(queue))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        post_batch,
        "interval",
        hours=POST_INTERVAL_HOURS,
        args=[bot],
        next_run_time=datetime.now(),
    )
    scheduler.start()
    log.info("Планировщик: каждые %d ч., батч %d-%d треков.", POST_INTERVAL_HOURS, BATCH_MIN, BATCH_MAX)

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("Бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
