from flask import Blueprint, request, jsonify, current_app
import flask_login
import json
from werkzeug.utils import secure_filename
import re  # Import for regex operations

from SlothAI.lib.util import upload_to_storage
from SlothAI.web.models import Log

callback = Blueprint('callback', __name__)

@callback.route('/<user_name>/callback', methods=['POST'])
@flask_login.login_required
def handle_callback(user_name):
    json_data_dict = {}  # Initialize the dict for JSON data
    uploaded_filenames = []  # List to store filenames of uploaded files

    # Loop through uploaded files
    for uploaded_file in request.files.values():
        filename = secure_filename(uploaded_file.filename)

        # Check if the file matches the expected JSON file pattern
        if re.match(r'^json_data(_[0-9a-z]+)?\.json$', filename):
            print(f"Processing JSON file: {filename}")
            try:
                uploaded_file.seek(0)  # Go to the beginning of the file
                json_content = json.load(uploaded_file)
                json_data_dict.update(json_content)  # Merge content into json_data_dict
            except Exception as ex:
                return jsonify({"error": f"Error parsing JSON data from file {filename}: {ex}"}), 400
        else:
            # For non-JSON files, upload to storage and add their filenames to the list
            upload_uri = upload_to_storage(flask_login.current_user.uid, filename, uploaded_file)
            uploaded_filenames.append(filename)

    # Append the list of uploaded filenames to the json_data_dict
    if uploaded_filenames:
        json_data_dict['filename'] = uploaded_filenames

    # Attempt to parse JSON data from request body if no JSON files were uploaded
    if not json_data_dict:
        try:
            data = request.get_data()
            json_data_dict = json.loads(data)
        except Exception as ex:
            return jsonify({"error": "Error parsing JSON data from request body: {ex}"}), 400

    # Ensure 'node_id' and 'pipe_id' exist, populate with placeholders if missing
    node_id = json_data_dict.get('node_id', 'None')
    pipe_id = json_data_dict.get('pipe_id', 'None')
    json_data_dict['node_id'] = node_id  # Ensure the dict contains the node_id
    json_data_dict['pipe_id'] = pipe_id  # Ensure the dict contains the pipe_id

    # Create the log entry with 'node_id' and 'pipe_id', whether provided or placeholders
    log = Log.create(user_id=flask_login.current_user.uid, line=json.dumps(json_data_dict), node_id=node_id, pipe_id=pipe_id)
    if log:
        message = "Successfully processed callback and created log entry"
        current_app.logger.info(message)
        return jsonify({'message': message}), 200
    else:
        error_message = "Failed to create log entry"
        current_app.logger.error(f"ERROR: {error_message}")
        return jsonify({'error': 'LogWriteError', 'message': error_message}), 500
