import os
import re
import json
import sys
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)

# 🚀 LATEST GEMINI MODELS - Try newest first!
GEMINI_MODEL_NAMES = [
    'gemini-2.5-flash',          # 🔥 NEWEST & MOST CAPABLE (2024)
    'gemini-2.0-flash',          # 🚀 Very new (December 2024)  
    'gemini-2.0-flash-001',      # 🚀 Specific version
    'gemini-1.5-flash',          # Backup option
    'gemini-1.5-pro',            # Fallback
    'gemini-pro',                # Last resort
]

def find_best_gemini_model(api_key):
    """Try the latest Gemini models first, working down to older ones"""
    genai.configure(api_key=api_key)
    
    logger.info("🔍 Searching for the BEST available Gemini model...")
    
    # First, show all available models
    try:
        models = genai.list_models()
        available_models = [model.name for model in models]
        logger.info(f"📋 Found {len(available_models)} total models available")
        
        # Show Gemini models specifically
        gemini_models = [m for m in available_models if 'gemini' in m.lower()]
        logger.info(f"🤖 Available Gemini models: {gemini_models}")
        
    except Exception as e:
        logger.warning(f"⚠️ Could not list models: {e}")
        available_models = []
    
    # Try each model in order of preference (newest first)
    for model_name in GEMINI_MODEL_NAMES:
        try:
            logger.info(f"🧪 Testing model: {model_name}")
            model = genai.GenerativeModel(model_name)
            
            # Test with a simple prompt
            response = model.generate_content("Say 'Hello from " + model_name + "'")
            if response and response.text:
                logger.info(f"🎉 SUCCESS! Using model: {model_name}")
                logger.info(f"📝 Test response: {response.text.strip()}")
                return model, model_name
                
        except Exception as e:
            logger.warning(f"❌ Model {model_name} failed: {str(e)[:100]}...")
            continue
    
    # If nothing works, return None
    logger.error("💥 No working Gemini model found!")
    return None, None

def test_supabase_connection(supabase_client):
    """Test Supabase connection and schema with updated column names"""
    try:
        logger.info("🧪 Testing Supabase connection and schema...")
        
        # Test 1: Basic connection
        logger.info("🔗 Testing basic connection...")
        test_result = supabase_client.table('activity_logs').select('id').limit(1).execute()
        logger.info("✅ Basic connection successful")
        
        # Test 2: Check if we can see the schema
        logger.info("🔍 Testing schema access...")
        schema_test = supabase_client.table('activity_logs').select('*').limit(1).execute()
        if schema_test.data:
            logger.info(f"✅ Schema test successful - found {len(schema_test.data)} records")
            logger.info(f"📋 Sample record keys: {list(schema_test.data[0].keys()) if schema_test.data else 'No data'}")
        else:
            logger.info("ℹ️ Schema test successful but no data found")
        
        # Test 3: Try a simple insert to check permissions with new column names
        logger.info("🧪 Testing insert permissions with updated schema...")
        test_data = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'activity_name': 'connection_test',  # Updated column name
            'activity_type': 'exercise',  # New activity type column (only exercise or measurement)
            'set_number': 1,
            'metric_type': 'test',
            'value': 1,
            'unit': 'test',
            'user_id': 'test_user',
            'username': 'Test User',
            'raw_input': 'Connection test',
            'notes': 'Test connection note'  # New notes column
        }
        
        # Try the insert
        insert_result = supabase_client.table('activity_logs').insert(test_data).execute()
        
        # If successful, delete the test record
        if insert_result.data:
            test_id = insert_result.data[0]['id']
            supabase_client.table('activity_logs').delete().eq('id', test_id).execute()
            logger.info("✅ Insert/delete permissions successful with new schema")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Supabase test failed: {e}")
        logger.error(f"🔍 Error details: {type(e).__name__}: {str(e)}")
        return False

def initialize_apis():
    """Initialize Gemini and Supabase clients with latest models"""
    try:
        logger.info("🔑 Starting API initialization...")
        
        # Check environment variables
        required_vars = {
            'GOOGLE_API_KEY': os.getenv('GOOGLE_API_KEY'),
            'SUPABASE_URL': os.getenv('SUPABASE_URL'), 
            'SUPABASE_ANON_KEY': os.getenv('SUPABASE_ANON_KEY')
        }
        
        # Log what we found
        for var_name, var_value in required_vars.items():
            if var_value:
                logger.info(f"✅ {var_name}: Found (length: {len(var_value)})")
            else:
                logger.error(f"❌ {var_name}: MISSING!")
        
        # Check if any are missing
        missing_vars = [name for name, value in required_vars.items() if not value]
        if missing_vars:
            raise ValueError(f"Missing environment variables: {', '.join(missing_vars)}")
        
        # Find the best Gemini model
        logger.info("🤖 Finding the BEST Gemini model...")
        gemini_model, model_name = find_best_gemini_model(required_vars['GOOGLE_API_KEY'])
        
        if not gemini_model:
            raise ValueError("No working Gemini model found")
        
        logger.info(f"✅ Gemini initialized successfully with: {model_name}")
        
        # Initialize Supabase
        logger.info("🗄️ Initializing Supabase...")
        try:
            supabase = create_client(
                required_vars['SUPABASE_URL'], 
                required_vars['SUPABASE_ANON_KEY']
            )
            
            # Test Supabase connection thoroughly
            connection_ok = test_supabase_connection(supabase)
            if not connection_ok:
                raise ValueError("Supabase connection test failed")
            
            logger.info("✅ Supabase initialized and tested successfully")
            
        except Exception as e:
            logger.error(f"❌ Supabase initialization failed: {e}")
            raise ValueError(f"Supabase initialization failed: {e}")
        
        return gemini_model, supabase, model_name
        
    except Exception as e:
        logger.error(f"❌ CRITICAL: API initialization failed: {e}")
        return None, None, None

# Try to initialize APIs
logger.info("🚀 Starting API initialization...")
gemini_model, supabase, working_model_name = initialize_apis()

# Log final status
if gemini_model and supabase:
    logger.info(f"🎉 ALL SYSTEMS GO! Using: {working_model_name}")
else:
    logger.error("💥 SYSTEM INITIALIZATION FAILED")

class WorkoutLogger:
    """Advanced workout logger with improved notes handling and simplified activity types"""
    
    def __init__(self, gemini_model, supabase_client):
        if not gemini_model or not supabase_client:
            raise ValueError("Cannot initialize WorkoutLogger: APIs not available")
        self.gemini_model = gemini_model
        self.supabase = supabase_client
        logger.info("💪 WorkoutLogger initialized successfully")
    
    def determine_activity_type(self, activity_name: str) -> str:
        """Determine if an activity is exercise or measurement (NO CARDIO CATEGORY)"""
        activity_lower = activity_name.lower()
        
        # Body measurements - these are the ONLY things that get 'measurement' type
        measurement_keywords = [
            'weight', 'body weight', 'bodyweight', 'body fat', 'bodyfat', 'body mass',
            'height', 'waist', 'chest', 'arm', 'leg', 'neck', 'hip', 'measurement',
            'body composition', 'bmi', 'muscle mass', 'fat percentage', 'circumference'
        ]
        
        # Check for measurements
        if any(keyword in activity_lower for keyword in measurement_keywords):
            return 'measurement'
        
        # EVERYTHING ELSE is 'exercise' - running, cycling, pull-ups, squats, etc.
        return 'exercise'
    
    def generate_gemini_prompt(self, user_input: str, current_date: str, user_id: str = "default_user") -> str:
        """Enhanced prompt with better notes handling and simplified activity types"""
        return f"""
Today's date is {current_date}.
You are an advanced fitness tracking AI. Convert the following workout description into structured JSON.

CRITICAL INSTRUCTIONS FOR NOTES:
- Notes should be associated with the SPECIFIC exercise they relate to
- If notes mention a specific exercise, attach them ONLY to that exercise
- If notes are general (like "good workout"), attach to the first exercise only
- If no specific exercise is mentioned, attach to the exercise immediately before the note

INSTRUCTIONS:
- Extract the date from input if specified (e.g., 'today', 'yesterday', specific dates)
- Use today's date if no date is specified
- Return ONLY valid JSON, no additional text
- Use consistent activity names (e.g., "pull-up" not "pullup", "push-up" not "pushup")
- Be smart about exercise variations (e.g., "chin-ups" vs "pull-ups")
- ALL TIME VALUES must be in SECONDS (convert minutes to seconds: 5 min = 300 sec)
- Activity types: ONLY 'exercise' or 'measurement' (NO CARDIO - running/cycling = exercise)

INPUT: "{user_input}"

OUTPUT FORMAT (JSON only):
{{
  "date": "YYYY-MM-DD",
  "user_id": "{user_id}",
  "username": "User",
  "raw_input": "{user_input}",
  "exercises": [
    {{
      "name": "Activity Name",
      "activity_type": "exercise|measurement",
      "notes": "notes specific to THIS exercise only, or null",
      "sets": [
        {{
          "set_number": 1,
          "metrics": [
            {{
              "type": "reps",
              "value": 10,
              "unit": "reps"
            }},
            {{
              "type": "weight",
              "value": 20.5,
              "unit": "kg"
            }},
            {{
              "type": "time",
              "value": 300,
              "unit": "sec"
            }},
            {{
              "type": "distance",
              "value": 5.0,
              "unit": "km"
            }}
          ]
        }}
      ]
    }}
  ]
}}

EXAMPLES OF PROPER NOTE HANDLING:
- "5 pull ups, shoulder pain. 5 deadlifts 50kg" 
  → pull-ups: notes="shoulder pain", deadlifts: notes=null
  
- "bench press 80kg 5 reps, easy set. squats 100kg 3 reps"
  → bench press: notes="easy set", squats: notes=null
  
- "ran 5km in 25 minutes, felt tired. 10 push ups"
  → running: notes="felt tired", push-ups: notes=null
  
- "weighed myself, 75kg. did 10 push ups, good form"
  → body weight: notes=null, push-ups: notes="good form"

ACTIVITY TYPE EXAMPLES (SIMPLIFIED):
- "pull-ups", "bench press", "squats", "running", "cycling" → "exercise"
- "body weight", "waist measurement", "body fat" → "measurement"
"""
    
    def parse_input(self, user_input: str, current_date: str = None, user_id: str = "default_user") -> dict:
        """Parse user input using latest Gemini model with improved notes handling"""
        if current_date is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            logger.info(f"🤖 Parsing with {working_model_name}: '{user_input}'")
            prompt = self.generate_gemini_prompt(user_input, current_date, user_id)
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text
            
            # Extract JSON from response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_string = json_match.group(1).strip()
            else:
                json_string = response_text.strip()
            
            parsed_data = json.loads(json_string)
            logger.info("✅ Successfully parsed JSON from Gemini")
            
            # Post-process to ensure activity_type is set correctly
            for exercise in parsed_data.get('exercises', []):
                if 'activity_type' not in exercise or not exercise['activity_type']:
                    exercise['activity_type'] = self.determine_activity_type(exercise.get('name', ''))
                
                # Log notes for debugging
                if exercise.get('notes'):
                    logger.info(f"📝 Notes for {exercise['name']}: '{exercise['notes']}'")
            
            return parsed_data
        except Exception as e:
            logger.error(f"❌ Error parsing input: {e}")
            logger.error(f"Raw response: {response_text[:200]}...")
            raise
    
    def log_workout(self, workout_data: dict) -> bool:
        """Log workout data to database with improved schema"""
        try:
            logger.info(f"📝 Logging workout data")
            
            log_date = workout_data.get("date", datetime.now().strftime('%Y-%m-%d'))
            user_id = workout_data.get("user_id", "default_user")
            username = workout_data.get("username", "User")
            raw_input = workout_data.get("raw_input", "")
            
            # Prepare all rows for batch insert
            rows_to_insert = []
            
            for exercise in workout_data.get("exercises", []):
                activity_name = exercise.get("name", "Unknown Activity")
                activity_type = exercise.get("activity_type", "exercise")
                exercise_notes = exercise.get("notes")  # Notes specific to this exercise
                
                for set_data in exercise.get("sets", []):
                    set_number = set_data.get("set_number", 1)
                    
                    # Each metric becomes one row
                    for metric in set_data.get("metrics", []):
                        if metric.get("value") is not None:
                            row_data = {
                                'date': log_date,
                                'activity_name': activity_name,
                                'activity_type': activity_type,  # Only 'exercise' or 'measurement'
                                'set_number': set_number,
                                'metric_type': metric.get("type"),
                                'value': float(metric.get("value")),
                                'unit': metric.get("unit"),
                                'user_id': user_id,
                                'username': username,
                                'raw_input': raw_input,
                                'notes': exercise_notes  # Exercise-specific notes
                            }
                            rows_to_insert.append(row_data)
            
            if not rows_to_insert:
                logger.warning("⚠️ No workout data to insert")
                return False
            
            logger.info(f"📊 Preparing to insert {len(rows_to_insert)} records")
            logger.info(f"🔍 Sample record: {rows_to_insert[0]}")
            
            # Single batch insert with better error handling
            try:
                result = self.supabase.table('activity_logs').insert(rows_to_insert).execute()
                
                if result.data:
                    logger.info(f"✅ Successfully inserted {len(result.data)} workout records")
                    
                    # Log summary of what was inserted
                    activities_logged = {}
                    for row in rows_to_insert:
                        activity = row['activity_name']
                        activity_type = row['activity_type']
                        notes = row['notes']
                        key = f"{activity} ({activity_type})"
                        if key not in activities_logged:
                            activities_logged[key] = {'count': 0, 'notes': notes}
                        activities_logged[key]['count'] += 1
                    
                    logger.info("📋 Activities logged:")
                    for activity, info in activities_logged.items():
                        notes_str = f" - Notes: {info['notes']}" if info['notes'] else ""
                        logger.info(f"   • {activity}: {info['count']} records{notes_str}")
                    
                    return True
                else:
                    logger.error("❌ Insert returned no data")
                    return False
                    
            except Exception as insert_error:
                logger.error(f"❌ Database insert error: {insert_error}")
                logger.error(f"🔍 Error type: {type(insert_error).__name__}")
                
                # Try to get more details about the error
                if hasattr(insert_error, 'details'):
                    logger.error(f"🔍 Error details: {insert_error.details}")
                
                # If it's a schema error, try to diagnose
                if 'schema' in str(insert_error).lower() or 'column' in str(insert_error).lower():
                    logger.error("🚨 This looks like a schema/column issue!")
                    logger.error("💡 Possible solutions:")
                    logger.error("   1. Run the database migration script first")
                    logger.error("   2. Check if 'activity_name', 'activity_type', and 'notes' columns exist")
                    logger.error("   3. Verify RLS (Row Level Security) policies")
                
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in log_workout: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            return False
    
    def delete_latest_exercise(self, user_id: str = "default_user") -> bool:
        """Delete the most recent exercise entry"""
        try:
            # Get the latest exercise entry
            result = self.supabase.table('activity_logs')\
                .select('date, activity_name')\
                .eq('user_id', user_id)\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if result.data:
                latest = result.data[0]
                # Delete all entries for this activity on this date
                self.supabase.table('activity_logs')\
                    .delete()\
                    .eq('user_id', user_id)\
                    .eq('date', latest['date'])\
                    .eq('activity_name', latest['activity_name'])\
                    .execute()
                
                logger.info(f"✅ Deleted latest activity: {latest['activity_name']}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error deleting activity: {e}")
            return False
    
    def get_recent_workouts(self, days: int = 7, user_id: str = "default_user", activity_type: str = None) -> list:
        """Get recent workout data, optionally filtered by activity type"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            query = self.supabase.table('activity_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', cutoff_date)
            
            # Add activity type filter if specified
            if activity_type:
                query = query.eq('activity_type', activity_type)
            
            result = query.order('created_at', desc=True).limit(50).execute()
            
            logger.info(f"📊 Retrieved {len(result.data)} recent workout records")
            if activity_type:
                logger.info(f"🎯 Filtered by activity type: {activity_type}")
            
            return result.data
        except Exception as e:
            logger.error(f"❌ Error getting workouts: {e}")
            return []

# Initialize workout logger only if APIs are available
workout_logger = None
if gemini_model and supabase:
    try:
        workout_logger = WorkoutLogger(gemini_model, supabase)
        logger.info("💪 WorkoutLogger created successfully")
    except Exception as e:
        logger.error(f"❌ Failed to create WorkoutLogger: {e}")

@app.route('/')
def index():
    """Main page with input form and recent workouts"""
    recent_workouts = []
    if workout_logger:
        recent_workouts = workout_logger.get_recent_workouts()
    
    return render_template('index.html', recent_workouts=recent_workouts)

@app.route('/log', methods=['POST'])
def log_workout():
    """Handle workout logging with improved notes handling"""
    if not workout_logger:
        logger.error("❌ Workout logger not available - system not initialized")
        return jsonify({
            'success': False, 
            'error': 'System not initialized. Check server logs for API initialization errors.'
        })
    
    try:
        user_input = request.json.get('input', '').strip()
        if not user_input:
            return jsonify({'success': False, 'error': 'No input provided'})
        
        # Check if this is an edit command
        edit_keywords = ['delete', 'remove', 'edit', 'undo', 'clear']
        is_edit = any(keyword in user_input.lower() for keyword in edit_keywords)
        
        if is_edit:
            if 'latest' in user_input.lower() or 'last' in user_input.lower():
                success = workout_logger.delete_latest_exercise()
                if success:
                    return jsonify({'success': True, 'message': 'Latest activity deleted successfully!'})
                else:
                    return jsonify({'success': False, 'error': 'No activity found to delete'})
            else:
                return jsonify({'success': False, 'error': 'Edit command not recognized'})
        else:
            # Handle workout logging
            parsed_data = workout_logger.parse_input(user_input)
            success = workout_logger.log_workout(parsed_data)
            
            if success:
                # Create detailed success message
                activities = []
                for exercise in parsed_data.get('exercises', []):
                    activity_name = exercise.get('name', 'Unknown')
                    activity_type = exercise.get('activity_type', 'exercise')
                    notes = exercise.get('notes')
                    
                    activity_str = f"{activity_name} ({activity_type})"
                    if notes:
                        activity_str += f" - {notes}"
                    activities.append(activity_str)
                
                activities_msg = "; ".join(activities)
                return jsonify({
                    'success': True, 
                    'message': f'Logged: {activities_msg}',
                    'model': working_model_name
                })
            else:
                return jsonify({'success': False, 'error': 'Failed to log workout - check server logs for details'})
    
    except Exception as e:
        logger.error(f"❌ Exception in log_workout: {e}")
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/workouts')
def get_workouts():
    """API endpoint to get recent workouts"""
    if not workout_logger:
        return jsonify([])
    
    # Get optional activity type filter
    activity_type = request.args.get('type')
    workouts = workout_logger.get_recent_workouts(activity_type=activity_type)
    return jsonify(workouts)

@app.route('/health')
def health():
    """Health check endpoint with model info"""
    env_vars = {
        'GOOGLE_API_KEY': '✅ Set' if os.getenv('GOOGLE_API_KEY') else '❌ Missing',
        'SUPABASE_URL': '✅ Set' if os.getenv('SUPABASE_URL') else '❌ Missing',
        'SUPABASE_ANON_KEY': '✅ Set' if os.getenv('SUPABASE_ANON_KEY') else '❌ Missing'
    }
    
    return jsonify({
        'status': 'healthy' if workout_logger else 'degraded',
        'gemini_initialized': gemini_model is not None,
        'supabase_initialized': supabase is not None,
        'workout_logger_initialized': workout_logger is not None,
        'active_model': working_model_name if working_model_name else 'None',
        'model_preference_order': GEMINI_MODEL_NAMES,
        'environment_variables': env_vars,
        'schema_version': '2.2 - activity_name, activity_type (exercise/measurement only), notes_per_exercise',
        'features': [
            'Exercise-specific notes handling',
            'Simplified activity types: exercise OR measurement only',
            'Latest Gemini 2.5 Flash support',
            'Improved error handling'
        ],
        'activity_types': ['exercise', 'measurement'],  # Only these two
        'timestamp': datetime.now().isoformat()
    })

@app.route('/models')
def list_models():
    """List all available Gemini models"""
    try:
        if not os.getenv('GOOGLE_API_KEY'):
            return jsonify({'error': 'No API key available'})
        
        genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
        models = genai.list_models()
        
        all_models = []
        gemini_models = []
        
        for model in models:
            model_info = {
                'name': model.name,
                'display_name': getattr(model, 'display_name', 'N/A'),
                'supported_methods': list(getattr(model, 'supported_generation_methods', []))
            }
            all_models.append(model_info)
            
            if 'gemini' in model.name.lower():
                gemini_models.append(model_info)
        
        return jsonify({
            'current_model': working_model_name,
            'preference_order': GEMINI_MODEL_NAMES,
            'available_gemini_models': gemini_models,
            'total_models': len(all_models),
            'all_models': all_models
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/test-db')
def test_database():
    """Test database connection and permissions"""
    if not supabase:
        return jsonify({'error': 'Supabase not initialized'})
    
    try:
        # Test connection
        connection_ok = test_supabase_connection(supabase)
        
        return jsonify({
            'connection_test': 'passed' if connection_ok else 'failed',
            'schema_version': '2.2 - activity_name, activity_type (exercise/measurement only), notes_per_exercise',
            'activity_types': ['exercise', 'measurement'],
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/stats')
def get_stats():
    """Get activity statistics by type (simplified)"""
    if not workout_logger:
        return jsonify({'error': 'Workout logger not available'})
    
    try:
        # Get data for the two activity types
        exercises = workout_logger.get_recent_workouts(days=30, activity_type='exercise')
        measurements = workout_logger.get_recent_workouts(days=30, activity_type='measurement')
        
        stats = {
            'exercise_count': len(exercises),
            'measurement_count': len(measurements),
            'total_activities': len(exercises) + len(measurements),
            'recent_exercises': exercises[:5],
            'recent_measurements': measurements[:5],
            'activity_types': ['exercise', 'measurement']  # Only these two
        }
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🌐 Starting Flask app on port {port}")
    if working_model_name:
        logger.info(f"🤖 Powered by: {working_model_name}")
    logger.info("🔄 Schema version: 2.2 (activity_name, activity_type: exercise/measurement only)")
    logger.info("✨ Features: Exercise-specific notes, Simplified activity types")
    app.run(host='0.0.0.0', port=port, debug=False)
