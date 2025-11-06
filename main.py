import os
import re
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration - UPDATED TO GEMINI 2.5 FLASH
GEMINI_MODEL_NAME = 'gemini-2.5-flash'

# Initialize APIs
def initialize_apis():
    """Initialize Gemini and Supabase clients"""
    try:
        # Gemini API
        google_api_key = os.getenv('GOOGLE_API_KEY')
        if not google_api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not found")
        
        genai.configure(api_key=google_api_key)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        print("✅ Gemini API initialized successfully")
        
        # Supabase - FIXED: Using SUPABASE_KEY instead of SUPABASE_ANON_KEY
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')  # CORRECTED!
        
        if not supabase_url:
            raise ValueError("SUPABASE_URL environment variable not found")
        if not supabase_key:
            raise ValueError("SUPABASE_KEY environment variable not found")
        
        supabase = create_client(supabase_url, supabase_key)
        print("✅ Supabase initialized successfully")
        
        return gemini_model, supabase
    except Exception as e:
        print(f"❌ Error initializing APIs: {e}")
        return None, None

# Global variables
gemini_model, supabase = initialize_apis()

class WorkoutLogger:
    """Handle workout parsing and logging"""
    
    def __init__(self, gemini_model, supabase_client):
        self.gemini_model = gemini_model
        self.supabase = supabase_client
    
    def generate_gemini_prompt(self, user_input: str, current_date: str, is_edit: bool = False) -> str:
        """Generate prompt for Gemini based on input type"""
        
        if is_edit:
            return f"""
            Today's date is {current_date}.
            
            The user wants to edit/modify their workout data. Parse this command and return the action type and details.
            
            Input: "{user_input}"
            
            Return ONLY JSON in this format:
            {{
              "action": "delete|edit|remove",
              "target": "latest|last|today|yesterday|specific_exercise",
              "details": {{
                "exercise_name": "exercise name if specified",
                "date": "YYYY-MM-DD if date specified",
                "set_number": "number if specified"
              }}
            }}
            """
        else:
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
    
    def parse_input(self, user_input: str, current_date: str = None, is_edit: bool = False) -> dict:
        """Parse user input using Gemini"""
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            prompt = self.generate_gemini_prompt(user_input, current_date, is_edit)
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text
            
            # Extract JSON from response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
            else:
                json_string = response_text.strip()
            
            parsed_data = json.loads(json_string)
            print(f"✅ Successfully parsed: {user_input}")
            return parsed_data
        except Exception as e:
            print(f"❌ Error parsing input '{user_input}': {e}")
            raise
    
    def log_workout(self, workout_data: dict) -> bool:
        """Log workout data to Supabase"""
        try:
            log_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))
            print(f"📝 Logging workout for date: {log_date}")
            
            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name", "Unknown Exercise")
                print(f"  Exercise: {exercise_name}")
                
                for set_data in exercise.get("sets", []):
                    # Insert into exercise_logs table
                    data = {
                        "user_id": "default_user",  # For now, single user
                        "date": log_date,
                        "exercise_name": exercise_name,
                        "set_number": set_data.get("set_id", 1),
                        "weight_kg": set_data.get("weight_kg"),
                        "reps": set_data.get("reps"),
                        "distance_km": set_data.get("distance_km"),
                        "time_seconds": set_data.get("time_seconds"),
                        "notes": set_data.get("notes")
                    }
                    
                    result = self.supabase.table('exercise_logs').insert(data).execute()
                    print(f"    Set {set_data.get('set_id', 1)}: {set_data.get('reps', 'N/A')} reps")
                    
            print("✅ Workout logged successfully!")
            return True
        except Exception as e:
            print(f"❌ Error logging workout: {e}")
            print(f"❌ Workout data: {workout_data}")
            return False
    
    def delete_latest_exercise(self) -> bool:
        """Delete the most recent exercise entry"""
        try:
            # Get the latest entry
            result = self.supabase.table('exercise_logs')\
                .select('*')\
                .eq('user_id', 'default_user')\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if result.data:
                latest_id = result.data[0]['id']
                self.supabase.table('exercise_logs').delete().eq('id', latest_id).execute()
                print(f"✅ Deleted exercise with ID: {latest_id}")
                return True
            print("⚠️ No exercises found to delete")
            return False
        except Exception as e:
            print(f"❌ Error deleting exercise: {e}")
            return False
    
    def get_recent_workouts(self, days: int = 7) -> list:
        """Get recent workout data"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            result = self.supabase.table('exercise_logs')\
                .select('*')\
                .eq('user_id', 'default_user')\
                .gte('date', cutoff_date)\
                .order('date', desc=True)\
                .execute()
            
            print(f"📊 Retrieved {len(result.data)} recent workout entries")
            return result.data
        except Exception as e:
            print(f"❌ Error getting workouts: {e}")
            return []

# Initialize workout logger
if gemini_model and supabase:
    workout_logger = WorkoutLogger(gemini_model, supabase)
    print("✅ WorkoutLogger initialized successfully")
else:
    workout_logger = None
    print("❌ WorkoutLogger failed to initialize - APIs not available")

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
        print("❌ Workout logger not available")
        return jsonify({'success': False, 'error': 'System not initialized - check environment variables'})
    
    try:
        user_input = request.json.get('input', '').strip()
        if not user_input:
            return jsonify({'success': False, 'error': 'No input provided'})
        
        print(f"📥 Received input: '{user_input}'")
        
        # Check if this is an edit command
        edit_keywords = ['delete', 'remove', 'edit', 'undo', 'clear']
        is_edit = any(keyword in user_input.lower() for keyword in edit_keywords)
        
        if is_edit:
            # Handle edit commands
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
                return jsonify({'success': False, 'error': 'Failed to log workout - check logs for details'})
                
    except Exception as e:
        print(f"❌ Exception in log_workout: {e}")
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/workouts')
def get_workouts():
    """API endpoint to get recent workouts"""
    if not workout_logger:
        return jsonify([])
    
    workouts = workout_logger.get_recent_workouts()
    return jsonify(workouts)

@app.route('/health')
def health_check():
    """Health check endpoint"""
    status = {
        'gemini_available': gemini_model is not None,
        'supabase_available': supabase is not None,
        'workout_logger_available': workout_logger is not None
    }
    return jsonify(status)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
