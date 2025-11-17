import os
import re
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from supabase import create_client
from dotenv import load_dotenv

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

class WorkoutLogger:
    def __init__(self, gemini_model, supabase_client):
        self.gemini_model = gemini_model
        self.supabase = supabase_client

    def fetch_known_styles(self):
        try:
            activity_result = self.supabase.table('activity_logs').select('activity_name').execute()
            unit_result = self.supabase.table('activity_logs').select('unit').execute()

            known_activities = sorted(set(log['activity_name'] for log in activity_result.data if log.get('activity_name')))
            known_units = sorted(set(log['unit'] for log in unit_result.data if log.get('unit')))

            return known_activities, known_units
        except Exception as e:
            print(f"Error fetching known styles: {e}")
            return [], []

    def generate_gemini_prompt(self, user_input: str, current_date: str) -> str:
        known_activities, known_units = self.fetch_known_styles()
        activity_list = ', '.join(f'"{a}"' for a in known_activities)
        unit_list = ', '.join(f'"{u}"' for u in known_units)

        return f"""
Today's date is {current_date}.
Convert the following workout description into structured JSON.
Extract the date from the input if specified and include it in 'YYYY-MM-DD' format. If no date is specified, use today's date.
Use the following known activity names: [{activity_list}]
Use the following known units: [{unit_list}]
If the input matches any of these, use the same writing style.
If the input is new, use the most conventional format.
Return ONLY the JSON and no additional text.

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

            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                match = re.search(r'{.*}', response_text, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
                raise ValueError("Could not parse JSON from Gemini response")
        except Exception as e:
            print(f"Error parsing input: {e}")
            raise

    def log_workout(self, workout_data: dict) -> dict:
        try:
            logged_exercises = []
            rows_to_insert = []

            for exercise in workout_data.get('exercises', []):
                row = {
                    'date': workout_data.get('date'),
                    'activity_name': exercise.get('activity_name'),
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

            if rows_to_insert:
                self.supabase.table('activity_logs').insert(rows_to_insert).execute()

            return {
                'success': True,
                'message': f'Logged {len(logged_exercises)} exercises',
                'exercises': logged_exercises
            }
        except Exception as e:
            print(f"Error logging workout: {e}")
            return {'success': False, 'error': str(e)}

workout_logger = WorkoutLogger(gemini_model, supabase)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/log', methods=['POST'])
def log_workout():
    try:
        data = request.get_json()
        user_input = data.get('input', '') or data.get('workout', '')
        user_input = user_input.strip()

        if not user_input:
            return jsonify({'success': False, 'error': 'No workout input provided'}), 400

        parsed_workout = workout_logger.parse_input(user_input)
        result = workout_logger.log_workout(parsed_workout)
        return jsonify(result)
    except Exception as e:
        print(f"Error in log_workout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/recent')
def recent_workouts():
    try:
        result = supabase.table('activity_logs').select('*').order('created_at', desc=True).limit(20).execute()
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
