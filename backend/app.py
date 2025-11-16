from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client
import os
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
# NEW IMPORT required for non-interactive token refresh
import google.auth.transport.requests 

# Load env
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

try:
    # Attempt to initialize Supabase client
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
except Exception as e:
    print(f"Supabase Client Error: {e}")
    supabase = None 

# Global variable to store the Drive service object (FIX: Prevents repeated authentication)
DRIVE_SERVICE = None 

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


# Google Drive API
SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]

# Map of required labels used in the database
REQUIRED_LABELS = ["photo", "aadhar", "community", "marksheet", "tc"]

# MAPPING for Code-based detection (s1 -> photo, s2 -> aadhar, etc.)
FILE_CODE_MAP = {
    "s1": "photo",
    "s2": "aadhar",
    "s3": "community",
    "s4": "marksheet",
    "s5": "tc"
}


def authenticate_drive_service():
    """
    Handles initial authentication and returns the service object.
    This is called once at startup.
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token is expired but can be refreshed non-interactively
            print("Refreshing Google Drive token...")
            creds.refresh(google.auth.transport.requests.Request())
        else:
            # No valid token, start interactive flow (pops up browser)
            print("Starting Google Drive interactive authentication flow...")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the new/refreshed token
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def scan_drive_folder(folder_id: str):
    """
    Uses dual detection logic: checks for label match OR code prefix match.
    """
    global DRIVE_SERVICE 
    
    if DRIVE_SERVICE is None:
        raise Exception("Drive service not initialized globally.")

    results = DRIVE_SERVICE.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(name)",
        pageSize=1000
    ).execute()
    
    files = [f["name"].lower() for f in results.get("files", [])]
    
    # Stores the labels of the documents that were found (e.g., "photo", "aadhar")
    found_labels = set()
    
    for file_name in files:
        # Check 1: Keyword match (e.g., 'photo' in 'my_passport_photo.pdf')
        for label in REQUIRED_LABELS:
            if label in file_name:
                found_labels.add(label)
        
        # Check 2: Code prefix match (e.g., file name starts with 's1' or 's2')
        for code, label in FILE_CODE_MAP.items():
            if file_name.startswith(code):
                found_labels.add(label)
                
    # Determine missing files based on the primary labels list
    found_files_list = sorted(list(found_labels))
    missing_files = [f for f in REQUIRED_LABELS if f not in found_files_list]
    status = "Complete" if not missing_files else "Incomplete"

    return {"found_files": found_files_list, "missing_files": missing_files, "status": status}


@app.route("/verify", methods=["POST"])
def verify():
    if supabase is None:
        return jsonify({"error": "Database connection failed to initialize."}), 500
        
    try:
        data = request.get_json()
        name = data.get("name")
        serial_no = data.get("serial_no")
        drive_link = data.get("drive_link")

        if not (name and serial_no and drive_link):
            return jsonify({"error": "name, serial_no and drive_link are required"}), 400

        existing = (
            supabase.table("student_verifications")
            .select("*")
            .eq("serial_no", serial_no)
            .execute()
        )

        if existing.data:
            return jsonify({"result": existing.data[0]})

        if "folders/" not in drive_link:
            return jsonify({"error": "Invalid Google Drive folder link"}), 400

        folder_id = drive_link.split("folders/")[1].split("?")[0]

        res = scan_drive_folder(folder_id)

        record = {
            "name": name,
            "serial_no": serial_no,
            "drive_link": drive_link,
            "status": res["status"],
            "found_files": res["found_files"],
            "missing_files": res["missing_files"],
        }

        supabase.table("student_verifications").insert(record).execute()

        return jsonify({"result": record})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/students", methods=["GET"]) 
def get_all_students():
    if supabase is None:
        return jsonify({"error": "Database connection failed to initialize."}), 500
        
    try:
        data = supabase.table("student_verifications").select("*").execute()
        return jsonify({"data": data.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/refresh/<serial_no>", methods=["POST"])
def refresh_student(serial_no):
    if supabase is None:
        return jsonify({"error": "Database connection failed to initialize."}), 500
        
    try:
        serial = serial_no.strip()
        resp = supabase.table("student_verifications").select("*").eq("serial_no", serial).execute()
        rows = resp.data or []
        if not rows:
            return jsonify({"error": "Student not found"}), 404

        student = rows[0]
        drive_link = student.get("drive_link")
        if not drive_link or "folders/" not in drive_link:
            return jsonify({"error": "No valid drive_link found for this student"}), 400

        folder_id = drive_link.split("folders/")[1].split("?")[0]

        res = scan_drive_folder(folder_id)

        updated_record = {
            "found_files": res["found_files"],
            "missing_files": res["missing_files"],
            "status": res["status"],
        }

        supabase.table("student_verifications").update(updated_record).eq("serial_no", serial).execute()

        merged = {**student, **updated_record}
        return jsonify({"updated": merged})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/delete/<serial_no>", methods=["DELETE"])
def delete_student(serial_no):
    if supabase is None:
        return jsonify({"error": "Database connection failed to initialize."}), 500
        
    try:
        serial_no_clean = serial_no.strip()

        response = (
            supabase.table("student_verifications")
            .delete()
            .eq("serial_no", serial_no_clean)
            .execute()
        )

        if response.data and len(response.data) > 0:
            return jsonify({"message": f"Student {serial_no_clean} deleted successfully"})
        else:
            return jsonify({"error": f"No student found for serial_no {serial_no_clean}"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    try:
        # STEP 1: Authenticate and set the global service ONCE
        DRIVE_SERVICE = authenticate_drive_service() 
        print("✅ Google Drive Service Authenticated.")
        
        # STEP 2: Start Flask App
        print("🚀 Server running... Routes:")
        print(app.url_map)
        app.run(debug=True, host='0.0.0.0') # Runs on 0.0.0.0 for external access
    except Exception as e:
        print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! FLASK SERVER FAILED TO START DUE TO CRITICAL ERROR !!!")
        print(f"Error Message: {e}")
        print("!!! Check your .env or credentials.json files. !!!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")