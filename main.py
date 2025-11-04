# Create the fixed main.py with port binding for Render

print("🔧 FIXED MAIN.PY - COPY THIS TO REPLACE YOUR CURRENT main.py:")
print("=" * 65)

fixed_main_py = '''import os
import json
import re
from datetime import datetime
import asyncio
import logging
from threading import Thread

# Telegram Bot imports
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Supabase imports
from supabase import create_client, Client

# Google Gemini imports
import google.generativeai as genai

# Flask for health check endpoint
from flask import Flask

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_KEY')
google_api_key = os.environ.get('GOOGLE_API_KEY')

if not supabase_url or not supabase_key:
    logger.error("Missing Supabase credentials in environment variables")
    exit(1)

if not google_api_key:
    logger.error("Missing Google API key in environment variables")
    exit(1)

# Configure Gemini
genai.configure(api_key=google_api_key)
gemini_model = genai.GenerativeModel('gemini-2.0-flash-exp')

supabase: Client = create_client(supabase_url, supabase_key)

# Flask app for health check
app = Flask(__name__)

@app.route('/')
def health_check():
    return "🤖 Fitness Tracker Bot is running!", 200

@app.route('/health')
def health():
    return {"status": "healthy", "bot": "running"}, 200

class WorkoutLogger:
    def __init__(self):
        self.supabase = supabase
        self.gemini_model = gemini_model
        logger.info("WorkoutLogger initialized with Supabase and Gemini")

    def _generate_gemini_prompt(self, user_input: str, current_date: str) -&gt; str:
        """
        Constructs the detailed prompt for the Gemini model to parse workout data.
        """
        date_context = f"Today's date is {current_date}. " if current_date else ""
        prompt = f"""
        {date_context}Convert the following workout description into structured JSON.
        Extract the date from the input if specified (e.g., 'today', 'yesterday', or other date inputs in different formats) and include it in the top-level 'date' field in 'YYYY-MM-DD' format. If no date is specified, use today's date.
        Return ONLY the JSON and no additional text or explanations.
        If the same exercise is entered multiple times, log it with the successive set number. Keep the order of exercises same as input and do not group exercises together.
        Use the most common and correct ways of spelling the exercise names to ensure consistency (e.g. if the input is pullup or pl-up, log it as pull-up).

        # --- Special Handling for 'Cindy' Workout ---
        If the input describes a 'Cindy' workout (e.g., 'cindy, 5 rounds'), record the number of rounds completed in the 'rounds' field. For 'Cindy' workouts, the 'reps' field should be null. The 'time_sec' for a Cindy workout should default to 1200 (20 minutes) unless a different time is explicitly mentioned in the input.

        Input: "{user_input}"

        Output format:
        ```json
        {{
          "date": "YYYY-MM-DD",
          "exercises": [
            {{
              "name": "Exercise Name",
              "sets": [
                {{
                  "set_id": 1,
                  "kg": null,
                  "reps": null,
                  "rounds": null,
                  "distance_km": null,
                  "time_sec": null,
                  "size_cm": null
                }}
              ]
            }}
          ]
        }}
        ```
        """
        return prompt

    def parse_workout_with_gemini(self, user_input: str, current_date: str = None) -&gt; dict:
        """
        Calls the Gemini model to parse user input into a structured workout dictionary.
        """
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')

        logger.info(f"🤖 Sending prompt to Gemini for input: '{user_input}'")

        try:
            response = self.gemini_model.generate_content(
                self._generate_gemini_prompt(user_input, current_date)
            )
            response_text = response.text

            # Extract JSON from response
            json_match = re.search(r'```json\\n(.*?)\\n```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
            else:
                json_string = response_text.strip()
                logger.warning("⚠️ Gemini response did not contain a ```json block. Attempting to parse raw response.")

            parsed_data = json.loads(json_string)
            logger.info("✅ Successfully parsed JSON from Gemini response.")
            return parsed_data
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error decoding JSON from Gemini response: {e}")
            logger.error(f"Problematic response text: \\n{response_text}")
            raise ValueError(f"Gemini response did not contain valid JSON: {e}")
        except Exception as e:
            logger.error(f"❌ An error occurred during Gemini API call: {e}")
            raise

    def log_workout_to_supabase(self, workout_data: dict, user_id: str) -&gt; bool:
        """
        Logs the parsed workout data to Supabase database.
        """
        logger.info(f"📝 Logging workout data to Supabase for user {user_id}")
        
        try:
            log_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))

            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name", "Unknown Exercise")
                
                for set_data in exercise.get("sets", []):
                    # Insert into workouts table first
                    workout_result = self.supabase.table('workouts').insert({
                        'user_id': user_id,
                        'date': log_date,
                        'notes': f"Logged via Telegram bot: {exercise_name}"
                    }).execute()
                    
                    workout_id = workout_result.data[0]['id']
                    
                    # Prepare exercise log data
                    exercise_log = {
                        'workout_id': workout_id,
                        'exercise_name': exercise_name,
                        'set_number': set_data.get("set_id", 1),
                        'reps': set_data.get("reps"),
                        'weight_kg': set_data.get("kg"),
                        'distance_km': set_data.get("distance_km"),
                        'time_seconds': set_data.get("time_sec"),
                        'rounds': set_data.get("rounds")
                    }
                    
                    # Insert into exercise_logs table
                    self.supabase.table('exercise_logs').insert(exercise_log).execute()

            logger.info(f"✅ Successfully logged workout for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error logging workout to Supabase: {e}")
            return False

# Initialize workout logger
workout_logger = WorkoutLogger()

# Telegram Bot Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -&gt; None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! 👋\\n\\n"
        "I'm your AI-powered fitness tracking bot! 🤖💪\\n\\n"
        "Send me your workouts in natural language like:\\n"
        "• '5 pull ups, 10 pushups'\\n"
        "• 'ran 3km in 20 minutes'\\n"
        "• 'cindy 5 rounds yesterday'\\n"
        "• 'squats 3x10 at 50kg'\\n\\n"
        "I'll understand and log everything automatically!"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -&gt; None:
    """Send a help message when the command /help is issued."""
    await update.message.reply_text(
        "🤖 AI Workout Logger Help\\n\\n"
        "I use Google Gemini AI to understand your workouts!\\n\\n"
        "Examples of what I understand:\\n"
        "• '5 pull ups, 10 pushups'\\n"
        "• 'ran 3km in 20 min'\\n"
        "• 'squats 3x10 at 50kg, yesterday'\\n"
        "• 'bicep curls 12kg 8 reps 3 sets'\\n"
        "• 'cindy 5 rounds' (CrossFit workout)\\n"
        "• 'deadlifts 100kg 5 reps, bench press 80kg 8 reps'\\n\\n"
        "Just describe your workout naturally - I'll figure it out! 🧠"
    )

async def handle_workout_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -&gt; None:
    """Parse and log workout messages using Gemini AI."""
    user_input = update.message.text
    user_id = str(update.effective_user.id)
    
    logger.info(f"Received workout from {update.effective_user.first_name}: {user_input}")
    
    # Send "thinking" message
    thinking_message = await update.message.reply_text("🤖 Analyzing your workout...")
    
    try:
        # Parse the workout using Gemini
        workout_data = workout_logger.parse_workout_with_gemini(user_input)
        
        if not workout_data.get('exercises') or len(workout_data['exercises']) == 0:
            await thinking_message.edit_text(
                "🤔 I couldn't find any exercises in that message. Try something like:\\n"
                "'5 pull ups, 10 pushups' or 'ran 3km in 20 minutes'"
            )
            return
        
        # Log to Supabase
        success = workout_logger.log_workout_to_supabase(workout_data, user_id)
        
        if success:
            # Create summary of logged exercises
            exercise_summaries = []
            for exercise in workout_data['exercises']:
                for set_data in exercise['sets']:
                    parts = []
                    if set_data.get('reps'):
                        parts.append(f"{set_data['reps']} reps")
                    if set_data.get('kg'):
                        parts.append(f"{set_data['kg']}kg")
                    if set_data.get('rounds'):
                        parts.append(f"{set_data['rounds']} rounds")
                    if set_data.get('distance_km'):
                        parts.append(f"{set_data['distance_km']}km")
                    if set_data.get('time_sec'):
                        minutes = set_data['time_sec'] // 60
                        seconds = set_data['time_sec'] % 60
                        if minutes &gt; 0:
                            parts.append(f"{minutes}m{seconds}s" if seconds &gt; 0 else f"{minutes}m")
                        else:
                            parts.append(f"{seconds}s")
                    
                    summary = f"{exercise['name']}"
                    if parts:
                        summary += f" ({', '.join(parts)})"
                    exercise_summaries.append(summary)
            
            await thinking_message.edit_text(
                f"✅ Workout logged successfully!\\n\\n"
                f"📅 Date: {workout_data['date']}\\n"
                f"💪 Exercises: {', '.join(exercise_summaries)}"
            )
        else:
            await thinking_message.edit_text(
                "❌ Sorry, there was an error saving your workout to the database. Please try again."
            )
            
    except ValueError as e:
        # Specific error for invalid JSON from Gemini
        await thinking_message.edit_text(
            f"❌ I had trouble understanding that workout. Could you try rephrasing it?\\n"
            f"Example: '5 pull ups, 10 pushups'"
        )
        logger.error(f"Error parsing workout: {e}")
    except Exception as e:
        # General error for any other unexpected issues
        await thinking_message.edit_text(
            f"❌ Something went wrong while processing your workout. Please try again."
        )
        logger.error(f"Unexpected error: {e}")

def run_flask():
    """Run Flask app in a separate thread"""
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

def main() -&gt; None:
    """Start the bot and Flask server."""
    # Get bot token from environment
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    if not bot_token:
        logger.error("Missing TELEGRAM_BOT_TOKEN in environment variables")
        return
    
    # Start Flask server in background thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("🌐 Flask health check server started")
    
    # Create the Application
    application = Application.builder().token(bot_token).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT &amp; ~filters.COMMAND, handle_workout_message))

    # Run the bot
    logger.info("🚀 Starting AI-powered Telegram fitness bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()'''

print(fixed_main_py)

print("\n\n📦 UPDATED REQUIREMENTS.TXT:")
print("=" * 35)

updated_requirements = '''python-telegram-bot
supabase
python-dotenv
google-generativeai
flask'''

print(updated_requirements)

print("\n\n🔧 WHAT CHANGED:")
print("=" * 20)

changes = '''
✅ Added Flask web server for health checks
✅ Added routes: / and /health  
✅ Runs Flask in background thread
✅ Bot still works exactly the same
✅ Render will now detect the open port
'''

print(changes)
