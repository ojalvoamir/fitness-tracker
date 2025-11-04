import os
import json
import logging
from datetime import datetime

# Telegram Bot with connection pool settings
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

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

# FIXED: Initialize bot with larger connection pool and timeout settings
request_handler = HTTPXRequest(
    connection_pool_size=20,  # Increased from default 8
    pool_timeout=30.0,        # Increased timeout
    read_timeout=30.0,        # Increased read timeout
    write_timeout=30.0        # Increased write timeout
)

application = Application.builder().token(bot_token).updater(None).request(request_handler).build()

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
            
            # Process the update - SYNCHRONOUS VERSION with timeout handling
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # FIXED: Add timeout to prevent hanging
                loop.run_until_complete(
                    asyncio.wait_for(application.process_update(update), timeout=25.0)
                )
                logger.info("✅ Update processed successfully")
            except asyncio.TimeoutError:
                logger.warning("⚠️ Update processing timed out, but continuing...")
            except Exception as e:
                logger.error(f"❌ Error processing update: {e}")
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

# Bot handlers with timeout protection
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"📱 /start command from user {update.effective_user.id}")
    try:
        await asyncio.wait_for(
            update.message.reply_text(
                "🤖 Fitness Tracker Bot v3.4 (TIMEOUT FIXED!)\n\n"
                "Send me your workouts and I'll log them!\n"
                "Examples:\n"
                "• '5 pull ups, 10 pushups'\n"
                "• 'ran 3km in 20 minutes'\n"
                "• 'squats 3x8 at 60kg'\n\n"
                "✅ Now with better timeout handling!"
            ),
            timeout=20.0
        )
    except asyncio.TimeoutError:
        logger.warning("⚠️ Start command reply timed out")
    except Exception as e:
        logger.error(f"❌ Error in start command: {e}")

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
        
        # FIXED: Add timeout to reply
        try:
            await asyncio.wait_for(
                update.message.reply_text(response_text),
                timeout=20.0
            )
            logger.info(f"✅ Response sent to {username}")
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Reply to {username} timed out, but workout was logged")
        
    except Exception as e:
        logger.error(f"❌ Error processing workout: {e}")
        try:
            await asyncio.wait_for(
                update.message.reply_text("❌ Error logging workout. Please try again."),
                timeout=20.0
            )
        except:
            logger.warning("⚠️ Error reply also timed out")

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
    logger.info("🚀 Starting Fitness Tracker Bot (TIMEOUT FIXED)...")
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
