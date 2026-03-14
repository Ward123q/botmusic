#!/usr/bin/env python3
"""
Telegram Music Channel Auto-Post Bot
Скачивает треки с YouTube/Spotify и постит по расписанию в Telegram канал.
"""

import os
import asyncio
import logging
import json
from pathlib import Path
from datetime import datetime

import yt_dlp
from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import requests

# ─── Настройки ────────────────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@your_channel")   # или числовой ID: -1001234567890

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# Интервал постинга (в часах)
POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "3"))

# Файл очереди треков
QUEUE_FILE = "queue.json"
POSTED_FILE = "posted.json"

# Папка для временных файлов
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


# ─── Очередь треков ───────────────────────────────────────────────────────────

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


# ─── Скачивание с YouTube ─────────────────────────────────────────────────────

def download_from_youtube(url: str) -> dict | None:
    """
    Скачивает трек с YouTube.
    Возвращает словарь с путём к файлу и метаданными.
    """
    ydl_opts = {
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
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "Unknown Title")
            uploader = info.get("uploader", "Unknown Artist")
            description = info.get("description", "")[:500]
            tags = info.get("tags", [])[:10]
            thumbnail_url = info.get("thumbnail", "")

            # Найти скачанный mp3
            mp3_path = DOWNLOAD_DIR / f"{ydl.prepare_filename(info).rsplit('.', 1)[0]}.mp3"
            # Fallback поиск
            if not mp3_path.exists():
                candidates = list(DOWNLOAD_DIR.glob("*.mp3"))
                mp3_path = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

            if not mp3_path or not mp3_path.exists():
                log.error("MP3 файл не найден после скачивания: %s", url)
                return None

            # Скачать обложку отдельно если не встроена
            cover_path = None
            if thumbnail_url:
                cover_path = DOWNLOAD_DIR / "cover.jpg"
                r = requests.get(thumbnail_url, timeout=10)
                if r.status_code == 200:
                    cover_path.write_bytes(r.content)

            return {
                "file": str(mp3_path),
                "cover": str(cover_path) if cover_path and cover_path.exists() else None,
                "title": title,
                "artist": uploader,
                "description": description,
                "tags": tags,
                "source_url": url,
            }
    except Exception as e:
        log.error("Ошибка скачивания YouTube: %s — %s", url, e)
        return None


# ─── Скачивание через Spotify + yt-dlp ───────────────────────────────────────

def get_spotify_track_info(spotify_url: str) -> dict | None:
    """Получает метаданные трека из Spotify."""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        log.warning("Spotify credentials не заданы, пропускаю.")
        return None
    try:
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
        ))
        track_id = spotify_url.split("/track/")[-1].split("?")[0]
        track = sp.track(track_id)
        artist = ", ".join(a["name"] for a in track["artists"])
        title = track["name"]
        cover_url = track["album"]["images"][0]["url"] if track["album"]["images"] else None
        search_query = f"{artist} - {title} official audio"
        return {
            "title": title,
            "artist": artist,
            "cover_url": cover_url,
            "search_query": search_query,
            "source_url": spotify_url,
        }
    except Exception as e:
        log.error("Ошибка Spotify API: %s", e)
        return None


def download_from_spotify(spotify_url: str) -> dict | None:
    """
    Получает метаданные из Spotify, ищет на YouTube и скачивает.
    """
    info = get_spotify_track_info(spotify_url)
    if not info:
        return None

    # Ищем на YouTube
    ydl_search_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    try:
        with yt_dlp.YoutubeDL(ydl_search_opts) as ydl:
            results = ydl.extract_info(f"ytsearch1:{info['search_query']}", download=False)
            if not results or not results.get("entries"):
                log.error("YouTube: ничего не найдено для: %s", info["search_query"])
                return None
            yt_url = results["entries"][0]["url"]
    except Exception as e:
        log.error("Ошибка поиска YouTube: %s", e)
        return None

    track_data = download_from_youtube(yt_url)
    if not track_data:
        return None

    # Обновляем метаданные из Spotify
    track_data["title"] = info["title"]
    track_data["artist"] = info["artist"]
    track_data["source_url"] = spotify_url

    # Скачиваем обложку из Spotify (лучше качество)
    if info.get("cover_url"):
        cover_path = DOWNLOAD_DIR / "cover_spotify.jpg"
        r = requests.get(info["cover_url"], timeout=10)
        if r.status_code == 200:
            cover_path.write_bytes(r.content)
            track_data["cover"] = str(cover_path)

    return track_data


# ─── Постинг в Telegram ───────────────────────────────────────────────────────

def format_caption(track: dict) -> str:
    """Формирует подпись к треку."""
    title = track.get("title", "Unknown Title")
    artist = track.get("artist", "Unknown Artist")
    description = track.get("description", "")
    tags = track.get("tags", [])

    caption = f"🎵 *{title}*\n👤 {artist}"

    if description:
        # Обрезаем описание до разумного размера
        short_desc = description[:300].strip()
        if short_desc:
            caption += f"\n\n📝 {short_desc}"

    if tags:
        tag_str = " ".join(f"#{t.replace(' ', '_')}" for t in tags[:8])
        caption += f"\n\n{tag_str}"

    return caption


async def post_track(bot: Bot, track: dict):
    """Отправляет трек в Telegram канал."""
    audio_path = track.get("file")
    cover_path = track.get("cover")
    caption = format_caption(track)

    if not audio_path or not Path(audio_path).exists():
        log.error("Аудиофайл не найден: %s", audio_path)
        return False

    try:
        # Отправляем обложку (если есть) как фото
        if cover_path and Path(cover_path).exists():
            with open(cover_path, "rb") as img:
                await bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=img,
                    caption=caption,
                    parse_mode="Markdown",
                )

        # Отправляем аудио
        with open(audio_path, "rb") as audio:
            await bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=audio,
                title=track.get("title", ""),
                performer=track.get("artist", ""),
                caption=caption if not cover_path else None,
                parse_mode="Markdown" if not cover_path else None,
            )

        log.info("✅ Запостил: %s — %s", track.get("artist"), track.get("title"))
        return True

    except TelegramError as e:
        log.error("Ошибка Telegram: %s", e)
        return False


# ─── Главная задача планировщика ──────────────────────────────────────────────

async def post_next_track(bot: Bot):
    """Берёт следующий трек из очереди и постит его."""
    queue = load_queue()
    posted = load_posted()

    if not queue:
        log.info("Очередь пуста, нечего постить.")
        return

    # Берём первый непостенный URL
    url = queue.pop(0)
    save_queue(queue)

    log.info("Обрабатываю: %s", url)

    # Определяем источник
    if "spotify.com" in url:
        track = download_from_spotify(url)
    else:
        track = download_from_youtube(url)

    if not track:
        log.error("Не удалось скачать трек: %s", url)
        return

    success = await post_track(bot, track)

    if success:
        posted.append({"url": url, "posted_at": datetime.now().isoformat()})
        save_posted(posted)

    # Чистим временные файлы
    for f in [track.get("file"), track.get("cover")]:
        if f and Path(f).exists():
            try:
                Path(f).unlink()
            except Exception:
                pass


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def main():
    bot = Bot(token=BOT_TOKEN)

    # Проверка соединения
    me = await bot.get_me()
    log.info("Бот запущен: @%s", me.username)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        post_next_track,
        "interval",
        hours=POST_INTERVAL_HOURS,
        args=[bot],
        next_run_time=datetime.now(),  # первый запуск сразу
    )
    scheduler.start()
    log.info("Планировщик запущен. Интервал: каждые %d ч.", POST_INTERVAL_HOURS)

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("Бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
