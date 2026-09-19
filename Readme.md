# Anime Channel Creator Userbot

Creates one Telegram channel per anime name you give it, generates the two
fixed-format commands per channel, and produces a day-grouped report with
invite links. Handles Telegram flood-waits safely (stop, notify, wait,
notify again) and supports resuming an interrupted batch.

**Does not** include any admin-granting functionality. Adding your anime
bots (or anyone else) as admin to created channels is a manual step you do
yourself via Telegram's UI, using the invite link the bot gives you.

## Setup

1. Get API credentials from https://my.telegram.org ("API development
   tools" → create an app) — you'll get an `api_id` and `api_hash`.

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example config and fill it in:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and set `API_ID` and `API_HASH`. Leave `OWNER_ID` blank for now.

4. First run — this logs your account in and creates a session file:
   ```bash
   python3 bot.py
   ```
   It will ask for your phone number, then the login code sent to your
   Telegram app, then your 2FA password if you have one. On success it
   prints your numeric user id and reminds you to set `OWNER_ID`.

5. Stop the script (Ctrl+C), open `.env`, set:
   ```
   OWNER_ID=<the number it printed>
   ```
   This restricts every command to only work when sent from your own
   account — nobody else can trigger channel creation even if they somehow
   message the same account.

6. Run it again:
   ```bash
   python3 bot.py
   ```
   Leave it running (use `tmux`, `screen`, or a systemd service on your VPS
   so it survives disconnecting your SSH session).

All the delay/cooldown numbers (`MIN_DELAY`, `MAX_DELAY`, `COOLDOWN_EVERY`,
`COOLDOWN_MIN`, `COOLDOWN_MAX`) also live in `.env` now if you want to tune
them without touching `bot.py` at all.

## Usage

In any chat with yourself (e.g. Saved Messages), send:

```
/makechannel
```

Bot asks:

```
Private or Public? Reply with `private` or `public`.
```

Reply with one word, then send your list, e.g.:

```
Monday
Black Clover
Reincarnated as a Sword
Cyberpunk
Tuesday
Jujutsu Kaisen
```

The bot creates channels one at a time (randomized 30–60s delay between
each, with a longer 5–10 min cooldown every 8 channels), posting a
confirmation with the two commands and invite link as each one finishes.

When everything's done, it sends the full report:

```
Monday
Black Clover
/add_channel -1001234567890 F
/add_anime -1001234567890 Black Clover
Invite: https://t.me/+xxxxxxxx

Cyberpunk
/add_channel -1009876543210 F
/add_anime -1009876543210 Cyberpunk
Invite: https://t.me/+yyyyyyyy

Tuesday
Jujutsu Kaisen
/add_channel -1005556667770 F
/add_anime -1005556667770 Jujutsu Kaisen
Invite: https://t.me/+zzzzzzzz
```

### Other commands

- `/status` — shows progress of an in-progress batch (X/Y channels done).
- `/resume` — continues an interrupted batch (e.g. after a flood wait, a
  script crash, or a VPS restart) from exactly where it left off.
- `/cancel` — discards the current in-progress batch.
- `/addadmin` — to provide addmin rights to bots or people /addadmin @xyz @yzx.


### Flood-wait handling

If Telegram rate-limits a request:

1. The bot stops immediately (no auto-retry loop).
2. It saves progress to `state.json` on disk.
3. It messages you with how long the wait is.
4. It waits out the flood-wait internally, then messages you again:
   `✅ Flood wait cleared. Send /resume to continue.`
5. It does **not** auto-resume — you decide when to send `/resume`.

There is no daily cap on channel creation — the flood-wait handling above
is the only throttle, plus the built-in per-channel delay and periodic
cooldown.

### Public channels

Channels are created private by default. Making one public requires
setting a valid, available `@username` on it — since anime titles usually
aren't valid/available usernames as typed, that's left as a manual
per-channel step afterward (Telegram Desktop/mobile → channel settings →
"Channel type" → Public → set a username) rather than something the bot
guesses at automatically.

### Adding your anime bots to created channels

Use the invite link from the report to add your anime bot as a member,
then grant it admin rights yourself via Telegram's normal channel-settings
UI. This is intentionally a manual step, not automated by this script.

## Files

- `bot.py` — the userbot itself.
- `.env.example` — template config; copy to `.env` and fill in your values.
- `state.json` — created automatically while a batch is in progress;
  deleted automatically once a batch finishes. Safe to inspect if you want
  to see raw progress, but don't hand-edit it while the bot is running.
- `requirements.txt` — Python dependencies.

## Safety notes

- Keep `.env`, the `.session` file, and `state.json` (contains channel IDs)
  private — don't commit them to a public repo. If this is a git repo, add
  a `.gitignore` with `.env`, `*.session`, and `state.json` in it.
- The account used should ideally have some existing normal activity
  history rather than being brand new, since channel creation is a
  monitored action on Telegram.
- If you get persistent flood-waits even after waiting them out, that's a
  signal to slow down further (increase `MIN_DELAY`/`MAX_DELAY` in
  `bot.py`) rather than push through.
