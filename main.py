import os
import json
from datetime import datetime
from flask import Flask, request, render_template, jsonify
import google.generativeai as genai
from supabase import create_client, Client

app = Flask(__name__)

# Configure Gemini API
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-2.5-flash')

# Configure Supabase
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_ANON_KEY')
supabase: Client = create_client(supabase_url, supabase_key)

def parse_workout_with_gemini(user_input: str) -> dict:
    """Parse natural language workout input using Gemini AI"""
    
    prompt = f"""
    Parse this workout description into structured JSON format.
    
    Input: "{user_input}"
    
    Return ONLY valid JSON in this exact format:
    {{
        "date": "YYYY-MM-DD",
        "exercises": [
            {{
                "activity_name": "exercise name",
                "sets": [
                    {{
                        "set_number": 1,
                        "metrics": [
                            {{"metric_type": "reps", "value": 10, "unit": "reps"}},
                            {{"metric_type": "weight", "value": 50, "unit": "kg"}}
                        ]
                    }}
                ]
            }}
        ]
    }}
    
    Rules:
    - Use today's date if no date specified: {datetime.now().strftime('%Y-%m-%d')}
    - Standardize exercise names (e.g., "pullup" -> "pull-up")
    - Common metric types: reps, weight, distance, time, rounds
    - Common units: reps, kg, lbs, km, miles, seconds, minutes
    - For Cindy workout: use "rounds" metric with default 20 minutes time
    """
    
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        
        return json.loads(response_text.strip())
    except Exception as e:
        print(f"Error parsing with Gemini: {e}")
        raise

def log_to_supabase(workout_data: dict, raw_input: str):
    """Log parsed workout data to Supabase activity_logs table"""
    
    try:
        workout_date = workout_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        for exercise in workout_data.get('exercises', []):
            activity_name = exercise.get('activity_name', 'Unknown')
            
            for set_data in exercise.get('sets', []):
                set_number = set_data.get('set_number', 1)
                
                for metric in set_data.get('metrics', []):
                    row_data = {
                        'date': workout_date,
                        'activity_name': activity_name,
                        'set_number': set_number,
                        'metric_type': metric.get('metric_type'),
                        'value': metric.get('value'),
                        'unit': metric.get('unit'),
                        'user_id': 'default_user',
                        'username': 'User',
                        'raw_input': raw_input,
                        'notes': None
                    }
                    
                    result = supabase.table('activity_logs').insert(row_data).execute()
                    
        print(f"✅ Successfully logged workout to Supabase")
        return True
        
    except Exception as e:
        print(f"❌ Error logging to Supabase: {e}")
        raise

def get_recent_workouts(limit=10):
    """Retrieve recent workouts from Supabase"""
    try:
        result = supabase.table('activity_logs').select('*').order('created_at', desc=True).limit(limit).execute()
        return result.data
    except Exception as e:
        print(f"Error retrieving workouts: {e}")
        return []

@app.route('/')
def index():
    recent_workouts = get_recent_workouts(10)
    return render_template('index.html', recent_workouts=recent_workouts)

@app.route('/log', methods=['POST'])
def log_workout():
    try:
        data = request.get_json()
        workout_input = data.get('workout', '').strip()
        
        if not workout_input:
            return jsonify({'success': False, 'error': 'No workout input provided'})
        
        # Parse with Gemini
        parsed_workout = parse_workout_with_gemini(workout_input)
        
        # Log to Supabase
        log_to_supabase(parsed_workout, workout_input)
        
        return jsonify({'success': True, 'message': 'Workout logged successfully'})
        
    except Exception as e:
        print(f"Error in /log endpoint: {e}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
