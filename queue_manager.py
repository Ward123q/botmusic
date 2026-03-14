#!/usr/bin/env python3
"""
Утилита управления очередью треков.
Использование:
  python queue_manager.py add <url1> <url2> ...
  python queue_manager.py list
  python queue_manager.py clear
  python queue_manager.py add-playlist <youtube_playlist_url>
"""

import sys
import json
from pathlib import Path
import yt_dlp

QUEUE_FILE = "queue.json"


def load_queue():
    if Path(QUEUE_FILE).exists():
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_queue(q):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)


def cmd_add(urls):
    q = load_queue()
    for url in urls:
        url = url.strip()
        if url and url not in q:
            q.append(url)
            print(f"  + Добавлен: {url}")
        else:
            print(f"  ~ Уже в очереди: {url}")
    save_queue(q)
    print(f"\nВсего в очереди: {len(q)}")


def cmd_list():
    q = load_queue()
    if not q:
        print("Очередь пуста.")
        return
    print(f"Треков в очереди: {len(q)}\n")
    for i, url in enumerate(q, 1):
        print(f"  {i:3}. {url}")


def cmd_clear():
    save_queue([])
    print("Очередь очищена.")


def cmd_add_playlist(playlist_url):
    """Добавляет все треки из YouTube-плейлиста в очередь."""
    print(f"Загружаю плейлист: {playlist_url}")
    ydl_opts = {"quiet": True, "extract_flat": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        entries = info.get("entries", [])
        urls = [f"https://youtube.com/watch?v={e['id']}" for e in entries if e.get("id")]

    print(f"Найдено {len(urls)} треков.")
    cmd_add(urls)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0]

    if cmd == "add" and len(args) > 1:
        cmd_add(args[1:])
    elif cmd == "list":
        cmd_list()
    elif cmd == "clear":
        cmd_clear()
    elif cmd == "add-playlist" and len(args) > 1:
        cmd_add_playlist(args[1])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
