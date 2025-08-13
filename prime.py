import os
import re
import json
import discord
from discord.ext import commands, tasks
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# === Configuration Constants ===
TOKEN = os.environ.get('TOKEN')  # Bot token from environment variable
SOURCE_CHANNEL_ID = 1179902312739782758
DEST_CHANNEL_ID = 1179902329126928495
ROLE_ID = 1106515037184593940

# The JSON file where we store persistent data (e.g. last processed message ID).
DATA_FILE = 'bot_data.json'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Needed to see and DM role members

bot = commands.Bot(command_prefix='!', intents=intents)

# === Helper functions ===

def load_data() -> dict:
    """Load bot data (e.g., last processed message ID) from a JSON file."""
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data: dict):
    """Save bot data to a JSON file."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def is_media_link(url: str) -> bool:
    """
    Check if a link likely points to media (by file extension or by pointing to the Discord CDN).
    This helps us decide which links are "normal" vs. "weird."
    """
    media_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mov', '.avi', '.webm', '.webp')
    url_lower = url.lower()
    return (
        any(url_lower.endswith(ext) for ext in media_extensions)
        or 'cdn.discordapp.com/attachments' in url_lower
    )

def is_image_link(url: str) -> bool:
    """
    Check if a link points to an image that can be embedded.
    Images can be displayed in Discord embeds, videos cannot.
    """
    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
    return any(url.lower().endswith(ext) for ext in image_extensions)

def chunk_list(lst, chunk_size):
    """
    Yields successive chunks of size `chunk_size` from list `lst`.
    E.g., if lst=[1..25] and chunk_size=10, yields chunks of length 10, 10, 5.
    """
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    # Start the once-per-day scan task, if not already running.
    if not daily_media_scan.is_running():
        daily_media_scan.start()

# === 1) Move message on reply & mention ===

@bot.event
async def on_message(message: discord.Message):
    # 1) Ignore messages from bots (including yourself).
    if message.author.bot:
        return

    # 2) We only care about messages in SOURCE_CHANNEL_ID.
    if message.channel.id != SOURCE_CHANNEL_ID:
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
        await bot.process_commands(message)
        return
    except discord.HTTPException:
        await bot.process_commands(message)
        return

    # 5) Separate all links into categories.
    #    - For attachments, convert them to URLs. Then check if it's "normal" or "weird."
    attachments = [att.url for att in original_message.attachments]
    #    - For content links, capture everything that starts with http(s).
    content_links = re.findall(r'(https?://\S+)', original_message.content)

    # Combine them (but we haven't filtered them yet)
    all_links = attachments + content_links

    if not all_links:
        # No links at all, do nothing
        await bot.process_commands(message)
        return

    # Categorize links
    normal_links = [url for url in all_links if is_media_link(url)]
    weird_links = [url for url in all_links if not is_media_link(url)]
    
    # Further separate normal links into images (embeddable) and videos (not embeddable)
    image_links = [url for url in normal_links if is_image_link(url)]
    video_links = [url for url in normal_links if not is_image_link(url)]

    # 6) Move the message
    #   (a) Delete it from source
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

    #   (b) Post in destination channel
    dest_channel = bot.get_channel(DEST_CHANNEL_ID)
    if not dest_channel:
        print(f"Could not find the destination channel ID: {DEST_CHANNEL_ID}")
        await bot.process_commands(message)
        return

    # If we want to preserve the original text, do it here:
    original_text = original_message.content.strip()
    if original_text:
        # Post just the text, with no embeds
        try:
            await dest_channel.send(content=original_text)
        except discord.HTTPException as e:
            print(f"Error sending text content: {e}")

    # 6.1) Send image links in embed form (up to 10 per message)
    for chunk in chunk_list(image_links, 10):
        embeds = []
        for link in chunk:
            embed = discord.Embed()
            embed.set_image(url=link)
            embeds.append(embed)
        try:
            await dest_channel.send(embeds=embeds)
        except discord.HTTPException as e:
            print(f"Error sending embed chunk: {e}")

    # 6.2) Send video links as regular messages (Discord will auto-embed them)
    for link in video_links:
        try:
            await dest_channel.send(link)
        except discord.HTTPException as e:
            print(f"Error sending video link: {e}")

    # 6.3) Send weird links one message at a time (raw link)
    for link in weird_links:
        try:
            await dest_channel.send(link)
        except discord.HTTPException as e:
            print(f"Error sending weird link: {e}")

    await bot.process_commands(message)

# === 2) Once-per-day scanning task ===

@tasks.loop(minutes=10)
async def daily_media_scan():
    """
    Once per day, find new links in SOURCE_CHANNEL_ID and DM them to all members of ROLE_ID.
    - Image links: embed them (up to 10 per message).
    - Video links: send as regular messages.
    - "Weird" links: one message per link, with the raw link only.
    """
    data = load_data()
    last_checked_id = data.get("last_checked_message_id")

    channel = bot.get_channel(SOURCE_CHANNEL_ID)
    if not channel:
        print(f"Could not find source channel ID: {SOURCE_CHANNEL_ID}")
        return

    # Fetch messages after last_checked_id (if present)
    if last_checked_id:
        history = channel.history(limit=None, after=discord.Object(id=last_checked_id))
    else:
        history = channel.history(limit=None)

    new_last_checked_id = last_checked_id or 0
    all_image_links = []
    all_video_links = []
    all_weird_links = []

    async for msg in history:
        if msg.id > new_last_checked_id:
            new_last_checked_id = msg.id

        # Ignore bots
        if msg.author.bot:
            continue

        # Gather attachments & content links
        attachments = [att.url for att in msg.attachments]
        content_links = re.findall(r'(https?://\S+)', msg.content)
        combined_links = attachments + content_links

        # Separate links by type
        normal_links = [url for url in combined_links if is_media_link(url)]
        weird_links = [url for url in combined_links if not is_media_link(url)]
        
        # Further separate normal links into images and videos
        image_links = [url for url in normal_links if is_image_link(url)]
        video_links = [url for url in normal_links if not is_image_link(url)]

        # Add them to our big lists
        all_image_links.extend(image_links)
        all_video_links.extend(video_links)
        all_weird_links.extend(weird_links)

    # If we found no new links, just save and exit
    if not all_image_links and not all_video_links and not all_weird_links:
        data["last_checked_message_id"] = new_last_checked_id
        save_data(data)
        return

    guild = channel.guild
    role = guild.get_role(ROLE_ID)
    if not role:
        print(f"Role ID {ROLE_ID} not found in guild {guild.name}.")
        data["last_checked_message_id"] = new_last_checked_id
        save_data(data)
        return

    # For each member in the role, DM the collected links
    for member in role.members:
        if member.bot:
            continue
        try:
            dm = await member.create_dm()

            # 1) Send image links in embed form, up to 10 per message
            for chunk in chunk_list(all_image_links, 10):
                embeds = []
                for link in chunk:
                    embed = discord.Embed()
                    embed.set_image(url=link)
                    embeds.append(embed)
                await dm.send(embeds=embeds)

            # 2) Send video links as regular messages (Discord will auto-embed them)
            for link in all_video_links:
                await dm.send(link)

            # 3) Then send weird links, one link per message
            for link in all_weird_links:
                await dm.send(link)

        except discord.Forbidden:
            print(f"Could not DM user {member} (Forbidden).")
        except discord.HTTPException as e:
            print(f"Error sending DM to user {member}: {e}")

    # Update last_checked_message_id
    data["last_checked_message_id"] = new_last_checked_id
    save_data(data)

# === Health Check Server for hosting ===
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress health check logs to reduce noise
        if self.path == '/':
            return
        super().log_message(format, *args)

def run_health_server():
    port = int(os.environ.get('PORT', 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"Health check server running on port {port}")
    server.serve_forever()

# Start health check server in a separate thread
health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()

# === Run the bot ===
if __name__ == "__main__":
    
    bot.run(TOKEN)
