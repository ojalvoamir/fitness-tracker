import os
import json
import logging
from datetime import datetime
from threading import Thread

# Telegram Bot
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Flask for health check
from flask import Flask

# Simple in-memory storage
workouts_storage = []

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get bot token
bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')

if not bot_token:
    logger.error("Missing TELEGRAM_BOT_TOKEN")
    exit(1)

# Flask app
app = Flask(__name__)

@app.route('/')
def health_check():
    return f"Bot is running! Logged {len(workouts_storage)} workouts.", 200

@app.route('/workouts')
def show_workouts():
    return {"workouts": workouts_storage}

# Simple parser (no AI)
def simple_parse(text):
    return {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "text": text,
        "timestamp": datetime.now().isoformat()
    }

# Bot handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Simple Workout Bot v1.0\n\n"
        "Send me your workouts and I'll store them!\n"
        "Example: '5 pull ups, 10 pushups'"
    )

async def handle_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    user_id = str(update.effective_user.id)
    
    try:
        workout_data = simple_parse(user_input)
        workout_data['user_id'] = user_id
        workout_data['username'] = update.effective_user.first_name or "Unknown"
        
        workouts_storage.append(workout_data)
        
        await update.message.reply_text(
            f"✅ Workout logged!\n"
            f"📝 '{user_input}'\n"
            f"📊 Total workouts: {len(workouts_storage)}"
        )
        
        logger.info(f"Logged workout for {workout_data['username']}: {user_input}")
        
    except Exception as e:
        await update.message.reply_text("❌ Error logging workout")
        logger.error(f"Error: {e}")

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

def main():
    logger.info("Starting Ultra Simple Workout Bot...")
    
    # Start Flask in background
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start bot
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout))
    
    logger.info("Bot is ready! 🚀")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
