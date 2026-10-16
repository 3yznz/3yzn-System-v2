# Deployment — 3YZN Discord Bot

For a local or hosted process, install Python dependencies, provide environment variables securely, and run `python bot.py`. Use `SYNC_MODE=guild` for development and `SYNC_MODE=global` for production. Keep logs accessible to maintainers but free of tokens and credentials. Configure a restart policy with your host's process manager rather than running multiple bot copies against the same bot token.


## Member events and automation

The bot enables `members` and `message_content` intents in code. In the Discord Developer Portal, enable **Server Members Intent** for automatic roles, welcome messages, and leave messages, and **Message Content Intent** for auto-responses and separator automation. The dashboard is not part of this release's startup path; the bot runs as a Discord gateway client only.

## Release 2 additions

Member-system settings and giveaway data are added using additive SQLite schema migrations. Back up the database before upgrading. Giveaways are free-entry only; active giveaway buttons and deadlines are restored after restart.
