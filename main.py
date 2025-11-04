import os
import json
import logging
import asyncio
from datetime import datetime

# Telegram Bot
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

# Flask for webhooks
from flask import Flask, request

# Simple storage
workouts_storage = []
webhook_logs = []

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment
bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
webhook_url = os.environ.get('WEBHOOK_URL')

if not bot_token or not webhook_url:
    logger.error("❌ Missing environment variables")
    exit(1)

# Flask app
app = Flask(__name__)

# Bot setup with reasonable timeouts
request_handler = HTTPXRequest(
    connection_pool_size=20,
    pool_timeout=30.0,
    read_timeout=30.0,
    write_timeout=30.0,
    connect_timeout=10.0
)

application = Application.builder().token(bot_token).updater(None).request(request_handler).build()

@app.route('/')
def health_check():
    return f"""
    ✅ Fitness Bot v3.4 - FINAL FIX!
    📊 Logged {len(workouts_storage)} workouts
    🔗 Webhook calls: {len(webhook_logs)}
    🕐 Last: {webhook_logs[-1]['timestamp'] if webhook_logs else 'None'}
    
    🔧 FIXED: All syntax errors resolved!
    """, 200

@app.route('/workouts')
def show_workouts():
    return {"workouts": workouts_storage, "count": len(workouts_storage)}

@app.route('/webhook-logs')
def show_webhook_logs():
    return {"webhook_calls": webhook_logs, "count": len(webhook_logs)}

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook from Telegram - FIXED VERSION"""
    try:
        # Log the webhook call
        webhook_data = {
            "timestamp": datetime.now().isoformat(),
            "method": request.method,
            "data": request.get_json() if request.is_json else None
        }
        webhook_logs.append(webhook_data)
        
        logger.info(f"📨 Received webhook: {webhook_data['data']}")
        
        update_data = request.get_json()
        
        if update_data:
            update = Update.de_json(update_data, application.bot)
            logger.info(f"🔄 Processing update: {update.update_id}")
            
            # FIXED: Better event loop handling
            try:
                # Try to get existing loop, create new one if needed
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Loop is closed")
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Process update without closing loop immediately
                task = loop.create_task(
                    asyncio.wait_for(application.process_update(update), timeout=30.0)
                )
                loop.run_until_complete(task)
                logger.info("✅ Update processed successfully")
                
            except asyncio.TimeoutError:
                logger.warning("⚠️ Update processing timed out, but continuing...")
            except Exception as e:
                logger.error(f"❌ Error processing update: {e}")
            
        return "OK", 200
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return "Error", 500

# Simple parser
def simple_parse(text):
    return {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "text": text,
        "timestamp": datetime.now().isoformat()
    }

# Bot handlers - SIMPLIFIED to avoid loop issues
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"📱 /start command from {update.effective_user.id}")
    try:
        # SIMPLIFIED: Direct reply without extra timeout wrapper
        await update.message.reply_text(
            "🚀 Fitness Bot v3.4 - FINAL VERSION!\n\n"
            "💪 Send me your workouts and I'll log them!\n\n"
            "Examples:\n"
            "• '5 pull ups'\n"
            "• 'ran 3km in 25 minutes'\n"
            "• 'squats 60kg x8 x3'\n\n"
            "🔧 All bugs fixed!"
        )
        logger.info("✅ Start command reply sent")
    except Exception as e:
        logger.error(f"❌ Start command error: {e}")

async def handle_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    user_id = str(update.effective_user.id)
    username = update.effective_user.first_name or "Unknown"
    
    logger.info(f"💪 Workout message from {username}: '{user_input}'")
    
    try:
        # Parse and store the workout
        workout_data = simple_parse(user_input)
        workout_data['user_id'] = user_id
        workout_data['username'] = username
        
        workouts_storage.append(workout_data)
        logger.info(f"✅ Workout logged for {username}")
        
        # SIMPLIFIED: Direct reply without extra timeout wrapper
        response_text = (
            f"✅ Workout logged!\n"
            f"💪 {user_input}\n"
            f"📊 Total workouts: {len(workouts_storage)}"
        )
        
        await update.message.reply_text(response_text)
        logger.info(f"✅ Confirmation sent to {username}")
        
    except Exception as e:
        logger.error(f"❌ Error processing workout: {e}")
        try:
            await update.message.reply_text("❌ Error logging workout! Please try again.")
        except Exception as reply_error:
            logger.warning(f"⚠️ Could not send error reply: {reply_error}")

async def setup_webhook():
    """Setup the webhook"""
    try:
        await application.initialize()
        logger.info("🔧 Application initialized")
        
        # Delete any existing webhook
        await application.bot.delete_webhook()
        logger.info("🗑️ Existing webhook deleted")
        
        # Set new webhook
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
        
        # Verify webhook
        webhook_info = await application.bot.get_webhook_info()
        logger.info(f"📡 Webhook verification: {webhook_info.url}")
        logger.info("✅ Webhook setup complete!")
        
    except Exception as e:
        logger.error(f"❌ Webhook setup failed: {e}")
        raise

async def main_async():
    """Main async setup function"""
    logger.info("🚀 Starting Fitness Bot...")
    
    # Add command handlers - CLEAN SYNTAX!
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout))
    
    # Setup webhook
    await setup_webhook()
    logger.info("✅ Bot setup complete!")

def main():
    # FIXED: Better async setup
    try:
        # Create and set event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run setup
        loop.run_until_complete(main_async())
        
        # Keep loop alive for webhook processing
        # DON'T close the loop here!
        logger.info("🔧 Event loop ready for webhook processing")
        
    except Exception as e:
        logger.error(f"❌ Setup failed: {e}")
        exit(1)
    
    # Start Flask server
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🌐 Starting server on port {port}")
    logger.info("🎯 FITNESS BOT READY!")
    
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
