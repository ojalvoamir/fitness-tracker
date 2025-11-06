import os
import re
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
GEMINI_MODEL_NAME = 'gemini-1.5-flash'

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
    """Handle workout parsing and logging using existing Supabase schema"""
    
    def __init__(self, gemini_model, supabase_client):
        self.gemini_model = gemini_model
        self.supabase = supabase_client
    
    def get_or_create_exercise_type(self, exercise_name: str) -> int:
        """Get exercise_type_id or create new exercise type"""
        try:
            # First, try to find existing exercise by canonical name
            result = self.supabase.table('exercise_types').select('id').eq('canonical_name', exercise_name).execute()
            
            if result.data:
                return result.data[0]['id']
            
            # If not found, create new exercise type
            new_exercise = {
                'canonical_name': exercise_name,
                'category': 'general'  # Default category
            }
            
            result = self.supabase.table('exercise_types').insert(new_exercise).execute()
            return result.data[0]['id']
            
        except Exception as e:
            print(f"Error getting/creating exercise type: {e}")
            # Return a default ID or create a fallback
            return 1
    
    def generate_gemini_prompt(self, user_input: str, current_date: str, is_edit: bool = False) -> str:
        """Generate prompt for Gemini based on input type"""
        
        if is_edit:
            return f"""
            Today's date is {current_date}.
            
            The user wants to edit/modify their workout data. Parse this command and return the action type and details.
            
            Input: "{user_input}"
            
            Return ONLY JSON in this format:
            {{
              "action": "delete|edit|remove",
              "target": "latest|last|today|yesterday|specific_exercise",
              "details": {{
                "exercise_name": "exercise name if specified",
                "date": "YYYY-MM-DD if date specified",
                "set_number": "number if specified"
              }}
            }}
            """
        else:
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
              "exercises": [
                {{
                  "name": "Exercise Name",
                  "sets": [
                    {{
                      "set_id": 1,
                      "weight_kg": null,
                      "reps": null,
                      "distance_km": null,
                      "time_seconds": null,
                      "notes": null
                    }}
                  ]
                }}
              ]
            }}
            """
    
    def parse_input(self, user_input: str, current_date: str = None, is_edit: bool = False) -> dict:
        """Parse user input using Gemini"""
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            prompt = self.generate_gemini_prompt(user_input, current_date, is_edit)
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
            raise
    
    def log_workout(self, workout_data: dict) -> bool:
        """Log workout data to existing Supabase schema"""
        try:
            log_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))
            
            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name", "Unknown Exercise")
                
                # Get or create exercise type
                exercise_type_id = self.get_or_create_exercise_type(exercise_name)
                
                for set_data in exercise.get("sets", []):
                    # Insert into exercise_logs table with existing schema
                    log_entry = {
                        "user_id": "default_user",
                        "username": "default_user", 
                        "date": log_date,
                        "exercise_type_id": exercise_type_id,
                        "set_number": set_data.get("set_id", 1),
                        "notes": set_data.get("notes"),
                        "raw_input": str(workout_data)  # Store original input for reference
                    }
                    
                    # Insert the main log entry
                    result = self.supabase.table('exercise_logs').insert(log_entry).execute()
                    exercise_log_id = result.data[0]['id']
                    
                    # Insert metrics into exercise_metrics table
                    metrics_to_insert = []
                    
                    if set_data.get("weight_kg"):
                        metrics_to_insert.append({
                            "exercise_log_id": exercise_log_id,
                            "metric_type": "weight",
                            "value": float(set_data["weight_kg"]),
                            "unit": "kg"
                        })
                    
                    if set_data.get("reps"):
                        metrics_to_insert.append({
                            "exercise_log_id": exercise_log_id,
                            "metric_type": "reps",
                            "value": float(set_data["reps"]),
                            "unit": "count"
                        })
                    
                    if set_data.get("distance_km"):
                        metrics_to_insert.append({
                            "exercise_log_id": exercise_log_id,
                            "metric_type": "distance",
                            "value": float(set_data["distance_km"]),
                            "unit": "km"
                        })
                    
                    if set_data.get("time_seconds"):
                        metrics_to_insert.append({
                            "exercise_log_id": exercise_log_id,
                            "metric_type": "time",
                            "value": float(set_data["time_seconds"]),
                            "unit": "seconds"
                        })
                    
                    # Insert all metrics
                    if metrics_to_insert:
                        self.supabase.table('exercise_metrics').insert(metrics_to_insert).execute()
                    
            return True
        except Exception as e:
            print(f"Error logging workout: {e}")
            return False
    
    def delete_latest_exercise(self) -> bool:
        """Delete the most recent exercise entry"""
        try:
            # Get the latest entry
            result = self.supabase.table('exercise_logs').select('id').eq('user_id', 'default_user').order('created_at', desc=True).limit(1).execute()
            
            if result.data:
                latest_id = result.data[0]['id']
                
                # Delete associated metrics first
                self.supabase.table('exercise_metrics').delete().eq('exercise_log_id', latest_id).execute()
                
                # Delete the exercise log
                self.supabase.table('exercise_logs').delete().eq('id', latest_id).execute()
                
                return True
            return False
        except Exception as e:
            print(f"Error deleting exercise: {e}")
            return False
    
    def get_recent_workouts(self, days: int = 7) -> list:
        """Get recent workout data with exercise names"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Get exercise logs with exercise types
            result = self.supabase.table('exercise_logs').select('*, exercise_types!inner(canonical_name), exercise_metrics(metric_type, value, unit)').eq('user_id', 'default_user').gte('date', cutoff_date).order('created_at', desc=True).execute()
            
            # Format the data for display
            formatted_workouts = []
            for workout in result.data:
                # Get exercise name from joined table
                exercise_name = workout['exercise_types']['canonical_name']
                
                # Collect metrics
                metrics = {}
                for metric in workout.get('exercise_metrics', []):
                    metrics[metric['metric_type']] = {
                        'value': metric['value'],
                        'unit': metric['unit']
                    }
                
                formatted_workout = {
                    'id': workout['id'],
                    'date': workout['date'],
                    'exercise_name': exercise_name,
                    'set_number': workout['set_number'],
                    'weight_kg': metrics.get('weight', {}).get('value'),
                    'reps': metrics.get('reps', {}).get('value'),
                    'distance_km': metrics.get('distance', {}).get('value'),
                    'time_seconds': metrics.get('time', {}).get('value'),
                    'notes': workout.get('notes')
                }
                formatted_workouts.append(formatted_workout)
            
            return formatted_workouts
            
        except Exception as e:
            print(f"Error getting workouts: {e}")
            return []

# Initialize workout logger
workout_logger = WorkoutLogger(gemini_model, supabase) if gemini_model and supabase else None

@app.route('/')
def index():
    """Main page with input form and recent workouts"""
    recent_workouts = []
    if workout_logger:
        recent_workouts = workout_logger.get_recent_workouts()
    
    return render_template('index.html', recent_workouts=recent_workouts)

@app.route('/log', methods=['POST'])
def log_workout():
    """Handle workout logging"""
    if not workout_logger:
        return jsonify({'success': False, 'error': 'System not initialized'})
    
    try:
        user_input = request.json.get('input', '').strip()
        if not user_input:
            return jsonify({'success': False, 'error': 'No input provided'})
        
        # Check if this is an edit command
        edit_keywords = ['delete', 'remove', 'edit', 'undo', 'clear']
        is_edit = any(keyword in user_input.lower() for keyword in edit_keywords)
        
        if is_edit:
            # Handle edit commands
            if 'latest' in user_input.lower() or 'last' in user_input.lower():
                success = workout_logger.delete_latest_exercise()
                if success:
                    return jsonify({'success': True, 'message': 'Latest exercise deleted successfully!'})
                else:
                    return jsonify({'success': False, 'error': 'No exercise found to delete'})
            else:
                return jsonify({'success': False, 'error': 'Edit command not recognized'})
        else:
            # Handle workout logging
            parsed_data = workout_logger.parse_input(user_input)
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
