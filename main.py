# Let's create a SIMPLE, WORKING version based on your original Colab code
# but adapted for Render deployment

simple_main = '''import os
import re
import json
from datetime import datetime
import logging

# Telegram Bot imports
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Supabase imports
from supabase import create_client, Client

# Google Gemini imports
import google.generativeai as genai

# Flask for health check
from flask import Flask
from threading import Thread

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_KEY')
google_api_key = os.environ.get('GOOGLE_API_KEY')
bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')

if not all([supabase_url, supabase_key, google_api_key, bot_token]):
    logger.error("Missing environment variables")
    exit(1)

# Configure Gemini
genai.configure(api_key=google_api_key)
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

# Initialize Supabase
supabase = create_client(supabase_url, supabase_key)

# Flask app for health check
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

class SimpleWorkoutLogger:
    def __init__(self):
        self.supabase = supabase
        self.gemini_model = gemini_model

    def parse_workout(self, user_input: str) -&gt; dict:
        """Simple workout parsing with Gemini"""
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        prompt = f"""
        Today's date is {current_date}. Convert this workout into JSON:
        "{user_input}"
        
        Return ONLY JSON in this format:
        {{
          "date": "YYYY-MM-DD",
          "exercises": [
            {{
              "name": "exercise_name",
              "sets": [
                {{
                  "reps": null,
                  "kg": null,
                  "distance_km": null,
                  "time_sec": null,
                  "rounds": null
                }}
              ]
            }}
          ]
        }}
        """
        
        try:
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text
            
            # Extract JSON
            json_match = re.search(r'\\{.*\\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            else:
                return json.loads(response_text)
                
        except Exception as e:
            logger.error(f"Error parsing workout: {e}")
            raise

    def log_workout(self, workout_data: dict, user_id: str) -&gt; bool:
        """Simple logging to Supabase"""
        try:
            log_date = workout_data.get("date")
            
            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name")
                
                for i, set_data in enumerate(exercise.get("sets", []), 1):
                    # Insert workout
                    workout_result = self.supabase.table('workouts').insert({
                        'user_id': user_id,
                        'date': log_date,
                        'notes': f"Logged via bot: {exercise_name}"
                    }).execute()
                    
                    workout_id = workout_result.data[0]['id']
                    
                    # Insert exercise log
                    self.supabase.table('exercise_logs').insert({
                        'workout_id': workout_id,
                        'exercise_name': exercise_name,
                        'set_number': i,
                        'reps': set_data.get("reps"),
                        'weight_kg': set_data.get("kg"),
                        'distance_km': set_data.get("distance_km"),
                        'time_seconds': set_data.get("time_sec"),
                        'rounds': set_data.get("rounds")
                    }).execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Error logging workout: {e}")
            return False

# Initialize logger
workout_logger = SimpleWorkoutLogger()

# Bot handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me your workouts like '5 pull ups, 10 pushups' and I'll log them!"
    )

async def handle_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    user_id = str(update.effective_user.id)
    
    try:
        # Parse workout
        workout_data = workout_logger.parse_workout(user_input)
        
        # Log to database
        success = workout_logger.log_workout(workout_data, user_id)
        
        if success:
            await update.message.reply_text("✅ Workout logged!")
        else:
            await update.message.reply_text("❌ Error logging workout")
            
    except Exception as e:
        await update.message.reply_text("❌ Couldn't understand that workout")
        logger.error(f"Error: {e}")

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

def main():
    # Start Flask in background
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start bot
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT &amp; ~filters.COMMAND, handle_workout))
    
    logger.info("Starting simple bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
'''

# Simple requirements
simple_requirements = '''python-telegram-bot==20.3
supabase==1.0.3
google-generativeai==0.3.0
flask==2.2.5
'''

# Save files
with open('/tmp/main_simple.py', 'w') as f:
    f.write(simple_main)

with open('/tmp/requirements_simple.txt', 'w') as f:
    f.write(simple_requirements)

print("🔧 SIMPLE SOLUTION CREATED!")
print("=" * 50)
print("\n✅ This uses:")
print("• OLDER, STABLE package versions")
print("• MINIMAL code (no caching, no complex features)")
print("• SAME core functionality as your Colab version")
print("\n📝 Replace your files with:")
print("1. main.py ← main_simple.py")
print("2. requirements.txt ← requirements_simple.txt")
print("\n🚀 This should work without conflicts!")
