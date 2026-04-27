# Prime

A small Discord bot that moves messages between channels on demand.

## What it does

A reply to any message that mentions the bot will make it move media from source to destination channels. Links are sorted on the way out:

- **Images** (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`) are bundled into
  Discord embeds, up to 10 per message.
- **Videos** (`.mp4`, `.mov`, `.webm`, etc.) are sent as plain links so Discord
  auto-embeds them inline.
- **Everything else** (articles, tweets, random URLs) is sent one link per
  message so each one gets its own preview.

The bot needs the **Message Content Intent** enabled in the Discord developer
portal, plus permission in both channels to read, send, embed, and delete
messages.

## Hosting

Currently runs on an Oracle Cloud Always Free VM under `systemd`, with a cron
job that polls the repo every five minutes and pulls updates automatically.
