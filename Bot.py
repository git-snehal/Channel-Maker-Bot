"""
Anime Channel Creator Userbot
==============================

Commands (work in your own Saved Messages / any admin PM with yourself):

  /makechannel       Start a new batch. Bot asks Private/Public, Admins, then your anime list.
  /addadmin          Start a batch to add specified admins/bots to a list of channels.
  /setsticker        Reply to a sticker to save it as the default sticker to post after anime info cards.
  /resume            Resume a batch that was interrupted (e.g. by a flood wait).
  /status            Show current progress of an in-progress batch, if any.
  /cancel            Discard the current active batch.

List format example (after setup):

    Monday
    Black Clover
    Reincarnated as a Sword
    Cyberpunk
    Tuesday
    Jujutsu Kaisen

State is persisted to disk (state.json) after every successful channel
creation or admin addition, so /resume works even after a full script restart.
"""

import asyncio
import json
import os
import random
import re
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    EditAdminRequest,
    InviteToChannelRequest,
)
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import ChatAdminRights, DocumentAttributeSticker

# ---------------------------------------------------------------------------
# CONFIG  -- loaded from a .env file (see .env.example) instead of hardcoded
# ---------------------------------------------------------------------------
load_dotenv()

def _int_env(name, default=None):
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return int(val)

API_ID = _int_env("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "anime_channel_bot")

# Only this Telegram user id may issue commands to the bot.
OWNER_ID = _int_env("OWNER_ID")

# Target group for /a automated searches (can be a username like @group or id like -100...)
TARGET_GROUP = os.getenv("TARGET_GROUP")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
STICKER_PATH = os.path.join(os.path.dirname(__file__), "default_sticker.webp")

# Delay (seconds) between each channel creation -- randomized within range.
MIN_DELAY = _int_env("MIN_DELAY", 30)
MAX_DELAY = _int_env("MAX_DELAY", 60)

# After this many actions in a row, take a longer cooldown break.
COOLDOWN_EVERY = _int_env("COOLDOWN_EVERY", 8)
COOLDOWN_MIN = _int_env("COOLDOWN_MIN", 300)    # 5 minutes
COOLDOWN_MAX = _int_env("COOLDOWN_MAX", 600)    # 10 minutes

if API_ID is None or not API_HASH:
    raise SystemExit(
        "Missing API_ID / API_HASH. Copy .env.example to .env and fill them "
        "in before running."
    )

DAY_NAMES = {
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
}

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, STATE_FILE)


def clear_state():
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def load_saved_sticker():
    if os.path.exists(STICKER_PATH):
        return STICKER_PATH
    return None


# ---------------------------------------------------------------------------
# Parsing the anime list with day headers
# ---------------------------------------------------------------------------

def parse_list(text):
    items = []
    current_day = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower() in DAY_NAMES:
            current_day = line.capitalize()
            continue
        items.append({"day": current_day, "name": line})
    return items


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report(items):
    lines = []
    last_day = object()
    for item in items:
        if item["status"] != "done":
            continue
        if item["day"] != last_day:
            if lines:
                lines.append("")
            if item["day"]:
                lines.append(item["day"])
            last_day = item["day"]
        lines.append(item["name"])
        lines.extend(item.get("commands", []))
        if item.get("invite_link"):
            lines.append(f"Invite: {item['invite_link']}")
        if item.get("admin_notes"):
            lines.append(f"Admins: {item['admin_notes']}")
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Core channel creation & admin promotion
# ---------------------------------------------------------------------------

async def create_one_channel(name, is_private):
    result = await client(CreateChannelRequest(
        title=name,
        about="",
        megagroup=False,
    ))
    new_channel = result.chats[0]
    channel_id = new_channel.id
    full_id = int(f"-100{channel_id}")

    invite = await client(ExportChatInviteRequest(peer=new_channel))
    invite_link = invite.link

    commands = [
        f"/add_channel {full_id} F",
        f"/add_anime {full_id} {name}",
    ]

    return full_id, new_channel, commands, invite_link


async def promote_admins_to_channel(channel_entity, admin_usernames):
    promoted = []
    admin_rights = ChatAdminRights(
        change_info=True,
        post_messages=True,
        edit_messages=True,
        delete_messages=True,
        ban_users=True,
        invite_users=True,
        pin_messages=True,
        add_admins=True,
        manage_call=True
    )

    input_channel = await client.get_input_entity(channel_entity)

    for username in admin_usernames:
        try:
            user_entity = await client.get_entity(username)
            try:
                await client(InviteToChannelRequest(
                    channel=input_channel,
                    users=[user_entity]
                ))
            except Exception:
                pass

            input_user = await client.get_input_entity(user_entity)

            await client(EditAdminRequest(
                channel=input_channel,
                user_id=input_user,
                admin_rights=admin_rights,
                rank="Admin"
            ))
            promoted.append(username)
        except Exception as e:
            print(f"Failed to add {username} as admin: {e}")
    return promoted


# ---------------------------------------------------------------------------
# Automated Search & Forward Sequence in the Target Group
# ---------------------------------------------------------------------------

async def execute_anime_automation(target_group_entity, anime_name, channel_entity):
    """
    Sends /a <anime_name> to the target group, polls for the inline response buttons,
    clicks the matching button, waits for the info card to appear, forwards it anonymously
    to the channel, and sends the saved sticker.
    """
    try:
        # 1. Send search command
        sent_msg = await client.send_message(target_group_entity, f"/a {anime_name}")
        
        # 2. Poll for the search bot's inline keyboard response message
        target_msg = None
        for _ in range(12):  # Try for up to 6 seconds
            await asyncio.sleep(0.5)
            messages = await client.get_messages(target_group_entity, limit=5)
            for msg in messages:
                if msg.id > sent_msg.id and msg.reply_markup and hasattr(msg.reply_markup, 'rows'):
                    target_msg = msg
                    break
            if target_msg:
                break
        
        if not target_msg:
            print(f"Could not find inline result message for '{anime_name}'")
            return False

        # 3. Find and click the button matching the anime name
        button_clicked = False
        for row in target_msg.reply_markup.rows:
            for button in row.buttons:
                if anime_name.lower() in button.text.lower():
                    await target_msg.click(text=button.text)
                    button_clicked = True
                    break
            if button_clicked:
                break
        
        # Fallback to the first button if exact name match isn't found
        if not button_clicked and target_msg.reply_markup.rows:
            await target_msg.click(0, 0)
            button_clicked = True

        if not button_clicked:
            print(f"No clickable button found for '{anime_name}'")
            return False

        # 4. Poll for the final info card posted by the search bot
        info_card_msg = None
        for _ in range(16):  # Try for up to 8 seconds
            await asyncio.sleep(0.5)
            recent_msgs = await client.get_messages(target_group_entity, limit=5)
            for msg in recent_msgs:
                if msg.id > target_msg.id and (msg.media or msg.text):
                    info_card_msg = msg
                    break
            if info_card_msg:
                break

        if info_card_msg:
            # Forward the info card to the newly created channel anonymously
            await client.forward_messages(channel_entity, info_card_msg, drop_author=True)
            
            # Send saved sticker if available
            saved_sticker = load_saved_sticker()
            if saved_sticker:
                try:
                    await client.send_file(channel_entity, saved_sticker)
                except Exception as ex:
                    print(f"Failed to send saved sticker: {ex}")
            
            return True
        else:
            print(f"Info card message not found after clicking button for '{anime_name}'")

    except Exception as e:
        print(f"Automation sequence failed for {anime_name}: {e}")
    
    return False


# ---------------------------------------------------------------------------
# Batch processing loop
# ---------------------------------------------------------------------------

async def process_batch(event, state):
    items = state["items"]
    mode = state.get("mode", "makechannel")
    created_since_cooldown = state.get("created_count_since_cooldown", 0)
    admin_usernames = state.get("admin_usernames", [])

    target_group_entity = None
    if mode == "makechannel" and TARGET_GROUP:
        try:
            entity_id = int(TARGET_GROUP) if TARGET_GROUP.lstrip("-").isdigit() else TARGET_GROUP
            target_group_entity = await client.get_entity(entity_id)
        except Exception as e:
            await event.respond(f"❌ Could not resolve target search group '{TARGET_GROUP}' from .env: {e}")
            return

    for item in items:
        if item["status"] == "done":
            continue

        name = item["name"]
        try:
            if mode == "makechannel":
                full_id, channel_entity, commands, invite_link = await create_one_channel(
                    name, state["visibility"] == "private"
                )
                
                promoted = []
                if admin_usernames:
                    promoted = await promote_admins_to_channel(channel_entity, admin_usernames)

                automation_success = False
                if target_group_entity:
                    await event.respond(f"🔍 Automating search & post for: {name}...")
                    automation_success = await execute_anime_automation(target_group_entity, name, channel_entity)

                item["status"] = "done"
                item["channel_id"] = full_id
                item["commands"] = commands
                item["invite_link"] = invite_link
                item["admin_notes"] = ", ".join(promoted) if promoted else "None"
                
                msg = f"✅ Created & Posted: {name}\n" + "\n".join(commands) + f"\nInvite: {invite_link}"
                if promoted:
                    msg += f"\n🛡 Added Admins: {', '.join(promoted)}"
                if automation_success:
                    msg += f"\n📤 Anime info card & sticker successfully posted anonymously!"
                await event.respond(msg)

            elif mode == "addadmin":
                channel_entity = await client.get_entity(name)
                promoted = await promote_admins_to_channel(channel_entity, admin_usernames)

                item["status"] = "done"
                item["admin_notes"] = ", ".join(promoted) if promoted else "None"
                await event.respond(f"✅ Processed channel '{name}': Added admins -> {item['admin_notes']}")

        except FloodWaitError as e:
            wait_seconds = e.seconds
            save_state(state)
            await event.respond(
                f"⚠️ Flood wait hit after processing up to (but not including) "
                f"'{name}'.\nWaiting {wait_seconds}s (~{wait_seconds // 60} min). "
                f"I'll message you when it's clear -- then send /resume."
            )
            await asyncio.sleep(wait_seconds)
            await event.respond("✅ Flood wait cleared. Send /resume to continue.")
            return

        except Exception as e:
            await event.respond(f"❌ Error processing '{name}': {e}")
            continue

        created_since_cooldown += 1
        state["created_count_since_cooldown"] = created_since_cooldown
        save_state(state)

        if created_since_cooldown >= COOLDOWN_EVERY:
            cooldown = random.uniform(COOLDOWN_MIN, COOLDOWN_MAX)
            state["created_count_since_cooldown"] = 0
            save_state(state)
            await event.respond(
                f"⏸ Taking a short cooldown break (~{int(cooldown // 60)} min) "
                f"after {COOLDOWN_EVERY} actions..."
            )
            await asyncio.sleep(cooldown)
        else:
            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    state["active"] = False
    save_state(state)
    report = format_report(state["items"])
    await event.respond("🎉 Batch processing complete!\n\n" + report)
    clear_state()


# ---------------------------------------------------------------------------
# Command handlers & Wizard steps
# ---------------------------------------------------------------------------

def is_owner(event):
    return OWNER_ID is not None and event.sender_id == OWNER_ID


@client.on(events.NewMessage(pattern=r"/setsticker$"))
async def setsticker_cmd(event):
    if not is_owner(event):
        return
    
    reply = await event.get_reply_message()
    if not reply or not reply.media:
        await event.respond("❌ Please reply to a **sticker** with `/setsticker` to save it.")
        return

    is_sticker = False
    if hasattr(reply.media, 'document'):
        for attr in reply.media.document.attributes:
            if isinstance(attr, DocumentAttributeSticker):
                is_sticker = True
                break

    if not is_sticker:
        await event.respond("❌ The message you replied to is not a valid sticker.")
        return

    await reply.download_media(file=STICKER_PATH)
    await event.respond("✅ Default sticker saved successfully! It will now be sent after every anime info card.")


@client.on(events.NewMessage(pattern=r"/makechannel$"))
async def makechannel_cmd(event):
    if not is_owner(event):
        return

    existing = load_state()
    if existing and existing.get("active"):
        await event.respond(
            "There's already an in-progress batch. Send /resume to continue it, "
            "or /cancel to discard it before starting a new one."
        )
        return

    state = {
        "active": True,
        "mode": "makechannel",
        "visibility": None,
        "awaiting_visibility": True,
        "awaiting_admins": False,
        "awaiting_list": False,
        "admin_usernames": [],
        "items": [],
        "created_count_since_cooldown": 0,
    }
    save_state(state)
    await event.respond("Private or Public? Reply with `private` or `public`.")


@client.on(events.NewMessage(pattern=r"^/addadmin\s+(.+)"))
async def addadmin_command(event):
    if not is_owner(event):
        return

    existing = load_state()
    if existing and existing.get("active"):
        await event.respond(
            "There's already an in-progress batch. Send /resume to continue it, "
            "or /cancel to discard it first."
        )
        return

    raw_args = event.pattern_match.group(1).strip()
    admin_usernames = raw_args.split()

    if not admin_usernames:
        await event.respond("❌ Please provide at least one username/bot handle. Example: `/addadmin @xyz @yzx`")
        return

    state = {
        "active": True,
        "mode": "addadmin",
        "awaiting_visibility": False,
        "awaiting_admins": False,
        "awaiting_list": True,
        "admin_usernames": admin_usernames,
        "items": [],
        "created_count_since_cooldown": 0,
    }
    save_state(state)
    await event.respond(
        f"✅ Target admins/bots recorded: {', '.join(admin_usernames)}\n\n"
        "Now send or paste your channel list line-by-line."
    )


@client.on(events.NewMessage(pattern=r"(?i)^(private|public)$"))
async def visibility_reply(event):
    if not is_owner(event):
        return
    state = load_state()
    if not state or not state.get("awaiting_visibility"):
        return

    state["visibility"] = event.raw_text.strip().lower()
    state["awaiting_visibility"] = False
    state["awaiting_admins"] = True
    save_state(state)

    await event.respond(
        "Got it! Now, which bots or usernames should be added as admins to each channel?\n"
        "*(Send them separated by spaces like `@Maiilman_robot @Od3nsLinks_bot`, or type `none`)*"
    )


@client.on(events.NewMessage())
async def wizard_responses(event):
    if not is_owner(event):
        return
    if event.raw_text.strip().startswith("/"):
        return
    if event.raw_text.strip().lower() in ("private", "public"):
        return

    state = load_state()
    if not state or not state.get("active"):
        return

    # Step 2: Capturing Admin Usernames
    if state.get("awaiting_admins"):
        text = event.raw_text.strip()
        if text.lower() == "none":
            state["admin_usernames"] = []
        else:
            state["admin_usernames"] = text.split()

        state["awaiting_admins"] = False
        state["awaiting_list"] = True
        save_state(state)

        await event.respond(
            f"✅ Admins saved: {', '.join(state['admin_usernames']) if state['admin_usernames'] else 'None'}\n\n"
            "Now send or paste your anime list (day headers optional, e.g. 'Monday' on its own line)."
        )
        return

    # Step 3: Capturing the Anime List
    if state.get("awaiting_list"):
        items = parse_list(event.raw_text)
        if not items:
            await event.respond("Didn't find any items in that message. Try again.")
            return

        for it in items:
            it["status"] = "pending"
        state["items"] = items
        state["awaiting_list"] = False
        save_state(state)

        await event.respond(f"Starting batch of {len(items)} item(s) with automation...")
        await process_batch(event, state)


@client.on(events.NewMessage(pattern=r"/resume$"))
async def resume_cmd(event):
    if not is_owner(event):
        return
    state = load_state()
    if not state or not state.get("active"):
        await event.respond("No in-progress batch to resume.")
        return
    if state.get("awaiting_visibility") or state.get("awaiting_admins") or state.get("awaiting_list"):
        await event.respond("Batch isn't ready to resume yet -- finish setup first.")
        return

    remaining = sum(1 for i in state["items"] if i["status"] != "done")
    await event.respond(f"Resuming -- {remaining} item(s) left.")
    await process_batch(event, state)


@client.on(events.NewMessage(pattern=r"/status$"))
async def status_cmd(event):
    if not is_owner(event):
        return
    state = load_state()
    if not state or not state.get("active"):
        await event.respond("No in-progress batch.")
        return
    done = sum(1 for i in state["items"] if i["status"] == "done")
    total = len(state["items"])
    await event.respond(f"Batch in progress: {done}/{total} completed.")


@client.on(events.NewMessage(pattern=r"/cancel$"))
async def cancel_cmd(event):
    if not is_owner(event):
        return
    state = load_state()
    if not state:
        await event.respond("Nothing to cancel.")
        return
    clear_state()
    await event.respond("Batch discarded.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main():
    await client.start()
    me = await client.get_me()
    print(f"Logged in as {me.first_name} (id={me.id})")
    if OWNER_ID is None:
        print(
            "\n*** OWNER_ID is not set. ***\n"
            f"Your numeric user id is: {me.id}\n"
            f"Add OWNER_ID={me.id} to your .env file, then restart.\n"
        )
    print("Bot is running. Send commands from your own account to begin.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
