
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

# Initialize Flask
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
        print("Supabase client initialized:", supabase is not None)
        return gemini_model, supabase
    except Exception as e:
        print(f"Error initializing APIs: {e}")
        return None, None

gemini_model, supabase = initialize_apis()

# Connectivity test
print("Testing Supabase connection...")
try:
    test = supabase.table('sessions').select('*').limit(1).execute()
    print("Supabase test response:", test)
except Exception as e:
    print("Supabase connectivity error:", e)

# Gemini prompt generator
def generate_gemini_prompt(user_input: str) -> str:
    return f"""
Convert the following workout description into structured JSON.
Rules:
- If input contains multiple dates, output an array of sessions.
- Each session should include its date and exercises.
- For each exercise, include: activity_name, set_number, metric_type, value, unit.
Return ONLY valid JSON. No extra text.
Input: "{user_input}"
Output format:
{{
  "sessions": [
    {{
      "date": "YYYY-MM-DD",
      "exercises": [
        {{
          "activity_name": "pull-up",
          "set_number": 1,
          "metric_type": "reps",
          "value": 10,
          "unit": "reps"
        }}
      ]
    }}
  ]
}}
"""

# Parse input using Gemini
def parse_input(user_input: str) -> dict:
    try:
        prompt = generate_gemini_prompt(user_input)
        response = gemini_model.generate_content(prompt)
        response_text = response.text.strip()
        print("Gemini raw response:", response_text)
        try:
            parsed_json = json.loads(response_text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if match:
                parsed_json = json.loads(match.group(0).strip())
            else:
                return {'success': False, 'error': 'Could not parse JSON'}
        return parsed_json
    except Exception as e:
        print(f"Error parsing input: {e}")
        return {'success': False, 'error': str(e)}

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

        parsed_workout = parse_input(user_input)
        if parsed_workout.get('success') is False:
            return jsonify(parsed_workout), 400

        user_id = 1  # Default user
        raw_input = user_input

        for session in parsed_workout.get('sessions', []):
            workout_date = session['date']

            # Insert session
            session_insert = supabase.table('sessions').insert({
                'user_id': user_id,
                'date': workout_date,
                'created_at': datetime.utcnow().isoformat()
            }).execute()
            print("Session insert response:", session_insert)

            if not session_insert.data:
                return jsonify({'success': False, 'error': 'Session insert failed'}), 500

            session_id = session_insert.data[0]['session_id']

            # Group exercises
            grouped_exercises = {}
            for exercise in session.get('exercises', []):
                key = exercise['activity_name']
                if key not in grouped_exercises:
                    grouped_exercises[key] = {
                        'raw_input': raw_input,
                        'notes': '',
                        'metrics': []
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
                    'created_at': datetime.utcnow().isoformat()
                }
                set_result = supabase.table('sets').insert(set_entry).execute()
                print("Set insert response:", set_result)

                if not set_result.data:
                    return jsonify({'success': False, 'error': 'Set insert failed'}), 500

                set_id = set_result.data[0]['set_id']

                for metric in details['metrics']:
                    metric_entry = {
                        'set_id': set_id,
                        'metric_type': metric['metric_type'],
                        'value': metric['value'],
                        'unit': metric['unit'],
                        'created_at': datetime.utcnow().isoformat()
                    }
                    metric_result = supabase.table('metrics').insert(metric_entry).execute()
                    print("Metric insert response:", metric_result)

                    if not metric_result.data:
                        return jsonify({'success': False, 'error': 'Metric insert failed'}), 500

        return jsonify({'success': True, 'parsed_workout': parsed_workout})

    except Exception as e:
        print(f"Error in log_workout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
