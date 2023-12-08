import os
import json
import re

from datetime import datetime

from google.cloud import ndb

from flask import Blueprint, jsonify, request, redirect, url_for, Response
from flask import current_app as app

import flask_login
from flask_login import current_user

from werkzeug.utils import secure_filename

from SlothAI.lib.tasks import Task, TaskState
from SlothAI.web.models import Pipeline, Node, Token
from SlothAI.lib.util import random_string, upload_to_storage, deep_scrub, transform_single_items_to_lists
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
            return jsonify({"error": "Invalid JSON Object", "message": "The request body must be valid JSON data and contain a 'name' and 'nodess' key."}), 400
        
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
@flask_login.login_required
def ingest_post(pipeline_id):
    pipeline = Pipeline.get(uid=current_user.uid, pipe_id=pipeline_id)
    if not pipeline:
        return jsonify({"response": f"pipeline with id {pipeline_id} not found"}), 404

    # start looking for uploaded files in the payload
    file_field_names = request.files.keys()

    # if we find any, we take the first one only and stick it in cloud storage
    for field_name in file_field_names:
        uploaded_file = request.files[field_name]
        filename = secure_filename(uploaded_file.filename)
        bucket_uri = upload_to_storage(current_user.uid, filename, uploaded_file)
        break

    # Check if we have a file upload
    if file_field_names:
        try:
            json_data = request.form.get('data')
            if not json_data:
                return jsonify({"error": "When using mixed mode POSTs, you must supply a 'json' key with a JSON object."}), 400
            json_data_dict = transform_single_items_to_lists(json.loads(json_data))

            if not isinstance(json_data_dict, dict):
                return jsonify({"error": "The 'json' data is not a dictionary"}), 400

            json_data_dict['filename'] = [filename]
            json_data_dict['content_type'] = [uploaded_file.content_type]
        except Exception as ex:
            return jsonify({"error": f"Error getting or transforming JSON data."}), 400
    else:
        # If it's not a file upload, try to read JSON data
        try:
            json_data_dict = transform_single_items_to_lists(request.get_json())

            if not isinstance(json_data_dict, dict):
                return jsonify({"error": "The JSON data is not a dictionary"}), 400
        
        except Exception as ex:
            return jsonify({"error": f"Error getting or transforming JSON data: {ex}"}), 400

    # now we create the task
    task_id = random_string()
    task = Task(
        id=task_id,
        user_id=current_user.uid,
        pipe_id=pipeline.get('pipe_id'),
        nodes=pipeline.get('node_ids'),
        document=dict(),
        created_at=datetime.utcnow(),
        retries=0,
        error=None,
        state=TaskState.RUNNING,
        split_status=-1
    )

    # store and queue
    task.document = json_data_dict

    try:
        app.config['task_service'].create_task(task)
        return jsonify(task.to_dict()), 200
    except Exception as ex:
        print(ex)
        return jsonify({"error": "task queue is erroring. site admin needs to setup task queue"})


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
                        print(value)
                        print(k)
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

