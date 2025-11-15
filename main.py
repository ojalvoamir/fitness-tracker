import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import google.generativeai as genai
from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configure Gemini
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable is required")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-exp')

# Configure Supabase
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY')

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY environment variables are required")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def parse_workout_with_gemini(user_input):
    """Parse workout input using Gemini AI"""
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    prompt = f"""
    Today's date is {current_date}. Convert the following workout description into structured JSON.
    
    IMPORTANT: Extract any notes, feelings, or comments from the input (like "felt good", "easy", "hard", "tired", "challenging", "smooth", etc.) and include them in a 'notes' field for each exercise.
    
    Extract the date from the input if specified, otherwise use today's date.
    Return ONLY the JSON, no additional text.
    
    Use consistent exercise names (e.g., "pull-up" not "pullup" or "pull up").
    
    Input: "{user_input}"
    
    Output format:
    {{
      "date": "YYYY-MM-DD",
      "exercises": [
        {{
          "name": "Exercise Name",
          "notes": "Any feelings, comments, or notes about this exercise",
          "sets": [
            {{
              "set_id": 1,
              "reps": null,
              "weight_kg": null,
              "distance_km": null,
              "time_seconds": null
            }}
          ]
        }}
      ]
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Clean up the response
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        
        return json.loads(response_text.strip())
    except Exception as e:
        logger.error(f"Error parsing with Gemini: {e}")
        raise

def log_workout_to_supabase(workout_data):
    """Log workout data to Supabase"""
    try:
        workout_date = workout_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        for exercise in workout_data.get('exercises', []):
            exercise_name = exercise.get('name', 'Unknown')
            exercise_notes = exercise.get('notes', '')  # Get notes from exercise
            
            for set_data in exercise.get('sets', []):
                # Insert into activity_logs table
                log_entry = {
                    'date': workout_date,
                    'exercise_name': exercise_name,
                    'set_number': set_data.get('set_id', 1),
                    'reps': set_data.get('reps'),
                    'weight_kg': set_data.get('weight_kg'),
                    'distance_km': set_data.get('distance_km'),
                    'time_seconds': set_data.get('time_seconds'),
                    'notes': exercise_notes  # Add notes to the log entry
                }
                
                # Remove None values
                log_entry = {k: v for k, v in log_entry.items() if v is not None}
                
                result = supabase.table('activity_logs').insert(log_entry).execute()
                logger.info(f"Logged: {log_entry}")
        
        return True
    except Exception as e:
        logger.error(f"Error logging to Supabase: {e}")
        raise

@app.route('/')
def index():
    """Serve the main page"""
    return render_template_string(open('index.html').read())

@app.route('/log', methods=['POST'])
def log_workout():
    """Handle workout logging"""
    try:
        data = request.get_json()
        user_input = data.get('input', '').strip()
        
        if not user_input:
            return jsonify({'success': False, 'error': 'No input provided'}), 400
        
        # Parse with Gemini
        workout_data = parse_workout_with_gemini(user_input)
        
        # Log to Supabase
        log_workout_to_supabase(workout_data)
        
        return jsonify({
            'success': True,
            'message': 'Workout logged successfully!',
            'parsed_data': workout_data
        })
        
    except Exception as e:
        logger.error(f"Error in /log endpoint: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/recent', methods=['GET'])
def get_recent_workouts():
    """Get recent workout entries"""
    try:
        result = supabase.table('activity_logs').select('*').order('date', desc=True).limit(10).execute()
        return jsonify({'success': True, 'data': result.data})
    except Exception as e:
        logger.error(f"Error fetching recent workouts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
