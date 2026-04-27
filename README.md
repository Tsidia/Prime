# Prime

A small Discord bot that moves messages between channels on demand.

## What it does

In a designated source channel, reply to any message and ping the bot. Prime
will grab every link and attachment from the original message, repost them in
the destination channel, and delete the original. Links are sorted on the way
out:

- **Images** (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`) are bundled into
  Discord embeds, up to 10 per message.
- **Videos** (`.mp4`, `.mov`, `.webm`, etc.) are sent as plain links so Discord
  auto-embeds them inline.
- **Everything else** (articles, tweets, random URLs) is sent one link per
  message so each one gets its own preview.

If the destination send fails for any reason, the original message is left
alone instead of being deleted into the void.

## Configuration

Three values live at the top of `prime.py`:

| Constant | Meaning |
| --- | --- |
| `TOKEN` | Bot token, read from the `TOKEN` environment variable |
| `SOURCE_CHANNEL_ID` | Channel where Prime listens for reply-and-ping |
| `DEST_CHANNEL_ID` | Channel where the moved content gets reposted |

The bot needs the **Message Content Intent** enabled in the Discord developer
portal, plus permission in both channels to read, send, embed, and delete
messages.

## Running it

```bash
pip install -r requirements.txt
TOKEN='your-bot-token' python prime.py
```

## Hosting

Currently runs on an Oracle Cloud Always Free VM under `systemd`, with a cron
job that polls the repo every five minutes and pulls updates automatically.
