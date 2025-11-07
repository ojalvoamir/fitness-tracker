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

# Configuration - FIXED TO USE GEMINI 2.0!
GEMINI_MODEL_NAME = 'gemini-2.0-flash-exp'  # ✅ CORRECTED MODEL NAME

# Initialize APIs
def initialize_apis():
    """Initialize Gemini and Supabase clients"""
    try:
        # Gemini API
        genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        
        # Supabase
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        supabase = create_client(supabase_url, supabase_key)
        
        return gemini_model, supabase
    except Exception as e:
        print(f"Error initializing APIs: {e}")
        return None, None

# Global variables
gemini_model, supabase = initialize_apis()

class WorkoutLogger:
    """Handle workout parsing and logging with trial mode support"""
    
    def __init__(self, gemini_model, supabase_client):
        self.gemini_model = gemini_model
        self.supabase = supabase_client
    
    def generate_gemini_prompt(self, user_input: str, current_date: str, user_id: str = "default_user") -> str:
        """Generate prompt for Gemini 2.0"""
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

    def parse_input_with_gemini(self, user_input: str, current_date: str = None, user_id: str = "default_user") -> dict:
        """Parse user input using Gemini 2.0"""
        if current_date is None:
            current_date = datetime.today().strftime('%Y-%m-%d')

        try:
            response = self.gemini_model.generate_content(
                self.generate_gemini_prompt(user_input, current_date, user_id)
            )
            response_text = response.text

            # Extract JSON from response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
            else:
                json_string = response_text.strip()

            parsed_data = json.loads(json_string)
            return parsed_data
        except Exception as e:
            print(f"Error parsing with Gemini: {e}")
            raise

    def log_workout_to_supabase(self, workout_data: dict, trial_mode: bool = False):
        """Log workout to Supabase (or simulate if trial_mode=True)"""
        if trial_mode:
            # Trial mode: just return success without saving
            return {
                "success": True,
                "message": "🧪 Trial mode: Workout parsed successfully but not saved to database",
                "parsed_data": workout_data
            }
        
        try:
            # Real mode: save to database
            log_date = workout_data.get("date", datetime.today().strftime('%Y-%m-%d'))
            user_id = workout_data.get("user_id", "default_user")
            username = workout_data.get("username", "User")
            raw_input = workout_data.get("raw_input", "")

            for exercise in workout_data.get("exercises", []):
                exercise_name = exercise.get("name", "Unknown Exercise")
                
                for set_data in exercise.get("sets", []):
                    # Insert into workouts table
                    workout_entry = {
                        "date": log_date,
                        "user_id": user_id,
                        "username": username,
                        "exercise_name": exercise_name,
                        "set_number": set_data.get("set_number", 1),
                        "weight_kg": set_data.get("weight_kg"),
                        "reps": set_data.get("reps"),
                        "distance_km": set_data.get("distance_km"),
                        "time_seconds": set_data.get("time_seconds"),
                        "notes": set_data.get("notes"),
                        "raw_input": raw_input
                    }
                    
                    result = self.supabase.table("workouts").insert(workout_entry).execute()

            return {
                "success": True,
                "message": "💪 Workout logged successfully!",
                "parsed_data": workout_data
            }
        except Exception as e:
            print(f"Error logging to Supabase: {e}")
            return {
                "success": False,
                "error": f"Database error: {str(e)}"
            }

# Initialize logger
workout_logger = WorkoutLogger(gemini_model, supabase)

@app.route('/')
def index():
    """Main page with recent workouts"""
    try:
        # Get recent workouts
        result = supabase.table("workouts").select("*").order("date", desc=True).limit(10).execute()
        recent_workouts = result.data if result.data else []
        
        return render_template('index.html', recent_workouts=recent_workouts)
    except Exception as e:
        print(f"Error loading recent workouts: {e}")
        return render_template('index.html', recent_workouts=[])

@app.route('/log', methods=['POST'])
def log_workout():
    """Handle workout logging with trial mode support"""
    try:
        data = request.get_json()
        user_input = data.get('input', '').strip()
        trial_mode = data.get('trial_mode', False)  # New: trial mode flag
        
        if not user_input:
            return jsonify({"success": False, "error": "Please enter a workout description"})

        # Parse with Gemini
        parsed_workout = workout_logger.parse_input_with_gemini(user_input)
        
        # Log to database (or simulate if trial mode)
        result = workout_logger.log_workout_to_supabase(parsed_workout, trial_mode=trial_mode)
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error in log_workout: {e}")
        return jsonify({"success": False, "error": f"An error occurred: {str(e)}"})

@app.route('/delete_latest', methods=['POST'])
def delete_latest():
    """Delete the most recent workout entry"""
    try:
        # Get the most recent workout
        result = supabase.table("workouts").select("*").order("created_at", desc=True).limit(1).execute()
        
        if not result.data:
            return jsonify({"success": False, "error": "No workouts found to delete"})
        
        latest_workout = result.data[0]
        workout_id = latest_workout['id']
        
        # Delete the workout
        supabase.table("workouts").delete().eq("id", workout_id).execute()
        
        return jsonify({"success": True, "message": "Latest workout deleted successfully"})
        
    except Exception as e:
        print(f"Error deleting workout: {e}")
        return jsonify({"success": False, "error": f"Error deleting workout: {str(e)}"})

if __name__ == '__main__':
    app.run(debug=True)
