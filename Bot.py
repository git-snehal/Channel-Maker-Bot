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
"""

import asyncio
import json
import logging
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
# Logging Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AnimeChannelBot")

# ---------------------------------------------------------------------------
# CONFIG
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
OWNER_ID = _int_env("OWNER_ID")
TARGET_GROUP = os.getenv("TARGET_GROUP")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
STICKER_PATH = os.path.join(os.path.dirname(__file__), "default_sticker.webp")

# Slower delays to completely prevent flood waits
MIN_DELAY = _int_env("MIN_DELAY", 45)
MAX_DELAY = _int_env("MAX_DELAY", 75)

COOLDOWN_EVERY = _int_env("COOLDOWN_EVERY", 5)
COOLDOWN_MIN = _int_env("COOLDOWN_MIN", 300)
COOLDOWN_MAX = _int_env("COOLDOWN_MAX", 600)

if API_ID is None or not API_HASH:
    raise SystemExit("Missing API_ID / API_HASH in .env file.")

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
# Robust List Parser & Command Formatting
# ---------------------------------------------------------------------------

def parse_list(text):
    items = []
    current_day = None
    
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
            
        # Ignore horizontal borders (any line consisting mostly of dashes/box-drawing characters)
        if set(line).issubset({"─", "-", "_", "═", "━"}):
            continue
            
        # Clean up line from formatting markers like emojis, bullet points, and '🔗'
        cleaned = re.sub(r"^[•\-\*➢•\s🔗]+", "", line).strip()
        if not cleaned:
            continue
            
        # Check if line is a day header
        if cleaned.lower() in DAY_NAMES:
            current_day = cleaned.capitalize()
            continue
            
        items.append({"day": current_day, "name": cleaned})
        
    return items


def generate_anime_commands(full_id, name):
    parts = name.strip().split()
    if len(parts) > 1:
        first_field = parts[-1]
    else:
        first_field = name.strip()
    
    return [
        f"/add_channel {full_id} F",
        f"/add_anime {first_field}, {name}, {full_id}",
    ]


def format_report(items, admin_usernames):
    lines = []
    last_day = object()
    
    for item in items:
        if item["status"] != "done":
            continue
        if item["day"] != last_day:
            if lines:
                lines.append("")
            if item["day"]:
                lines.append(f"🔗 {item['day']}")
                lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            last_day = item["day"]
            
        lines.append(f"• {item['name']}")
        for cmd in item.get("commands", []):
            lines.append(cmd)
        if item.get("invite_link"):
            lines.append(f"Invite: {item['invite_link']}")
        lines.append("")
        
    report_text = "\n".join(lines).strip()
    
    # Append batch summary details at the very end
    if admin_usernames:
        report_text += f"\n🛡 Added Admins: {', '.join(admin_usernames)}"
    report_text += "\n📤 Anime info card & sticker successfully posted anonymously!"
    
    return report_text


# ---------------------------------------------------------------------------
# Core channel creation & admin promotion
# ---------------------------------------------------------------------------

async def create_one_channel(name, is_private):
    logger.info(f"Creating channel: '{name}' (Private={is_private})")
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

    commands = generate_anime_commands(full_id, name)
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
        manage_call=True,
        other=True
    )

    input_channel = await client.get_input_entity(channel_entity)

    for username in admin_usernames:
        try:
            logger.info(f"Adding admin {username} to channel...")
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
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Failed to add {username} as admin: {e}")
    return promoted


# ---------------------------------------------------------------------------
# Automated Search & Forward Sequence
# ---------------------------------------------------------------------------

async def execute_anime_automation(target_group_entity, anime_name, channel_entity):
    try:
        logger.info(f"Automation: Sending search query for '{anime_name}'")
        sent_msg = await client.send_message(target_group_entity, f"/a {anime_name}")
        await asyncio.sleep(3)
        
        target_msg = None
        for _ in range(16):
            await asyncio.sleep(0.7)
            messages = await client.get_messages(target_group_entity, limit=5)
            for msg in messages:
                if msg.id > sent_msg.id and msg.reply_markup and hasattr(msg.reply_markup, 'rows'):
                    target_msg = msg
                    break
            if target_msg:
                break
        
        if not target_msg:
            logger.warning(f"Automation: Could not find inline result message for '{anime_name}'")
            return False

        button_clicked = False
        for row in target_msg.reply_markup.rows:
            for button in row.buttons:
                if anime_name.lower() in button.text.lower():
                    await target_msg.click(text=button.text)
                    button_clicked = True
                    break
            if button_clicked:
                break
        
        if not button_clicked and target_msg.reply_markup.rows:
            await target_msg.click(0, 0)
            button_clicked = True

        if not button_clicked:
            logger.warning(f"Automation: No clickable button found for '{anime_name}'")
            return False

        logger.info(f"Automation: Clicked button for '{anime_name}', waiting for info card...")
        await asyncio.sleep(4)

        info_card_msg = None
        for _ in range(20):
            await asyncio.sleep(0.7)
            recent_msgs = await client.get_messages(target_group_entity, limit=5)
            for msg in recent_msgs:
                if msg.id > target_msg.id and (msg.media or msg.text):
                    info_card_msg = msg
                    break
            if info_card_msg:
                break

        if info_card_msg:
            logger.info(f"Automation: Forwarding info card anonymously for '{anime_name}'")
            await client.forward_messages(channel_entity, info_card_msg, drop_author=True)
            await asyncio.sleep(2)
            
            saved_sticker = load_saved_sticker()
            if saved_sticker:
                try:
                    await client.send_file(channel_entity, saved_sticker)
                    logger.info("Automation: Sent default sticker.")
                except Exception as ex:
                    logger.error(f"Failed to send saved sticker: {ex}")
            
            return True
        else:
            logger.warning(f"Automation: Info card message not found for '{anime_name}'")

    except Exception as e:
        logger.error(f"Automation sequence failed for {anime_name}: {e}")
    
    return False


# ---------------------------------------------------------------------------
# Batch processing loop (Silent individual steps, summary at the end)
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
            logger.error(f"Could not resolve target group '{TARGET_GROUP}': {e}")
            await event.respond(f"❌ Could not resolve target search group '{TARGET_GROUP}': {e}")
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

                if target_group_entity:
                    await execute_anime_automation(target_group_entity, name, channel_entity)

                item["status"] = "done"
                item["channel_id"] = full_id
                item["commands"] = commands
                item["invite_link"] = invite_link
                item["admin_notes"] = ", ".join(promoted) if promoted else "None"

            elif mode == "addadmin":
                channel_entity = await client.get_entity(name)
                promoted = await promote_admins_to_channel(channel_entity, admin_usernames)

                item["status"] = "done"
                item["admin_notes"] = ", ".join(promoted) if promoted else "None"

        except FloodWaitError as e:
            wait_seconds = e.seconds
            logger.warning(f"FloodWait hit! Sleeping for {wait_seconds} seconds.")
            save_state(state)
            await event.respond(
                f"⚠️ Telegram Flood Wait hit. Pausing for {wait_seconds}s "
                f"(~{wait_seconds // 60} min). Send /resume afterwards."
            )
            await asyncio.sleep(wait_seconds)
            await event.respond("✅ Flood wait cleared. Send /resume to continue.")
            return

        except Exception as e:
            logger.error(f"Error processing '{name}': {e}")
            continue

        created_since_cooldown += 1
        state["created_count_since_cooldown"] = created_since_cooldown
        save_state(state)

        if created_since_cooldown >= COOLDOWN_EVERY:
            cooldown = random.uniform(COOLDOWN_MIN, COOLDOWN_MAX)
            state["created_count_since_cooldown"] = 0
            save_state(state)
            logger.info(f"Taking a cooldown break for {int(cooldown // 60)} minutes...")
            await event.respond(
                f"⏸ Taking a safe cooldown break (~{int(cooldown // 60)} min) "
                f"to prevent flood limits..."
            )
            await asyncio.sleep(cooldown)
        else:
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            logger.info(f"Waiting {int(delay)}s before next channel...")
            await asyncio.sleep(delay)

    state["active"] = False
    save_state(state)
    
    report = format_report(state["items"], admin_usernames)
    logger.info("Batch processing complete!")
    await event.respond("🎉 **Batch processing complete!**\n\n" + report)
    clear_state()


# ---------------------------------------------------------------------------
# Command Handlers & Wizard
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
    logger.info("Default sticker updated successfully.")
    await event.respond("✅ Default sticker saved successfully!")


@client.on(events.NewMessage(pattern=r"/makechannel$"))
async def makechannel_cmd(event):
    if not is_owner(event):
        return

    existing = load_state()
    if existing and existing.get("active"):
        await event.respond("There's already an active batch. Send /resume or /cancel first.")
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
        await event.respond("There's already an active batch. Send /resume or /cancel first.")
        return

    raw_args = event.pattern_match.group(1).strip()
    admin_usernames = raw_args.split()

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
    await event.respond(f"✅ Admins recorded: {', '.join(admin_usernames)}\n\nNow send your channel list.")


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

    await event.respond("Got it! Which bots/usernames should be added as admins? (Or type `none`)")


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

    if state.get("awaiting_admins"):
        text = event.raw_text.strip()
        if text.lower() == "none":
            state["admin_usernames"] = []
        else:
            state["admin_usernames"] = text.split()

        state["awaiting_admins"] = False
        state["awaiting_list"] = True
        save_state(state)
        await event.respond("✅ Admins saved. Now send or paste your anime list line-by-line.")
        return

    if state.get("awaiting_list"):
        items = parse_list(event.raw_text)
        if not items:
            await event.respond("No items found. Try again.")
            return

        for it in items:
            it["status"] = "pending"
        state["items"] = items
        state["awaiting_list"] = False
        save_state(state)

        await event.respond(f"🚀 Starting batch of {len(items)} anime channel(s) safely with slow pacing. I will send the final summary report when complete.")
        await process_batch(event, state)


@client.on(events.NewMessage(pattern=r"/resume$"))
async def resume_cmd(event):
    if not is_owner(event):
        return
    state = load_state()
    if not state or not state.get("active"):
        await event.respond("No batch to resume.")
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
    await event.respond(f"Progress: {done}/{total} completed.")


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
    logger.info(f"Logged in as {me.first_name} (id={me.id})")
    if OWNER_ID is None:
        logger.warning(f"OWNER_ID is not set. Your user ID is {me.id}")
    logger.info("Bot is running and ready.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
