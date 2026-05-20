# 📡 Telegram Broadcaster Bot

A beginner-friendly, production-ready Telegram bot for broadcasting messages — text, photos, videos, documents, audio, and stickers — to multiple groups and channels at once.

---

## 📁 Project Structure

```
telegram-bot/
├── bot.py            ← Main bot code (all logic lives here)
├── config.json       ← Target group/channel IDs (auto-managed)
├── requirements.txt  ← Python dependencies
├── .env.example      ← Template for your secrets
├── .env              ← Your actual secrets (create this, never commit!)
├── .gitignore        ← Keeps .env out of Git
├── Procfile          ← For Railway / Heroku deployment
└── README.md         ← This file
```

---

## ✅ Step-by-Step Setup

### Step 1 — Create Your Bot with @BotFather

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Give your bot a **name** (e.g. `My Broadcaster`)
4. Give it a **username** ending in `bot` (e.g. `my_broadcaster_bot`)
5. BotFather replies with your **Bot Token** — copy it!
   ```
   7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
   ```

---

### Step 2 — Clone and Install

```bash
# Clone the project (or download the files)
git clone https://github.com/yourname/telegram-bot.git
cd telegram-bot

# Create a Python virtual environment (recommended)
python -m venv venv

# Activate it
# On Linux/macOS:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

### Step 3 — Configure Environment Variables

```bash
# Copy the template
cp .env.example .env

# Open .env and fill in your values
nano .env   # or use any text editor
```

Your `.env` file should look like this:

```env
BOT_TOKEN=7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
ADMIN_IDS=123456789
```

> **How to get your user ID:**
> 1. Start your bot (next step)
> 2. Send `/myid` to your bot in a private message
> 3. Copy the number and add it to `ADMIN_IDS`

---

### Step 4 — Run the Bot

```bash
python bot.py
```

You should see:
```
2024-01-15 10:30:00 | INFO | __main__ | Starting Telegram Broadcaster Bot...
2024-01-15 10:30:01 | INFO | __main__ | Bot is running. Press Ctrl+C to stop.
```

---

## 📌 How to Get Chat IDs

You need chat IDs to tell the bot where to send messages.

### Method A — Use the `/chatid` command (easiest)

1. Add your bot to the group or channel
2. Send `/chatid` in that chat
3. The bot replies with the chat ID

### Method B — Use @userinfobot or @RawDataBot

Forward any message from the group to **@userinfobot** — it shows the chat ID.

### Method C — Use the Telegram API directly

```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

Send a message in the group, then open that URL in your browser. Look for `"chat":{"id":` in the JSON.

> **Note:** Group and channel IDs are always **negative** (e.g. `-1001234567890`).
> User IDs are always **positive** (e.g. `123456789`).

---

## ➕ Adding the Bot to Groups and Channels

### Adding to a Group

1. Open the group in Telegram
2. Tap the group name → **Add Members**
3. Search for your bot's username
4. Add it

### Adding to a Channel (with Admin Rights)

1. Open the channel
2. Tap the channel name → **Administrators** → **Add Administrator**
3. Search for your bot's username
4. Grant it **Post Messages** permission (minimum required)
5. Tap Save

> The bot must have **Send Messages** permission to post in groups,
> and **Post Messages** permission to post in channels.

---

## ⚙️ Configuring Target Chats

### Option A — Bot Commands (recommended)

```
/addchat -1001234567890      ← Add a group
/addchat -1009876543210      ← Add a channel
/removechat -1001234567890   ← Remove a chat
/listchats                   ← See all configured chats
```

### Option B — Edit config.json manually

```json
{
  "target_chats": [-1001234567890, -1009876543210, 987654321]
}
```

Restart the bot after editing manually.

---

## 📨 Usage Examples

### Send Plain Text

```
/sendtext Hello everyone! 👋
```

### Send Formatted Text (HTML)

```
/sendtext <b>📢 Announcement!</b> We just launched our new product. Visit <a href="https://example.com">our website</a> for details!
```

Supported HTML tags:
| Tag | Effect |
|-----|--------|
| `<b>text</b>` | **Bold** |
| `<i>text</i>` | *Italic* |
| `<u>text</u>` | Underline |
| `<s>text</s>` | ~~Strikethrough~~ |
| `<code>text</code>` | `Monospace` |
| `<a href="url">text</a>` | Hyperlink |

### Send a Photo

**Method 1 — Send photo with caption command:**
Send a photo to the bot chat, and write `/sendphoto Your caption here` as the caption.

**Method 2 — Reply to a photo:**
Reply to any photo in your bot chat with `/sendphoto Optional caption`

### Send a Video

Same as photo — send a video with `/sendvideo` as caption, or reply to a video with `/sendvideo`.

### Send a Document/File

Same pattern — send any file with `/sendfile` as caption, or reply to a file with `/sendfile`.

### Send Audio

Send an audio file with `/sendaudio` as caption, or reply to an existing audio with `/sendaudio`.

### Send a Sticker

Reply to any sticker with `/sendsticker`.

---

## 🔐 Admin-Only Mode

Set `ADMIN_IDS` in your `.env` to restrict all commands to specific users:

```env
ADMIN_IDS=123456789,987654321
```

- Only listed user IDs can use any bot commands
- Other users get: `❌ Access Denied`
- Leave `ADMIN_IDS=` empty to allow anyone (open mode)

---

## 📋 Command Reference

| Command | Description |
|---------|-------------|
| `/start` or `/help` | Show all commands |
| `/myid` | Get your Telegram user ID |
| `/chatid` | Get the current chat's ID |
| `/addchat <id>` | Add a target chat (admin only) |
| `/removechat <id>` | Remove a target chat (admin only) |
| `/listchats` | List all target chats (admin only) |
| `/sendtext <msg>` | Broadcast text (HTML supported) |
| `/sendphoto [caption]` | Broadcast a photo |
| `/sendvideo [caption]` | Broadcast a video |
| `/sendfile [caption]` | Broadcast a document |
| `/sendaudio [caption]` | Broadcast an audio file |
| `/sendsticker` | Broadcast a sticker |

---

## 🚀 Deployment Guide

### Option A — VPS (Ubuntu/Debian)

```bash
# 1. SSH into your VPS
ssh user@your-server-ip

# 2. Install Python (if needed)
sudo apt update && sudo apt install python3 python3-pip python3-venv -y

# 3. Upload your files (or git clone)
git clone https://github.com/yourname/telegram-bot.git
cd telegram-bot

# 4. Create venv and install deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Create your .env
cp .env.example .env
nano .env   # Fill in BOT_TOKEN and ADMIN_IDS

# 6. Run with systemd (keeps bot alive on reboot)
sudo nano /etc/systemd/system/telegrambot.service
```

Paste this into the systemd service file:

```ini
[Unit]
Description=Telegram Broadcaster Bot
After=network.target

[Service]
User=YOUR_LINUX_USERNAME
WorkingDirectory=/home/YOUR_LINUX_USERNAME/telegram-bot
ExecStart=/home/YOUR_LINUX_USERNAME/telegram-bot/venv/bin/python bot.py
Restart=always
RestartSec=5
EnvironmentFile=/home/YOUR_LINUX_USERNAME/telegram-bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable telegrambot
sudo systemctl start telegrambot

# Check logs
sudo journalctl -u telegrambot -f
```

---

### Option B — Railway (Free, easiest)

1. Push your code to GitHub (make sure `.env` is in `.gitignore`)
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Select your repository
4. Go to **Variables** tab → Add:
   - `BOT_TOKEN` = your token
   - `ADMIN_IDS` = your user ID
5. Railway auto-detects the `Procfile` and starts the bot
6. Done! Railway keeps it running 24/7.

---

### Option C — Run Locally (for testing)

```bash
python bot.py
```

Keep the terminal open. Ctrl+C to stop.

---

## 🪵 Logs

- Console output is shown in real time
- Logs are also saved to `bot.log` in the project directory
- Errors are sent to admins via Telegram DM automatically

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---------|-----|
| `BOT_TOKEN is not set` | Create `.env` from `.env.example` and add your token |
| Bot doesn't respond | Make sure `python bot.py` is running |
| Can't post to channel | Give the bot **Post Messages** admin permission in the channel |
| `Forbidden: bot was kicked` | Bot was removed from that chat — use `/removechat` |
| `Chat not found` | Double-check the chat ID (must include the minus sign for groups) |
| Commands don't show in menu | Message @BotFather, send `/setcommands`, and paste the command list |

---

## 🤖 Set Bot Commands in Telegram UI (Optional)

Send this to @BotFather after `/setcommands`:

```
start - Show help
myid - Get your user ID
chatid - Get current chat ID
addchat - Add a target chat
removechat - Remove a target chat
listchats - List all target chats
sendtext - Broadcast text message
sendphoto - Broadcast a photo
sendvideo - Broadcast a video
sendfile - Broadcast a document
sendaudio - Broadcast an audio file
sendsticker - Broadcast a sticker
```

This makes commands appear in the `/` menu inside Telegram.

---

## 📄 License

MIT — free to use, modify, and deploy.
