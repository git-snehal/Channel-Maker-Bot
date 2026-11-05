# 🎬 Channel Creator Userbot

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/Pyrogram-Asyncio-orange.svg" alt="Framework">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/Telegram-Userbot-informational.svg" alt="Telegram">
</p>

A robust, asynchronous Telegram userbot designed to automate the creation and organization of anime broadcast channels. It maps lists of anime titles grouped by days, generates fixed-format configuration commands per channel, and produces a structured summary report complete with secure invite links.

> **⚠️ Security Note:** This tool **does not** include automated admin-granting features. Adding bots or users as administrators to created channels is a manual security step performed via Telegram's native UI using the generated invite links.

---

## ✨ Key Features

* **Day-Grouped Batch Creation:** Seamlessly parses lists sorted by days and creates dedicated Telegram channels.
* **Smart Flood-Wait Protection:** Detects Telegram rate limits, stops safely, saves state to disk (`state.json`), waits out the penalty, and notifies you when it is safe to resume.
* **Resumable State Management:** Interrupted batches (due to crashes, restarts, or flood-waits) can be resumed right where they left off via `/resume`.
* **Configurable Throttling:** Built-in randomized delays (`MIN_DELAY`, `MAX_DELAY`) between channels and extended cooling breaks (`COOLDOWN_EVERY`, `COOLDOWN_MIN`, `COOLDOWN_MAX`) to protect your account.
* **Strict Access Control:** Restricted exclusively to your account via `OWNER_ID` verification.

---

## 🛠️ Setup Guide

### 1. Get Telegram API Credentials
Head over to [my.telegram.org](https://my.telegram.org), navigate to **API development tools**, and create a new application to obtain your `api_id` and `api_hash`.

### 2. Install Dependencies
Clone the repository and install the required Python libraries:
```bash
git clone [https://github.com/your-username/anime-channel-creator-bot.git](https://github.com/your-username/anime-channel-creator-bot.git)
cd anime-channel-creator-bot
pip install -r requirements.txt
3. Configure Environment VariablesCopy the template configuration file and open .env in your preferred text editor:Bashcp .env.example .env
Fill in your credentials:Code snippetAPI_ID=your_api_id_here
API_HASH=your_api_hash_here
OWNER_ID=
(Leave OWNER_ID blank for the initial run).4. Authenticate Your AccountRun the bot for the first time to generate your session file:Bashpython3 bot.py
Follow the interactive prompts to enter your phone number, login code, and 2FA password (if enabled).Upon successful login, the script will output your numeric Telegram user ID in the terminal.5. Secure Your BotOpen .env again and set your OWNER_ID:Code snippetOWNER_ID=123456789
This guarantees that only you can trigger commands, preventing unauthorized access even if someone messages your account.6. Run in ProductionKeep the script running persistently on a VPS using a terminal multiplexer like tmux, screen, or a systemd service:Bashtmux new -s userbot
python3 bot.py
# Press Ctrl+B then D to detach safely
📱 UsageSend /makechannel in any private chat with yourself (e.g., Saved Messages).The bot will prompt you for channel visibility:PlaintextPrivate or Public? Reply with `private` or `public`.
Send your list structured by days:PlaintextMonday
Black Clover
Reincarnated as a Sword
Cyberpunk

Tuesday
Jujutsu Kaisen
📊 Sample Output ReportOnce processing completes, the bot outputs a comprehensive summary report:PlaintextMonday
Black Clover
/add_channel -1001234567890 F
/add_anime -1001234567890 Black Clover
Invite: [https://t.me/+xxxxxxxx](https://t.me/+xxxxxxxx)

Cyberpunk
/add_channel -1009876543210 F
/add_anime -1009876543210 Cyberpunk
Invite: [https://t.me/+yyyyyyyy](https://t.me/+yyyyyyyy)

Tuesday
Jujutsu Kaisen
/add_channel -1005556667770 F
/add_anime -1005556667770 Jujutsu Kaisen
Invite: [https://t.me/+zzzzzzzz](https://t.me/+zzzzzzzz)
🎛️ Commands ReferenceCommandDescription/makechannelStarts a new batch channel creation workflow./statusDisplays live progress of an active batch (X / Y channels completed)./resumeResumes an interrupted batch from where it left off./cancelDiscards the current in-progress batch state./addadminGrants admin privileges to specified bots or users (e.g., /addadmin @xyz @yzx).🛡️ Flood-Wait & Safety ArchitectureImmediate Halt: If Telegram triggers a rate-limit error, the bot stops instantly rather than looping or risking a ban.State Persistence: Progress is instantly saved to state.json.Internal Timers: The bot calculates the required wait time, sleeps internally, and notifies you when cleared:✅ Flood wait cleared. Send /resume to continue.Manual Gate: The bot never auto-resumes—you maintain full control over when execution continues.💡 Tip: If you encounter persistent rate limits, increase MIN_DELAY and MAX_DELAY values inside your .env configuration rather than forcing throughput.📁 File StructurePlaintext├── bot.py              # Core userbot logic & event handlers
├── .env.example        # Template configuration file
├── requirements.txt    # Python package dependencies
└── state.json          # Auto-generated runtime state (ignored in git)
🔒 Security Best PracticesAlways add a .gitignore to prevent leaking sensitive files:Code snippet.env
*.session
state.json
__pycache__/
Use an established Telegram account with normal activity history rather than a brand-new account to minimize automated flagging risks.
---

<ElicitationsGroup message="Here are a few ways we can continue improving your GitHub profile and repositories:">
  <Elicitation label="Create a `.gitignore` and `requirements.txt` template" query="Create a robust .gitignore file and requirements.txt template for this Python Telegram userbot project."/>
  <Elicitation label="Draft a professional GitHub profile README (profile overview)" query="Help me draft a professional GitHub profile README.md to showcase my programming background, anime projects, and development stack."/>
  <Elicitation label="Refactor configuration loading into a clean Python module" query="Show me how to refactor the configuration loading in bot.py using python-dotenv with clean validation checks."/>
</ElicitationsGroup>

<FollowUp label="Would you like me to generate a clean .gitignore file specifically tailored f
