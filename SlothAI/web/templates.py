from flask import current_app as app

from flask import Blueprint, flash, jsonify, request

import flask_login
from flask_login import current_user

from SlothAI.lib.util import random_name, callback_extras
from SlothAI.web.models import Node, Token

from datetime import datetime

from SlothAI.lib.template import Template

template_handler = Blueprint('template_handler', __name__)


# API HANDLERS
@template_handler.route('/templates/list', methods=['GET'])
@flask_login.login_required
def templates_list():
    template_service = app.config['template_service']
    templates = template_service.fetch_template(user_id=current_user.uid)
    return jsonify(templates)


@template_handler.route('/templates/<template_id>/detail', methods=['GET'])
@flask_login.login_required
def get_template(template_id):
    # Get the user and their tables
    username = current_user.name
    
    template_service = app.config['template_service']
    template = template_service.get_template(user_id=current_user.uid, template_id=template_id)

    template['extras'], update = callback_extras(template.get('extras'))

    # build the list and store callback_token if local callback was updated
    _extras = {}
    for key, value in template.get('extras').items():
        if "callback_token" in key and update:
            Token.create(current_user.uid, key, value)
            value = f"[{key}]"
            template['extras'][key] = value

    # always replace the actual token with a holder
    tokens = Token.get_all_by_uid(current_user.uid)
    _tokens = []
    for token in tokens:
        token['value'] = f"[{token.get('name')}]"
        _tokens.append(token)

    # _tokens MUST be used to secure tokens
    data = {
        "template": template,
        "tokens": _tokens
    }

    print(data)
    if template:
        return jsonify(data)
    else:
        return jsonify({"error": "Not found", "message": "The requested template was not found."}), 404


@template_handler.route('/templates/<template_id>', methods=['POST'])
@template_handler.route('/templates/<template_id>/update', methods=['POST'])
@flask_login.login_required
def template_update(template_id):

    # verify the the template with this id has exists in persistent storage.
    template_service = app.config['template_service']
    template = template_service.get_template(user_id=current_user.uid, template_id=template_id)
    if not template:
        return jsonify({"error": "Not found", "message": "The requested template was not found."}), 404

    # do some checking of the payload
    if not request.is_json:
        return jsonify({"error": "Invalid JSON", "message": "The request body must be valid JSON data."}), 400
    
    request_data = request.get_json()
    # Check if 'template' key exists in json_data and use it to update the template
    if not ('template' in request_data and isinstance(request_data['template'], dict)):
        return jsonify({"error": "Invalid JSON", "message": "'template' key with dictionary data is required in the request JSON."}), 400
    template_payload = request_data['template']
    
    # update template obj based on payload
    allowed_keys = {'name', 'text', 'created', 'user_id'}
    for key in allowed_keys:
        if key in template_payload:
            template[key] = template_payload[key]

    _template = Template.from_dict(template)

    nodes = Node.fetch(template_id=template_id)
    if nodes and not sorted(template.get('extras')) == sorted(_template.extras):
        return jsonify({"error": "Update failed", "message": "Extras may not be changed while in use by a node. Edit the node's extras instead."}), 500

    updated_template = template_service.update_template(
        template_id=template_id,
        user_id=_template.user_id,
        name=_template.name,
        text=_template.text,
        input_fields=_template.input_fields,
        output_fields=_template.output_fields,
        extras=_template.extras,
        processor=_template.processor,
    )

    if updated_template:
        return jsonify(updated_template)
    else:
        return jsonify({"error": "Update failed", "message": "Failed to update the template."}), 500


@template_handler.route('/templates/generate_name', methods=['GET'])
@flask_login.login_required
def generate_name():
    # get short name
    for x in range(20):
        name_random = random_name(2).split('-')[0]
        if len(name_random) < 9:
            break
    return jsonify({"name": name_random})


@template_handler.route('/templates', methods=['POST'])
@template_handler.route('/templates/create', methods=['POST'])
@flask_login.login_required
def template_create():
    uid = current_user.uid
    template_service = app.config['template_service']

    if not request.is_json:
        return jsonify({"error": "Invalid JSON", "message": "The request body must be valid JSON data."}), 400

    json_data = request.get_json()
    
    if not ('template' in json_data and isinstance(json_data['template'], dict)):
        return jsonify({"error": "Invalid JSON", "message": "'template' key with dictionary data is required in the request JSON."}), 400

    template_data = json_data['template']
    if 'text' not in template_data:
        return jsonify({"error": "Invalid Request", "message": "'template' object must contain 'text' key"}), 400
    if 'name' not in template_data:
        return jsonify({"error": "Invalid Request", "message": "'template' object must contain 'name' key"}), 400

    if 'user_id' not in template_data:
        template_data['user_id'] = uid
    if 'created' not in template_data:
        template_data['created'] = datetime.utcnow()

    try:
        template = Template.from_dict(template_data)
    except:
        return jsonify({"error": "Invalid JSON.", "message": "Invalid JSON syntax. Check your definitions."}), 400
    created_template = template_service.create_template(
        name=template.name,
        user_id=template.user_id,
        text=template.text,
        input_fields=template.input_fields,
        output_fields=template.output_fields,
        extras=template.extras,
        processor=template.processor,
    )

    if created_template:
        flash("Template created.")
        return jsonify(created_template), 201
    else:
        return jsonify({"error": "Creation failed", "message": "Failed to create the template."}), 500


@template_handler.route('/templates/<template_id>', methods=['DELETE'])
@template_handler.route('/templates/<template_id>/delete', methods=['DELETE'])
@flask_login.login_required
def template_delete(template_id):
    template_service = app.config['template_service']
    template = template_service.get_template(user_id=current_user.uid, template_id=template_id)
    if template:
        # fetch all nodes
        nodes = Node.fetch(uid=current_user.uid)

        # Check if the template is used in any node
        is_in_node = any(node.get('template_id') == template_id for node in nodes if 'template_id' in node)

        if is_in_node:
            return jsonify({"error": "Template is in use in a node.", "message": "This template cannot be deleted until it's removed from the nodes using it."}), 409
        template_service = app.config['template_service']
        _ = template_service.delete_template(user_id=current_user.uid, template_id=template.get('template_id'))

        return jsonify({"response": "success", "message": "Template deleted successfully!"}), 200
    else:
        return jsonify({"error": f"Unable to delete template with id {template_id}"}), 501
