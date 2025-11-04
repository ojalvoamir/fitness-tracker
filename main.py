import os
import json
import logging
from datetime import datetime
from threading import Thread

# Telegram Bot
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Flask for webhooks and health check
from flask import Flask, request

# Simple in-memory storage
workouts_storage = []

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
webhook_url = os.environ.get('WEBHOOK_URL')  # e.g., https://your-app.onrender.com/webhook

if not bot_token:
    logger.error("Missing TELEGRAM_BOT_TOKEN")
    exit(1)

if not webhook_url:
    logger.error("Missing WEBHOOK_URL - set this to https://your-app.onrender.com/webhook")
    exit(1)

# Flask app
app = Flask(__name__)

# Initialize bot application
application = Application.builder().token(bot_token).build()

@app.route('/')
def health_check():
    return f"✅ Bot is running! Logged {len(workouts_storage)} workouts.", 200

@app.route('/workouts')
def show_workouts():
    return {"workouts": workouts_storage, "count": len(workouts_storage)}

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram updates via webhook"""
    try:
        # Get the update from Telegram
        update_data = request.get_json()
        
        if update_data:
            # Create Update object and process it
            update = Update.de_json(update_data, application.bot)
            
            # Process the update asynchronously
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(application.process_update(update))
            loop.close()
            
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "Error", 500

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
        "🤖 Webhook Workout Bot v2.0\n\n"
        "Send me your workouts and I'll store them!\n"
        "Example: '5 pull ups, 10 pushups'\n\n"
        "✅ Now running with webhooks (Render-compatible)!"
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

async def setup_webhook():
    """Set up the webhook with Telegram"""
    try:
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

def main():
    logger.info("🚀 Starting Webhook Workout Bot...")
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout))
    
    # Set up webhook
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_webhook())
    loop.close()
    
    # Start Flask app
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🌐 Starting Flask on port {port}")
    logger.info(f"🔗 Webhook URL: {webhook_url}")
    logger.info("✅ Bot is ready to receive webhooks!")
    
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
