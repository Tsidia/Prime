import os
import re
import discord
from discord.ext import commands

# Load the bot token from the environment variable 'TOKEN'
TOKEN = os.environ.get('TOKEN')

# IDs of the channels you’re working with
SOURCE_CHANNEL_ID = 1179902312739782758
DEST_CHANNEL_ID = 1179902329126928495

# A helper function to check if a link likely points to media.
# This is a simple heuristic approach; adapt as needed.
def is_media_link(url: str) -> bool:
    media_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mov', '.avi', '.webm', '.webp')
    url_lower = url.lower()
    # Check for common media extensions or Discord CDN
    return any(url_lower.endswith(ext) for ext in media_extensions) or 'cdn.discordapp.com/attachments' in url_lower

intents = discord.Intents.default()
intents.message_content = True  # Make sure to enable this in your bot's settings on the Dev Portal

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    # 1) Ignore messages from bots (including yourself).
    if message.author.bot:
        return

    # 2) We only care about messages in SOURCE_CHANNEL_ID.
    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    # 3) Check if the message is a reply (message.reference is not None) 
    #    and if it mentions the bot.
    if not message.reference:
        return
    if bot.user not in message.mentions:
        return

    # 4) Get the original message being replied to.
    try:
        original_message = await message.channel.fetch_message(message.reference.message_id)
    except discord.NotFound:
        # Original message no longer exists
        return
    except discord.HTTPException:
        # Some other error occurred fetching the message
        return

    # 5) Check if the original message has:
    #    - At least one attachment
    #    - OR content that includes a link that likely points to media
    has_attachments = len(original_message.attachments) > 0
    # Simple check for URLs; you can use a more robust approach or library if needed
    urls_in_content = re.findall(r'(https?://\S+)', original_message.content)
    has_media_link = any(is_media_link(url) for url in urls_in_content)

    if not has_attachments and not has_media_link:
        # No media found in the original message, so do nothing
        return

    # 6) If we got here, original_message has the media we want to move.

    #   (a) Delete the original message
    try:
        await original_message.delete()
    except discord.Forbidden:
        print("Bot does not have permissions to delete messages.")
        return
    except discord.HTTPException as e:
        print(f"Error deleting message: {e}")
        return

    #   (b) Post the identical content (and attachments) to DEST_CHANNEL_ID
    dest_channel = bot.get_channel(DEST_CHANNEL_ID)
    if not dest_channel:
        print(f"Could not find the destination channel: {DEST_CHANNEL_ID}")
        return

    # Re-upload any attachments to the destination channel
    files = []
    for attachment in original_message.attachments:
        try:
            file = await attachment.to_file()
            files.append(file)
        except discord.HTTPException as e:
            print(f"Error downloading attachment: {e}")

    # Send the message content and the attached files
    try:
        await dest_channel.send(content=original_message.content, files=files)
    except discord.Forbidden:
        print("Bot does not have permissions to send messages in the destination channel.")
    except discord.HTTPException as e:
        print(f"Error sending message: {e}")

    # 7) Always process commands last if you have any commands that begin with your prefix
    await bot.process_commands(message)

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)
