import os
import json
import logging
from datetime import datetime

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
    logger.error("❌ Missing TELEGRAM_BOT_TOKEN environment variable")
    exit(1)

if not webhook_url:
    logger.error("❌ Missing WEBHOOK_URL environment variable")
    logger.error("Set WEBHOOK_URL to: https://your-app-name.onrender.com/webhook")
    exit(1)

# Flask app
app = Flask(__name__)

# Initialize bot application - WEBHOOK MODE ONLY
application = Application.builder().token(bot_token).updater(None).build()

@app.route('/')
def health_check():
    return f"✅ Fitness Bot is running! Logged {len(workouts_storage)} workouts.", 200

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

# Simple parser (no AI for now)
def simple_parse(text):
    return {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "text": text,
        "timestamp": datetime.now().isoformat()
    }

# Bot handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Fitness Tracker Bot v3.0\n\n"
        "Send me your workouts and I'll log them!\n"
        "Examples:\n"
        "• '5 pull ups, 10 pushups'\n"
        "• 'ran 3km in 20 minutes'\n"
        "• 'squats 3x8 at 60kg'\n\n"
        "✅ Running on webhooks (no polling conflicts!)"
    )

async def handle_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    user_id = str(update.effective_user.id)
    username = update.effective_user.first_name or "Unknown"
    
    try:
        workout_data = simple_parse(user_input)
        workout_data['user_id'] = user_id
        workout_data['username'] = username
        
        workouts_storage.append(workout_data)
        
        await update.message.reply_text(
            f"✅ Workout logged!\n"
            f"📝 '{user_input}'\n"
            f"📊 Total workouts: {len(workouts_storage)}\n"
            f"👤 User: {username}"
        )
        
        logger.info(f"Logged workout for {username}: {user_input}")
        
    except Exception as e:
        await update.message.reply_text("❌ Error logging workout. Please try again.")
        logger.error(f"Error processing workout: {e}")

async def setup_webhook():
    """Set up the webhook with Telegram"""
    try:
        # First delete any existing webhook
        await application.bot.delete_webhook()
        logger.info("🗑️ Deleted any existing webhook")
        
        # Set the new webhook
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
        
        # Verify webhook
        webhook_info = await application.bot.get_webhook_info()
        logger.info(f"📡 Webhook status: {webhook_info.url}")
        
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")
        raise

def main():
    logger.info("🚀 Starting Fitness Tracker Bot...")
    logger.info(f"🔗 Webhook URL: {webhook_url}")
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout))
    
    # Set up webhook
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(setup_webhook())
        loop.close()
        logger.info("✅ Webhook setup complete!")
    except Exception as e:
        logger.error(f"❌ Webhook setup failed: {e}")
        exit(1)
    
    # Start Flask app
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🌐 Starting Flask server on port {port}")
    logger.info("✅ Bot is ready to receive webhooks!")
    
    # Run Flask (this keeps the app alive)
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
