import os
import re
import discord
from discord.ext import commands

# === Configuration Constants ===
TOKEN = os.environ.get('TOKEN')  # Bot token from environment variable
SOURCE_CHANNEL_ID = 1179902312739782758
DEST_CHANNEL_ID = 1179902329126928495

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# === Helper functions ===

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
    """
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# === Move message on reply & mention ===

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.id != SOURCE_CHANNEL_ID:
        await bot.process_commands(message)
        return

    if not message.reference:
        await bot.process_commands(message)
        return
    if bot.user not in message.mentions:
        await bot.process_commands(message)
        return

    try:
        original_message = await message.channel.fetch_message(message.reference.message_id)
    except (discord.NotFound, discord.HTTPException):
        await bot.process_commands(message)
        return

    attachments = [att.url for att in original_message.attachments]
    content_links = re.findall(r'(https?://\S+)', original_message.content)
    all_links = attachments + content_links

    if not all_links:
        await bot.process_commands(message)
        return

    normal_links = [url for url in all_links if is_media_link(url)]
    weird_links = [url for url in all_links if not is_media_link(url)]
    image_links = [url for url in normal_links if is_image_link(url)]
    video_links = [url for url in normal_links if not is_image_link(url)]

    dest_channel = bot.get_channel(DEST_CHANNEL_ID)
    if not dest_channel:
        print(f"Could not find the destination channel ID: {DEST_CHANNEL_ID}")
        await bot.process_commands(message)
        return

    original_text = original_message.content.strip()

    # Send everything to the destination first; only delete the source if that succeeds.
    try:
        if original_text:
            await dest_channel.send(content=original_text)

        for chunk in chunk_list(image_links, 10):
            embeds = [discord.Embed().set_image(url=link) for link in chunk]
            await dest_channel.send(embeds=embeds)

        for link in video_links:
            await dest_channel.send(link)

        for link in weird_links:
            await dest_channel.send(link)
    except discord.HTTPException as e:
        print(f"Error posting to destination channel, leaving original in place: {e}")
        await bot.process_commands(message)
        return

    try:
        await original_message.delete()
    except discord.Forbidden:
        print("Bot does not have permission to delete messages.")
    except discord.HTTPException as e:
        print(f"Error deleting message: {e}")

    await bot.process_commands(message)

# === Run the bot ===
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("TOKEN environment variable is not set.")
    bot.run(TOKEN)
