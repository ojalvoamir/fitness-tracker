import os
import json
import logging
from datetime import datetime

# Telegram Bot
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Flask for webhooks and health check
from flask import Flask, request, jsonify

# Simple in-memory storage
workouts_storage = []
webhook_logs = []

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
webhook_url = os.environ.get('WEBHOOK_URL')

if not bot_token:
    logger.error("❌ Missing TELEGRAM_BOT_TOKEN environment variable")
    exit(1)

if not webhook_url:
    logger.error("❌ Missing WEBHOOK_URL environment variable")
    exit(1)

# Flask app
app = Flask(__name__)

# Initialize bot application - WEBHOOK MODE ONLY
application = Application.builder().token(bot_token).updater(None).build()

@app.route('/')
def health_check():
    return f"""
    ✅ Fitness Bot is running!
    📊 Logged {len(workouts_storage)} workouts
    🔗 Webhook calls: {len(webhook_logs)}
    🕐 Last webhook: {webhook_logs[-1]['timestamp'] if webhook_logs else 'None'}
    
    🧪 Test endpoints:
    • /workouts - View all workouts
    • /webhook-logs - View webhook call logs
    """, 200

@app.route('/workouts')
def show_workouts():
    return {"workouts": workouts_storage, "count": len(workouts_storage)}

@app.route('/webhook-logs')
def show_webhook_logs():
    return {"webhook_calls": webhook_logs, "count": len(webhook_logs)}

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram updates via webhook - NON-ASYNC VERSION"""
    try:
        # Log the webhook call
        webhook_logs.append({
            "timestamp": datetime.now().isoformat(),
            "method": request.method,
            "headers": dict(request.headers),
            "data": request.get_json() if request.is_json else None
        })
        
        # Get the update from Telegram
        update_data = request.get_json()
        logger.info(f"📨 Received webhook: {update_data}")
        
        if update_data:
            # Create Update object and process it
            update = Update.de_json(update_data, application.bot)
            logger.info(f"🔄 Processing update: {update.update_id}")
            
            # Process the update - SYNCHRONOUS VERSION
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(application.process_update(update))
                logger.info("✅ Update processed successfully")
            finally:
                loop.close()
            
        return "OK", 200
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        webhook_logs.append({
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "traceback": str(e)
        })
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
    logger.info(f"📱 /start command from user {update.effective_user.id}")
    await update.message.reply_text(
        "🤖 Fitness Tracker Bot v3.3 (WORKING!)\n\n"
        "Send me your workouts and I'll log them!\n"
        "Examples:\n"
        "• '5 pull ups, 10 pushups'\n"
        "• 'ran 3km in 20 minutes'\n"
        "• 'squats 3x8 at 60kg'\n\n"
        "✅ Finally working properly!"
    )

async def handle_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    user_id = str(update.effective_user.id)
    username = update.effective_user.first_name or "Unknown"
    
    logger.info(f"💪 Workout message from {username}: '{user_input}'")
    
    try:
        workout_data = simple_parse(user_input)
        workout_data['user_id'] = user_id
        workout_data['username'] = username
        
        workouts_storage.append(workout_data)
        
        response_text = (
            f"✅ Workout logged!\n"
            f"📝 '{user_input}'\n"
            f"📊 Total workouts: {len(workouts_storage)}\n"
            f"👤 User: {username}\n"
            f"🆔 Update ID: {update.update_id}"
        )
        
        await update.message.reply_text(response_text)
        logger.info(f"✅ Response sent to {username}")
        
    except Exception as e:
        logger.error(f"❌ Error processing workout: {e}")
        await update.message.reply_text("❌ Error logging workout. Please try again.")

async def setup_webhook():
    """Set up the webhook with Telegram"""
    try:
        # Initialize the application first!
        await application.initialize()
        logger.info("🔧 Application initialized")
        
        # First delete any existing webhook
        await application.bot.delete_webhook()
        logger.info("🗑️ Deleted any existing webhook")
        
        # Set the new webhook
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
        
        # Verify webhook
        webhook_info = await application.bot.get_webhook_info()
        logger.info(f"📡 Webhook status: {webhook_info.url}")
        logger.info(f"📊 Pending updates: {webhook_info.pending_update_count}")
        
        if webhook_info.last_error_message:
            logger.warning(f"⚠️ Last webhook error: {webhook_info.last_error_message}")
        
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")
        raise

async def main_async():
    """Main async function to set up everything"""
    logger.info("🚀 Starting Fitness Tracker Bot (WORKING VERSION)...")
    logger.info(f"🔗 Webhook URL: {webhook_url}")
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout))
    
    # Set up webhook
    await setup_webhook()
    logger.info("✅ Webhook setup complete!")

def main():
    # Run the async setup
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main_async())
        loop.close()
    except Exception as e:
        logger.error(f"❌ Setup failed: {e}")
        exit(1)
    
    # Start Flask app
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🌐 Starting Flask server on port {port}")
    logger.info("✅ Bot is ready to receive webhooks!")
    
    # Run Flask (this keeps the app alive)
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
