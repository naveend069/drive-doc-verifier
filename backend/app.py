from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client
import os
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import base64
import json

# Load env
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# -------------------------
# Load service account key from Base64 (Render)
# -------------------------
SERVICE_KEY_PATH = "service_account.json"

if os.getenv("GOOGLE_SERVICE_KEY_BASE64"):
    print("Detected Base64 Google service key in environment... decoding.")

    try:
        decoded = base64.b64decode(os.getenv("GOOGLE_SERVICE_KEY_BASE64"))
        with open(SERVICE_KEY_PATH, "wb") as f:
            f.write(decoded)
        print("Service account key written successfully.")
    except Exception as e:
        print("Failed to decode Base64 key:", e)
else:
    print("WARNING: GOOGLE_SERVICE_KEY_BASE64 not found in Render Env!!")


# Supabase client
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    print("Supabase connected.")
except Exception as e:
    print(f"Supabase Client Error: {e}")
    supabase = None


# Google Drive Service
DRIVE_SERVICE = None

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


# Google Drive
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

REQUIRED_LABELS = ["photo", "aadhar", "community", "marksheet", "tc"]

FILE_CODE_MAP = {
    "s1": "photo",
    "s2": "aadhar",
    "s3": "community",
    "s4": "marksheet",
    "s5": "tc"
}


# -------------------------
# SERVICE ACCOUNT LOGIN
# -------------------------
def authenticate_drive_service():
    print("Authenticating Google Drive...")

    if not os.path.exists(SERVICE_KEY_PATH):
        raise Exception("service_account.json not found! Base64 key not loaded.")

    creds = Credentials.from_service_account_file(
        SERVICE_KEY_PATH,
        scopes=SCOPES
    )
    print("Google Drive authenticated successfully.")
    return build("drive", "v3", credentials=creds)


def scan_drive_folder(folder_id: str):
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

    return {
        "found_files": found_files_list,
        "missing_files": missing_files,
        "status": status
    }


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

        existing = supabase.table("student_verifications") \
                           .select("*").eq("serial_no", serial_no).execute()

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

    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        resp = supabase.table("student_verifications") \
                       .select("*").eq("serial_no", serial_no).execute()

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

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/delete/<serial_no>", methods=["DELETE"])
def delete_student(serial_no):
    try:
        resp = supabase.table("student_verifications")\
                       .delete().eq("serial_no", serial_no).execute()

        if resp.data:
            return jsonify({"message": "Deleted successfully"})
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    try:
        DRIVE_SERVICE = authenticate_drive_service()
        print("Service Account Loaded: Google Drive Connected ✔")
        app.run(debug=True, host="0.0.0.0")
    except Exception as e:
        print("CRITICAL ERROR:", e)
