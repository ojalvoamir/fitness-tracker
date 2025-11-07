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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)

# Configuration
GEMINI_MODEL_NAME = 'gemini-2.0-flash-exp'

def initialize_apis():
    """Initialize Gemini and Supabase clients"""
    try:
        logger.info("🔑 Starting API initialization...")
        
        # Gemini API
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found")
        
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        logger.info("✅ Gemini initialized successfully")
        
        # Supabase
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_ANON_KEY')
        
        if not supabase_url or not supabase_key:
            raise ValueError("Supabase credentials missing")
            
        supabase = create_client(supabase_url, supabase_key)
        logger.info("✅ Supabase initialized successfully")
        
        return gemini_model, supabase
    except Exception as e:
        logger.error(f"❌ Error initializing APIs: {e}")
        return None, None

gemini_model, supabase = initialize_apis()

class WorkoutLogger:
    """Simplified workout logger for the new schema"""
    
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
            
            # Extract JSON from response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
            else:
                json_string = response_text.strip()
            
            parsed_data = json.loads(json_string)
            logger.info("✅ Successfully parsed JSON from Gemini")
            return parsed_data
        except Exception as e:
            logger.error(f"❌ Error parsing input: {e}")
            raise
    
    def log_workout(self, workout_data: dict) -> bool:
        """Log workout data to simplified schema - MUCH SIMPLER!"""
        try:
            logger.info(f"📝 Logging workout data")
            
            log_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))
            user_id = workout_data.get("user_id", "default_user")
            username = workout_data.get("username", "User")
            raw_input = workout_data.get("raw_input", "")
            
            # Prepare all rows for batch insert
            rows_to_insert = []
            
            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name", "Unknown Exercise")
                
                for set_data in exercise.get("sets", []):
                    set_number = set_data.get("set_number", 1)
                    
                    # Each metric becomes one row - SIMPLE!
                    for metric in set_data.get("metrics", []):
                        if metric.get("value") is not None:
                            rows_to_insert.append({
                                'date': log_date,
                                'exercise_name': exercise_name,
                                'set_number': set_number,
                                'metric_type': metric.get("type"),
                                'value': metric.get("value"),
                                'unit': metric.get("unit"),
                                'user_id': user_id,
                                'username': username,
                                'raw_input': raw_input
                            })
            
            # Single batch insert - MUCH FASTER!
            if rows_to_insert:
                result = self.supabase.table('activity_logs').insert(rows_to_insert).execute()
                logger.info(f"✅ Inserted {len(rows_to_insert)} workout records")
                return True
            else:
                logger.warning("⚠️ No workout data to insert")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error logging workout: {e}")
            return False
    
    def delete_latest_exercise(self, user_id: str = "default_user") -> bool:
        """Delete the most recent exercise entry"""
        try:
            # Get the latest exercise entry
            result = self.supabase.table('activity_logs')\
                .select('date, exercise_name')\
                .eq('user_id', user_id)\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if result.data:
                latest = result.data[0]
                # Delete all entries for this exercise on this date
                self.supabase.table('activity_logs')\
                    .delete()\
                    .eq('user_id', user_id)\
                    .eq('date', latest['date'])\
                    .eq('exercise_name', latest['exercise_name'])\
                    .execute()
                
                logger.info(f"✅ Deleted latest exercise: {latest['exercise_name']}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error deleting exercise: {e}")
            return False
    
    def get_recent_workouts(self, days: int = 7, user_id: str = "default_user") -> list:
        """Get recent workout data - SUPER SIMPLE NOW!"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # One simple query gets everything!
            result = self.supabase.table('activity_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', cutoff_date)\
                .order('created_at', desc=True)\
                .limit(50)\
                .execute()
            
            logger.info(f"📊 Retrieved {len(result.data)} recent workout records")
            return result.data
        except Exception as e:
            logger.error(f"❌ Error getting workouts: {e}")
            return []

# Initialize workout logger
workout_logger = WorkoutLogger(gemini_model, supabase) if gemini_model and supabase else None

@app.route('/')
def index():
    """Main page with input form and recent workouts"""
    recent_workouts = []
    if workout_logger:
        recent_workouts = workout_logger.get_recent_workouts()
    
    return render_template('index.html', recent_workouts=recent_workouts)

@app.route('/log', methods=['POST'])
def log_workout():
    """Handle workout logging"""
    if not workout_logger:
        return jsonify({'success': False, 'error': 'System not initialized'})
    
    try:
        user_input = request.json.get('input', '').strip()
        if not user_input:
            return jsonify({'success': False, 'error': 'No input provided'})
        
        # Check if this is an edit command
        edit_keywords = ['delete', 'remove', 'edit', 'undo', 'clear']
        is_edit = any(keyword in user_input.lower() for keyword in edit_keywords)
        
        if is_edit:
            if 'latest' in user_input.lower() or 'last' in user_input.lower():
                success = workout_logger.delete_latest_exercise()
                if success:
                    return jsonify({'success': True, 'message': 'Latest exercise deleted successfully!'})
                else:
                    return jsonify({'success': False, 'error': 'No exercise found to delete'})
            else:
                return jsonify({'success': False, 'error': 'Edit command not recognized'})
        else:
            # Handle workout logging
            parsed_data = workout_logger.parse_input(user_input)
            success = workout_logger.log_workout(parsed_data)
            
            if success:
                return jsonify({'success': True, 'message': 'Workout logged successfully!'})
            else:
                return jsonify({'success': False, 'error': 'Failed to log workout'})
    
    except Exception as e:
        logger.error(f"❌ Exception in log_workout: {e}")
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/workouts')
def get_workouts():
    """API endpoint to get recent workouts"""
    if not workout_logger:
        return jsonify([])
    
    workouts = workout_logger.get_recent_workouts()
    return jsonify(workouts)

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'gemini_initialized': gemini_model is not None,
        'supabase_initialized': supabase is not None,
        'workout_logger_initialized': workout_logger is not None
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
