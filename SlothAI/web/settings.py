import os
import json

from google.cloud import ndb

from flask import Blueprint, jsonify, request, redirect, url_for
from flask import current_app as app

import flask_login
from flask_login import current_user

from SlothAI.web.models import User, Token
from SlothAI.lib.util import random_string

from SlothAI.lib.database import featurebase_query, weaviate_get_all_schemas

settings_handler = Blueprint('settings', __name__)

# LOGIN POST
@settings_handler.route('/connect', methods=['POST'])
@flask_login.login_required
def connect_db():
    uid = current_user.uid

    try:
        data = request.get_json()
    except:
        return jsonify({"error": "Data must be posted as a dictionary containing the dbid and db_token keys with values."}), 406

    dbid = data.get('dbid')
    db_token = data.get('db_token')

    if not dbid or not db_token:
        return jsonify({"error": "You need to enter both the dbid and db_token fields."}), 406

    # check for access to FeatureBase database
    resp, err = featurebase_query(
        {
            "sql": f"SHOW TABLES;",
            "dbid": f"{dbid}",
            "db_token": f"{db_token}" 
        }
    )

    if err:
        if "Unauthorized" in err:
            return jsonify({"error": "Error authenticating. Enter or check your credentials."}), 401
        else:
            return jsonify({"error": f"Unhandled error while authenticating: {err}. Try again."}), 409
    
    if not resp.execution_time:
        return jsonify({"error": "Something horrible happened, and I have no idea what."}), 400

    # look the user up (here we know they are telling the truth)
    user = User.update_db(uid, dbid, db_token)

    if not user:
        return jsonify({"error": "You are not authenticated. Check your login or token and try again."}), 401

    return jsonify({"success": "FeatureBase account successfully connected."})


@settings_handler.route('/disconnect/<dbid>', methods=['DELETE'])
@flask_login.login_required
def disconnect_db(dbid):
    uid = current_user.uid
    if not uid:
        return jsonify({"error": "Error authenticating. Enter or check your credentials."}), 401

    user = User.update_db(uid, None, None)
    return jsonify({"success": "FeatureBase account removed."})


@settings_handler.route('/casino', methods=['POST'])
@flask_login.login_required
def connect_weaviate():
    uid = flask_login.current_user.uid

    try:
        data = request.get_json()
    except:
        return jsonify({"error": "Data must be posted as a dictionary containing the weaviate_url and weaviate_token keys."}), 406

    weaviate_url = data.get('weaviate_url')
    weaviate_token = data.get('weaviate_token')
    print(weaviate_url, weaviate_token)

    if not weaviate_url or not weaviate_token:
        return jsonify({"error": "Both the weaviate_url and weaviate_token fields are required."}), 406

    auth = {"weaviate_url": weaviate_url, "weaviate_token": weaviate_token}
    
    # Attempt to list all schemas as a way to check connectivity and authentication
    schemas = weaviate_get_all_schemas(auth)
    if schemas is None:
        return jsonify({"error": "Error authenticating with Weaviate. Check your URL and token."}), 401

    # Assuming update_weaviate is similar to update_db in your User model
    user_updated = User.update_weaviate(uid, weaviate_url, weaviate_token)

    if not user_updated:
        return jsonify({"error": "Failed to update user with Weaviate credentials. Try again."}), 409

    return jsonify({"success": "Weaviate connection successfully established."})

@settings_handler.route('/disco/<weaviate_url>', methods=['DELETE'])
@flask_login.login_required
def disconnect_weaviate(weaviate_url):
    uid = flask_login.current_user.uid
    if not uid:
        return jsonify({"error": "Error authenticating. Please check your credentials."}), 401

    # Assuming None values are used to remove the Weaviate connection
    user = User.update_weaviate(uid, None, None)
    if not user:
        return jsonify({"error": "Failed to disconnect Weaviate. Try again."}), 409

    return jsonify({"success": "Weaviate connection successfully removed."})


@settings_handler.route('/tokens', methods=['GET'])
@settings_handler.route('/tokens/<name>', methods=['GET'])
@flask_login.login_required
def get_tokens(name=None):
    uid = current_user.uid
    if not uid:
        return jsonify({"error": "Error authenticating. Enter or check your credentials."}), 401

    if not name:
        tokens = Token.get_all_by_uid(uid)
    else:
        token = Token.get_by_uid_name(uid, name)
        if token:
            tokens = [token]
        else:
            # return an empty list so people can't scan for tokens
            tokens = []

    return jsonify(tokens)


@settings_handler.route('/tokens', methods=['POST'])
@flask_login.login_required
def add_token():
    uid = current_user.uid
    if not uid:
        return jsonify({"error": "Error authenticating. Enter or check your credentials."}), 401

    try:
        data = request.get_json()
    except:
        return jsonify({"error": "Data must be posted as a dictionary with values."}), 406

    if data.get('name') and data.get('value'):
        keywords = ["password", "token", "secret"]
        for keyword in keywords:
            if keyword in data.get('name'):
                break
        else:
            return jsonify({"error": "Token name must contain 'secret', 'token', or 'password', such that it can be hidden properly."}), 422

        token = Token.create(uid, data.get('name'), data.get('value'))

    token['value'] = f"[{token.get('name')}]"

    return jsonify(token)


@settings_handler.route('/tokens/<token_id>', methods=['DELETE'])
@flask_login.login_required
def delete_token(token_id=None):
    uid = current_user.uid
    if not uid:
        return jsonify({"error": "Error authenticating. Enter or check your credentials."}), 401

    if not token_id:
        return jsonify({"error": "Requires a token ID."}), 400

    if Token.delete(uid, token_id):
        return jsonify({"message": "Token deleted!"}), 200
    else:
        return jsonify({"error": "Error deleting token."}), 400