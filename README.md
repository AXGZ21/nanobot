# NanoBot Railway Template

Deploy [NanoBot](https://github.com/HKUDS/nanobot) on Railway with a browser-based Web UI for configuration.

## Features
- Browser-based config UI (LLM providers, Telegram/Discord/Slack channels)
- Start/stop/restart the nanobot gateway from the browser
- Live log streaming
- One-click Railway deploy

## Deploy to Railway
[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template)

## Environment Variables
Set these in Railway dashboard:
- `OPENROUTER_API_KEY` - Your OpenRouter API key
- `ANTHROPIC_API_KEY` - Your Anthropic API key  
- `OPENAI_API_KEY` - Your OpenAI API key
- `TELEGRAM_TOKEN` - Telegram bot token (optional)
- `DISCORD_TOKEN` - Discord bot token (optional)
- `WEBUI_PASSWORD` - Password to protect the Web UI (optional)