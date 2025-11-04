# fitness-tracker
Natural language fitness tracking bot
# Fitness Tracker Bot

A Telegram bot that logs your workouts to a Supabase database using natural language input.

## Features

- Log workouts via Telegram messages
- Simple natural language parsing
- Automatic database storage
- Support for common exercises (pull-ups, push-ups, squats, etc.)

## Usage

Send messages to your bot like:
- "5 pull ups, 10 pushups"
- "20 squats, 15 burpees"
- "30 sit ups"

The bot will automatically parse and log your workouts.

## Setup

1. Create a Telegram bot with @BotFather
2. Set up a Supabase database
3. Deploy to Render.com or similar platform
4. Add environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`

## Future Features

- LLM-powered natural language parsing
- More exercise types
- Progress tracking and analytics
- Nutrition logging
