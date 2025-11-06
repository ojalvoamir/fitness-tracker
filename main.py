import os
import re
import json
import sys
import traceback
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

# FORCE LOGGING CONFIGURATION
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

# Force stdout to flush immediately
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
GEMINI_MODEL_NAME = 'gemini-2.5-flash'

def debug_log(message):
    """Force debug logging to multiple outputs"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatted_msg = f"[{timestamp}] {message}"
    
    # Print to stdout
    print(formatted_msg, flush=True)
    
    # Log using logger
    logger.info(formatted_msg)
    
    # Force flush
    sys.stdout.flush()
    sys.stderr.flush()

# Initialize APIs
def initialize_apis():
    """Initialize Gemini and Supabase clients"""
    debug_log("🚀 STARTING API INITIALIZATION")
    
    try:
        # Gemini API
        debug_log("🤖 Initializing Gemini API...")
        google_api_key = os.getenv('GOOGLE_API_KEY')
        if not google_api_key:
            debug_log("❌ GOOGLE_API_KEY environment variable not found")
            raise ValueError("GOOGLE_API_KEY environment variable not found")
        
        genai.configure(api_key=google_api_key)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        debug_log("✅ Gemini API initialized successfully")
        
        # Supabase
        debug_log("🗄️ Initializing Supabase...")
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        
        debug_log(f"🔍 SUPABASE_URL exists: {bool(supabase_url)}")
        debug_log(f"🔍 SUPABASE_KEY exists: {bool(supabase_key)}")
        
        if not supabase_url:
            debug_log("❌ SUPABASE_URL environment variable not found")
            raise ValueError("SUPABASE_URL environment variable not found")
        if not supabase_key:
            debug_log("❌ SUPABASE_KEY environment variable not found")
            raise ValueError("SUPABASE_KEY environment variable not found")
        
        supabase = create_client(supabase_url, supabase_key)
        debug_log("✅ Supabase client created")
        
        # Test Supabase connection
        debug_log("🧪 Testing Supabase connection...")
        try:
            test_result = supabase.table('exercise_logs').select('count').limit(1).execute()
            debug_log(f"✅ Supabase connection test successful: {test_result}")
        except Exception as e:
            debug_log(f"⚠️ Supabase connection test failed: {e}")
            debug_log(f"⚠️ Supabase test error traceback: {traceback.format_exc()}")
        
        debug_log("🎉 ALL APIs INITIALIZED SUCCESSFULLY")
        return gemini_model, supabase
        
    except Exception as e:
        debug_log(f"❌ CRITICAL ERROR initializing APIs: {e}")
        debug_log(f"❌ Full traceback: {traceback.format_exc()}")
        return None, None

# Global variables
debug_log("🌍 Initializing global variables...")
gemini_model, supabase = initialize_apis()

class WorkoutLogger:
    """Handle workout parsing and logging"""
    
    def __init__(self, gemini_model, supabase_client):
        debug_log("🏋️ Initializing WorkoutLogger...")
        self.gemini_model = gemini_model
        self.supabase = supabase_client
        debug_log("✅ WorkoutLogger initialized")
    
    def generate_gemini_prompt(self, user_input: str, current_date: str, is_edit: bool = False) -&gt; str:
        """Generate prompt for Gemini based on input type"""
        debug_log(f"📝 Generating prompt for: '{user_input}' (edit: {is_edit})")
        
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
    
    def parse_input(self, user_input: str, current_date: str = None, is_edit: bool = False) -&gt; dict:
        """Parse user input using Gemini"""
        debug_log(f"🤖 STARTING PARSE for: '{user_input}'")
        
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            debug_log(f"🤖 STEP 1: Generating prompt...")
            prompt = self.generate_gemini_prompt(user_input, current_date, is_edit)
            debug_log(f"🤖 STEP 1 COMPLETE: Prompt generated")
            
            debug_log(f"🤖 STEP 2: Calling Gemini API...")
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text
            debug_log(f"🤖 STEP 2 COMPLETE: Response received (length: {len(response_text)})")
            debug_log(f"🤖 Response preview: {response_text[:100]}...")
            
            # Extract JSON from response
            debug_log(f"🤖 STEP 3: Extracting JSON...")
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
                debug_log(f"🤖 STEP 3A: Found JSON in code block")
            else:
                json_string = response_text.strip()
                debug_log(f"🤖 STEP 3B: Using raw response as JSON")
            
            debug_log(f"🤖 STEP 4: Parsing JSON string: {json_string}")
            parsed_data = json.loads(json_string)
            debug_log(f"✅ PARSE SUCCESS: {parsed_data}")
            return parsed_data
            
        except Exception as e:
            debug_log(f"❌ PARSE ERROR: {e}")
            debug_log(f"❌ Full traceback: {traceback.format_exc()}")
            raise
    
    def log_workout(self, workout_data: dict) -&gt; bool:
        """Log workout data to Supabase"""
        debug_log(f"📝 STARTING WORKOUT LOG")
        debug_log(f"📝 Workout data: {workout_data}")
        
        try:
            log_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))
            debug_log(f"📝 Log date: {log_date}")
            
            exercises = workout_data.get("exercises", [])
            debug_log(f"📝 Number of exercises: {len(exercises)}")
            
            for exercise_idx, exercise in enumerate(exercises):
                exercise_name = exercise.get("name", "Unknown Exercise")
                debug_log(f"📝 Exercise {exercise_idx + 1}: {exercise_name}")
                
                sets = exercise.get("sets", [])
                debug_log(f"📝 Number of sets: {len(sets)}")
                
                for set_idx, set_data in enumerate(sets):
                    debug_log(f"📝 Processing set {set_idx + 1}: {set_data}")
                    
                    # Prepare data for insertion
                    data = {
                        "user_id": "default_user",
                        "date": log_date,
                        "exercise_name": exercise_name,
                        "set_number": set_data.get("set_id", 1),
                        "weight_kg": set_data.get("weight_kg"),
                        "reps": set_data.get("reps"),
                        "distance_km": set_data.get("distance_km"),
                        "time_seconds": set_data.get("time_seconds"),
                        "notes": set_data.get("notes")
                    }
                    
                    debug_log(f"📝 INSERT DATA: {data}")
                    
                    try:
                        debug_log(f"📝 Calling Supabase insert...")
                        result = self.supabase.table('exercise_logs').insert(data).execute()
                        debug_log(f"📝 INSERT SUCCESS: {result}")
                        debug_log(f"    ✅ Set {set_data.get('set_id', 1)} logged successfully")
                        
                    except Exception as insert_error:
                        debug_log(f"❌ INSERT FAILED: {insert_error}")
                        debug_log(f"❌ Insert traceback: {traceback.format_exc()}")
                        raise insert_error
                    
            debug_log("🎉 ALL EXERCISES LOGGED SUCCESSFULLY!")
            return True
            
        except Exception as e:
            debug_log(f"❌ WORKOUT LOG FAILED: {e}")
            debug_log(f"❌ Full traceback: {traceback.format_exc()}")
            return False
    
    def get_recent_workouts(self, days: int = 7) -&gt; list:
        """Get recent workout data"""
        debug_log(f"📊 Getting recent workouts (last {days} days)")
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            debug_log(f"📊 Cutoff date: {cutoff_date}")
            
            result = self.supabase.table('exercise_logs')\
                .select('*')\
                .eq('user_id', 'default_user')\
                .gte('date', cutoff_date)\
                .order('date', desc=True)\
                .execute()
            
            debug_log(f"📊 Retrieved {len(result.data)} workout entries")
            return result.data
        except Exception as e:
            debug_log(f"❌ Error getting workouts: {e}")
            debug_log(f"❌ Traceback: {traceback.format_exc()}")
            return []

# Initialize workout logger
debug_log("🏋️ Creating WorkoutLogger instance...")
if gemini_model and supabase:
    workout_logger = WorkoutLogger(gemini_model, supabase)
    debug_log("✅ WorkoutLogger created successfully")
else:
    workout_logger = None
    debug_log("❌ WorkoutLogger creation failed - APIs not available")

@app.route('/')
def index():
    """Main page with input form and recent workouts"""
    debug_log("🌐 INDEX route called")
    recent_workouts = []
    if workout_logger:
        recent_workouts = workout_logger.get_recent_workouts()
    debug_log(f"🌐 Rendering index with {len(recent_workouts)} recent workouts")
    return render_template('index.html', recent_workouts=recent_workouts)

@app.route('/log', methods=['POST'])
def log_workout():
    """Handle workout logging"""
    debug_log("\n" + "="*60)
    debug_log("🚀 NEW WORKOUT LOG REQUEST RECEIVED")
    debug_log("="*60)
    
    if not workout_logger:
        debug_log("❌ Workout logger not available")
        return jsonify({'success': False, 'error': 'System not initialized'})
    
    try:
        debug_log("📥 Getting request data...")
        request_data = request.get_json()
        debug_log(f"📥 Request data: {request_data}")
        
        user_input = request_data.get('input', '').strip() if request_data else ''
        debug_log(f"📥 User input: '{user_input}'")
        
        if not user_input:
            debug_log("❌ No input provided")
            return jsonify({'success': False, 'error': 'No input provided'})
        
        # Check if this is an edit command
        edit_keywords = ['delete', 'remove', 'edit', 'undo', 'clear']
        is_edit = any(keyword in user_input.lower() for keyword in edit_keywords)
        debug_log(f"🔍 Is edit command: {is_edit}")
        
        if is_edit:
            debug_log("🔄 Processing edit command")
            return jsonify({'success': False, 'error': 'Edit commands not implemented yet'})
        else:
            debug_log("📝 Processing workout logging")
            
            # Parse input
            debug_log("🤖 Starting input parsing...")
            parsed_data = workout_logger.parse_input(user_input)
            debug_log("✅ Input parsing completed")
            
            # Log workout
            debug_log("📝 Starting workout logging...")
            success = workout_logger.log_workout(parsed_data)
            debug_log(f"📝 Workout logging result: {success}")
            
            if success:
                debug_log("🎉 WORKOUT LOGGED SUCCESSFULLY!")
                return jsonify({'success': True, 'message': 'Workout logged successfully!'})
            else:
                debug_log("❌ WORKOUT LOGGING FAILED!")
                return jsonify({'success': False, 'error': 'Failed to log workout'})
                
    except Exception as e:
        debug_log(f"❌ EXCEPTION in log_workout: {e}")
        debug_log(f"❌ Exception traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/health')
def health_check():
    """Health check endpoint"""
    debug_log("🏥 Health check requested")
    status = {
        'gemini_available': gemini_model is not None,
        'supabase_available': supabase is not None,
        'workout_logger_available': workout_logger is not None
    }
    debug_log(f"🏥 Health status: {status}")
    return jsonify(status)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_log(f"🚀 Starting Flask app on port {port}")
    debug_log("🚀 App startup complete - ready to receive requests")
    app.run(host='0.0.0.0', port=port, debug=False)
