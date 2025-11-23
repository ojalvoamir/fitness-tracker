
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

# Gemini prompt generator
def generate_gemini_prompt(user_input: str, current_date: str) -> str:
    return f"""
Today's date is {current_date}.
Convert the following workout description into structured JSON.
Rules:
- If the workout is a composite (e.g., consists of multiple exercises like Cindy), include BOTH:
    1. The composite workout as one entry (with rounds/time).
    2. The individual exercises as separate entries, each referencing the composite workout in 'parent_activity'.
- For each exercise, include: activity_name, set_number, metric_type, value, unit.
- If an exercise has multiple metrics (e.g., weight and reps), output them as separate objects in the "metrics" array, not combined.
- Extract date from input if specified; otherwise use today's date.
Return ONLY valid JSON. Do not include any text, comments, markdown, or explanations.
Input: "{user_input}"
Output format:
{{
  "date": "YYYY-MM-DD",
  "user_id": 1,
  "username": "User",
  "raw_input": "{user_input}",
  "exercises": [
    {{
      "activity_name": "Cindy",
      "set_number": 1,
      "metric_type": "rounds",
      "value": 8,
      "unit": "rounds"
    }},
    {{
      "activity_name": "pull-up",
      "set_number": 1,
      "metric_type": "reps",
      "value": 40,
      "unit": "reps",
      "parent_activity": "Cindy"
    }}
  ]
}}
"""

# Safe parsing layer
def parse_input(user_input: str, current_date: str = None) -> dict:
    if current_date is None:
        current_date = datetime.now().strftime('%Y-%m-%d')
    try:
        prompt = generate_gemini_prompt(user_input, current_date)
        response = gemini_model.generate_content(prompt)
        response_text = response.text.strip()

        # Try direct JSON parse
        try:
            parsed_json = json.loads(response_text)
        except json.JSONDecodeError:
            # Attempt to extract JSON block
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if match:
                try:
                    parsed_json = json.loads(match.group(0).strip())
                except json.JSONDecodeError:
                    raise ValueError("Could not parse JSON from Gemini response")
            else:
                raise ValueError("Gemini response did not contain JSON")

        return parsed_json
    except Exception as e:
        print(f"Error parsing input: {e}")
        raise

workout_logger = type('WorkoutLogger', (), {'parse_input': parse_input})()

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
        workout_date = parsed_workout['date']
        user_id = 1
        raw_input = parsed_workout['raw_input']

        # Ensure all activity names exist
        for exercise in parsed_workout.get('exercises', []):
            activity_name = exercise['activity_name']
            activity_check = supabase.table('activity_names').select('activity_name').eq('activity_name', activity_name).execute()
            if not activity_check.data:
                supabase.table('activity_names').insert({
                    'activity_name': activity_name,
                    'activity_type': 'exercise'
                }).execute()

        # Validate exercises and units
        validation = validate_exercises_and_units(parsed_workout, supabase)
        if validation.get('suggestions'):
            return jsonify({'success': False, 'error': 'Validation failed', 'validation': validation}), 400

        # Check session
        existing_session = supabase.table('sessions').select('session_id').eq('user_id', user_id).eq('date', workout_date).execute()
        if existing_session.data:
            session_id = existing_session.data[0]['session_id']
        else:
            session_insert = supabase.table('sessions').insert({
                'user_id': user_id,
                'date': workout_date,
                'created_at': datetime.utcnow().isoformat()
            }).execute()
            session_id = session_insert.data[0]['session_id']

        # Group exercises
        grouped_exercises = {}
        for exercise in parsed_workout.get('exercises', []):
            key = exercise['activity_name']
            if key not in grouped_exercises:
                grouped_exercises[key] = {
                    'raw_input': raw_input,
                    'notes': parsed_workout.get('notes', ''),
                    'metrics': [],
                    'parent_activity': exercise.get('parent_activity')
                }
            grouped_exercises[key]['metrics'].append({
                'metric_type': exercise['metric_type'],
                'value': exercise['value'],
                'unit': exercise.get('unit')
            })

        # Insert sets and metrics
        for activity_name, details in grouped_exercises.items():
            set_entry = {
                'session_id': session_id,
                'activity_name': activity_name,
                'raw_input': details['raw_input'],
                'notes': details['notes'],
                'created_at': datetime.utcnow().isoformat(),
                'parent_activity': details['parent_activity']
            }
            set_result = supabase.table('sets').insert(set_entry).execute()
            set_id = set_result.data[0]['set_id']

            for metric in details['metrics']:
                # Handle combined metrics if any
                if isinstance(metric['value'], dict):
                    for key, val in metric['value'].items():
                        metric_entry = {
                            'set_id': set_id,
                            'metric_type': key,
                            'value': val,
                            'unit': 'kg' if key == 'weight' else 'reps',
                            'created_at': datetime.utcnow().isoformat()
                        }
                        supabase.table('metrics').insert(metric_entry).execute()
                else:
                    metric_entry = {
                        'set_id': set_id,
                        'metric_type': metric['metric_type'],
                        'value': metric['value'],
                        'unit': metric['unit'],
                        'created_at': datetime.utcnow().isoformat()
                    }
                    supabase.table('metrics').insert(metric_entry).execute()

        return jsonify({'success': True, 'parsed_workout': parsed_workout})

    except Exception as e:
        print(f"Error in log_workout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
