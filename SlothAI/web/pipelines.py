import os
import json
import re
import mimetypes

from datetime import datetime

from google.cloud import ndb

from flask import Blueprint, jsonify, request, redirect, url_for, Response
from flask import current_app as app

import flask_login
from flask_login import current_user

from werkzeug.utils import secure_filename

from SlothAI.lib.tasks import Task, TaskState
from SlothAI.web.models import Pipeline, Node, Token
from SlothAI.lib.util import random_string, upload_to_storage, load_from_storage, deep_scrub, transform_single_items_to_lists, gpt_dict_completion
from SlothAI.lib.template import Template

from SlothAI.web.nodes import node_create

pipeline = Blueprint('pipeline', __name__)

# client connection
client = ndb.Client()


# API HANDLERS
@pipeline.route('/pipelines/list', methods=['GET'])
@flask_login.login_required
def pipelines_list():
    # get the user and their tables
    username = current_user.name
    pipelines = Pipeline.fetch(uid=current_user.uid)

    return jsonify(pipelines)


@pipeline.route('/pipeline/<pipe_id>/add_node', methods=['POST'])
@flask_login.login_required
def node_to_pipeline(pipe_id):
    user_id = current_user.uid
    pipeline = Pipeline.get(uid=user_id, pipe_id=pipe_id)

    if not pipeline:
        return jsonify({"error": "Pipeline not found", "message": "The pipeline was not found."}), 404

    if request.is_json:
        try:
            json_data = request.get_json()
            node_id = json_data.get('node_id')
            uid = current_user.uid  # Assuming the UID is obtained from the current logged-in user

            # Call the method to add the node
            pipeline = Pipeline.add_node(uid, pipe_id, node_id)

            # Prepare and return a success response
            return jsonify({
                'message': 'Node successfully added to pipeline!',
                'pipeline': pipeline
            }), 200

        except Exception as e:
            print(e)
            # Handle any exceptions that might occur
            return jsonify({
                'error': str(e)
            }), 500
    else:
        # If the request is not in JSON format, return an error
        return jsonify({
            'error': 'Invalid request format, JSON expected.'
        }), 400

@pipeline.route('/pipeline/<pipe_id>/rename', methods=['POST'])
@flask_login.login_required
def update_name(pipe_id):
    # Parse the JSON data from the request
    try:
        json_data = request.get_json()
        new_name = json_data["pipeline"]["name"]
    except Exception as e:
        return jsonify({"error": "Invalid JSON data"}), 400

    # Check if the user has permission to update the node
    pipeline = Pipeline.get(uid=current_user.uid, pipe_id=pipe_id)
    if not pipeline:
        return jsonify({"error": "Pipeline not found"}), 404

    # Update the node's name with the new name
    updated_node = Pipeline.rename(current_user.uid, pipe_id, new_name)

    if updated_node:
        return jsonify({"message": "Pipeline renamed successfully"}), 200
    else:
        return jsonify({"error": "Failed to rename pipeline"}), 500


@pipeline.route('/pipeline/<pipe_id>', methods=['POST'])
@flask_login.login_required
def pipeline_update(pipe_id):
    user_id = current_user.uid
    pipeline = Pipeline.get(uid=user_id, pipe_id=pipe_id)

    if not pipeline:
        return jsonify({"error": "Pipeline not found", "message": "The pipeline was not found."}), 404
        
    # Make sure request is valid JSON
    if request.is_json:
        json_data = request.get_json()

        # Make sure request JSON contains name and node_ids keys
        name = pipeline.get('name')
        nodes = json_data.get('nodes', None)

        if not name or not nodes:
            return jsonify({"error": "Invalid JSON Object", "message": "The pipelin must contain a 'name' and 'nodes' key."}), 400
        
        if not isinstance(nodes, list):
            return jsonify({"error": "Invalid JSON Object", "message": f"The value of the 'nodes' key must be a list of node_ids. Got: {type(nodes)}"}), 400

        # Make sure all nodes exist
        for node in nodes:
            node = Node.fetch(node_id=node, uid=user_id)
            if not node:
                return jsonify({"error": "Invalid Node ID", "message": f"Unable to find a node with name {node}"}), 400

        # update with the create method
        pipeline = Pipeline.create(user_id, name, nodes)
        
        if not pipeline:
            return jsonify({"error": "Update failed", "message": "Unable to update pipeline."}), 501
        
        return jsonify(pipeline), 200

    return jsonify({"error": "Invalid JSON", "message": "The request body must be valid JSON data."}), 400


@pipeline.route('/pipeline', methods=['POST'])
@flask_login.login_required
def pipeline_add():
    user_id = current_user.uid
    pipelines = Pipeline.fetch(uid=user_id)

    # Make sure request is valid JSON
    if request.is_json:
        json_data = request.get_json()

        # Make sure request JSON contains name and node_ids keys
        name = json_data.get('name', None)
        nodes = json_data.get('nodes', None)

        if not name or not nodes:
            return jsonify({"error": "Invalid JSON Object", "message": "Ensure you have added a valid node to the pipeline."}), 400
        
        if not isinstance(nodes, list):
            return jsonify({"error": "Invalid JSON Object", "message": f"The value of the 'nodes' key must be a list of node_ids. Got: {type(nodes)}"}), 400

        # Make sure pipeline name is avaliable
        if pipelines:
            for pipeline in pipelines:
                if pipeline.get('name') == name:
                    return jsonify({"error": "Invalid Pipeline Name", "message": f"A pipeline already exists with name {name}"}), 400
 
        # Make sure all nodes exist
        for node in nodes:
            node = Node.fetch(node_id=node, uid=user_id)
            if not node:
                return jsonify({"error": "Invalid Node ID", "message": f"Unable to find a node with name {node}"}), 400

        pipeline = Pipeline.create(user_id, name, nodes)
        if not pipeline:
            return jsonify({"error": "Create failed", "message": "Unable to create pipeline."}), 501
        
        return jsonify(pipeline), 200

    return jsonify({"error": "Invalid JSON", "message": "The request body must be valid JSON data."}), 400


# totally lame, but popovers still don't allow click handling TODO FIX THIS
@pipeline.route('/pipelines/<pipe_id>/<node_id>/delete', methods=['GET'])
@flask_login.login_required
def pipeline_node_delete(pipe_id, node_id):
    pipeline = Pipeline.get(uid=current_user.uid, pipe_id=pipe_id)
    nodes = pipeline.get('node_ids')
    
    if node_id in nodes:
        nodes.remove(node_id) 

    pipeline = Pipeline.create(current_user.uid, pipeline.get('name'), nodes)
    return redirect(url_for('site.pipeline_view', pipe_id=pipe_id))


@pipeline.route('/pipeline/<pipe_id>', methods=['DELETE'])
@flask_login.login_required
def pipeline_delete(pipe_id):
    pipe = Pipeline.get(uid=current_user.uid, pipe_id=pipe_id)

    if pipe:
        # delete table
        Pipeline.delete_by_pipe_id(pipe.get('pipe_id'))

        return jsonify({"response": "success", "message": "Table deleted successfully!"}), 200
    else:
        return jsonify({"error": f"DELETE failed", "message": "Can't delete the pipeline."}), 501


@pipeline.route('/pipeline/<pipeline_id>/task', methods=['POST'])
@pipeline.route('/pipeline/<pipeline_id>/task/<task_id>', methods=['POST'])
@flask_login.login_required
def ingest_post(pipeline_id, task_id=None):
    # user
    uid = current_user.uid
    username = current_user.name

    pipeline = Pipeline.get(uid=uid, pipe_id=pipeline_id)
    if not pipeline:
        return jsonify({"response": f"Pipeline '{pipeline_id}' not found"}), 404

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
                bucket_uri = upload_to_storage(uid, filename, uploaded_file)
                filenames.append(filename)
                
                # Guess the MIME type based on the file extension
                mime_type, _ = mimetypes.guess_type(filename)
                content_types.append(mime_type)

                # Build the URI for access
                upload_uris.append(f"https://{app.config.get('APP_DOMAIN')}/d/{username}/{filename}")

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

    # Transform and validate JSON data
    json_data_dict = transform_single_items_to_lists(json_data_dict)
    if not isinstance(json_data_dict, dict):
        return jsonify({"error": "Transformed JSON data is not a dictionary"}), 400

    # Add file upload details to JSON data
    if filenames:
        json_data_dict['filename'] = filenames
        json_data_dict['content_type'] = content_types
        json_data_dict['access_uri'] = upload_uris


    # This section handles asynchronous calls directed to specific nodes in the processing pipeline.
    # It is triggered when a task_id is provided in the request, indicating that the operation
    # should continue from a specified point in the pipeline rather than starting from the beginning.
    if task_id:
        try:
            # Construct the filename from the task_id to locate the stored JSON data.
            json_filename = f'json_data_{task_id}.json'
            
            # Load the JSON file from storage using the unique identifier (uid) of the current user
            # and the constructed filename. The file contains the current state of the task's data.
            buffer = load_from_storage(uid, json_filename)
            json_storage_dict = json.load(buffer)
            
            # Extract the 'task_node_id' from the loaded JSON data, which specifies the next node
            # in the pipeline to process. This key is then removed from the dictionary to prevent
            # redundancy and potential conflicts during data merging.
            node_id = json_storage_dict.get('task_node_id')
            json_storage_dict.pop('task_node_id', None)  # Use pop with None as default to avoid KeyError
            
            # Locate the index of the specified node_id within the pipeline's sequence of nodes.
            # This determines the starting point for processing within the pipeline.
            node_index = pipeline.get('node_ids').index(node_id)
            
            # Adjust the list of node_ids to process by slicing the original list from the
            # identified starting point onwards. This effectively "jumps" the processing
            # to the specified node, skipping all previous nodes in the pipeline.
            modified_node_ids = pipeline.get('node_ids')[node_index:]
            jump_status = 1  # Set a flag indicating that a jump in the pipeline has occurred.
            
            # Ensure newer data from json_data_dict overrides older data in json_storage_dict
            json_storage_dict.update(json_data_dict)

            # At this point, json_storage_dict contains the merged data with newer updates taking precedence.
            # The updated data is required to be in json_data_dict, reassign it:
            json_data_dict = json_storage_dict
            
        except Exception as ex:
            print(ex)
            # This block catches the case where the specified node_id does not exist within
            # the pipeline's list of node_ids. An error response is returned to indicate
            # that the requested jump to a specific node cannot be fulfilled.
            return jsonify({"error": "The 'node_id' was not found, or the JSON document for the previous task was not loaded."}), 400
    else:
        # This branch handles the case where no specific task_id is provided in the request.
        # In such cases, the operation proceeds with the original, unmodified list of node_ids
        # from the pipeline, starting from the beginning of the process.
        modified_node_ids = pipeline.get('node_ids')
        jump_status = -1  # Set a flag indicating that no jump in the pipeline is occurring.

    # Create and store the task with either the modified or original node_ids
    task_id = random_string()
    task = Task(
        id=task_id,
        user_id=uid,
        pipe_id=pipeline.get('pipe_id'),
        nodes=modified_node_ids,
        document=json_data_dict,
        created_at=datetime.utcnow(),
        retries=0,
        error=None,
        state=TaskState.RUNNING,
        split_status=-1,
        jump_status=jump_status
    )

    try:
        app.config['task_service'].create_task(task)
        return jsonify(task.to_dict()), 200
    except Exception as e:
        print(e)
        return jsonify({"error": f"Error creating task: {e}"}), 400


def custom_serializer(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime):
        # Assuming DatetimeWithNanoseconds is a subclass of datetime.datetime
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


@pipeline.route('/pipelines/<pipe_id>/download', methods=['GET'])
@flask_login.login_required
def pipelines_download(pipe_id):
    # Get the user and their tables
    username = current_user.name

    # Retrieve the pipeline by pipe_id (you need to implement your Pipeline class)
    pipeline = Pipeline.get(uid=current_user.uid, pipe_id=pipe_id)

    if pipeline is None:
        return jsonify({"error": "Pipeline not found"})

    # Retrieve nodes for the pipeline (you need to implement your Nodes class)
    node_ids = pipeline.get('node_ids')  # Assuming 'nodes' is a list of node IDs

    nodes = []
    for node_id in node_ids:
        node = Node.get(uid=current_user.uid, node_id=node_id)

        # Retrieve the template for each node
        template_service = app.config['template_service']
        template = template_service.get_template(user_id=current_user.uid, template_id=node.get('template_id'))

        # Append the node and its associated template to the nodes list
        nodes.append({
            "node": node,
            "template": template,
        })

    # Create a dictionary containing pipeline information, including pipe_id
    pipeline_data = {
        "pipe_id": pipe_id,
        "name": pipeline.get('name'),
        "nodes": nodes,
    }

    # scrub the data for secrets Response
    deep_scrub(pipeline_data)

    # Convert pipeline_data to a pretty formatted JSON string
    pretty_json_data = json.dumps(pipeline_data, indent=4, default=custom_serializer)

    # Create a Response object with the pretty formatted JSON
    response = Response(pretty_json_data, content_type="application/json")

    # Set the headers to force a file download with a custom filename
    response.headers["Content-Disposition"] = f"attachment; filename=pipeline_{pipeline.get('name')}.json"

    return response


@pipeline.route('/pipelines/<pipe_id>/describe', methods=['GET'])
@flask_login.login_required
def pipelines_describe(pipe_id):
    # Get the user and their tables
    username = current_user.name

    # Retrieve the pipeline by pipe_id (you need to implement your Pipeline class)
    pipeline = Pipeline.get(uid=current_user.uid, pipe_id=pipe_id)

    if pipeline is None:
        return jsonify({"error": "Pipeline not found"})

    # Retrieve nodes for the pipeline (you need to implement your Nodes class)
    node_ids = pipeline.get('node_ids')  # Assuming 'nodes' is a list of node IDs

    nodes = []
    for node_id in node_ids:
        node = Node.get(uid=current_user.uid, node_id=node_id)

        # Retrieve the template for each node
        template_service = app.config['template_service']
        template = template_service.get_template(user_id=current_user.uid, template_id=node.get('template_id'))

        # Append the node and its associated template to the nodes list
        nodes.append({
            "node": node,
            "template": template,
        })

    # Create a dictionary containing pipeline information, including pipe_id
    pipeline_data = {
        "pipe_id": pipe_id,
        "name": pipeline.get('name'),
        "nodes": nodes,
    }

    # scrub the data for secrets Response
    deep_scrub(pipeline_data)

    # Convert pipeline_data to a pretty formatted JSON string
    json_data = json.dumps(pipeline_data, default=custom_serializer)

    # get the description
    result = gpt_dict_completion(document={"pipeline": json_data}, template="pipeline_description")

    # Create a Response object with the pretty formatted JSON
    return jsonify({"description": result.get('description'), "blurb": result.get('blurb')})

    return response


@pipeline.route('/pipeline/upload', methods=['POST'])
@flask_login.login_required
def pipeline_upload():
    template_service = app.config['template_service']
    
    if not request.is_json:
        return jsonify({"error": "Invalid JSON", "message": "The request body must be valid JSON data."}), 400

    json_data = request.get_json()

    pipe_name = json_data.get('name')
    nodes = json_data.get('nodes')
    user_id = current_user.uid

    if not pipe_name or not nodes:
        return jsonify({"error": "Invalid JSON Object", "message": "The request body must be valid JSON data and contain a 'name' and 'nodes' key."}), 400
    
    if not isinstance(nodes, list):
        return jsonify({"error": "Invalid JSON Object", "message": f"The value of the 'nodes' key must be a list of node objects. Got: {type(nodes)}"}), 400

    node_ids = []
    tokens_to_update = []

    # Make sure all nodes exist
    for n in nodes:
        node = n.get('node')
        template = n.get('template')
        if not node or not template:
            return jsonify({"error": "Invalid JSON Object", "message": f"Each node in nodes must contain a 'node' and 'template' key"}), 400

        node_name = node.get('name')
        processor = node.get('processor', template.get('processor'))

        if not node_name:
            return jsonify({"error": "Invalid JSON Object", "message": f"Nested node object must contain a 'name' key value pair"}), 400
        if not processor:
            return jsonify({"error": "Invalid JSON Object", "message": f"Processor not found in template or node"}), 400

        template_extras = template.get('extras')
        node_extras = node.get('extras')
        # Check that both or neither are None
        if not ((template_extras is None and node_extras is None) or (template_extras is not None and node_extras is not None)):
            return jsonify({"error": "Invalid JSON Object", "message": f"the extras key must either be missing or present for both template and node"}), 400

        if not isinstance(template_extras, dict):
            return jsonify({"error": "Invalid JSON Object", "message": f"extras must be a JSON object"}), 400

        if not isinstance(node_extras, dict):
            return jsonify({"error": "Invalid JSON Object", "message": f"extras must be a JSON object"}), 400

        template['user_id'] = current_user.uid

        try:
            template = template_service.create_template_from_dict(template)
        except Exception as e:
            return str(e), 400
        
        # scan for values enclosed in brackets
        pattern = r'(?<!\S)\[(.*?)\](?!\S)'
        
        for k, v in node.get('extras').items():
            match = re.search(pattern, str(v))
            if match:
                value = match.group(1)
                token = Token.get_by_uid_name(current_user.uid, value)
                if not token:
                    # create the callback token if local
                    if value == "callback_token" and template.get('extras').get('callback_uri') == "[callback_uri]":
                        token = Token.create(current_user.uid, "callback_token", current_user.api_token)
                    else:
                        tokens_to_update.append(value)

        node = Node.create(
            name=node_name,
            uid=current_user.uid,
            extras=node_extras,
            processor=processor,
            template_id=template['template_id']
        )

        node_ids.append(node['node_id'])


    # update with the create method
    pipeline = Pipeline.create(user_id, pipe_name, node_ids)
    
    if not pipeline:
        return jsonify({"error": "Update failed", "message": "Unable to update pipeline."}), 501
    
    return jsonify({"pipeline": pipeline, "service_tokens_to_update": tokens_to_update}), 200

