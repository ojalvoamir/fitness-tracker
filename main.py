import os
import re
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration - UPDATED TO 2.5-FLASH!
GEMINI_MODEL_NAME = 'gemini-2.5-flash'

# Initialize APIs
def initialize_apis():
    """Initialize Gemini and Supabase clients"""
    try:
        # Gemini API
        genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        
        # Supabase
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_ANON_KEY')
        supabase = create_client(supabase_url, supabase_key)
        
        return gemini_model, supabase
    except Exception as e:
        print(f"Error initializing APIs: {e}")
        return None, None

# Global variables
gemini_model, supabase = initialize_apis()

class WorkoutLogger:
    """Handle workout parsing and logging with YOUR ACTUAL FLAT TABLE SCHEMA"""
    
    def __init__(self, gemini_model, supabase_client):
        self.gemini_model = gemini_model
        self.supabase = supabase_client
    
    def generate_gemini_prompt(self, user_input: str, current_date: str) -> str:
        """Generate prompt for Gemini based on your actual flat table schema"""
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
  "user_id": "default_user",
  "username": "User",
  "raw_input": "{user_input}",
  "exercises": [
    {{
      "activity_name": "pull-up",
      "set_number": 1,
      "metric_type": "reps",
      "value": 5,
      "unit": "reps"
    }},
    {{
      "activity_name": "push-up", 
      "set_number": 1,
      "metric_type": "reps",
      "value": 5,
      "unit": "reps"
    }}
  ]
}}
"""
    
    def parse_input(self, user_input: str, current_date: str = None) -> dict:
        """Parse user input using Gemini"""
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            prompt = self.generate_gemini_prompt(user_input, current_date)
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text
            
            # Extract JSON from response
            json_match = re.search(r'```json
(.*?)
```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
            else:
                json_string = response_text.strip()
            
            return json.loads(json_string)
        except Exception as e:
            print(f"Error parsing input: {e}")
            raise
    
    def log_workout(self, workout_data: dict) -> dict:
        """Log workout to database using YOUR ACTUAL FLAT TABLE SCHEMA"""
        try:
            logged_exercises = []
            
            # Prepare rows for insertion into your flat table
            rows_to_insert = []
            
            for exercise in workout_data.get('exercises', []):
                row = {
                    'date': workout_data.get('date'),
                    'activity_name': exercise.get('activity_name'),  # YOUR ACTUAL COLUMN
                    'set_number': exercise.get('set_number', 1),
                    'metric_type': exercise.get('metric_type'),
                    'value': exercise.get('value'),
                    'unit': exercise.get('unit'),
                    'user_id': workout_data.get('user_id', 'default_user'),
                    'username': workout_data.get('username', 'User'),
                    'raw_input': workout_data.get('raw_input', ''),
                    'notes': None
                }
                rows_to_insert.append(row)
                
                logged_exercises.append({
                    'exercise': exercise.get('activity_name'),
                    'set': exercise.get('set_number', 1),
                    'metric_type': exercise.get('metric_type'),
                    'value': exercise.get('value'),
                    'unit': exercise.get('unit')
                })
            
            # Insert all rows at once
            if rows_to_insert:
                result = self.supabase.table('activity_logs').insert(rows_to_insert).execute()
                print(f"Successfully inserted {len(rows_to_insert)} rows")
            
            return {
                'success': True,
                'message': f'Logged {len(logged_exercises)} exercises',
                'exercises': logged_exercises
            }
        except Exception as e:
            print(f"Error logging workout: {e}")
            return {'success': False, 'error': str(e)}

# Initialize workout logger
workout_logger = WorkoutLogger(gemini_model, supabase)

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/log', methods=['POST'])
def log_workout():
    """Log a workout from natural language input"""
    try:
        data = request.get_json()
        user_input = data.get('workout', '').strip()
        
        if not user_input:
            return jsonify({'success': False, 'error': 'No workout input provided'}), 400
        
        # Parse the input
        parsed_workout = workout_logger.parse_input(user_input)
        
        # Log to database
        result = workout_logger.log_workout(parsed_workout)
        
        return jsonify(result)
    except Exception as e:
        print(f"Error in log_workout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/recent')
def recent_workouts():
    """Get recent workouts"""
    try:
        # Get recent activity logs from your flat table
        result = supabase.table('activity_logs')            .select('*')            .order('created_at', desc=True)            .limit(20)            .execute()
        
        workouts = []
        for log in result.data:
            workouts.append({
                'date': log['date'],
                'activity_name': log['activity_name'],
                'set_number': log['set_number'],
                'metric_type': log['metric_type'],
                'value': log['value'],
                'unit': log['unit'],
                'raw_input': log['raw_input']
            })
        
        return jsonify({'success': True, 'workouts': workouts})
    except Exception as e:
        print(f"Error getting recent workouts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
