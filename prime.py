import os
import re
import json
import discord
from discord.ext import commands, tasks

# === Configuration Constants ===
TOKEN = os.environ.get('TOKEN')  # Bot token from environment variable
SOURCE_CHANNEL_ID = 1179902312739782758
DEST_CHANNEL_ID = 1179902329126928495
ROLE_ID = 1106515037184593940

# The JSON file where we store persistent data such as the last processed message ID
DATA_FILE = 'bot_data.json'

# Discord's basic file size limit for non-Nitro users is roughly 8 MB.
# Adjust if you expect higher or lower limits (e.g., if you have a Nitro boost).
FILE_SIZE_LIMIT = 8 * 1024 * 1024  # 8 MB in bytes

intents = discord.Intents.default()
intents.message_content = True  # Enable message content
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# === Helper functions ===

def load_data() -> dict:
    """
    Load bot data (e.g., last processed message ID) from a JSON file.
    Returns an empty dict if file doesn't exist or is invalid.
    """
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data: dict):
    """
    Save bot data (e.g., last processed message ID) to a JSON file.
    """
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def is_media_link(url: str) -> bool:
    """
    Check if a link likely points to media (by file extension or by pointing to the Discord CDN).
    """
    media_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mov', '.avi', '.webm', '.webp')
    url_lower = url.lower()
    return any(url_lower.endswith(ext) for ext in media_extensions) or 'cdn.discordapp.com/attachments' in url_lower

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # Start the once-per-day scan task, if not already running.
    if not daily_media_scan.is_running():
        daily_media_scan.start()

# === 1) Original: Move message on reply & mention ===

@bot.event
async def on_message(message: discord.Message):
    # 1) Ignore messages from bots (including yourself).
    if message.author.bot:
        return

    # 2) We only care about messages in SOURCE_CHANNEL_ID.
    if message.channel.id != SOURCE_CHANNEL_ID:
        # Process commands if in another channel (or do nothing otherwise).
        await bot.process_commands(message)
        return

    # 3) Check if the message is a reply and if it mentions the bot.
    if not message.reference:
        await bot.process_commands(message)
        return
    if bot.user not in message.mentions:
        await bot.process_commands(message)
        return

    # 4) Get the original message being replied to.
    try:
        original_message = await message.channel.fetch_message(message.reference.message_id)
    except discord.NotFound:
        # Original message no longer exists
        await bot.process_commands(message)
        return
    except discord.HTTPException:
        # Some other error occurred
        await bot.process_commands(message)
        return

    # 5) Check if the original message has media
    has_attachments = len(original_message.attachments) > 0

    # Find URLs in message content
    urls_in_content = re.findall(r'(https?://\S+)', original_message.content)
    has_media_link = any(is_media_link(url) for url in urls_in_content)

    if not has_attachments and not has_media_link:
        # No media found in the original message
        await bot.process_commands(message)
        return

    # 6) Move the message
    #    (a) Delete from source
    try:
        await original_message.delete()
    except discord.Forbidden:
        print("Bot does not have permission to delete messages.")
        await bot.process_commands(message)
        return
    except discord.HTTPException as e:
        print(f"Error deleting message: {e}")
        await bot.process_commands(message)
        return

    #    (b) Post in destination channel
    dest_channel = bot.get_channel(DEST_CHANNEL_ID)
    if not dest_channel:
        print(f"Could not find the destination channel ID: {DEST_CHANNEL_ID}")
        await bot.process_commands(message)
        return

    # Re-upload attachments
    files = []
    for attachment in original_message.attachments:
        try:
            file = await attachment.to_file()
            files.append(file)
        except discord.HTTPException as e:
            print(f"Error downloading attachment: {e}")

    try:
        await dest_channel.send(content=original_message.content, files=files)
    except discord.Forbidden:
        print("Bot does not have permission to send messages in the destination channel.")
    except discord.HTTPException as e:
        print(f"Error sending message: {e}")

    # 7) Process commands (if any) after handling the logic.
    await bot.process_commands(message)

# === 2) New: Once-per-day scanning task ===

@tasks.loop(hours=24)
async def daily_media_scan():
    """
    Once per day, find new media in SOURCE_CHANNEL_ID and DM it to all members of ROLE_ID.
    """
    print("Starting media send task")
    # Load last checked ID from file (persistent storage)
    data = load_data()
    last_checked_id = data.get("last_checked_message_id")
    print("Loaded last message id: " + str(last_checked_id))

    channel = bot.get_channel(SOURCE_CHANNEL_ID)
    print("Scanning channel: " + str(SOURCE_CHANNEL_ID))
    if not channel:
        print(f"Could not find source channel ID: {SOURCE_CHANNEL_ID}")
        return

    # We will collect all the new media found in messages AFTER last_checked_id
    new_media_messages = []
    
    # Fetch messages in descending order (newest first).
    # We'll invert them later if we want ascending, but it's enough to track the max ID.
    if last_checked_id:
        history = channel.history(limit=None, after=discord.Object(id=last_checked_id))
    else:
        history = channel.history(limit=None)
    
    # The highest message ID we encounter in this scan
    new_last_checked_id = last_checked_id or 0

    async for msg in history:
        # Track the largest ID encountered so we don’t re-check this message again next time
        if msg.id > new_last_checked_id:
            new_last_checked_id = msg.id
        
        # Ignore messages by bots
        if msg.author.bot:
            continue

        # Check for attachments or media links
        has_attachments = any(a for a in msg.attachments)
        urls_in_content = re.findall(r'(https?://\S+)', msg.content)
        has_media_link = any(is_media_link(url) for url in urls_in_content)

        if not has_attachments and not has_media_link:
            continue

        new_media_messages.append(msg)

    # If we found no new media, just update our last_checked_message_id and exit
    if not new_media_messages:
        # Store updated last_checked ID
        data["last_checked_message_id"] = new_last_checked_id
        save_data(data)
        return

    # Grab the role in question. We need the guild from the channel.
    guild = channel.guild
    role = guild.get_role(ROLE_ID)
    print("Found role: " + str(role))
    if not role:
        print(f"Role ID {ROLE_ID} not found in guild {guild.name}.")
        # Still update last_checked_message_id to avoid re-sending
        data["last_checked_message_id"] = new_last_checked_id
        save_data(data)
        return

    # For each member in this role, send them the new media.
    # We'll gather the content from all new_media_messages and DM them once per user.
    # If you prefer to DM each message individually, change logic accordingly.
    for member in role.members:
        print("Sending messages to: " + str(member))
        # Some members might have DMs disabled or block the bot
        # so we'll handle that case gracefully.
        if member.bot:
            continue  # skip bots

        # Build up a list of attachments and links to send.
        # We’ll store them in separate containers for clarity.
        files_to_send = []  
        links_to_send = []

        for msg in new_media_messages:
            # Collect attachments (respect file size limit)
            for att in msg.attachments:
                if att.size <= FILE_SIZE_LIMIT:
                    try:
                        # Convert the attachment to a File object for re-uploading
                        file_obj = await att.to_file()
                        files_to_send.append(file_obj)
                    except discord.HTTPException as e:
                        print(f"Error downloading attachment from {msg.id}: {e}")
                else:
                    print(f"Skipping attachment (too large): {att.url}")

            # Collect media links
            found_links = re.findall(r'(https?://\S+)', msg.content)
            for link in found_links:
                if is_media_link(link):
                    links_to_send.append(link)
                    print("I am attaching the following link: " + link)

        # Now send a DM to the user. We need to be mindful that we cannot send more 
        # than 10 attachments in a single message and also keep under total size limit.
        
        # We'll split large sets of files into chunks of up to 10 each.
        # Then we’ll send a separate message with all the links.
        try:
            dm = await member.create_dm()

            # 1) Send all attachments in chunks of 10
            MAX_ATTACHMENTS_PER_MESSAGE = 10
            for i in range(0, len(files_to_send), MAX_ATTACHMENTS_PER_MESSAGE):
                chunk = files_to_send[i : i + MAX_ATTACHMENTS_PER_MESSAGE]
                await dm.send(files=chunk)
                print("Message sent")

            # 2) Send all links in a single message (if any)
            if links_to_send:
                # For neatness, compile them into a single string
                links_str = "\n".join(links_to_send)
                await dm.send(f"Here are new media links from <#{SOURCE_CHANNEL_ID}>:\n{links_str}")
                print("Message sent")

        except discord.Forbidden:
            print(f"Could not DM user {member} (Forbidden).")
        except discord.HTTPException as e:
            print(f"Error sending DM to user {member}: {e}")

    # Finally, update our "last_checked_message_id" so we don't repeat.
    data["last_checked_message_id"] = new_last_checked_id
    save_data(data)

# === Run the bot ===
if __name__ == "__main__":
    bot.run(TOKEN)
