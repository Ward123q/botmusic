# 🎵 Telegram Music Channel Bot

Бот автоматически скачивает треки с YouTube/Spotify и постит их в Telegram-канал по расписанию.

---

## ⚙️ Установка

### 1. Зависимости системы
```bash
# Ubuntu/Debian
sudo apt install ffmpeg python3 python3-pip

# macOS
brew install ffmpeg
```

### 2. Python зависимости
```bash
pip install -r requirements.txt
```

---

## 🔑 Настройка

### Telegram Bot Token
1. Открой [@BotFather](https://t.me/BotFather) в Telegram
2. Отправь `/newbot`, следуй инструкциям
3. Скопируй токен

### Добавить бота в канал
1. Открой настройки канала → Администраторы
2. Добавь своего бота как администратора с правом **публикации сообщений**

### Spotify (опционально, для лучших метаданных)
1. Зайди на [developer.spotify.com](https://developer.spotify.com/dashboard)
2. Создай приложение → скопируй `Client ID` и `Client Secret`

---

## 🚀 Запуск

### Вариант 1 — переменные окружения
```bash
export BOT_TOKEN="1234567890:AABBcc..."
export CHANNEL_ID="@my_music_channel"
export POST_INTERVAL_HOURS="3"
export SPOTIFY_CLIENT_ID="abc123"       # опционально
export SPOTIFY_CLIENT_SECRET="xyz456"   # опционально

python bot.py
```

### Вариант 2 — .env файл
Создай файл `.env` в папке бота:
```
BOT_TOKEN=1234567890:AABBcc...
CHANNEL_ID=@my_music_channel
POST_INTERVAL_HOURS=3
SPOTIFY_CLIENT_ID=abc123
SPOTIFY_CLIENT_SECRET=xyz456
```
Затем установи `pip install python-dotenv` и добавь в начало `bot.py`:
```python
from dotenv import load_dotenv
load_dotenv()
```

---

## 📋 Управление очередью

```bash
# Добавить треки по одному
python queue_manager.py add https://youtube.com/watch?v=xxx https://youtube.com/watch?v=yyy

# Добавить ссылку Spotify
python queue_manager.py add https://open.spotify.com/track/xxx

# Добавить весь YouTube-плейлист
python queue_manager.py add-playlist https://youtube.com/playlist?list=xxx

# Посмотреть очередь
python queue_manager.py list

# Очистить очередь
python queue_manager.py clear
```

---

## 📁 Структура файлов

```
music_bot/
├── bot.py              # Основной бот
├── queue_manager.py    # Управление очередью
├── requirements.txt    # Зависимости
├── queue.json          # Очередь треков (создаётся автоматически)
├── posted.json         # История постов (создаётся автоматически)
├── bot.log             # Логи (создаётся автоматически)
└── downloads/          # Временные файлы (создаётся автоматически)
```

---

## 🐳 Запуск через Docker (опционально)

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

```bash
docker build -t music-bot .
docker run -d \
  -e BOT_TOKEN="..." \
  -e CHANNEL_ID="@channel" \
  -e POST_INTERVAL_HOURS="3" \
  -v $(pwd)/queue.json:/app/queue.json \
  music-bot
```

---

## ❗ Важно

- Бот качает треки только перед постингом — не хранит библиотеку
- Если очередь пуста — бот ждёт, ничего не ломается
- Логи пишутся в `bot.log`
- ffmpeg **обязателен** для конвертации аудио
