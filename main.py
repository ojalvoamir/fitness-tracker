import os
import json
from datetime import datetime
from flask import Flask, request, render_template_string, jsonify
import google.generativeai as genai
from supabase import create_client, Client

app = Flask(__name__)

# Configure Gemini API
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('models/gemini-2.5-flash')

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
        # Clean the response to extract JSON
        response_text = response.text.strip()
        
        # Remove markdown code blocks if present
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
                
                # Insert each metric as a separate row
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
                    
                    # Insert into activity_logs table
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

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Workout Logger</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        .input-section {
            margin-bottom: 30px;
        }
        textarea {
            width: 100%;
            padding: 15px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 16px;
            min-height: 100px;
            resize: vertical;
        }
        button {
            background: #007AFF;
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            width: 100%;
            margin-top: 10px;
        }
        button:hover {
            background: #0056CC;
        }
        .recent-workouts {
            margin-top: 30px;
        }
        .workout-item {
            background: #f8f9fa;
            padding: 15px;
            margin: 10px 0;
            border-radius: 8px;
            border-left: 4px solid #007AFF;
        }
        .message {
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
        }
        .success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .loading {
            display: none;
            text-align: center;
            color: #666;
        }
        .examples {
            background: #e9ecef;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .examples h3 {
            margin-top: 0;
            color: #495057;
        }
        .examples ul {
            margin: 0;
            padding-left: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>💪 Workout Logger</h1>
        
        <div class="examples">
            <h3>Example inputs:</h3>
            <ul>
                <li>"5 pull-ups, 10 push-ups"</li>
                <li>"ran 5km in 25 minutes"</li>
                <li>"bench press 3 sets of 8 reps at 80kg"</li>
                <li>"cindy 5 rounds"</li>
                <li>"squats 50kg 3x10 yesterday"</li>
            </ul>
        </div>
        
        <div class="input-section">
            <form id="workoutForm">
                <textarea 
                    id="workoutInput" 
                    placeholder="Describe your workout in natural language..."
                    required
                ></textarea>
                <button type="submit">Log Workout</button>
            </form>
        </div>
        
        <div id="message"></div>
        <div id="loading" class="loading">Processing your workout...</div>
        
        <div class="recent-workouts">
            <h2>Recent Workouts</h2>
            <div id="workoutsList">
                {% for workout in recent_workouts %}
                <div class="workout-item">
                    <strong>{{ workout.date }}</strong> - 
                    {{ workout.activity_name }} 
                    (Set {{ workout.set_number }})
                    <br>
                    {{ workout.metric_type }}: {{ workout.value }} {{ workout.unit or '' }}
                    {% if workout.raw_input %}
                    <br><small>Original: "{{ workout.raw_input }}"</small>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <script>
        document.getElementById('workoutForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const input = document.getElementById('workoutInput');
            const messageDiv = document.getElementById('message');
            const loadingDiv = document.getElementById('loading');
            
            if (!input.value.trim()) {
                messageDiv.innerHTML = '<div class="message error">Please enter a workout description</div>';
                return;
            }
            
            // Show loading
            loadingDiv.style.display = 'block';
            messageDiv.innerHTML = '';
            
            try {
                const response = await fetch('/log', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        workout: input.value
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    messageDiv.innerHTML = '<div class="message success">✅ Workout logged successfully!</div>';
                    input.value = '';
                    // Reload page to show new workout
                    setTimeout(() => location.reload(), 1500);
                } else {
                    messageDiv.innerHTML = `<div class="message error">❌ Error: ${data.error}</div>`;
                }
            } catch (error) {
                messageDiv.innerHTML = `<div class="message error">❌ Network error: ${error.message}</div>`;
            } finally {
                loadingDiv.style.display = 'none';
            }
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    recent_workouts = get_recent_workouts(10)
    return render_template_string(HTML_TEMPLATE, recent_workouts=recent_workouts)

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
