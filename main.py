import os
import re
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
GEMINI_MODEL_NAME = 'gemini-2.0-flash-exp'

# Initialize APIs
def initialize_apis():
    """Initialize Gemini and Supabase clients"""
    try:
        # Gemini API
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            print("❌ GOOGLE_API_KEY not found!")
            return None, None
        
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        print("✅ Gemini initialized successfully")
        
        # Supabase
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_ANON_KEY')  # FIXED: Using SUPABASE_ANON_KEY
        
        if not supabase_url or not supabase_key:
            print(f"❌ Supabase credentials missing! URL: {bool(supabase_url)}, KEY: {bool(supabase_key)}")
            return gemini_model, None
        
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
                            "set_id": 1,
                            "kg": null,
                            "reps": null,
                            "distance_km": null,
                            "time_sec": null,
                            "size_cm": null
                        }}
                    ]
                }}
            ]
        }}
        """
    
    def parse_input(self, user_input: str, user_id: str = "default_user") -> dict:
        """Parse user input using Gemini"""
        try:
            current_date = datetime.today().strftime('%Y-%m-%d')
            prompt = self.generate_gemini_prompt(user_input, current_date, user_id)
            
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text
            
            # Extract JSON from response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
            else:
                json_string = response_text.strip()
            
            return json.loads(json_string)
        except Exception as e:
            print(f"Error parsing input: {e}")
            return None
    
    def log_workout(self, workout_data: dict) -> bool:
        """Log workout to Supabase"""
        try:
            if not workout_data or not self.supabase:
                return False
            
            # Insert workout record
            workout_result = self.supabase.table('workouts').insert({
                'date': workout_data['date'],
                'user_id': workout_data.get('user_id', 'default_user'),
                'username': workout_data.get('username', 'User'),
                'raw_input': workout_data.get('raw_input', '')
            }).execute()
            
            if not workout_result.data:
                return False
            
            workout_id = workout_result.data[0]['id']
            
            # Insert exercises
            for exercise in workout_data.get('exercises', []):
                exercise_result = self.supabase.table('exercises').insert({
                    'workout_id': workout_id,
                    'name': exercise['name']
                }).execute()
                
                if exercise_result.data:
                    exercise_id = exercise_result.data[0]['id']
                    
                    # Insert sets
                    for set_data in exercise.get('sets', []):
                        self.supabase.table('exercise_metrics').insert({
                            'exercise_id': exercise_id,
                            'set_id': set_data.get('set_id', 1),
                            'kg': set_data.get('kg'),
                            'reps': set_data.get('reps'),
                            'distance_km': set_data.get('distance_km'),
                            'time_sec': set_data.get('time_sec'),
                            'size_cm': set_data.get('size_cm')
                        }).execute()
            
            return True
        except Exception as e:
            print(f"Error logging workout: {e}")
            return False
    
    def get_recent_workouts(self, limit: int = 10) -> list:
        """Get recent workouts"""
        try:
            if not self.supabase:
                return []
            
            result = self.supabase.table('workouts').select('*').order('date', desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            print(f"Error getting workouts: {e}")
            return []

# Initialize workout logger
workout_logger = WorkoutLogger(gemini_model, supabase) if gemini_model and supabase else None

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/log', methods=['POST'])
def log_workout():
    """API endpoint to log workouts"""
    try:
        if not workout_logger:
            return jsonify({'success': False, 'error': 'System not initialized'})
        
        data = request.get_json()
        user_input = data.get('input', '').strip()
        
        if not user_input:
            return jsonify({'success': False, 'error': 'No input provided'})
        
        # Parse and log workout
        parsed_data = workout_logger.parse_input(user_input)
        
        if not parsed_data:
            return jsonify({'success': False, 'error': 'Failed to parse input'})
        
        success = workout_logger.log_workout(parsed_data)
        
        if success:
            return jsonify({'success': True, 'message': 'Workout logged successfully!'})
        else:
            return jsonify({'success': False, 'error': 'Failed to log workout'})
    
    except Exception as e:
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
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

# CRITICAL: EXPLICIT PORT BINDING FOR RENDER
if __name__ == '__main__':
    # Get port from environment variable (Render sets this automatically)
    port = int(os.environ.get('PORT', 5000))
    
    # Print debug info
    print(f"🚀 Starting Flask app...")
    print(f"📍 Host: 0.0.0.0")
    print(f"🔌 Port: {port}")
    print(f"🔑 Environment variables loaded:")
    print(f"   - GOOGLE_API_KEY: {'✅' if os.getenv('GOOGLE_API_KEY') else '❌'}")
    print(f"   - SUPABASE_URL: {'✅' if os.getenv('SUPABASE_URL') else '❌'}")
    print(f"   - SUPABASE_ANON_KEY: {'✅' if os.getenv('SUPABASE_ANON_KEY') else '❌'}")
    
    # FORCE EXPLICIT BINDING - NO AMBIGUITY
    try:
        app.run(
            host='0.0.0.0',    # MUST be 0.0.0.0 for external access
            port=port,         # Use Render's PORT environment variable
            debug=False,       # No debug in production
            threaded=True      # Enable threading for better performance
        )
    except Exception as e:
        print(f"❌ Failed to start Flask app: {e}")
        raise
