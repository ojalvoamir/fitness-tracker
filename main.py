import os
import re
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from supabase import create_client, Client

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
        
        # Supabase - Using your Render environment variables
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')  # Your Render env var name
        supabase = create_client(supabase_url, supabase_key)
        
        return gemini_model, supabase
    except Exception as e:
        print(f"Error initializing APIs: {e}")
        return None, None

# Global variables
gemini_model, supabase = initialize_apis()

class WorkoutLogger:
    """Handle workout parsing and logging with YOUR ACTUAL SCHEMA"""
    
    def __init__(self, gemini_model, supabase_client):
        self.gemini_model = gemini_model
        self.supabase = supabase_client
    
    def generate_gemini_prompt(self, user_input: str, current_date: str, user_id: str = "default_user") -> str:
        """Generate prompt for Gemini based on your actual schema"""
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
          "user_id": "{user_id}",
          "username": "User",
          "raw_input": "{user_input}",
          "exercises": [
            {{
              "name": "Exercise Name",
              "sets": [
                {{
                  "set_number": 1,
                  "metrics": [
                    {{
                      "type": "reps",
                      "value": 10,
                      "unit": "count"
                    }},
                    {{
                      "type": "weight", 
                      "value": 20.5,
                      "unit": "kg"
                    }}
                  ]
                }}
              ]
            }}
          ]
        }}
        """
    
    def parse_input(self, user_input: str, current_date: str = None, user_id: str = "default_user", trial_mode: bool = False) -> dict:
        """Parse user input using Gemini"""
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
        
        # Set user_id based on mode
        if trial_mode:
            user_id = "trial_user"
        
        try:
            prompt = self.generate_gemini_prompt(user_input, current_date, user_id)
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
    
    def get_or_create_exercise_type(self, exercise_name: str) -> int:
        """Get existing exercise type ID or create new one"""
        try:
            # Check if exercise exists in activity_names table
            result = self.supabase.table('activity_names').select('id').eq('canonical_name', exercise_name).execute()
            
            if result.data:
                return result.data[0]['id']
            else:
                # Create new exercise type
                new_exercise = {
                    'canonical_name': exercise_name,
                    'category': 'strength',  # Default category
                    'activity_type': 'Exercise'
                }
                result = self.supabase.table('activity_names').insert(new_exercise).execute()
                return result.data[0]['id']
        except Exception as e:
            print(f"Error with exercise type: {e}")
            raise
    
    def log_workout(self, workout_data: dict, trial_mode: bool = False) -> bool:
        """Log workout data to YOUR ACTUAL Supabase schema"""
        try:
            log_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))
            user_id = workout_data.get("user_id", "trial_user" if trial_mode else "default_user")
            username = workout_data.get("username", "Trial User" if trial_mode else "User")
            raw_input = workout_data.get("raw_input", "")
            
            # Process each exercise
            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name", "Unknown Exercise")
                
                # Get or create exercise type
                exercise_type_id = self.get_or_create_exercise_type(exercise_name)
                
                # Process each set
                for set_data in exercise.get("sets", []):
                    set_number = set_data.get("set_number", 1)
                    
                    # Create activity log entry (using correct table name)
                    log_result = self.supabase.table('activity_logs').insert({
                        'date': log_date,
                        'exercise_type_id': exercise_type_id,
                        'set_number': set_number,
                        'user_id': user_id,
                        'username': username,
                        'raw_input': raw_input
                    }).execute()
                    
                    exercise_log_id = log_result.data[0]['id']
                    
                    # Add metrics for this set
                    metrics = set_data.get("metrics", [])
                    for metric in metrics:
                        if metric.get("value") is not None:  # Only log non-null values
                            self.supabase.table('activity_metrics').insert({
                                'exercise_log_id': exercise_log_id,
                                'metric_type': metric.get("type"),
                                'value': metric.get("value"),
                                'unit': metric.get("unit")
                            }).execute()
            
            return True
        except Exception as e:
            print(f"Error logging workout: {e}")
            return False
    
    def delete_latest_exercise(self, user_id: str = "default_user") -> bool:
        """Delete the most recent exercise entry for this user"""
        try:
            # Get the latest exercise log for this user
            result = self.supabase.table('activity_logs').select('id').eq('user_id', user_id).order('created_at', desc=True).limit(1).execute()
            
            if result.data:
                exercise_log_id = result.data[0]['id']
                # Delete metrics first
                self.supabase.table('activity_metrics').delete().eq('exercise_log_id', exercise_log_id).execute()
                # Delete exercise log
                self.supabase.table('activity_logs').delete().eq('id', exercise_log_id).execute()
                return True
            return False
        except Exception as e:
            print(f"Error deleting exercise: {e}")
            return False
    
    def get_recent_workouts(self, days: int = 7, user_id: str = None) -> list:
        """Get recent workout data with proper joins - can filter by user or show all"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Build query
            query = self.supabase.table('activity_logs').select('*, activity_names(canonical_name)').gte('date', cutoff_date).order('date', desc=True)
            
            # Filter by user if specified
            if user_id:
                query = query.eq('user_id', user_id)
            
            result = query.execute()
            return result.data
        except Exception as e:
            print(f"Error getting workouts: {e}")
            return []
    
    def clear_trial_data(self) -> bool:
        """Clear all trial data from the database"""
        try:
            # Get all trial exercise logs
            trial_logs = self.supabase.table('activity_logs').select('id').eq('user_id', 'trial_user').execute()
            
            # Delete metrics for trial logs
            for log in trial_logs.data:
                self.supabase.table('activity_metrics').delete().eq('exercise_log_id', log['id']).execute()
            
            # Delete trial logs
            self.supabase.table('activity_logs').delete().eq('user_id', 'trial_user').execute()
            
            return True
        except Exception as e:
            print(f"Error clearing trial data: {e}")
            return False

# Initialize workout logger
workout_logger = WorkoutLogger(gemini_model, supabase) if gemini_model and supabase else None

@app.route('/')
def index():
    """Main page with input form and recent workouts"""
    recent_workouts = []
    if workout_logger:
        # Show both regular and trial workouts, but mark them differently
        recent_workouts = workout_logger.get_recent_workouts()
    
    return render_template('index.html', recent_workouts=recent_workouts)

@app.route('/log', methods=['POST'])
def log_workout():
    """Handle workout logging with trial mode support"""
    if not workout_logger:
        return jsonify({'success': False, 'error': 'System not initialized'})
    
    try:
        user_input = request.json.get('input', '').strip()
        trial_mode = request.json.get('trial_mode', False)
        
        if not user_input:
            return jsonify({'success': False, 'error': 'No input provided'})
        
        # Check if this is an edit command
        edit_keywords = ['delete', 'remove', 'edit', 'undo', 'clear']
        is_edit = any(keyword in user_input.lower() for keyword in edit_keywords)
        
        if is_edit:
            # Handle edit commands
            if 'latest' in user_input.lower() or 'last' in user_input.lower():
                user_id = "trial_user" if trial_mode else "default_user"
                success = workout_logger.delete_latest_exercise(user_id)
                if success:
                    mode_text = "trial" if trial_mode else "regular"
                    return jsonify({'success': True, 'message': f'Latest {mode_text} exercise deleted successfully!'})
                else:
                    return jsonify({'success': False, 'error': 'No exercise found to delete'})
            elif 'clear trial' in user_input.lower() or 'clear all trial' in user_input.lower():
                success = workout_logger.clear_trial_data()
                if success:
                    return jsonify({'success': True, 'message': 'All trial data cleared successfully!'})
                else:
                    return jsonify({'success': False, 'error': 'Failed to clear trial data'})
            else:
                return jsonify({'success': False, 'error': 'Edit command not recognized'})
        else:
            # Handle workout logging
            parsed_data = workout_logger.parse_input(user_input, trial_mode=trial_mode)
            success = workout_logger.log_workout(parsed_data, trial_mode=trial_mode)
            
            if success:
                if trial_mode:
                    return jsonify({'success': True, 'message': '🧪 Trial workout logged! (This won\'t affect your permanent records)'})
                else:
                    return jsonify({'success': True, 'message': '💪 Workout logged successfully to your fitness history!'})
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

@app.route('/clear-trials', methods=['POST'])
def clear_trials():
    """API endpoint to clear all trial data"""
    if not workout_logger:
        return jsonify({'success': False, 'error': 'System not initialized'})
    
    try:
        success = workout_logger.clear_trial_data()
        if success:
            return jsonify({'success': True, 'message': 'All trial data cleared successfully!'})
        else:
            return jsonify({'success': False, 'error': 'Failed to clear trial data'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
