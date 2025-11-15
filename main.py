
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import re

from flask import Flask, request, jsonify, render_template_string
import google.generativeai as genai
from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration - FIXED VARIABLE NAMES
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')  # ✅ FIXED: was GEMINI_API_KEY
SUPABASE_URL = os.environ.get('SUPABASE_URL') 
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY')

# Initialize services
if not all([GOOGLE_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY]):
    logger.error("Missing required environment variables")
    logger.error(f"GOOGLE_API_KEY: {'✅' if GOOGLE_API_KEY else '❌'}")
    logger.error(f"SUPABASE_URL: {'✅' if SUPABASE_URL else '❌'}")
    logger.error(f"SUPABASE_ANON_KEY: {'✅' if SUPABASE_ANON_KEY else '❌'}")
    exit(1)

genai.configure(api_key=GOOGLE_API_KEY)  # ✅ FIXED: was GEMINI_API_KEY
model = genai.GenerativeModel('models/gemini-2.5-flash')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

class WorkoutParser:
    """Simple, clean workout parser that trusts Gemini's natural abilities"""
    
    def __init__(self):
        self.model = model
    
    def parse_workout(self, user_input: str, user_id: str = "default_user") -> Dict[str, Any]:
        """Parse workout input using Gemini - clean and simple"""
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        # CLEAN prompt - no micromanagement, just clear requirements
        prompt = f"""
Today's date is {current_date}.
Convert this workout description into structured JSON.

REQUIREMENTS:
1. If multiple dates mentioned, create separate entries for each
2. ALWAYS return {{"entries": [...]}} format - never a raw array
3. Convert time formats (45:18 becomes 2718 seconds)
4. Use standard exercise names

INPUT: "{user_input}"

OUTPUT:
{{
  "entries": [
    {{
      "date": "YYYY-MM-DD",
      "user_id": "{user_id}",
      "username": "User",
      "raw_input": "relevant portion",
      "exercises": [
        {{
          "name": "exercise name",
          "activity_type": "exercise",
          "notes": "any notes or null",
          "sets": [
            {{
              "set_number": 1,
              "metrics": [
                {{"type": "reps", "value": 10, "unit": "reps"}},
                {{"type": "weight", "value": 50, "unit": "kg"}},
                {{"type": "time", "value": 300, "unit": "sec"}},
                {{"type": "distance", "value": 5, "unit": "km"}}
              ]
            }}
          ]
        }}
      ]
    }}
  ]
}}
"""
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Clean up response
            if '```json' in response_text:
                response_text = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL).group(1)
            elif '```' in response_text:
                response_text = re.search(r'```(.*?)```', response_text, re.DOTALL).group(1)
            
            parsed_data = json.loads(response_text)
            
            # Validate structure
            if not isinstance(parsed_data, dict):
                raise ValueError(f"Expected dict, got {type(parsed_data)}")
            
            if "entries" not in parsed_data:
                raise ValueError("Response missing 'entries' key")
            
            if not isinstance(parsed_data["entries"], list):
                raise ValueError("'entries' must be an array")
            
            logger.info(f"✅ Successfully parsed {len(parsed_data['entries'])} entries")
            return parsed_data
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            logger.error(f"Raw response: {response_text}")
            raise ValueError(f"Invalid JSON from Gemini: {e}")
        except Exception as e:
            logger.error(f"Parsing error: {e}")
            raise

class DatabaseLogger:
    """Simple database operations"""
    
    def __init__(self):
        self.supabase = supabase
    
    def log_workout_entries(self, entries: List[Dict[str, Any]]) -> List[str]:
        """Log multiple workout entries to database"""
        workout_ids = []
        
        for entry in entries:
            try:
                # Insert workout
                workout_data = {
                    'date': entry['date'],
                    'user_id': entry['user_id'],
                    'username': entry['username'],
                    'raw_input': entry['raw_input']
                }
                
                workout_result = self.supabase.table('workouts').insert(workout_data).execute()
                workout_id = workout_result.data[0]['id']
                workout_ids.append(workout_id)
                
                # Insert exercises
                for exercise in entry.get('exercises', []):
                    exercise_data = {
                        'workout_id': workout_id,
                        'name': exercise['name'],
                        'activity_type': exercise.get('activity_type', 'exercise'),
                        'notes': exercise.get('notes')
                    }
                    
                    exercise_result = self.supabase.table('exercises').insert(exercise_data).execute()
                    exercise_id = exercise_result.data[0]['id']
                    
                    # Insert sets and metrics
                    for set_data in exercise.get('sets', []):
                        set_info = {
                            'exercise_id': exercise_id,
                            'set_number': set_data['set_number']
                        }
                        
                        set_result = self.supabase.table('exercise_sets').insert(set_info).execute()
                        set_id = set_result.data[0]['id']
                        
                        # Insert metrics
                        for metric in set_data.get('metrics', []):
                            if metric['value'] is not None:
                                metric_data = {
                                    'set_id': set_id,
                                    'metric_type': metric['type'],
                                    'value': metric['value'],
                                    'unit': metric['unit']
                                }
                                self.supabase.table('exercise_metrics').insert(metric_data).execute()
                
                logger.info(f"✅ Logged workout entry for {entry['date']}")
                
            except Exception as e:
                logger.error(f"Database error for entry {entry.get('date', 'unknown')}: {e}")
                raise
        
        return workout_ids

# Initialize components
parser = WorkoutParser()
db_logger = DatabaseLogger()

# Simple HTML template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Simple Workout Logger</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { 
            font-family: Arial, sans-serif; 
            max-width: 600px; 
            margin: 50px auto; 
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 { color: #333; text-align: center; }
        textarea { 
            width: 100%; 
            height: 120px; 
            padding: 15px; 
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
            resize: vertical;
        }
        button { 
            width: 100%; 
            padding: 15px; 
            background: #007bff; 
            color: white; 
            border: none; 
            border-radius: 5px; 
            font-size: 16px;
            cursor: pointer;
            margin-top: 15px;
        }
        button:hover { background: #0056b3; }
        .result { 
            margin-top: 20px; 
            padding: 15px; 
            border-radius: 5px; 
            display: none;
        }
        .success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .examples {
            margin-top: 20px;
            padding: 15px;
            background: #e9ecef;
            border-radius: 5px;
        }
        .examples h3 { margin-top: 0; color: #495057; }
        .examples ul { margin: 10px 0; }
        .examples li { margin: 5px 0; color: #6c757d; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏋️ Simple Workout Logger</h1>
        
        <form id="workoutForm">
            <textarea 
                id="workoutInput" 
                placeholder="Describe your workout in natural language...

Examples:
• 5 pull-ups, 10 push-ups
• yesterday: ran 5k in 25 minutes  
• bodyweight 75kg, then 3x8 squats at 60kg
• a week ago: did some pullups and felt good"
                required
            ></textarea>
            <button type="submit">Log Workout</button>
        </form>
        
        <div id="result" class="result"></div>
        
        <div class="examples">
            <h3>💡 Tips</h3>
            <ul>
                <li>Use natural language - the AI understands typos and variations</li>
                <li>Mention dates like "yesterday", "last week", or specific dates</li>
                <li>Include details like weight, reps, time, distance</li>
                <li>Multiple exercises in one input work fine</li>
            </ul>
        </div>
    </div>

    <script>
        document.getElementById('workoutForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const input = document.getElementById('workoutInput').value;
            const result = document.getElementById('result');
            const button = document.querySelector('button');
            
            // Show loading
            button.textContent = 'Logging...';
            button.disabled = true;
            result.style.display = 'none';
            
            try {
                const response = await fetch('/log', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ input: input })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    result.className = 'result success';
                    result.innerHTML = `
                        <strong>✅ Success!</strong><br>
                        Logged ${data.entries_logged} workout entries<br>
                        <small>Workout IDs: ${data.workout_ids.join(', ')}</small>
                    `;
                    document.getElementById('workoutInput').value = '';
                } else {
                    throw new Error(data.error || 'Unknown error');
                }
                
            } catch (error) {
                result.className = 'result error';
                result.innerHTML = `<strong>❌ Error:</strong> ${error.message}`;
            }
            
            result.style.display = 'block';
            button.textContent = 'Log Workout';
            button.disabled = false;
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Simple workout logging interface"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/log', methods=['POST'])
def log_workout():
    """Log workout endpoint - clean and simple"""
    try:
        data = request.get_json()
        user_input = data.get('input', '').strip()
        
        if not user_input:
            return jsonify({'error': 'No input provided'}), 400
        
        # Parse with Gemini
        logger.info(f"Processing input: {user_input}")
        parsed_data = parser.parse_workout(user_input)
        
        # Log to database
        workout_ids = db_logger.log_workout_entries(parsed_data['entries'])
        
        return jsonify({
            'success': True,
            'entries_logged': len(parsed_data['entries']),
            'workout_ids': workout_ids,
            'message': f'Successfully logged {len(parsed_data["entries"])} workout entries'
        })
        
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return jsonify({'error': f'Parsing error: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/health')
def health():
    """Health check"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
