import os
import json
import re
from datetime import datetime
import asyncio
import logging

# Telegram Bot imports
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Supabase imports
from supabase import create_client, Client

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    logger.error("Missing Supabase credentials in environment variables")
    exit(1)

supabase: Client = create_client(supabase_url, supabase_key)

class WorkoutLogger:
    def __init__(self):
        self.supabase = supabase
        logger.info("WorkoutLogger initialized with Supabase connection")

    def parse_workout_simple(self, user_input: str) -> dict:
        """
        Simple workout parser - we'll upgrade this to use LLM later
        For now, handles basic patterns like "5 pull ups, 10 pushups"
        """
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Simple regex patterns for common exercises
        exercises = []
        
        # Pattern: number + exercise name
        patterns = [
            r'(\d+)\s+(pull\s*ups?|pullups?)',
            r'(\d+)\s+(push\s*ups?|pushups?)',
            r'(\d+)\s+(squats?)',
            r'(\d+)\s+(burpees?)',
            r'(\d+)\s+(sit\s*ups?|situps?)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, user_input.lower())
            for match in matches:
                reps = int(match[0])
                exercise_name = match[1].replace(' ', '-')
                exercises.append({
                    'name': exercise_name,
                    'reps': reps,
                    'sets': 1
                })
        
        return {
            'date': today,
            'exercises': exercises
        }

    def log_workout(self, workout_data: dict, user_id: str) -> bool:
        """
        Log workout to Supabase database
        """
        try:
            for exercise in workout_data['exercises']:
                # Insert into workouts table
                workout_result = self.supabase.table('workouts').insert({
                    'user_id': user_id,
                    'date': workout_data['date'],
                    'notes': f"Logged via Telegram bot"
                }).execute()
                
                workout_id = workout_result.data[0]['id']
                
                # Insert into exercise_logs table
                self.supabase.table('exercise_logs').insert({
                    'workout_id': workout_id,
                    'exercise_name': exercise['name'],
                    'sets': exercise['sets'],
                    'reps': exercise['reps'],
                    'weight_kg': None,
                    'distance_km': None,
                    'time_seconds': None
                }).execute()
            
            logger.info(f"Successfully logged workout for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error logging workout: {e}")
            return False

# Initialize workout logger
workout_logger = WorkoutLogger()

# Telegram Bot Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! 👋\n\n"
        "I'm your fitness tracking bot! Send me your workouts like:\n"
        "• '5 pull ups, 10 pushups'\n"
        "• '20 squats, 15 burpees'\n\n"
        "I'll log them to your database automatically!"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message when the command /help is issued."""
    await update.message.reply_text(
        "💪 How to use me:\n\n"
        "Just type your workout and I'll log it!\n\n"
        "Examples:\n"
        "• 5 pull ups, 10 pushups\n"
        "• 20 squats\n"
        "• 15 burpees, 30 sit ups\n\n"
        "I'll automatically save everything to your database."
    )

async def handle_workout_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse and log workout messages."""
    user_input = update.message.text
    user_id = str(update.effective_user.id)
    
    logger.info(f"Received workout from {update.effective_user.first_name}: {user_input}")
    
    try:
        # Parse the workout
        workout_data = workout_logger.parse_workout_simple(user_input)
        
        if not workout_data['exercises']:
            await update.message.reply_text(
                "🤔 I couldn't find any exercises in that message. Try something like:\n"
                "'5 pull ups, 10 pushups'"
            )
            return
        
        # Log to database
        success = workout_logger.log_workout(workout_data, user_id)
        
        if success:
            exercise_summary = ", ".join([
                f"{ex['reps']} {ex['name']}" for ex in workout_data['exercises']
            ])
            await update.message.reply_text(
                f"✅ Logged: {exercise_summary}\n"
                f"Date: {workout_data['date']}"
            )
        else:
            await update.message.reply_text(
                "❌ Sorry, there was an error logging your workout. Please try again."
            )
            
    except Exception as e:
        logger.error(f"Error handling workout message: {e}")
        await update.message.reply_text(
            "❌ Something went wrong. Please try again or contact support."
        )

def main() -> None:
    """Start the bot."""
    # Get bot token from environment
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    if not bot_token:
        logger.error("Missing TELEGRAM_BOT_TOKEN in environment variables")
        return
    
    # Create the Application
    application = Application.builder().token(bot_token).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout_message))

    # Run the bot
    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
