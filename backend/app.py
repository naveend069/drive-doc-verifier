from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client
import os
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials 
from googleapiclient.errors import HttpError 
import base64
import json 
import sys # Added for error debugging (optional)

# Load env
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# -------------------------
# Load Service Account Key from Base64 (Render)
# -------------------------
SERVICE_KEY_PATH = "service_account.json" 

if os.getenv("GOOGLE_SERVICE_KEY_BASE64"):
    try:
        decoded = base64.b64decode(os.getenv("GOOGLE_SERVICE_KEY_BASE64"))
        with open(SERVICE_KEY_PATH, "wb") as f:
            f.write(decoded)
    except Exception as e:
        print(f"CRITICAL: Base64 decoding failed: {e}", file=sys.stderr)
        
# Supabase client
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
except Exception as e:
    print(f"Supabase Client Error: {e}")
    supabase = None

# Global Drive Service initialized once
DRIVE_SERVICE = None

app = Flask(__name__)
# FIX: Simplified CORS to allow all origins universally.
CORS(app) 

# --- REMOVED THE CONFLICTING @app.after_request BLOCK ---

# Google Drive Configuration
SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"] 
REQUIRED_LABELS = ["photo", "aadhar", "community", "marksheet", "tc"]
FILE_CODE_MAP = {
    "s1": "photo", "s2": "aadhar", "s3": "community", "s4": "marksheet", "s5": "tc"
}
SERVICE_ACCOUNT_EMAIL = "drive-scanner-sa@dataverification-478012.iam.gserviceaccount.com"


def authenticate_drive_service():
    """Initializes Google Drive service using the Service Account file."""
    if not os.path.exists(SERVICE_KEY_PATH):
        raise Exception("Google Auth failed: service_account.json not found. Check GOOGLE_SERVICE_KEY_BASE64.")

    creds = Credentials.from_service_account_file(SERVICE_KEY_PATH, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def scan_drive_folder(folder_id: str):
    """Scans a Google Drive folder using the initialized global service."""
    global DRIVE_SERVICE
    if DRIVE_SERVICE is None:
        raise Exception("Drive service not initialized.")

    results = DRIVE_SERVICE.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(name)",
        pageSize=1000
    ).execute()

    files = [f["name"].lower() for f in results.get("files", [])]
    found_labels = set()

    for file_name in files:
        for label in REQUIRED_LABELS:
            if label in file_name:
                found_labels.add(label)
        for code, label in FILE_CODE_MAP.items():
            if file_name.startswith(code):
                found_labels.add(label)

    found_files_list = sorted(list(found_labels))
    missing_files = [f for f in REQUIRED_LABELS if f not in found_files_list]
    status = "Complete" if not missing_files else "Incomplete"

    return {"found_files": found_files_list, "missing_files": missing_files, "status": status}


@app.route("/verify", methods=["POST"])
def verify():
    if supabase is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        data = request.get_json()
        name = data.get("name")
        serial_no = data.get("serial_no")
        drive_link = data.get("drive_link")

        if not (name and serial_no and drive_link):
            return jsonify({"error": "name, serial_no, drive_link required"}), 400

        existing = supabase.table("student_verifications").select("*").eq("serial_no", serial_no).execute()
        if existing.data:
            return jsonify({"result": existing.data[0]})

        if "folders/" not in drive_link:
            return jsonify({"error": "Invalid Google Drive link"}), 400

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

    # FIX: Enhanced error handling for Google API issues
    except HttpError as e:
        if e.resp.status == 403:
            # Specific 403 error returned to frontend with instructions
            return jsonify({"error": f"Permission Denied (403). Please share the Drive folder with our verification account: {SERVICE_ACCOUNT_EMAIL}"}), 403
        if e.resp.status == 404:
            return jsonify({"error": "Drive Folder Not Found or Link is Bad."}), 400
        
        # General API HttpError
        return jsonify({"error": f"Google API Error ({e.resp.status}): {str(e.content.decode())}"}), 500
    
    except Exception as e:
        # Catch-all for low-level server errors (e.g., failed DB connection, unhandled exception)
        return jsonify({"error": f"Server Error: {str(e)}"}), 500


@app.route("/students", methods=["GET"])
def get_all_students():
    try:
        data = supabase.table("student_verifications").select("*").execute()
        return jsonify({"data": data.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/refresh/<serial_no>", methods=["POST"])
def refresh_student(serial_no):
    try:
        resp = supabase.table("student_verifications").select("*").eq("serial_no", serial_no).execute()
        rows = resp.data or []
        if not rows:
            return jsonify({"error": "Student not found"}), 404

        student = rows[0]
        drive_link = student.get("drive_link")

        if not drive_link or "folders/" not in drive_link:
            return jsonify({"error": "Invalid drive_link"}), 400

        folder_id = drive_link.split("folders/")[1].split("?")[0]
        res = scan_drive_folder(folder_id)

        updated = {
            "found_files": res["found_files"],
            "missing_files": res["missing_files"],
            "status": res["status"],
        }
        supabase.table("student_verifications").update(updated).eq("serial_no", serial_no).execute()
        return jsonify({"updated": {**student, **updated}})

    except HttpError as e:
        if e.resp.status == 403:
            return jsonify({"error": f"Permission Denied. Share with: {SERVICE_ACCOUNT_EMAIL}"}), 403
        return jsonify({"error": f"API Error: {str(e)}"}), 500
        
    except Exception as e:
        return jsonify({"error": f"Refresh failed: {str(e)}"}), 500


@app.route("/delete/<serial_no>", methods=["DELETE"])
def delete_student(serial_no):
    try:
        resp = supabase.table("student_verifications").delete().eq("serial_no", serial_no).execute()
        if resp.data:
            return jsonify({"message": "Deleted successfully"})
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    try:
        # Initialize Google Drive Service at startup
        DRIVE_SERVICE = authenticate_drive_service()
        print("Service Account Loaded: Google Drive Connected ✔")
        
        # Run Flask app on host 0.0.0.0 for external access
        app.run(debug=True, host="0.0.0.0")
    except Exception as e:
        print("CRITICAL ERROR: Failed to start application or authenticate Google Drive:", e)