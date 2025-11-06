import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

import google.generativeai as genai
from supabase import create_client, Client
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class FitnessTracker:
    def __init__(self):
        # Initialize Supabase client
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')  # Changed from SUPABASE_ANON_KEY
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")
        
        self.supabase: Client = create_client(supabase_url, supabase_key)
        
        # Initialize Gemini
        google_api_key = os.getenv('GOOGLE_API_KEY')
        if not google_api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is required")
        
        genai.configure(api_key=google_api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        
        logger.info("FitnessTracker initialized successfully")

    def parse_workout_input(self, user_input: str, current_date: str = None) -> Dict:
        """Parse natural language workout input using Gemini"""
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
        
        prompt = f"""
        Today's date is {current_date}. Convert the following workout description into structured JSON.
        Extract the date from the input if specified, otherwise use today's date.
        Return ONLY the JSON and no additional text.
        
        Use consistent exercise names (e.g., "pull-up" not "pullup" or "pull up").
        
        Input: "{user_input}"
        
        Output format:
        {{
          "date": "YYYY-MM-DD",
          "exercises": [
            {{
              "name": "Exercise Name",
              "sets": [
                {{
                  "set_id": 1,
                  "weight_kg": null,
                  "reps": null,
                  "distance_km": null,
                  "time_seconds": null,
                  "notes": null
                }}
              ]
            }}
          ]
        }}
        """
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Clean up response if it has markdown formatting
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            
            parsed_data = json.loads(response_text.strip())
            logger.info(f"Successfully parsed workout: {parsed_data}")
            return parsed_data
            
        except Exception as e:
            logger.error(f"Error parsing workout input: {e}")
            raise

    def log_workout_to_supabase(self, workout_data: Dict, user_id: str, username: str, raw_input: str):
        """Log parsed workout data to Supabase"""
        try:
            workout_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))
            
            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name", "Unknown Exercise")
                
                for set_data in exercise.get("sets", []):
                    # Prepare data for insertion
                    log_entry = {
                        "date": workout_date,
                        "exercise_name": exercise_name,
                        "set_number": set_data.get("set_id", 1),
                        "weight_kg": set_data.get("weight_kg"),
                        "reps": set_data.get("reps"),
                        "distance_km": set_data.get("distance_km"),
                        "time_seconds": set_data.get("time_seconds"),
                        "notes": set_data.get("notes"),
                        "user_id": user_id,
                        "username": username,
                        "raw_input": raw_input
                    }
                    
                    # Insert into Supabase
                    result = self.supabase.table('exercise_logs').insert(log_entry).execute()
                    logger.info(f"Logged exercise: {exercise_name}")
            
            logger.info("Workout logged successfully to Supabase")
            
        except Exception as e:
            logger.error(f"Error logging workout to Supabase: {e}")
            raise

    def get_recent_workouts(self, user_id: str, limit: int = 5) -> List[Dict]:
        """Get recent workouts for a user"""
        try:
            result = self.supabase.table('exercise_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('date', desc=True)\
                .order('created_at', desc=True)\
                .limit(limit)\
                .execute()
            
            return result.data
            
        except Exception as e:
            logger.error(f"Error fetching recent workouts: {e}")
            return []

# Initialize the fitness tracker
fitness_tracker = FitnessTracker()

# Telegram Bot Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    welcome_message = f"""
🏋️ Welcome {user.first_name}!

I'm your personal fitness tracker bot. Just send me your workout descriptions and I'll log them automatically!

Examples:
• "5 pull ups, 10 push ups"
• "ran 3km in 20 minutes"
• "bench press 80kg 3x8"
• "yesterday: squats 100kg 5x5"

Use /recent to see your last 5 workouts.
Use /help for more commands.
    """
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🤖 Available Commands:

/start - Welcome message
/help - Show this help
/recent - Show your last 5 workouts

📝 How to log workouts:
Just type your workout in natural language!

Examples:
• "5 pull ups, 10 push ups"
• "ran 5km in 30 minutes"
• "deadlift 120kg 3 sets 5 reps"
• "yesterday: bench press 80kg 8,8,6 reps"
• "bicep curls 15kg 12 reps 3 sets"

I'll automatically parse and save your workout data!
    """
    await update.message.reply_text(help_text)

async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /recent command"""
    user_id = str(update.effective_user.id)
    
    try:
        recent_workouts = fitness_tracker.get_recent_workouts(user_id, limit=5)
        
        if not recent_workouts:
            await update.message.reply_text("No workouts found. Start logging by sending me your workout!")
            return
        
        message = "🏋️ Your Recent Workouts:\n\n"
        
        current_date = None
        for workout in recent_workouts:
            workout_date = workout['date']
            
            # Add date header if it's a new date
            if workout_date != current_date:
                message += f"📅 {workout_date}\n"
                current_date = workout_date
            
            # Format workout entry
            exercise = workout['exercise_name']
            details = []
            
            if workout['weight_kg']:
                details.append(f"{workout['weight_kg']}kg")
            if workout['reps']:
                details.append(f"{workout['reps']} reps")
            if workout['distance_km']:
                details.append(f"{workout['distance_km']}km")
            if workout['time_seconds']:
                minutes = workout['time_seconds'] // 60
                seconds = workout['time_seconds'] % 60
                if minutes > 0:
                    details.append(f"{minutes}m {seconds}s" if seconds > 0 else f"{minutes}m")
                else:
                    details.append(f"{seconds}s")
            
            detail_str = " • ".join(details) if details else ""
            message += f"  • {exercise}" + (f" ({detail_str})" if detail_str else "") + "\n"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Error in recent_command: {e}")
        await update.message.reply_text("Sorry, I couldn't fetch your recent workouts. Please try again.")

async def handle_workout_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle workout input messages"""
    user = update.effective_user
    user_id = str(user.id)
    username = user.first_name or user.username or "Unknown"
    raw_input = update.message.text
    
    try:
        # Show typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Parse the workout
        parsed_workout = fitness_tracker.parse_workout_input(raw_input)
        
        # Log to Supabase
        fitness_tracker.log_workout_to_supabase(
            parsed_workout, 
            user_id, 
            username, 
            raw_input
        )
        
        # Send confirmation
        exercise_count = len(parsed_workout.get("exercises", []))
        total_sets = sum(len(ex.get("sets", [])) for ex in parsed_workout.get("exercises", []))
        
        confirmation = f"✅ Logged {exercise_count} exercise(s) with {total_sets} set(s)!"
        await update.message.reply_text(confirmation)
        
    except Exception as e:
        logger.error(f"Error handling workout message: {e}")
        await update.message.reply_text(
            "Sorry, I had trouble processing that workout. Could you try rephrasing it?"
        )

def main():
    """Main function to run the bot"""
    # Get bot token
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    # Create application
    application = Application.builder().token(bot_token).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("recent", recent_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout_message))
    
    # Get port from environment (Render provides this)
    port = int(os.getenv('PORT', 8000))
    
    # Check if we have the webhook URL (for production) or run polling (for development)
    render_url = os.getenv('RENDER_EXTERNAL_URL')
    
    if render_url:
        # Production: Use webhooks
        logger.info(f"Starting bot with webhooks on port {port}")
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=bot_token,
            webhook_url=f"https://{render_url}/{bot_token}"
        )
    else:
        # Development: Use polling (but still listen on port for health checks)
        logger.info(f"Starting bot with polling (development mode) on port {port}")
        
        # Start a simple HTTP server for health checks
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading
        
        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Bot is running')
            
            def log_message(self, format, *args):
                pass  # Suppress HTTP logs
        
        # Start health check server in a separate thread
        health_server = HTTPServer(("0.0.0.0", port), HealthHandler)
        health_thread = threading.Thread(target=health_server.serve_forever)
        health_thread.daemon = True
        health_thread.start()
        
        # Run bot with polling
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
