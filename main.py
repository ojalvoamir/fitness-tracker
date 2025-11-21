import os
import re
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from supabase import create_client
from dotenv import load_dotenv
from difflib import get_close_matches

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
GEMINI_MODEL_NAME = 'gemini-2.5-flash'

# Initialize APIs
def initialize_apis():
    try:
        genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)

        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_ANON_KEY')
        supabase = create_client(supabase_url, supabase_key)

        return gemini_model, supabase
    except Exception as e:
        print(f"Error initializing APIs: {e}")
        return None, None

gemini_model, supabase = initialize_apis()

# Validation function
def validate_exercises_and_units(parsed_workout, supabase_client):
    try:
        activity_result = supabase_client.table('activity_names').select('activity_name').execute()
        unit_result = supabase_client.table('metrics').select('unit').execute()

        existing_activities = set(log['activity_name'] for log in activity_result.data if log.get('activity_name'))
        existing_units = set(log['unit'] for log in unit_result.data if log.get('unit'))

        unknown_exercises = []
        unknown_units = []
        suggestions = []

        for exercise in parsed_workout.get('exercises', []):
            name = exercise.get('activity_name')
            unit = exercise.get('unit')

            if name and name not in existing_activities:
                unknown_exercises.append(name)
                match = get_close_matches(name, existing_activities, n=1)
                if match:
                    suggestions.append({'type': 'exercise_name', 'input': name, 'suggested': match[0]})

            if unit and unit not in existing_units:
                unknown_units.append(unit)
                match = get_close_matches(unit, existing_units, n=1)
                if match:
                    suggestions.append({'type': 'unit', 'input': unit, 'suggested': match[0]})

        return {
            'unknown_exercises': unknown_exercises,
            'unknown_units': unknown_units,
            'suggestions': suggestions
        }
    except Exception as e:
        print(f"Error during validation: {e}")
        return {}

class WorkoutLogger:
    def __init__(self, gemini_model, supabase_client):
        self.gemini_model = gemini_model
        self.supabase = supabase_client

    def generate_gemini_prompt(self, user_input: str, current_date: str) -> str:
        return f"""
Today's date is {current_date}.
Convert the following workout description into structured JSON.
Extract the date from the input if specified and include it in 'YYYY-MM-DD' format. If no date is specified, use today's date.
Return ONLY the JSON and no additional text. Don't use markdown and any additional characters such as '.

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
    }}
  ]
}}
"""

    def parse_input(self, user_input: str, current_date: str = None) -> dict:
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')

        try:
            prompt = self.generate_gemini_prompt(user_input, current_date)
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text.strip()
            print("Gemini raw response:", response_text)

            try:
                parsed_json = json.loads(response_text)
            except json.JSONDecodeError:
                match = re.search(r'{.*}', response_text, re.DOTALL)
                if match:
                    try:
                        parsed_json = json.loads(match.group(0).strip())
                    except json.JSONDecodeError:
                        raise ValueError("Could not parse JSON from Gemini response")
                else:
                    raise ValueError("Could not parse JSON from Gemini response")

            return parsed_json
        except Exception as e:
            print(f"Error parsing input: {e}")
            raise

workout_logger = WorkoutLogger(gemini_model, supabase)


@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/log', methods=['POST'])



def log_workout():
    try:
        data = request.get_json()
        user_input = data.get('input', '').strip()

        if not user_input:
            return jsonify({'success': False, 'error': 'No workout input provided'}), 400

        parsed_workout = workout_logger.parse_input(user_input)
        validation = validate_exercises_and_units(parsed_workout, supabase)

        if validation.get('suggestions'):
            return jsonify({
                'success': False,
                'error': 'Validation failed',
                'validation': validation
            }), 400

        # Use default integer user_id = 1 and username = 'User'
        user_id = 1
        workout_date = parsed_workout['date']

        # Check if session already exists for this user and date
        existing_session = supabase.table('sessions').select('session_id').eq('user_id', user_id).eq('date', workout_date).execute()
        if existing_session.data:
            session_id = existing_session.data[0]['session_id']
        else:
            session_insert = supabase.table('sessions').insert({
                'user_id': user_id,
                'date': workout_date
            }).execute()
            session_id = session_insert.data[0]['session_id']

        # Insert each exercise into sets and metrics
        for exercise in parsed_workout.get('exercises', []):
            activity_name = exercise['activity_name']
            metric_type = exercise['metric_type']
            unit = exercise.get('unit')

            # Ensure activity_name exists in activity_names table
            activity_check = supabase.table('activity_names').select('activity_name').eq('activity_name', activity_name).execute()
            if not activity_check.data:
                try:
                    supabase.table('activity_names').insert({
                        'activity_name': activity_name,
                        'activity_type': 'exercise'
                    }).execute()
                except Exception as e:
                    print(f"Error inserting new activity_name '{activity_name}': {e}")
                    return jsonify({
                        'success': False,
                        'error': f"Failed to insert new activity_name '{activity_name}': {str(e)}"
                    }), 500

            # Insert into sets
            set_entry = {
                'session_id': session_id,
                'activity_name': activity_name,
                'raw_input': parsed_workout['raw_input'],
                'notes': parsed_workout.get('notes', ''),
                'created_at': datetime.utcnow().isoformat()
            }
            set_result = supabase.table('sets').insert(set_entry).execute()
            set_id = set_result.data[0]['set_id']

            # Insert into metrics
            metric_entry = {
                'set_id': set_id,
                'metric_type': metric_type,
                'value': exercise['value'],
                'unit': unit
            }
            supabase.table('metrics').insert(metric_entry).execute()

        return jsonify({'success': True, 'parsed_workout': parsed_workout})
    except Exception as e:
        print(f"Error in log_workout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
