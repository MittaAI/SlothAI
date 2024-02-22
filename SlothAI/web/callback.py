from flask import Blueprint, request, jsonify, current_app
from flask import current_app as app
import flask_login
import json
import mimetypes
from werkzeug.utils import secure_filename
import re  # Import for regex operations

from SlothAI.lib.util import upload_to_storage, transform_single_items_to_lists
from SlothAI.web.models import Log

callback = Blueprint('callback', __name__)

@callback.route('/<user_name>/callback', methods=['POST'])
@flask_login.login_required
def handle_callback(user_name):
    # Prepare storage for JSON data and file upload details
    json_data_dict = {}
    filenames, content_types, upload_uris = [], [], []

    # Iterate over each file field name
    for field_name in request.files:
        # Now correctly handle multiple files under the same field name
        files_list = request.files.getlist(field_name)
        
        for uploaded_file in files_list:
            filename = secure_filename(uploaded_file.filename)
            if re.match(r'^json_data(_[0-9a-z]+)?\.json$', filename):
                try:
                    uploaded_file.stream.seek(0)
                    file_data = json.load(uploaded_file)
                    if isinstance(file_data, dict):
                        json_data_dict.update(file_data)
                    else:
                        return jsonify({"error": "JSON data must be a dictionary"}), 400
                except Exception as e:
                    return jsonify({"error": f"Error reading JSON file '{filename}': {e}"}), 400
            else:
                # Process and upload other files
                bucket_uri = upload_to_storage(flask_login.current_user.uid, filename, uploaded_file)
                filenames.append(filename)
                
                # Guess the MIME type based on the file extension
                mime_type, _ = mimetypes.guess_type(filename)
                content_types.append(mime_type)

                # Build the URI for access
                upload_uris.append(f"https://{app.config.get('APP_DOMAIN')}/d/{flask_login.current_user.name}/{filename}")

    # Directly process JSON payload if no JSON data files were uploaded
    if not json_data_dict:
        # Try to get JSON data from request.get_json() first
        json_payload = request.get_json(silent=True)

        if json_payload and isinstance(json_payload, dict):
            json_data_dict = json_payload
        else:
            # Iterate through each key in request.form and attempt JSON decoding
            for key in request.form.keys():
                try:
                    # Attempt to decode each form field as JSON
                    potential_json_data = json.loads(request.form[key])
                    if isinstance(potential_json_data, dict):
                        # Merge with json_data_dict if it's a dictionary
                        json_data_dict.update(potential_json_data)
                except json.JSONDecodeError:
                    # If decoding fails, it's not JSON data, so ignore
                    pass

    # Ensure 'node_id' and 'pipe_id' exist, populate with placeholders if missing
    node_id = json_data_dict.get('node_id', 'None')
    pipe_id = json_data_dict.get('pipe_id', 'None')
    json_data_dict['node_id'] = node_id  # Ensure the dict contains the node_id
    json_data_dict['pipe_id'] = pipe_id  # Ensure the dict contains the pipe_id

    # Transform and validate JSON data
    json_data_dict = transform_single_items_to_lists(json_data_dict)
    if not isinstance(json_data_dict, dict):
        return jsonify({"error": "Transformed JSON data is not a dictionary"}), 400

    # Add file upload details to JSON data
    if filenames:
        json_data_dict['filename'] = filenames
        json_data_dict['content_type'] = content_types
        json_data_dict['access_uri'] = upload_uris

    # Create the log entry with 'node_id' and 'pipe_id', whether provided or placeholders
    log = Log.create(user_id=flask_login.current_user.uid, line=json.dumps(json_data_dict, ensure_ascii=False), node_id=node_id, pipe_id=pipe_id)
    if log:
        message = "Successfully processed callback and created log entry"
        current_app.logger.info(message)
        return jsonify({'message': message}), 200
    else:
        error_message = "Failed to create log entry"
        current_app.logger.error(f"ERROR: {error_message}")
        return jsonify({'error': 'LogWriteError', 'message': error_message}), 500
