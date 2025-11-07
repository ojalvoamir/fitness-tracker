import os
import re
import json
import sys
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

# Configure logging to ensure output appears in Render logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
GEMINI_MODEL_NAME = 'gemini-2.0-flash-exp'

# Initialize APIs
def initialize_apis():
    """Initialize Gemini and Supabase clients"""
    try:
        # Force output to appear in logs
        logger.info("🔑 Starting API initialization...")
        logger.info(f"   - GOOGLE_API_KEY: {'✅' if os.getenv('GOOGLE_API_KEY') else '❌'}")
        logger.info(f"   - SUPABASE_URL: {'✅' if os.getenv('SUPABASE_URL') else '❌'}")
        logger.info(f"   - SUPABASE_ANON_KEY: {'✅' if os.getenv('SUPABASE_ANON_KEY') else '❌'}")
        
        # Gemini API
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            logger.error("❌ GOOGLE_API_KEY not found")
            raise ValueError("GOOGLE_API_KEY not found")
        
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        logger.info("✅ Gemini initialized successfully")
        
        # Supabase
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_ANON_KEY')
        
        if not supabase_url or not supabase_key:
            logger.error("❌ Supabase credentials missing")
            raise ValueError("Supabase credentials missing")
            
        supabase = create_client(supabase_url, supabase_key)
        logger.info("✅ Supabase initialized successfully")
        
        return gemini_model, supabase
    except Exception as e:
        logger.error(f"❌ Error initializing APIs: {e}")
        return None, None

# Global variables
logger.info("🚀 Initializing APIs...")
gemini_model, supabase = initialize_apis()

class WorkoutLogger:
    """Handle workout parsing and logging"""
    
    def __init__(self, gemini_model, supabase_client):
        self.gemini_model = gemini_model
        self.supabase = supabase_client
        logger.info("💪 WorkoutLogger initialized")
    
    def generate_gemini_prompt(self, user_input: str, current_date: str, user_id: str = "default_user") -> str:
        """Generate prompt for Gemini"""
        return f"""
Today's date is {current_date}.
Convert the following workout description into structured JSON.
Extract the date from the input if specified and include it in 'YYYY-MM-DD' format. If no date is specified, use today's date.
Return ONLY the JSON and no additional text.
Use consistent exercise names (e.g., "pull-up" not "pullup").

Input: "{user_input}"

Output format:
{{
  "date": "YYYY-MM-DD",
  "user_id": "{user_id}",
  "username": "User",
  "raw_input": "{user_input}",
  "exercises": [
    {{
      "name": "Exercise Name",
      "sets": [
        {{
          "set_number": 1,
          "metrics": [
            {{
              "type": "reps",
              "value": 10,
              "unit": "reps"
            }},
            {{
              "type": "weight_kg", 
              "value": 20.5,
              "unit": "kg"
            }}
          ]
        }}
      ]
    }}
  ]
}}
"""
    
    def parse_input(self, user_input: str, current_date: str = None, user_id: str = "default_user") -> dict:
        """Parse user input using Gemini"""
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            logger.info(f"🤖 Parsing input: '{user_input}'")
            prompt = self.generate_gemini_prompt(user_input, current_date, user_id)
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text
            logger.info(f"🤖 Gemini response: {response_text[:200]}...")
            
            # Extract JSON from response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
                logger.info("✅ Found JSON in code block")
            else:
                json_string = response_text.strip()
                logger.info("⚠️ No JSON code block found, using raw response")
            
            parsed_data = json.loads(json_string)
            logger.info("✅ Successfully parsed JSON from Gemini")
            return parsed_data
        except Exception as e:
            logger.error(f"❌ Error parsing input: {e}")
            logger.error(f"❌ Response text was: {response_text if 'response_text' in locals() else 'No response'}")
            raise
    
    def get_or_create_exercise_type(self, exercise_name: str) -> int:
        """Get existing exercise type ID or create new one"""
        try:
            logger.info(f"🔍 Looking for exercise type: {exercise_name}")
            # First, try to find existing exercise type
            result = self.supabase.table('exercise_types')\
                .select('id')\
                .eq('canonical_name', exercise_name)\
                .execute()
            
            if result.data:
                exercise_type_id = result.data[0]['id']
                logger.info(f"✅ Found existing exercise type ID: {exercise_type_id}")
                return exercise_type_id
            
            # If not found, create new exercise type
            logger.info(f"➕ Creating new exercise type: {exercise_name}")
            result = self.supabase.table('exercise_types')\
                .insert({'canonical_name': exercise_name})\
                .execute()
            
            exercise_type_id = result.data[0]['id']
            logger.info(f"✅ Created new exercise type ID: {exercise_type_id}")
            return exercise_type_id
        except Exception as e:
            logger.error(f"❌ Error getting/creating exercise type: {e}")
            raise
    
    def log_workout(self, workout_data: dict) -> bool:
        """Log workout data to Supabase"""
        try:
            logger.info(f"📝 Logging workout data: {workout_data}")
            
            log_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))
            user_id = workout_data.get("user_id", "default_user")
            username = workout_data.get("username", "User")
            raw_input = workout_data.get("raw_input", "")
            
            # Process each exercise
            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name", "Unknown Exercise")
                logger.info(f"🏋️ Processing exercise: {exercise_name}")
                
                # Get or create exercise type
                exercise_type_id = self.get_or_create_exercise_type(exercise_name)
                
                # Process each set
                for set_data in exercise.get("sets", []):
                    set_number = set_data.get("set_number", 1)
                    logger.info(f"📊 Processing set {set_number}")
                    
                    # Create exercise log entry
                    log_result = self.supabase.table('exercise_logs')\
                        .insert({
                            'date': log_date,
                            'exercise_type_id': exercise_type_id,
                            'set_number': set_number,
                            'user_id': user_id,
                            'username': username,
                            'raw_input': raw_input
                        })\
                        .execute()
                    
                    exercise_log_id = log_result.data[0]['id']
                    logger.info(f"✅ Created exercise log ID: {exercise_log_id}")
                    
                    # Add metrics for this set
                    metrics = set_data.get("metrics", [])
                    for metric in metrics:
                        if metric.get("value") is not None:  # Only log non-null values
                            logger.info(f"📈 Adding metric: {metric}")
                            self.supabase.table('exercise_metrics')\
                                .insert({
                                    'exercise_log_id': exercise_log_id,
                                    'metric_type': metric.get("type"),
                                    'value': metric.get("value"),
                                    'unit': metric.get("unit")
                                })\
                                .execute()
            
            logger.info("✅ Workout logged successfully!")
            return True
        except Exception as e:
            logger.error(f"❌ Error logging workout: {e}")
            logger.error(f"❌ Workout data was: {workout_data}")
            return False
    
    def delete_latest_exercise(self, user_id: str = "default_user") -> bool:
        """Delete the most recent exercise entry for this user"""
        try:
            # Get the latest exercise log for this user
            result = self.supabase.table('exercise_logs')\
                .select('id')\
                .eq('user_id', user_id)\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if result.data:
                exercise_log_id = result.data[0]['id']
                # Delete exercise log (cascade should handle exercise_metrics)
                self.supabase.table('exercise_logs').delete().eq('id', exercise_log_id).execute()
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting exercise: {e}")
            return False
    
    def get_recent_workouts(self, days: int = 7, user_id: str = "default_user") -> list:
        """Get recent workout data"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Simple query that should work
            result = self.supabase.table('exercise_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', cutoff_date)\
                .order('created_at', desc=True)\
                .limit(20)\
                .execute()
            
            return result.data
        except Exception as e:
            logger.error(f"Error getting workouts: {e}")
            return []

# Initialize workout logger
workout_logger = WorkoutLogger(gemini_model, supabase) if gemini_model and supabase else None
if workout_logger:
    logger.info("✅ WorkoutLogger created successfully")
else:
    logger.error("❌ WorkoutLogger could not be created")

@app.route('/')
def index():
    """Main page with input form and recent workouts"""
    logger.info("📱 Index page requested")
    recent_workouts = []
    if workout_logger:
        recent_workouts = workout_logger.get_recent_workouts()
    
    return render_template('index.html', recent_workouts=recent_workouts)

@app.route('/log', methods=['POST'])
def log_workout():
    """Handle workout logging"""
    logger.info("📥 Log workout endpoint called")
    
    if not workout_logger:
        logger.error("❌ WorkoutLogger not initialized")
        return jsonify({'success': False, 'error': 'System not initialized'})
    
    try:
        user_input = request.json.get('input', '').strip()
        if not user_input:
            logger.error("❌ No input provided")
            return jsonify({'success': False, 'error': 'No input provided'})
        
        logger.info(f"📥 Received input: {user_input}")
        
        # Check if this is an edit command
        edit_keywords = ['delete', 'remove', 'edit', 'undo', 'clear']
        is_edit = any(keyword in user_input.lower() for keyword in edit_keywords)
        
        if is_edit:
            logger.info("🗑️ Edit command detected")
            # Handle edit commands
            if 'latest' in user_input.lower() or 'last' in user_input.lower():
                success = workout_logger.delete_latest_exercise()
                if success:
                    logger.info("✅ Latest exercise deleted successfully")
                    return jsonify({'success': True, 'message': 'Latest exercise deleted successfully!'})
                else:
                    logger.error("❌ No exercise found to delete")
                    return jsonify({'success': False, 'error': 'No exercise found to delete'})
            else:
                logger.error("❌ Edit command not recognized")
                return jsonify({'success': False, 'error': 'Edit command not recognized'})
        else:
            logger.info("💪 Processing workout logging")
            # Handle workout logging
            parsed_data = workout_logger.parse_input(user_input)
            success = workout_logger.log_workout(parsed_data)
            
            if success:
                logger.info("✅ Workout logged successfully")
                return jsonify({'success': True, 'message': 'Workout logged successfully!'})
            else:
                logger.error("❌ Failed to log workout")
                return jsonify({'success': False, 'error': 'Failed to log workout'})
    
    except Exception as e:
        logger.error(f"❌ Exception in log_workout: {e}")
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/workouts')
def get_workouts():
    """API endpoint to get recent workouts"""
    logger.info("📊 Workouts endpoint called")
    if not workout_logger:
        return jsonify([])
    
    workouts = workout_logger.get_recent_workouts()
    return jsonify(workouts)

@app.route('/health')
def health():
    """Health check endpoint"""
    logger.info("🏥 Health check requested")
    return jsonify({
        'status': 'healthy',
        'gemini_initialized': gemini_model is not None,
        'supabase_initialized': supabase is not None,
        'workout_logger_initialized': workout_logger is not None
    })

if __name__ == '__main__':
    logger.info("🚀 Starting Flask app...")
    logger.info(f"📍 Host: 0.0.0.0")
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🔌 Port: {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
