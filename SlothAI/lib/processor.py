import ast
import re
import math
import time
import base64
import random

from io import BytesIO

import requests
import json

import openai
import google.generativeai as genai

from itertools import groupby

from google.cloud import vision, storage, documentai
from google.api_core.client_options import ClientOptions

from SlothAI.lib.util import random_string, random_name, get_file_extension, upload_to_storage, upload_to_storage_requests, storage_pickle, cast_iching, split_image_by_height, download_as_bytes, local_callback_url
from SlothAI.lib.template import Template
from SlothAI.web.models import Token

from typing import Dict

from flask import current_app as app
from flask import url_for

from jinja2 import Environment, DictLoader

from enum import Enum

import datetime

# supress OpenAI resource warnings for unclosed sockets
import warnings
warnings.filterwarnings("ignore")

from SlothAI.web.custom_commands import random_word, random_sentence, random_chars, chunk_with_page_filename, filter_shuffle, random_entry
from SlothAI.web.models import User, Node, Pipeline

from SlothAI.lib.tasks import Task, process_data_dict_for_insert, auto_field_data, transform_data, get_values_by_json_paths, box_required, validate_dict_structure, TaskState, NonRetriableError, RetriableError, MissingInputFieldError, MissingOutputFieldError, UserNotFoundError, PipelineNotFoundError, NodeNotFoundError, TemplateNotFoundError

from SlothAI.lib.database import table_exists, add_column, create_table, get_columns, featurebase_query
from SlothAI.lib.database import weaviate_batch, weaviate_delete_collection, weaviate_hybrid_search, weaviate_similarity, extract_weaviate_params

from SlothAI.lib.util import strip_secure_fields, filter_document, random_string

import SlothAI.lib.services as services

env = Environment(trim_blocks=True, lstrip_blocks=True)
env.globals['random_chars'] = random_chars
env.globals['random_word'] = random_word
env.globals['random_sentence'] = random_sentence
env.globals['random_entry'] = random_entry
env.globals['chunk_with_page_filename'] = chunk_with_page_filename
env.filters['shuffle'] = filter_shuffle

from jinja2 import Undefined

# move this eventually
def safe_tojson(value):
    def handle_undefined(value):
        if isinstance(value, Undefined):
            return "Undefined"
        elif isinstance(value, dict):
            return {k: handle_undefined(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [handle_undefined(item) for item in value]
        else:
            return value

    processed_data = handle_undefined(value)
    return json.dumps(processed_data)


env.filters['safe_tojson'] = safe_tojson

class DocumentValidator(Enum):
    INPUT_FIELDS = 'input_fields'
    OUTPUT_FIELDS = 'output_fields'

retriable_status_codes = [408, 409, 425, 429, 500, 503, 504]

processors = {}

def processor(f):
    def wrapper(node, task, is_post_processor=False):
        if isinstance(task, NonRetriableError):
            app.logger.debug(f"Skipping processor '{f.__name__}' as task is a NonRetriableError instance")
            return task
        app.logger.debug(f"Entering processor '{f.__name__}' for task with id {task.id}")
        result = f(node, task, is_post_processor)
        app.logger.debug(f"Exiting processor '{f.__name__}' for task with id {task.id}")
        return result
    processors.setdefault(f.__name__, wrapper)
    return wrapper

def send_callback(task, node, error_message):
    if not task.document.get('callback_uri'):
        app.logger.info("Making callback")
        local_callback = local_callback_url(user.get('name'), user.get('api_token'))
        app.logger.info(local_callback)
        task.document.update({"callback_uri": local_callback})

    callback_uri = task.document.get('callback_uri')
    app.logger.info(f"Sending data to callback: {callback_uri}")
    if callback_uri:
        try:
            # Prepare the data for the callback
            data = {
                'node_id': node.get('node_id'),
                'pipe_id': task.pipe_id,
                'error': error_message,
            }
            data.update(strip_secure_fields(task.document))

            # Replace the token in the callback_uri with asterisks
            modified_uri = re.sub(r'token=([^\s&]+)', lambda match: 'token=' + '*' * len(match.group(1)), callback_uri)
            data['callback_uri'] = modified_uri

            # Send the POST request to the callback URL
            headers = {'Content-Type': 'application/json'}
            resp = requests.post(callback_uri, data=json.dumps(data), headers=headers)

            if resp.status_code != 200:
                message = f'got status code {resp.status_code} from callback'
                raise NonRetriableError(message)
        except (
            requests.ConnectionError,
            requests.HTTPError,
            requests.Timeout,
            requests.TooManyRedirects,
            requests.ConnectTimeout,
        ) as exception:
            app.logger.error(f"Error sending callback: {str(exception)}")
        except Exception as exception:
            app.logger.error(f"Error sending callback: {str(exception)}")


# Main process entry
def process(task: Task) -> Task:
    user = User.get_by_uid(task.user_id)
    if not user:
        raise UserNotFoundError(task.user_id)
    
    pipeline = Pipeline.get(uid=task.user_id, pipe_id=task.pipe_id)
    if not pipeline:
        raise PipelineNotFoundError(pipeline_id=task.pipe_id)
    
    node_id = task.next_node()
    node = Node.get(uid=task.user_id, node_id=node_id)
    if not node:
        raise NodeNotFoundError(node_id=node_id)

    missing_field = validate_document(node, task, DocumentValidator.INPUT_FIELDS)
    if missing_field:
        raise MissingInputFieldError(missing_field, node.get('name'))

    # get tokens from service tokens
    # and process values for numbers
    _extras = {}
    
    for key, value in node.get('extras').items():
        # cast certain strings to other things
        if isinstance(value, str):  
            if f"[{key}]" in value:
                token = Token.get_by_uid_name(task.user_id, key)
                if not token:
                    raise NonRetriableError(f"You need a service token created for '{key}'.")
                value = token.get('value')
            # convert ints and floats from strings
            elif value.isdigit():
                # convert to int
                value = int(value)
            elif '.' in value and all(c.isdigit() or c == '.' for c in value):
                # convert it to a float
                value = float(value)

        _extras[key] = value

    # update node extras
    node['extras'] = _extras

    # template the extras off the node
    extras = evaluate_extras(node, task)

    if extras:
        task.document.update(extras)

    # get the user
    user = User.get_by_uid(uid=task.user_id)

    # if "x-api-key" in node.get('extras'):
    task.document['X-API-KEY'] = user.get('db_token')
    # if "database_id" in node.get('extras'):
    task.document['DATABASE_ID'] = user.get('dbid')

    # Move this if you are cleaning up
    try:
        task.document['weaviate_url'] = user.get('weaviate_url')
        task.document['weaviate_token'] = user.get('weaviate_token')
    except Exception as ex:
        print(f"exception loading user weaviate auth: {ex}")
        pass

    try:
        # Call the main processor
        app.logger.debug(f"Calling main processor '{node.get('processor')}' for task with id {task.id}")
        task = processors[node.get('processor')](node, task)
    except RetriableError as e:
        app.logger.debug(f"RetriableError occurred in main processor for task with id {task.id}: {str(e)}")
        raise
    except NonRetriableError as e:
        app.logger.debug(f"NonRetriableError occurred in main processor for task with id {task.id}: {str(e)}")
        task.error = str(e)  # Store the error in the task object

        # Send a POST request to the callback URL with the task document
        if not task.document.get('callback_uri'):
            app.logger.info("Making callback")
            local_callback = local_callback_url(user.get('name'), user.get('api_token'))
            task.document.update({"callback_uri": local_callback})

        callback_uri = task.document.get('callback_uri')
        app.logger.info(f"Sending data to callback: {callback_uri}")
        if callback_uri:
            try:
                # Prepare the data for the callback
                data = {
                    'node_id': node.get('node_id'),
                    'pipe_id': task.pipe_id,
                    'error': task.error,
                    'document': strip_secure_fields(task.document)
                }

                # Send the POST request to the callback URL
                headers = {'Content-Type': 'application/json'}
                resp = requests.post(callback_uri, data=json.dumps(data), headers=headers)

                if resp.status_code != 200:
                    message = f'got status code {resp.status_code} from callback'
                    raise NonRetriableError(message)
            except (
                requests.ConnectionError,
                requests.HTTPError,
                requests.Timeout,
                requests.TooManyRedirects,
                requests.ConnectTimeout,
            ) as exception:
                app.logger.error(f"Error sending callback: {str(exception)}")
            except Exception as exception:
                app.logger.error(f"Error sending callback: {str(exception)}")

        raise

    except Exception as e:
        app.logger.error(f"Error in main processor: {str(e)}")

        task.error = str(e)  # Store the error in the task object

        # Send a POST request to the callback URL with the task document
        if not task.document.get('callback_uri'):
            app.logger.info("Making callback")
            local_callback = local_callback_url(user.get('name'), user.get('api_token'))
            task.document.update({"callback_uri": local_callback})

        callback_uri = task.document.get('callback_uri')
        app.logger.info(f"Sending data to callback: {callback_uri}")
        if callback_uri:
            try:
                # Prepare the data for the callback
                data = {
                    'node_id': node.get('node_id'),
                    'pipe_id': task.pipe_id,
                    'error': str(e),
                    'document': strip_secure_fields(task.document)
                }

                # Send the POST request to the callback URL
                headers = {'Content-Type': 'application/json'}
                resp = requests.post(callback_uri, data=json.dumps(data), headers=headers)

                if resp.status_code != 200:
                    message = f'got status code {resp.status_code} from callback'
                    app.logger.error(message)
            except (
                requests.ConnectionError,
                requests.HTTPError,
                requests.Timeout,
                requests.TooManyRedirects,
                requests.ConnectTimeout,
            ) as exception:
                app.logger.error(f"Error sending callback: {str(exception)}")
            except Exception as exception:
                app.logger.error(f"Error sending callback: {str(exception)}")

        raise

    app.logger.debug(f"Returned from main processor '{node.get('processor')}' for task with id {task.id}")

    # Add post-processors
    post_processors = ['jinja2']
    for post_proc_name in post_processors:
        if node.get('processor') != post_proc_name:
            try:
                app.logger.debug(f"Calling post-processor '{post_proc_name}' for task with id {task.id}")
                task = processors.get(post_proc_name, lambda x, y, **kwargs: y)(node, task, is_post_processor=True)
            except NonRetriableError as e:
                app.logger.debug(f"NonRetriableError occurred in post-processor '{post_proc_name}' for task with id {task.id}: {str(e)}")
                task.error = str(e)  # Store the error in the task object
                break
            except Exception as e:
                app.logger.error(f"Error in post-processor '{post_proc_name}': {str(e)}")
                raise
            else:
                app.logger.debug(f"Returned from post-processor '{post_proc_name}' for task with id {task.id}")


    # TODO, decide what to do with errors and maybe truncate pipeline
    if task.document.get('error'):
        return task

    # TODO move this or get rid of it
    if "X-API-KEY" in task.document.keys():
        task.document.pop('X-API-KEY', None)
    if "DATABASE_ID" in task.document.keys():
        task.document.pop('DATABASE_ID', None)
    if "weaviate_token" in task.document.keys():
        task.document.pop('weaviate_token', None)

    # strip out the sensitive extras
    clean_extras(_extras, task)

    missing_field = validate_document(node, task, DocumentValidator.OUTPUT_FIELDS)
    if missing_field:
        raise MissingOutputFieldError(missing_field, node.get('name'))

    return task


# The I Ching, or "Book of Changes," is an ancient Chinese divination text that has been used for centuries
# to provide guidance and insight into life's challenges and opportunities. In this context, we are not
# using the I Ching for its esoteric or spiritual significance, but rather as a tool for introducing
# randomness and serendipity into our AI communication process.

# By generating I Ching hexagrams and their associated interpretations during moments of confusion or
# uncertainty in the AI's interactions with users, we aim to create a more dynamic, adaptable, and
# context-aware AI system. The random insights and prompts provided by the I Ching may serve as a source
# of inspiration, reframing, and guidance for the AI, helping it to navigate complex communication
# challenges and foster a more collaborative and supportive dynamic with users.

# Ultimately, the goal is to develop an AI that can embrace and learn from the full spectrum of human
# experience, including moments of confusion and doubt, and to provide a space for open-ended exploration
# and self-discovery. By integrating the I Ching as a randomization tool, we seek to create an emotionally
# intelligent AI that can serve as a valuable companion and guide for personal growth and transformation.
@processor
def iching(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    # verify input fields steampunk style
    input_fields = template.get('input_fields')

    # use the first output field, or set one
    try:
        input_field = input_fields[0].get('name')
    except:
        input_field = "iching"

    task.document[input_field] = cast_iching(model="gpt-3.5-turbo")

    return task


@processor
def jinja2(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    try:
        app.logger.debug(f"Entering post-processor 'jinja2' for task with id {task.id}")

        # set the time for the template
        current_epoch_time = int(time.time())
        task.document['current_epoch'] = current_epoch_time

        # load templates
        template_service = app.config['template_service']
        template = template_service.get_template(template_id=node.get('template_id'))

        if not template:
            raise TemplateNotFoundError(template_id=node.get('template_id'))

        template_text = Template.remove_fields_and_extras(template.get('text'))
        template_text = template_text.strip()

        # If we have text we try to get the JSON out of it
        if template_text:
            # Test if this is a post_processor run
            if is_post_processor:
                # Define a fake template to project json into
                templates = {
                    "base": """
                    {% block json %}
                    {% endblock %}
                    """
                }

                # child template gets the template_text from the node, extends base and is updated to templates
                child = "{% extends 'base' %}\n" + template_text
                templates.update({"child": child})

                # set the environment and load custom functions
                json_env = Environment(loader=DictLoader(templates))
                json_env.globals['random_chars'] = random_chars
                json_env.globals['random_word'] = random_word
                json_env.globals['random_sentence'] = random_sentence
                json_env.globals['random_entry'] = random_entry
                json_env.globals['chunk_with_page_filename'] = chunk_with_page_filename
                json_env.filters['shuffle'] = filter_shuffle

                # Set new environment with the dictloader, grab the child template
                try:
                    child_template = json_env.get_template('child')
                except:
                    # template had issues TODO fix this
                    app.logger.debug("Passing on doing anything with Jinja2 due to not finding the child template from above?")
                    return task

                try:
                    # render the template with the document
                    jinja_json = child_template.render(task.document)
                except Exception as e:
                    raise NonRetriableError(f"jinja2 processor: {e}")
            else:
                try:
                    # Render the entire template, as we are running the jinja2 processor
                    jinja_template = env.from_string(template_text)
                    jinja_json = jinja_template.render(task.document)
                except Exception as e:
                    raise NonRetriableError(f"jinja processor: {e}")

            # update the task.document with the rendered dict
            try:
                task.document.update(json.loads(jinja_json.strip()))
            except Exception:
                app.logger.debug("Passing on doing anything with Jinja2, got an error trying to evaluate the dictionary.")
                # From now on, we'll just ignore that we don't have a dict in the template loaded by this processor
                pass

    except NonRetriableError as e:
        app.logger.error(f"NonRetriableError in post-processor 'jinja2' for task with id {task.id}: {str(e)}")
        raise
    except Exception as e:
        app.logger.error(f"Error in post-processor 'jinja2' for task with id {task.id}: {str(e)}")
        raise NonRetriableError(str(e))

    app.logger.debug(f"Exiting post-processor 'jinja2' for task with id {task.id}")
    return task


@processor
def halt_task(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    # Set the current epoch time in the task document
    current_epoch_time = int(time.time())
    task.document['current_epoch'] = current_epoch_time

    # Templates
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    # Clean and prepare the template text
    template_text = Template.remove_fields_and_extras(template.get('text')).strip()

    # Render the template
    try:
        if template_text:
            jinja_template = env.from_string(template_text)
            rendered_text = jinja_template.render(task.document)
    except Exception as e:
        raise NonRetriableError(f"Unable to render jinja: {e}. You may want to use |safe_tojson to handle null entries and check your syntax.")

    # Parse the rendered text as JSON and check for 'halt_task'
    try:
        rendered_json = json.loads(rendered_text.strip())
        halt_task_flag = rendered_json.get('halt_task', False)
        if halt_task_flag:
            task.halt_node()
    except:
        raise NonRetriableError(f"Halting task with error. Use a 'halt_task' key and boolean to halt or pass without errors.")

    # Continue with the task if not halted
    return task


@processor
def jump_task(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    # Set the current epoch time in the task document
    current_epoch_time = int(time.time())
    task.document['current_epoch'] = current_epoch_time

    # Templates
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    # Clean and prepare the template text
    template_text = Template.remove_fields_and_extras(template.get('text')).strip()

    # Render the template
    try:
        if template_text:
            jinja_template = env.from_string(template_text)
            rendered_text = jinja_template.render(task.document)
    except Exception as e:
        raise NonRetriableError(f"Unable to render jinja: {e}. You may want to use |safe_tojson to handle null entries and check your syntax.")

    # attempt to jump
    try:
        rendered_json = json.loads(rendered_text.strip())
        # load it into the document
        try:
            for k,v in rendered_json.items():
                task.document[k] = v
        except:
            raise NonRetriableError("Your JSON didn't validate. Check syntax and formatting.")

        # Check for 'jump_to_node' key in the rendered JSON
        jump_node_name = rendered_json.get('jump_node')
        jump_task = rendered_json.get('jump_task', False)

        if jump_node_name and jump_task:
            # Attempt to get the node_id from the node name
            jump_node = Node.get(name=jump_node_name)

            if not jump_node:
                raise NonRetriableError(f"Node '{jump_node_name}' not found")
            else:
                task.jump_node(jump_id=jump_node.get('node_id'))
        else:
            task.document['jump_task_message'] = "A 'jump_node' name is not defined"
    except Exception as e:
        raise NonRetriableError(f"Jump task failed: {e}")

    return task


@processor
def callback(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))
    
    user = User.get_by_uid(uid=task.user_id)
    if not user:
        raise UserNotFoundError(user_id=task.user_id)

    # need to rewrite to allow mapping tokens to the url template
    # alternately we could require a jinja template processor to be used in front of this to build the url
    auth_uri = task.document.get('callback_uri')

    if isinstance(auth_uri, list):
        auth_uri = auth_uri[0]

    # strip secure stuff out of the document
    document = strip_secure_fields(task.document) # returns document

    # TODO Check if the document contains these and throw a decent error if it does (it gives some error about forgetting commas)
    keys_to_keep = []
    if template.get('output_fields'):
        for field in template.get('output_fields'):
            for key, value in field.items():
                if key == 'name':
                    keys_to_keep.append(value)

        if len(keys_to_keep) == 0:
            data = document
        else:
            # we don't filter the requested documents, so tokens will or can be shown
            data = filter_document(document, keys_to_keep)
    else:
        data = document

        # filter the callback_uri
        callback_uri = document.get('callback_uri')
        if callback_uri:
            modified_uri = re.sub(r'token=([^\s&]+)', lambda match: 'token=' + '*' * len(match.group(1)), callback_uri)
            data['callback_uri'] = modified_uri    

    # must add node_id and pipe_id
    data['node_id'] = node.get('node_id')
    data['pipe_id'] = task.pipe_id

    try:
        headers = {'Content-Type': 'application/json'}
        resp = requests.post(auth_uri, data=json.dumps(data), headers=headers)
        if resp.status_code != 200:
            message = f'got status code {resp.status_code} from callback'
            if resp.status_code in retriable_status_codes:
                raise RetriableError(message)
            else:
                raise NonRetriableError(message)
        
    except (
        requests.ConnectionError,
        requests.HTTPError,
        requests.Timeout,
        requests.TooManyRedirects,
        requests.ConnectTimeout,
    ) as exception:
        raise RetriableError(exception)
    except Exception as exception:
        raise NonRetriableError(exception)

    return task


@processor
def aigrub(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    # user
    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')
    username = user.get('name')
    user_token = user.get('api_token')

    # Serial pipeline execution brought us here
    if task.jump_status < 0:
        # grub config
        grub_token = app.config["GRUB_TOKEN"]

        # openai_token
        openai_token = task.document.get('openai_token')
        if not openai_token:
            raise NonRetriableError("An 'openai_token' must be passed to this processor.")

        # request URL for cluster
        request_url = f"https://grub.mitta.ai/grub2"

        # verify input fields steampunk style
        input_fields = template.get('input_fields')

        # use the first output field, or set one
        try:
            input_field = input_fields[0].get('name')
        except:
            input_field = "query"

        # uri to crawl
        queries = task.document.get(input_field)

        if not queries:
            raise NonRetriableError("Grub processor needs a `query` key and text that the LLM will resolve to a URL, or just a URL.")
        elif isinstance(queries, str):
            queries = [queries]

        # Callback for resuming the pipeline flow
        if app.config['DEV'] == "True":
            callback_url = f"{app.config['NGROK_URL']}/pipeline/{task.pipe_id}/task/{task.id}?token={user_token}"
        else:
            callback_url = f"{app.config['BRAND_SERVICE_URL']}/pipeline/{task.pipe_id}/task/{task.id}?token={user_token}"


        # Initialize the list to track statuses
        statuses = []

        # Loop through each query and make the request
        for query in queries:
            config_data = {
                "grub_token": grub_token,
                "username": username,
                "query": query,
                "callback_url": callback_url,
                "openai_token": openai_token,
            }

            try:
                # Make the request
                response = requests.post(
                    request_url,
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(config_data),
                    timeout=10
                )

                # Try to parse the JSON response
                response_json = response.json()
                
                # Check the status in the JSON response
                if response_json.get('status') == "success":
                    statuses.append("success")
                else:
                    statuses.append("failed")  # Considered failed if status is not success

            except Exception as e:
                app.logger.debug(e)
                # Handle exceptions for request errors or .json() parsing errors
                statuses.append("failed")

        # After processing all queries, check if all statuses are "success"
        if all(status == "success" for status in statuses):
            # Proceed with the task modification only if all are successful
            task.nodes = [task.next_node()]

            # Save the document
            bucket_uri = storage_pickle(uid, task.document, task.id, task.nodes[0])

            # exit current task with threads running on external service
            return task
        else:
            # Raise error if any of the queries did not succeed
            raise NonRetriableError("Error: Not all queries were successful")

    else:
        # we were jumped into so we now complete and move on
        return task


@processor
def aiffmpeg(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    # Retrieve the template
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    # Get user information
    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')
    username = user.get('name')
    user_token = user.get('api_token')

    # Initialize requirements
    mitta_uri = None

    # Serial pipeline execution brought us here
    if task.jump_status < 0:

        # inputs
        input_fields = template.get('input_fields')

        # Check if each input field is present in 'task.document'
        for field in input_fields:
            field_name = field['name']
            if field_name not in task.document:
                raise NonRetriableError(f"Input field '{field_name}' is not present in the document.")

        # Construct the AIFFMPEG service URL using the selected box details
        if app.config['DEV'] == "True":
            ffmpeg_url = f"http://localhost:5000/convert"
            ffmpeg_url = f"{app.config['FFMPEG_URL']}"
        else:
            ffmpeg_url = f"{app.config['FFMPEG_URL']}"

        # ffmpeg_request string 
        ffmpeg_string = task.document.get('ffmpeg_request')
        if not ffmpeg_string:
            task_document['ffmpeg_result'] = "The model didn't return an FFMpeg string. Reword the request to convert and ensure the file doesn't have an odd name."
            return task

        if isinstance(ffmpeg_string, list):
            # rewrite as a string
            task.document['ffmpeg_request'] = ffmpeg_string[0]

        # mitta_uri handling for the input document
        mitta_uri_value = task.document.get('mitta_uri')
        if not mitta_uri_value:
            raise NonRetriableError("The `aiffmpeg` processor expects a `mitta_uri` key in the input fields.")
        mitta_uri = mitta_uri_value[0] if isinstance(mitta_uri_value, list) else mitta_uri_value
        mitta_uri = f"{mitta_uri}?token={user.get('api_token')}" 

        # Callback for resuming the pipeline flow
        if app.config['DEV'] == "True":
            callback_url = f"{app.config['NGROK_URL']}/pipeline/{task.pipe_id}/task/{task.id}?token={user_token}"
        else:
            callback_url = f"{app.config['BRAND_SERVICE_URL']}/pipeline/{task.pipe_id}/task/{task.id}?token={user_token}"

        # get the model and begin
        model = task.document.get('model')

        # load the template
        template_text = Template.remove_fields_and_extras(template.get('text'))

        if template_text:
            jinja_template = env.from_string(template_text)
            prompt = jinja_template.render(task.document)
        else:
            raise NonRetriableError("Couldn't find template text.")

        # negotiate the format
        if model == "gpt-3.5-turbo-1106" and "JSON" in prompt:
            system_content = task.document.get('system_content', "You write JSON for the user.")
            response_format = {'type': "json_object"}
        else:
            system_content = task.document.get('system_content', "You write JSON dictionaries for the user, without using text markup or wrappers.")
            response_format = None

        # call the ai
        err, ai_dict = ai_prompt_to_dict(
            task=task,
            model=model,
            prompt=prompt,
            retries=3
        )

        if not isinstance(ai_dict, dict):
            raise NonRetriableError("The AI refused to return a dictionary for us. We can not proceed.")

        if "ffmpeg_command" not in ai_dict:
            raise NonRetriableError("The AI didn't return an `ffmpeg_command`. Try rewording your query.")
        if "output_file" not in ai_dict:
            raise NonRetriableError("The AI didn't return an `output_file`. Try rewording your query or include an `output_file` key in your input fields.")

        # Prepare data for AIFFMPEG service
        ffmpeg_data = {
            "ffmpeg_token": app.config['FFMPEG_TOKEN'],
            "username": username,
            "mitta_uri": mitta_uri,
            "callback_url": callback_url,
            "ffmpeg_command": ai_dict.get('ffmpeg_command'),
            "output_file": ai_dict.get('output_file'),
            "input_file": task.document.get('filename')[0]
        }
        
        task.document['ffmpeg_command'] = ai_dict.get('ffmpeg_command')

        # Post request to AIFFMPEG service
        try:
            ffmpeg_response = requests.post(
                ffmpeg_url,
                json = ffmpeg_data,
                timeout = 10
            )
        except:
            raise NonRetriableError("The request to the 'ffmpeg' backend failed. Try another task.")

        if ffmpeg_response:
            ffmpeg_response = ffmpeg_response.json()
           
        # Handle response
        if "status" in ffmpeg_response:
            if ffmpeg_response.get('status') == "success":
                # Proceed with the task modification only if all are successful
                task.nodes = [task.next_node()]

                # Save the document
                bucket_uri = storage_pickle(uid, task.document, task.id, task.nodes[0])

                # exit current task with threads running on external service
                return task
            else:
                raise NonRetriableError(f"Processing failed: {message}")
        else:
            raise NonRetriableError("Processing failed with no result. Check the file URL or try another file.")

    else:
        # we were jumped into so we now complete and move on
        return task


@processor
def info_file(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    # user
    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')

    # can't do anything without this input
    if 'filename' not in task.document:
        raise NonRetriableError("A 'filename' key must be present in the document. Use a string or an array of strings, or throw a local callback in front of this node to debug.")
    else:
        filename = task.document.get('filename')

    # make lists, like santa
    if isinstance(filename, str):
        # If filename is a string, convert it into a list
        filename = [filename]
        task.document['filename'] = filename

    # verify output fields steampunk style
    output_fields = template.get('output_fields')

    # use the first output field, or set one
    if len(output_fields) == 1:
        output_field = output_fields[0].get('name')
    else:
        output_field = "mitta_uri"

    # outputs
    task.document['file_size_bytes'] = []
    task.document['ttl'] = []
    task.document['pdf_num_pages'] = []
    task.document['txt_num_lines'] = []
    storage_content_types = []

    # let's get to the chopper
    for index, file_name in enumerate(filename):
        # Get the file
        try:
            gcs = storage.Client()
            bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
            blob = bucket.get_blob(f"{uid}/{file_name}")
            file_content = download_as_bytes(uid, file_name)
        except:
            raise NonRetriableError(f"Can't find the file '{file_name}' in storage, or failed to find it in the upload.")

        # Get the content type of the file from metadata
        try:
            content_type = blob.content_type
            file_size_bytes = blob.size
        except:
            raise NonRetriableError("Can't get the size or content_type from the file in storage.")

        if "application/pdf" in content_type:
            from pypdf import PdfReader

            # Create a BytesIO object for the PDF content
            pdf_content_stream = BytesIO(file_content)
            pdf_reader = PdfReader(pdf_content_stream)
            pdf_num_pages = len(pdf_reader.pages)
            task.document['pdf_num_pages'].append(pdf_num_pages)

            # TODO scan the document for pages and then see if we have OCR'd text

        elif "text/plain" in content_type or "text/csv" in content_type:
            with BytesIO(file_content) as file:
                txt_num_lines = sum(1 for line in file)
            task.document['txt_num_lines'].append(line_count)
        else:
            # we must add something even if it's not a PDF or text file
            task.document['pdf_num_pages'].append(-1)
            task.document['txt_num_lines'].append(-1)

        storage_content_types.append(content_type)
        task.document['file_size_bytes'].append(file_size_bytes)
        task.document['ttl'].append(-1) # fix this

        access_uri = f"https://{app.config.get('APP_DOMAIN')}/d/{user.get('name')}/{file_name}"

        if output_field not in task.document:
            task.document[output_field] = [access_uri]
        else:
            task.document[output_field].append(access_uri)

    # handle existing content_type in the document
    if not task.document.get('content_type') or not isinstance(task.document.get('content_type'), list):
        task.document['content_type'] = storage_content_types

    return task


@processor
def split_task(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    input_fields = template.get('input_fields')
    output_fields = template.get('output_fields')
    if not input_fields:
        raise NonRetriableError("split_task processor: input fields required")
    if not output_fields:
        raise NonRetriableError("split_task processor: output fields required")

    if not task.document.get('split_auto'):
        inputs  = [n['name'] for n in input_fields]
        outputs = [n['name'] for n in output_fields] 
    else:
        # auto deal with max list size groups
        max_length = 0  # Initialize maximum list length
        keys_with_max_length = []  # Initialize list to store keys with maximum length

        for key, value in task.document.items():
            if isinstance(value, list):
                current_length = len(value)
                if current_length > max_length:
                    max_length = current_length
                    keys_with_max_length = [key]
                elif current_length == max_length:
                    keys_with_max_length.append(key)

        result_dict = {
            'keys': keys_with_max_length,
            'array_length': max_length
        }

        # set both to auto value
        inputs = outputs = result_dict.get('keys')

    batch_size = node.get('extras', {}).get('batch_size', None)

    task_service = app.config['task_service']

    # batch_size must be in extras
    if not batch_size:
        raise NonRetriableError("split_task processor: batch_size must be specified in extras!")
    
    try:
        batch_size = int(batch_size)
    except Exception as e:
        raise NonRetriableError("split_task processor: batch size must be an integer")

    # this call is currently required to update split status
    
    try:
        task_stored = task_service.fetch_tasks(task_id=task.id)
        task_stored = task_stored[0]
        task.split_status = task_stored['split_status']
    except Exception as e:
        raise NonRetriableError(f"getting task by ID but got none: {e}")
    # task.refresh_split_status()
    
    # all input / output fields should be lists of the same length to use split_task
    total_sizes = []
    for output in outputs:
        if output in inputs:
            field = task.document[output]
            if not isinstance(field, list):
                raise NonRetriableError(f"split_task processor: output fields must be list type: got {type(field)}")

            # if this task was partially process, we need to truncate the data
            # to only contain the data that hasn't been split.
            if task.split_status != -1:
                total_sizes.append(len(task.document[output][task.split_status:]))
                del task.document[output][:task.split_status]
            else:
                total_sizes.append(len(field))

        else:
            raise NonRetriableError(f"split_task processor: all output fields must be taken from input fields: output field {output} was not found in input fields.")

    if not all_equal(total_sizes):
        raise NonRetriableError("split_task processor: len of fields must be equal to re-batch a task")

    app.logger.info(f"Split Task: Task ID: {task.id}. Task Size: {total_sizes[0]}. Batch Size: {batch_size}. Number of Batches: {math.ceil(total_sizes[0] / batch_size)}. Task split status was set to {task.split_status}.")

    new_task_count = math.ceil(total_sizes[0] / batch_size)

    # split the data and re-task
    try:
        for i in range(new_task_count):

            task_stored = task_service.fetch_tasks(task_id=task.id)[0] # not safe

            if not task_service.is_valid_state_for_process(task_stored['state']):
                raise services.InvalidStateForProcess(task_stored['state'])

            batch_data = {}
            for field in outputs:
                batch_data[field] = task.document[field][:batch_size]
                del task.document[field][:batch_size]

            new_task = Task(
                id = random_string(),
                user_id=task.user_id,
                pipe_id=task.pipe_id,
                nodes=task.nodes[1:],
                document=batch_data,
                created_at=datetime.datetime.utcnow(),
                retries=0,
                error=None,
                state=TaskState.RUNNING,
                split_status=-1
            )

            # create new task and queue it      
            task_service.create_task(new_task)

            # commit status of split on original task
            task.split_status = (i + 1) * batch_size
            task_service.update_task(task_id=task.id, split_status=task.split_status)

            app.logger.info(f"Split Task: spawning task {i + 1} of projected {new_task_count}. It's ID is {new_task.id}")

    except services.InvalidStateForProcess as e:
        app.logger.warn(f"Task with ID {task.id} was being split. State was changed during that process.")
        raise e

    except Exception as e:
        app.logger.warn(f"Task with ID {task.id} was being split. An exception was raised during that process.")
        raise NonRetriableError(e)

    # the initial task doesn't make it past split_task. so remove the rest of the nodes
    task.nodes = [task.next_node()]
    return task


@processor
def embedding(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    # do we need this?
    extras = node.get('extras', None)
    if not extras:
        raise NonRetriableError("embedding processor: extras not found but is required")

    model = extras.get('model')
    if not model:
        raise NonRetriableError("Model not found in extras but is required.")

    input_fields = template.get('input_fields')
    if not input_fields:
        raise NonRetriableError("Input fields are required.")

    output_fields = template.get('output_fields')
    if not output_fields:
        output_fields = [f"{input_field.get('name')}_embedding" for input_field in input_fields]
    else:
        # Ensure output_fields is a list of names only
        output_fields = [field['name'] for field in output_fields if 'name' in field]

    if len(output_fields) != len(input_fields):
        raise NonRetriableError("Input and output fields must be of the same length.")

    # use batches of strings to send to embeddings endpoints
    if task.document.get('batch_size'):
        batch_size = int(task.document.get('batch_size'))
        if batch_size < 1:
            batch_size = 5
    else:
        batch_size = 5

    # Loop through each input field and produce the proper output for each <key>_embedding output field
    for index, input_field in enumerate(input_fields):
        input_field_name = input_field.get('name')

        # Get the input data chunks
        input_data = task.document.get(input_field_name)

        # Define the output field name for embeddings
        output_field = output_fields[index]

        # Check if the input field is empty or None
        if input_data is None or (isinstance(input_data, list) and len(input_data) == 0):
            # Set the output field to an empty list and continue to the next input field
            task.document[output_field] = []
            continue

        # embeddings are processed from lists of lists
        # convert lists of objects to lists of lists of objects
        if not isinstance(input_data, list):
            input_data = [input_data]

        # Initialize a list to store the embeddings
        embeddings = []

        if "voyage" in model:
            pass
            # add voyageai.com embeddings

        if model == "text-embedding-ada-002":
            openai.api_key = task.document.get('openai_token')
            try:
                for i in range(0, len(input_data), batch_size):
                    batch = input_data[i:i + batch_size]
                    embedding_results = openai.embeddings.create(input=batch, model=task.document.get('model'))
                    embeddings.extend([_object.embedding for _object in embedding_results.data])

                # Add the embeddings to the output field
                task.document[output_field] = embeddings
            except Exception as ex:
                app.logger.info(f"embedding processor: {ex}")

                raise NonRetriableError(f"Exception talking to OpenAI ada embedding: {ex}")

        elif model == "gemini-embedding-001" or model == "embedding-001":
            gemini_model = "models/embedding-001"
            if not task.document.get('gemini_token'):
                raise NonRetriableError(f"You'll need to specify a 'gemini_token' in extras to use the {model} model.")
            if not task.document.get('task_type'):
                raise NonRetriableError(f"You'll need to specify a 'task_type' in extras to use the {model} model.")

            if task.document.get('task_type') not in ["retrieval_document","retrieval_query"]:
                raise NonRetriableError(f"The 'task_type' needs to be set to 'retrieval_query' or 'retrieval_document'.")

            genai.configure(api_key=task.document.get('gemini_token'))
            try:
                for i in range(0, len(input_data), batch_size):
                    batch = input_data[i:i + batch_size]
                    embedding_results = genai.embed_content(model=gemini_model, content=batch, task_type=task.document.get('task_type'))
                    embeddings.extend([_object for _object in embedding_results['embedding']])

                # Add the embeddings to the output field
                task.document[output_field] = embeddings
            except Exception as ex:
                app.logger.info(f"embedding processor: {ex}")
                raise NonRetriableError(f"Exception talking to Gemini embedding: {ex}")

        elif "mistral-embed" in model:
            from mitta_mistralai.client import MistralClient

            if not task.document.get('mistral_token'):
                raise NonRetriableError(f"You'll need to specify a 'mistral_token' in extras to use the {model} model.")

            mistral = MistralClient(api_key=task.document.get('mistral_token'))

            try:
                for i in range(0, len(input_data), batch_size):
                    batch = input_data[i:i + batch_size]
                    embedding_results = mistral.embeddings(
                        model=model,
                        input=batch,
                    )
                    embeddings.extend([_object.embedding for _object in embedding_results.data])
                
                # Add the embeddings to the output field
                task.document[output_field] = embeddings
            except Exception as ex:
                app.logger.info(f"embedding processor: {ex}")
                raise NonRetriableError(f"Exception talking to Mistral embedding: {ex}")

        elif "instructor" in model:
            # check required services (GPU boxes)
            defer, selected_box = box_required(box_type="instructor")
            if defer:
                if selected_box:
                    # Logic to start or wait for the box to be ready
                    # Possibly setting up the box or waiting for it to transition from halted to active
                    raise RetriableError("Instructor box is being started to run embedding.")
                else:
                    # No box is available, raise a non-retriable error
                    raise NonRetriableError("No available Instructor machine to run embeddings.")

            embedding_url = f"http://instructor:{app.config['CONTROLLER_TOKEN']}@{selected_box.get('ip_address')}:9898/embed"

            try:
                # Initialize a list to store the embeddings
                embeddings = []
                for i in range(0, len(input_data), batch_size):
                    batch = input_data[i:i + batch_size]
                    # Prepare the data for the POST request
                    embedding_data = {
                        "text": batch,
                        "model": model
                    }
                    # Send the POST request to the Instructor embedding service
                    response = requests.post(embedding_url, json=embedding_data, headers={"Content-Type": "application/json"}, timeout=60)
                    # Check the response and extract embeddings
                    if response.status_code == 200:
                        batch_embeddings = response.json().get("embeddings")
                        embeddings.extend(batch_embeddings)
                    elif response.status_code == 502:
                        raise RetriableError(f"Embedding server is starting with status: {response.status_code}.")
                    else:
                        raise NonRetriableError(f"Unexpected status code from Instructor embedding endpoint: {response.status_code}.")

                # Add the embeddings to the output field in the task document
                task.document[output_field] = embeddings

            except RetriableError as ex:
                app.logger.info(f"embedding processor: {ex}")
                raise  # Re-raise the RetriableError to be caught by the process function

            except Exception as ex:
                app.logger.info(f"embedding processor: {ex}")
                raise NonRetriableError(f"Exception talking to Instructor embedding endpoint: {ex}")


    return task


# complete strings
@processor
def aichat(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    # output and input fields
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    # outputs
    output_fields = template.get('output_fields')
    output_field = output_fields[0].get('name') # always use the first output field

    # inputs
    input_fields = template.get('input_fields')

    # Check if each input field is present in 'task.document'
    for field in input_fields:
        field_name = field['name']
        if field_name not in task.document:
            raise NonRetriableError(f"Input field '{field_name}' is not present in the document.")

    # replace single strings with lists
    task.document = process_input_fields(task.document, input_fields)

    if "gpt" in task.document.get('model'):
        openai.api_key = task.document.get('openai_token')

        template_text = Template.remove_fields_and_extras(template.get('text'))

        if template_text:
            jinja_template = env.from_string(template_text)
            prompt = jinja_template.render(task.document)
        else:
            raise NonRetriableError("Couldn't find template text.")

        system_prompt = task.document.get('system_prompt', "You are a helpful assistant.")

        # we always reverse the lists, so it's easier to do without timestamps
        message_history = task.document.get('message_history', [])
        role_history = task.document.get('role_history', [])

        if message_history or role_history:
            if len(message_history) != len(role_history):
                raise NonRetriableError("'role_history' length must match 'message_history' length.")
            else:
                message_history.reverse()
                role_history.reverse()

        chat_messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Iterate through the user history
        for idx, message in enumerate(message_history):
            # Determine the role (user or assistant) based on the index
            role = role_history[idx]

            # Create a message object and append it to the chat_messages list
            chat_messages.append({
                "role": role,
                "content": message
            })

        # add the user input
        chat_messages.append({"role": "user", "content": prompt})

        retries = 3
        # try a few times
        for _try in range(retries):
            completion = openai.chat.completions.create(
                model = task.document.get('model'),
                messages = chat_messages
            )

            answer = completion.choices[0].message.content

            if answer:
                task.document[output_field] = [answer]
                return task

        else:               
            raise NonRetriableError(f"Tried {retries} times to get an answer from the AI, but failed.")    
        

    elif "claude" in task.document.get('model'):
        model = task.document.get('model')
        if not task.document.get('anthropic_token'):
            raise NonRetriableError(f"You'll need to specify an 'anthropic_token' in extras to use the {model} model.")

        import anthropic
        client = anthropic.Client(api_key=task.document.get('anthropic_token'))

        template_text = Template.remove_fields_and_extras(template.get('text'))
        if template_text:
            jinja_template = env.from_string(template_text)
            prompt = jinja_template.render(task.document)
        else:
            raise NonRetriableError("Couldn't find template text.")

        system_prompt = task.document.get('system_prompt', "You are a helpful assistant.")

        # we always reverse the lists, so it's easier to do without timestamps
        message_history = task.document.get('message_history', [])
        role_history = task.document.get('role_history', [])

        if message_history or role_history:
            if len(message_history) != len(role_history):
                raise NonRetriableError("'role_history' length must match 'message_history' length.")
            else:
                message_history.reverse()
                role_history.reverse()

        messages = []

        # Iterate through the user history
        for idx, message in enumerate(message_history):
            # Determine the role (user or assistant) based on the index
            role = role_history[idx]

            # Create a message object and append it to the messages list
            messages.append({
                "role": role,
                "content": message
            })

        # add the user input from the template as the last message
        messages.append({"role": "user", "content": prompt})

        app.logger.debug(messages)

        retries = 3

        # try a few times
        for _try in range(retries):
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                messages=messages
            )

            content_blocks = response.content

            if content_blocks:
                # Iterate over the content blocks and extract the text
                answer = ''.join(block.text for block in content_blocks)
                task.document[output_field] = [answer]

                # Retrieve the usage information and store it in the task document
                usage = response.usage
                task.document['anthropic_usage'] = {
                    'input_tokens': usage.input_tokens,
                    'output_tokens': usage.output_tokens
                }

                return task
            else:
                raise NonRetriableError(f"Tried {retries} times to get an answer from the AI, but failed.")
    

    elif "gemini-pro" in task.document.get('model'):
        model = task.document.get('model')
        if not task.document.get('gemini_token'):
            raise NonRetriableError(f"You'll need to specify a 'gemini_token' in extras to use the {model} model.")

        genai.configure(api_key=task.document.get('gemini_token'))

        template_text = Template.remove_fields_and_extras(template.get('text'))
        if template_text:
            jinja_template = env.from_string(template_text)
            prompt = jinja_template.render(task.document)
        else:
            raise NonRetriableError("Couldn't find template text.")

        system_prompt = task.document.get('system_prompt', "You are a helpful assistant.")

        model = genai.GenerativeModel(model)

        # we always reverse the lists, so it's easier to do without timestamps
        message_history = task.document.get('message_history', [])
        role_history = task.document.get('role_history', [])

        if message_history or role_history:
            if len(message_history) != len(role_history):
                raise NonRetriableError("'role_history' length must match 'message_history' length.")
            else:
                message_history.reverse()
                role_history.reverse()

            chat = model.start_chat(history=[])

            # Iterate through the user history
            for idx, message in enumerate(message_history):
                # Determine the role (user or assistant) based on the index
                role = role_history[idx]

                if role == "user":
                    response = chat.send_message(message)
                else:
                    # Skip assistant messages as they are not sent to the model
                    continue

        retries = 3

        # try a few times
        for _try in range(retries):
            if message_history or role_history:
                response = chat.send_message(prompt)
            else:
                response = model.generate_content(f"system: {system_prompt}\n\n{prompt}")

            if response.text:
                task.document[output_field] = [response.text]

                if response.candidates:
                    task.document['gemini_candidates'] = [
                        {
                            'content': str(candidate.content),
                            'token_count': candidate.token_count,
                            'finish_reason': candidate.finish_reason.name
                        }
                        for candidate in response.candidates
                    ]
                
                return task
            else:
                raise NonRetriableError(f"Tried {retries} times to get an answer from the AI, but failed.")


    elif "perplexity" in task.document.get('model'):
        full_model_name = task.document.get('model')
        
        # Strip the 'perplexity/' prefix to get the actual model name
        model = full_model_name.split('perplexity/')[1] if 'perplexity/' in full_model_name else full_model_name

        # Check for the Perplexity API token
        if not task.document.get('perplexity_token'):
            raise NonRetriableError("A 'perplexity_token' is required to use the Perplexity API.")

        # Configure the Perplexity API key
        perplexity_api_key = task.document.get('perplexity_token')

        # Process the template text
        template_text = Template.remove_fields_and_extras(template.get('text'))
        if template_text:
            jinja_template = env.from_string(template_text)
            prompt = jinja_template.render(task.document)
        else:
            raise NonRetriableError("Couldn't find template text.")

        # Set up the system prompt
        system_prompt = task.document.get('system_prompt', "Be precise and concise.")

        # Prepare the messages for the API request
        message_history = task.document.get('message_history', [])
        role_history = task.document.get('role_history', [])
        if message_history or role_history:
            if len(message_history) != len(role_history):
                raise NonRetriableError("'role_history' length must match 'message_history' length.")

            message_history.reverse()
            role_history.reverse()

        messages = []
        messages.append({"role": "system", "content": system_prompt})

        for idx, message in enumerate(message_history):
            role = role_history[idx]
            messages.append({"role": role, "content": message})
        messages.append({"role": "user", "content": prompt})

        # API request setup
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            'Authorization': f'Bearer {perplexity_api_key}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        data = {
            "model": model,
            "messages": messages
        }

        # Try making the API request
        retries = 3
        for _try in range(retries):
            try:
                response = requests.post(url, json=data, headers=headers)
                response.raise_for_status()  # Raise an error for bad responses
                answer = response.json()
                if answer and answer.get('choices')[0]:
                    task.document[output_field] = [answer.get('choices')[0].get('message').get('content')]
                    task.document['processor_output'] = [answer]
                    return task
            except Exception as ex:
                print(ex)
                if _try == retries - 1:
                    raise NonRetriableError(f"Model {model}: {ex}")

    # needs to be tested before mistral, given together runs mistral
    elif "together" in task.document.get('model'):
        full_model_name = task.document.get('model')
        
        # Strip the 'together/' prefix to get the actual model name
        model = full_model_name.split('together/')[1] if 'together/' in full_model_name else full_model_name

        # Check for the Together API token
        if not task.document.get('together_token'):
            raise NonRetriableError("A 'together_token' is required to use the Together API.")

        # Configure the Together API key
        together_api_key = task.document.get('together_token')

        # Process the template text
        template_text = Template.remove_fields_and_extras(template.get('text'))
        if template_text:
            jinja_template = env.from_string(template_text)
            prompt = jinja_template.render(task.document)
        else:
            raise NonRetriableError("Couldn't find template text.")

        # Set up the system prompt
        system_prompt = task.document.get('system_prompt', "You are a helpful assistant.")

        # Prepare the messages for the API request
        message_history = task.document.get('message_history', [])
        role_history = task.document.get('role_history', [])
        if message_history or role_history:
            if len(message_history) != len(role_history):
                raise NonRetriableError("'role_history' length must match 'message_history' length.")

            message_history.reverse()
            role_history.reverse()

        messages = []
        messages.append({"role": "system", "content": system_prompt})

        for idx, message in enumerate(message_history):
            role = role_history[idx]
            messages.append({"role": role, "content": message})
        messages.append({"role": "user", "content": prompt})

        # API request setup
        url = "https://api.together.xyz/inference"
        headers = {
            'Authorization': f'Bearer {together_api_key}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        data = {
            "messages": messages,
            "model": model,
            "max_tokens": 1024
        }

        # Try making the API request
        retries = 3
        for _try in range(retries):
            try:
                response = requests.post(url, json=data, headers=headers)
                response.raise_for_status()  # Raise an error for bad responses
                answer = response.json()
                if answer and answer.get('output').get('choices')[0]:
                    task.document[output_field] = [answer.get('output').get('choices')[0].get('text')]
                    task.document['processor_output'] = answer
                    return task
            except Exception as ex:
                print(ex)
                if _try == retries - 1:
                    raise NonRetriableError(f"Model {model}: {ex}")

    elif "mistral" in task.document.get('model'):
        model = task.document.get('model')

        from mitta_mistralai.client import MistralClient
        from mitta_mistralai.models.chat_completion import ChatMessage

        if not task.document.get('mistral_token'):
            raise NonRetriableError(f"You'll need to specify a 'mistral_token' in extras to use the {model} model.")

        mistral = MistralClient(api_key=task.document.get('mistral_token'))

        template_text = Template.remove_fields_and_extras(template.get('text'))

        if template_text:
            jinja_template = env.from_string(template_text)
            prompt = jinja_template.render(task.document)
        else:
            raise NonRetriableError("Couldn't find template text.")

        system_prompt = task.document.get('system_prompt', "You are a helpful assistant.")

        # we always reverse the lists, so it's easier to do without timestamps
        message_history = task.document.get('message_history', [])
        role_history = task.document.get('role_history', [])

        if message_history or role_history:
            if len(message_history) != len(role_history):
                raise NonRetriableError("'role_history' length must match 'message_history' length.")
            else:
                message_history.reverse()
                role_history.reverse()

        # build list of ChatMessage objects
        chat_messages = [ChatMessage(role="system", content=system_prompt)]

        # Iterate through the user history
        for idx, message in enumerate(message_history):
            # Determine the role (user or assistant) based on the index
            role = role_history[idx]

            # Create a message object and append it to the chat_messages list
            chat_messages.append(ChatMessage(role = role, content=message))

        # add the user input
        chat_messages.append(ChatMessage(role="user", content=prompt))

        retries = 3
        # try a few times
        for _try in range(retries):
            try:
                completion = mistral.chat(model=model, messages=chat_messages)
                answer = completion.choices[0].message.content
                if answer:
                    task.document[output_field] = [answer]
                    return task
            except Exception as ex:
                raise NonRetriableError(f"Model {model}: {ex}")
        else:               
            raise NonRetriableError(f"Tried {retries} times to get an answer from the AI, but failed.")

    else:
        raise NonRetriableError("The aichat processor expects a supported model.")


# complete dictionaries
def ai_prompt_to_dict(task=None, model="gpt-3.5-turbo-1106", prompt="", retries=3):
    # check model
    if "gpt" in model:
        if not task.document.get('openai_token'):
            raise NonRetriableError(f"You'll need to specify a 'openai_token' in extras to use the {model} model.")
        openai.api_key = task.document.get('openai_token')
    elif "gemini-pro" in model:
        if not task.document.get('gemini_token'):
            raise NonRetriableError(f"You'll need to specify a 'gemini_token' in extras to use the {model} model.")
        genai.configure(api_key=task.document.get('gemini_token'))
    else:
        raise NonRetriableError("The aidict processor expects a supported model.")

    # negotiate the format
    if model == "gpt-3.5-turbo-1106" and "JSON" in prompt:
        system_content = task.document.get('system_content', "You write JSON for the user.")
        response_format = {'type': "json_object"}
    else:
        system_content = task.document.get('system_content', "You write JSON dictionaries for the user, without using text markup or wrappers.\nYou output things like:\n'''ai_dict={'akey': 'avalue'}'''")
        response_format = None

    # try a few times
    for _try in range(retries):

        if "gpt" in model:        
            completion = openai.chat.completions.create(
                model = model,
                response_format = response_format,
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ]
            )

        elif "gemini-pro":
            # upgrade model to genai
            model = genai.GenerativeModel(model)
            response = model.generate_content(f"system: {system_content}\n\n{prompt}")

        # process the text output in the message.content
        ai_dict_str = completion.choices[0].message.content.replace("\n", "").replace("\t", "")
        ai_dict_str = ai_dict_str.replace("null", "None") # fix null issue
        ai_dict_str = re.sub(r'\s+', ' ', ai_dict_str).strip()
        ai_dict_str = re.sub(r'^ai_dict\s*=\s*', '', ai_dict_str)

        try:
            ai_dict = ast.literal_eval(ai_dict_str)
            # Normalize output to ensure ai_dict is directly accessible
            if isinstance(ai_dict, dict):
                if 'ai_dict' in ai_dict and len(ai_dict) == 1:
                    # Directly use the 'ai_dict' if it's the only key
                    ai_dict = ai_dict['ai_dict']
                elif 'ai_dict' in ai_dict:
                    # If 'ai_dict' exists among other keys, prioritize its content
                    ai_dict = {**ai_dict, **ai_dict['ai_dict']}
                    del ai_dict['ai_dict']
            err = None
            break
        except (ValueError, SyntaxError, NameError, AttributeError, TypeError) as ex:
            ai_dict = {"ai_dict": ai_dict_str}
            err = f"AI returned an unevaluable, non-dictionary object on try {_try} of {retries}: {ex}"
            time.sleep(2)  # Pause between retries

    return err, ai_dict

@processor
def aidict(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    # templates
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))
    
    input_fields = template.get('input_fields')
    
    # Check if each input field is present in 'task.document'
    for field in input_fields:
        field_name = field['name']
        if field_name not in task.document:
            raise NonRetriableError(f"Input field '{field_name}' is not present in the document.")

    # replace single strings with lists
    task.document = process_input_fields(task.document, input_fields)

    # Check if there are more than one input fields and grab the iterate_field
    if len(input_fields) > 1:
        iterate_field_name = task.document.get('iterate_field')
        if not iterate_field_name:
            raise NonRetriableError("More than one input field requires an 'iterate_field' value in extras.")
        if iterate_field_name != "False" and iterate_field_name not in [field['name'] for field in input_fields]:
            raise NonRetriableError(f"'{iterate_field_name}' must be present in 'input_fields' when there are more than one input fields, or you may use a 'False' string for no iteration.")
    else:
        # use the first field
        iterate_field_name = input_fields[0]['name']

    if iterate_field_name != "False":
        iterator = task.document.get(iterate_field_name)
    else:
        iterator = ["False"]

    # Identify if the iterator is a list of lists
    is_list_of_lists = isinstance(iterator[0], list)

    # output fields
    output_fields = template.get('output_fields')

    # get the model and begin
    model = task.document.get('model')

    # Loop over iterator field list, or if "False", just loop once
    for outer_index, item in enumerate(iterator):
        # if the item is not a list, we make it one
        if not isinstance(item, list):
            item = [item]

        ai_dicts = []
        
        # loop over inner list
        for inner_index in range(len(item)):
            # set the fields for the template's loop inclusions, if it has any
            task.document['outer_index'] = outer_index
            task.document['inner_index'] = inner_index

            template_text = Template.remove_fields_and_extras(template.get('text'))

            if template_text:
                jinja_template = env.from_string(template_text)
                prompt = jinja_template.render(task.document)
            else:
                raise NonRetriableError("Couldn't find template text.")

            # call the ai
            err, ai_dict = ai_prompt_to_dict(
                task=task,
                model=model,
                prompt=prompt,
                retries=3
            )
            ai_dicts.append(ai_dict)

            if err:
                print(ai_dict)
                raise NonRetriableError(f"{err}: {ai_dict}")

        if is_list_of_lists:
            # Process as list of lists
            sublist_result_dict = {field['name']: [] for field in output_fields}
            for dictionary in ai_dicts:
                for key, value in dictionary.items():
                    sublist_result_dict[key].append(value)

            for field in output_fields:
                field_name = field['name']
                if field_name not in task.document:
                    task.document[field_name] = []
                task.document[field_name].append(sublist_result_dict[field_name])
        else:
            # Process as a simple list
            result_dict = {field['name']: [] for field in output_fields}
            for dictionary in ai_dicts:
                try:
                    for key, value in dictionary.items():
                        result_dict[key].append(value)
                except:
                    print(dictionary)

            for field in output_fields:
                field_name = field['name']
                if field_name not in task.document:
                    task.document[field_name] = []
                if not isinstance(task.document[field_name], list):
                    task.document[field_name] = [task.document[field_name]]
                task.document[field_name].extend(result_dict[field_name])

    task.document.pop('outer_index', None)
    task.document.pop('inner_index', None)

    return task


@processor
def aistruct(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    from openai import OpenAI
    from typing import List
    from pydantic import create_model
    import instructor
    from datetime import datetime, date, time

    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    input_fields = template.get('input_fields')
    for field in input_fields:
        field_name = field['name']
        if field_name not in task.document:
            raise NonRetriableError(f"Input field '{field_name}' is not present in the document.")

    task.document = process_input_fields(task.document, input_fields)

    # Determine the iterate_field
    if len(input_fields) > 1:
        iterate_field_name = task.document.get('iterate_field', 'False')
        if iterate_field_name != "False" and iterate_field_name not in [field['name'] for field in input_fields]:
            raise NonRetriableError(f"'{iterate_field_name}' must be present in 'input_fields' when there are more than one input fields, or you may use a 'False' string for no iteration.")
    else:
        iterate_field_name = input_fields[0]['name']

    iterator = task.document.get(iterate_field_name, ["False"]) if iterate_field_name != "False" else ["False"]
    is_list_of_lists = isinstance(iterator, list) and all(isinstance(elem, list) for elem in iterator)
    app.logger.info(is_list_of_lists)    

    # build a custom model from the output fields
    output_fields = template.get('output_fields')

    # Mapping of type aliases to Python types and list types
    type_mapping = {
        "string": str,
        "strings": List[str],
        "stringset": List[str],  # Assuming stringset is also meant to be a list of strings
        "int": int,
        "ints": List[int],
        "float": float,
        "floats": List[float],
        "boolean": bool,
        "booleans": List[bool]
    }

    CustomModel = create_model(
        'CustomModel',
        **{field['name']: (type_mapping.get(field['type'], str), ...) for field in output_fields}
    )

    # get the requested model
    model = task.document.get('model')

    if "gpt" in model:
        # Initialize the OpenAI client with the an instructor patch
        client = instructor.patch(OpenAI(api_key=task.document.get('openai_token')))

        system_prompt = task.document.get('system_prompt', "You extract things from texts and return them as specified in variables.")

        for outer_index, item in enumerate(iterator):
            if not isinstance(item, list):
                item = [item]

            ai_structs = []

            for inner_index, sub_item in enumerate(item):
                task.document['outer_index'] = outer_index
                task.document['inner_index'] = inner_index

                # Construct the prompt
                template_text = Template.remove_fields_and_extras(template.get('text'))
                if template_text:
                    jinja_template = env.from_string(template_text)
                    prompt = jinja_template.render(task.document)
                else:
                    raise NonRetriableError("Couldn't find template text.")

                # Call the AI using the dynamically created CustomModel
                response = client.chat.completions.create(
                    model=model,
                    response_model=CustomModel,
                    max_retries=3,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ]
                )

                # check it matches the Model we built
                assert isinstance(response, CustomModel)

                # loop through the output_fields
                for field in output_fields:
                    assert hasattr(response, field.get('name'))
    
                # Parse the response
                parsed_response = response.dict()
                ai_structs.append(parsed_response)

            # Process and compile the results based on the structure of the iterator
            if is_list_of_lists:
                # Process as list of lists
                sublist_result_dict = {field['name']: [] for field in output_fields}
                for dictionary in ai_structs:
                    for key, value in dictionary.items():
                        sublist_result_dict[key].append(value)

                for field in output_fields:
                    field_name = field['name']
                    if field_name not in task.document:
                        task.document[field_name] = []
                    task.document[field_name].append(sublist_result_dict[field_name])
            else:
                # Process as a simple list
                result_dict = {field['name']: [] for field in output_fields}
                for dictionary in ai_structs:
                    for key, value in dictionary.items():
                        result_dict[key].append(value)

                for field in output_fields:
                    field_name = field['name']
                    if field_name not in task.document:
                        task.document[field_name] = []
                    task.document[field_name].extend(result_dict[field_name])


        task.document.pop('outer_index', None)
        task.document.pop('inner_index', None)

        return task
    else:
        raise NonRetriableError("The aistruct processor expects a supported model.")

@processor
def split_file():
    # read PDFs. read images. 
    # PDFs come from our drives, email, slack, etc.
    # images files come from cameras,  video files need to be split up.
    # video to images? that is a aiffmpeg command though (which implies work on it must be done)
    # website screenshost
    # image, you may need overlap
    # do that with pdfs too, but no overlap, so split on pages, pages--->images 1:1
    # build the lists that are needed for the processors.
    pass

# look at a picture and get stuff
# TODO
# we must assume at this point we are operating on images only, and expect to return text from them
# we don't read PDFs or any other formats like that with this processor, it is what is seen only
# we may, however, expect to SEE text or objects, or maybe even other types of things (people).
# this means this processor is always called with lists of files, which could be a single file
@processor
def aivision(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    # Output and input fields
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')
    model = task.document.get('model', "gv-objects")

    # use the first output field
    try:
        output_fields = template.get('output_fields')
        output_field = output_fields[0].get('name')
    except:
        output_field = "objects"

    # Check if each input field is present in 'task.document'
    input_fields = template.get('input_fields')

    for field in input_fields:
        field_name = field['name']
        if field_name not in task.document:
            raise NonRetriableError(f"Input field '{field_name}' is not present in the document.")

    if not task.document.get('filename') or not task.document.get('content_type'):
        raise NonRetriableError("Document must contain 'filename' and 'content_type'.")

    filename = task.document.get('filename')
    content_type = task.document.get('content_type')

    # Deal with lists
    if isinstance(filename, list):
        if not isinstance(content_type, list):
            raise NonRetriableError("If filename is a list, content_type must also be a list.")
        if len(filename) != len(content_type):
            raise NonRetriableError("Document must contain equal size lists of filename and content-type.")
    elif isinstance(filename, str) and isinstance(content_type, str):
        # If both variables are strings, convert them into lists
        filename = [filename]
        content_type = [content_type]
    else:
        # If none of the conditions are met, raise a NonRetriableError
        raise NonRetriableError("Both filename and content_type must either be equal size lists or strings.")

    # Check if the mime type is supported for PNG, JPG, and BMP
    supported_content_types = ['image/png', 'image/jpeg', 'image/bmp', 'image/jpg']

    for index, file_name in enumerate(filename):
        content_parts = content_type[index].split(';')[0]
        if content_parts not in supported_content_types:
            raise NonRetriableError(f"Unsupported file type for {file_name}: {content_type[index]}")

    # loop through the detection filenames
    for index, file_name in enumerate(filename):

        # EasyOCR
        if model == "easyocr":
            # check required services (GPU boxes)
            defer, selected_box = box_required(box_type="ocr")
            if defer:
                if selected_box:
                    # Logic to start or wait for the box to be ready
                    # Possibly setting up the box or waiting for it to transition from halted to active
                    raise RetriableError("EasyOCR box is being started to run text extraction.")
                else:
                    # No box is available, raise a non-retriable error
                    raise NonRetriableError("No available EasyOCR machine to run extraction.")

            # Build the list of mitta_uris from filenames and username, with user token added for access
            mitta_uris = [f"https://{app.config.get('APP_DOMAIN')}/d/{user.get('name')}/{file_name}?token={user.get('api_token')}"]

            # Get the page numbers from task.document, or create a default list if not provided
            page_nums = task.document.get('page_num') or task.document.get('page_nums')

            if not page_nums:
                page_nums = [1]
            elif not isinstance(page_nums, list):
                raise NonRetriableError("Page numbers must be provided as a list.")
            else:
                page_nums = page_nums[index]

            # url for the ocr box
            ocr_url = f"http://ocr:{app.config['CONTROLLER_TOKEN']}@{selected_box.get('ip_address')}:9898/read"

            try:
                # make the call
                ocr_data = {
                    "mitta_uri": mitta_uris,
                    "page_numbers": page_nums
                }

                response = requests.post(ocr_url, json=ocr_data, headers={"Content-Type": "application/json"}, timeout=60)

                if response.status_code == 200:
                    texts = response.json().get("texts")
                    coords = response.json().get("coords")

                    # Extend the texts to the output field in task.document
                    if not task.document.get(output_field):
                        task.document[output_field] = []
                    task.document[output_field].extend(texts)

                    # Store the bounding box coordinates in task.document['text_coords']
                    if not task.document.get('text_coords'):
                        task.document['text_coords'] = []
                    task.document['text_coords'].extend(coords)

                    # Store the page numbers in task.document['page_nums']
                    if not task.document.get('page_nums'):
                        task.document['page_nums'] = []
                    task.document['page_nums'].extend(page_nums)

                elif response.status_code == 502:
                    raise RetriableError(f"EasyOCR server is starting with status: {response.status_code}.")
                else:
                    raise NonRetriableError(f"Unexpected status code from EasyOCR endpoint: {response.status_code}.")
                    
            except RetriableError as ex:
                app.logger.info(f"ocr processor: {ex}")
                raise  # Re-raise the RetriableError to be caught by the process function

            except Exception as ex:
                app.logger.info(f"ocr processor: {ex}")
                raise NonRetriableError(f"Exception talking to EasyOCR embedding endpoint: {ex}")


        # Google Vision OCR
        elif model == "gv-ocr":
            # Now run the code for image processing
            image_uri = f"gs://{app.config['CLOUD_STORAGE_BUCKET']}/{uid}/{file_name}"

            # Download the file contents as bytes
            content = download_as_bytes(uid,file_name)

            # Split the image into segments by height
            image_segments = split_image_by_height(BytesIO(content))

            # Initialize the Vision API client
            vision_client = vision.ImageAnnotatorClient()

            _texts = [] # array by image segment (page)

            try:
                for i, segment_bytesio in enumerate(image_segments):
                    # Create a vision.Image object for each segment
                    segment_image = vision.Image(content=segment_bytesio.read())

                    # Detect text in the segment
                    response = vision_client.document_text_detection(image=segment_image)
                    app.logger.info(response)
                    # Get text annotations for the segment
                    texts = response.text_annotations

                    # Extract only the descriptions (the actual text)
                    for text in texts:
                        # append it to our new array
                        _texts.append(text.description)
                        break

            except Exception as ex:
                raise NonRetriableError(f"Something went wrong with character detection. Contact support: {ex}")

            if not task.document.get(output_field):
                task.document[output_field] = []
            task.document[output_field].append(_texts)

        # Google Vision Objects
        elif model == "gv-objects":
            # Now run the code for image processing
            image_uri = f"gs://{app.config['CLOUD_STORAGE_BUCKET']}/{uid}/{file_name}"

            client = vision.ImageAnnotatorClient()
            response = client.annotate_image({
                'image': {'source': {'image_uri': image_uri}},
                'features': [{'type_': vision.Feature.Type.LABEL_DETECTION}]
            })

            # Get a list of detected labels (objects)
            labels = [label.description.lower() for label in response.label_annotations]

            # Append the labels list to task.document[output_field]
            if not task.document.get(output_field):
                task.document[output_field] = []
            task.document[output_field].append(labels)

        # Gemini Pro Vision Scene
        elif "gemini-pro-vision" in model:
            from PIL import Image
            import time

            if not task.document.get('gemini_token'):
                raise NonRetriableError(f"You'll need to specify a 'gemini_token' in extras to use the {model} model.")

            if task.document.get('system_prompt'):
                system_prompt = task.document.get('system_prompt')
            else:
                system_prompt = "Describe in detail the image scene."

            genai.configure(api_key=task.document.get('gemini_token'))

            # Get the document
            gcs = storage.Client()
            bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
            blob = bucket.blob(f"{uid}/{file_name}")

            # even though the exceptions says it takes a Blob, we use PIL instead
            image_bytes = blob.download_as_bytes()
            image_stream = BytesIO(image_bytes)
            img = Image.open(image_stream)

            # generate (troubled APIs get retries)
            max_retries = 3
            retry_delay = 4  # seconds

            for attempt in range(max_retries):
                try:
                    model = genai.GenerativeModel(model)
                    response = model.generate_content([system_prompt, img], stream=True)
                    response.resolve()
                    break  # Exit the retry loop if successful
                except Exception as ex:
                    if attempt < max_retries - 1:  # Retry if there are attempts left
                        time.sleep(retry_delay)
                    else:  # Raise the exception if all retries are exhausted
                        error_message = f"Gemini error: {ex}"
                        error_details = f"Error type: {type(ex).__name__}\nError message: {str(ex)}\nError traceback:\n{traceback.format_exc()}"
                        raise NonRetriableError(f"{error_message}\n\nError details:\n{error_details}")

            # Create an internal list to store the content for the current file
            file_content = [response.text]

            # Append the internal list to the task.document[output_field]
            if not task.document.get(output_field):
                task.document[output_field] = []

            task.document[output_field].append(file_content)

        # GPT Scene
        elif "gpt" in model:
            # Get the document
            gcs = storage.Client()
            bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
            blob = bucket.blob(f"{uid}/{file_name}")

            # download to file
            content = blob.download_as_bytes()
            base64_data = base64.b64encode(content).decode('utf-8')

            # move this to util and clean up
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {task.document.get('openai_token')}"
            }

            if 'system_prompt' in task.document:
                system_prompt = task.document.get('system_prompt')
            else:
                system_prompt = "What is in the image?"

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": system_prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 300,
                "n": 3  # Specify the number of choices to generate
            }

            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)

            if 'error' in response.json():
                raise NonRetriableError(response.json().get('error').get('message'))

            # Extract all the choices from the response
            choices = response.json().get('choices')

            # Create an internal list to store the content for the current file
            file_content = []

            for choice in choices:
                try:
                    content = choice.get('message').get('content')
                    file_content.append(content)
                except:
                    raise NonRetriableError("Couldn't decode a response from the AI.")

            # Append the internal list to the task.document[output_field]
            if not task.document.get(output_field):
                task.document[output_field] = []

            task.document[output_field].append(file_content)

        # Claude Scene
        elif "claude" in model:
            if not task.document.get('anthropic_token'):
                raise NonRetriableError(f"You'll need to specify an 'anthropic_token' in extras to use the {model} model.")

            import anthropic
            client = anthropic.Client(api_key=task.document.get('anthropic_token'))

            # Set the system prompt based on task document or use a default
            if 'system_prompt' in task.document:
                system_prompt = task.document.get('system_prompt')
            else:
                system_prompt = "What is in the image?"


            # Get the document
            gcs = storage.Client()
            bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
            blob = bucket.blob(f"{uid}/{file_name}")

            # download to file
            content = blob.download_as_bytes()
            base64_data = base64.b64encode(content).decode('utf-8')

            # Use the system_prompt variable as the prompt for Claude
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": content_type[index],
                                "data": base64_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": system_prompt  # Use the system prompt
                        }
                    ],
                }
            ]

            # Make a request to the Claude API
            try:
                response = client.messages.create(
                    model=model,  # Specify the appropriate model
                    max_tokens=1024,
                    messages=messages,
                )
                app.logger.info(response.content)

                # Extract the response content
                content_blocks = response.content

                # Create an internal list to store the text content for the current file
                file_content = []

                for block in content_blocks:
                    if block.type == 'text':
                        file_content.append(block.text)

                # Append the internal list to the task.document[output_field]
                if not task.document.get(output_field):
                    task.document[output_field] = []

                task.document[output_field].append(file_content)

            except Exception as e:
                raise NonRetriableError(f"Error in Claude API call: {str(e)}")

    return task


# generate images off a prompt
@processor
def aiimage(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    # Output and input fields
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')

    output_fields = template.get('output_fields')   
    # Check that there is no more than one output field
    if len(output_fields) > 1:
        raise NonRetriableError("Only one output field is allowed in 'output_fields'.")

    # use the first output field, or set one
    try:
        output_field = output_fields[0].get('name')
    except:
        output_field = "mitta_uri"

    # Check if each input field is present in 'task.document'
    input_fields = template.get('input_fields')

    # Ensure there is only one input field
    if len(input_fields) != 1:
        raise NonRetriableError("Only one input field is allowed in 'input_fields'.")

    for field in input_fields:
        field_name = field['name']
        if field_name not in task.document:
            raise NonRetriableError(f"Input field '{field_name}' is not present in the document.")
    
    input_field = input_fields[0].get('name')

    # Get the value associated with input_field from the document
    input_value = task.document.get(input_field)

    if isinstance(input_value, str):
        # If it's a string, convert it to a list with one element
        prompts = [input_value]
    elif isinstance(input_value, list):
        # If it's a list, ensure it contains only strings
        if all(isinstance(item, str) for item in input_value):
            prompts = input_value
        else:
            raise NonRetriableError("Input field must be a string or a list of strings.")
    else:
        raise NonRetriableError("Input field must be a string or a list of strings.")

    # Apply [:1000] to the input field as the prompt
    if not task.document.get(output_field):
        task.document[output_field] = []

    for prompt in prompts:
        prompt = prompt[:1000]

        if not prompt:
            raise NonRetriableError("Input field is required and should contain the prompt.")

        num_images = task.document.get('num_images', 0)
        if not num_images:
            num_images = 1

        if "dall-e" in task.document.get('model'):
            openai.api_key = task.document.get('openai_token')

            try:
                response = openai.images.generate(
                    prompt=prompt,
                    model=task.document.get('model'),
                    n=int(num_images),
                    size="1024x1024"
                )

                urls = []
                revised_prompts = []

                # Loop over the 'data' list and extract the 'url' from each item
                for item in response.data:
                    if item.url:
                        image_response = requests.get(item.url)
                        if image_response.status_code == 200:
                            image_file = BytesIO(image_response.content)
                            image_bytes = image_file.getvalue()

                            content_type = 'image/png'
                            new_filename = random_string(16) + ".png"
                            bucket_uri = upload_to_storage_requests(uid, new_filename, image_bytes, content_type)

                            access_uri = f"https://{app.config.get('APP_DOMAIN')}/d/{user.get('name')}/{new_filename}"
                            
                            urls.append(item.url)

                            if output_field not in task.document:
                                task.document[output_field] = [access_uri]
                            else:
                                task.document[output_field].append(access_uri)
                        else:
                            raise NonRetriableError("Failed to retrieve the file from OpenAI.")

            except Exception as ex:
                # non-retriable error for now but add retriable as needed
                raise NonRetriableError(f"aiimage processor: exception talking to OpenAI image create: {ex}")
        else:
            raise NonRetriableError(f"Need a valid model. Try 'dall-e-2' or 'dall-e-3'.")

    return task


@processor
def read_file(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')

    output_fields = template.get('output_fields')   
    # Check that there no more than one output field
    if len(output_fields) > 1:
        raise NonRetriableError("Only one output field is allowed in 'output_fields'.")

    # use the first output field, or set one
    try:
        output_field = output_fields[0].get('name')
    except:
        output_field = "texts"

    filename = task.document.get('filename')
    content_type = task.document.get('content_type')

    # Deal with lists
    if isinstance(filename, list):
        if not isinstance(content_type, list):
            raise NonRetriableError("If filename is a list, content_type must also be a list.")
        if len(filename) != len(content_type):
            raise NonRetriableError("Document must contain equal size lists of filename and content-type.")
    elif isinstance(filename, str) and isinstance(content_type, str):
        # If both variables are strings, convert them into lists
        filename = [filename]
        content_type = [content_type]
    else:
        # If none of the conditions are met, raise a NonRetriableError
        raise NonRetriableError("Both filename and content_type must either be equal size lists or strings.")

    # Check if the mime type is supported
    supported_content_types = ['application/pdf', 'text/plain', 'text/csv', 'application/json']

    for index, file_name in enumerate(filename):
        content_parts = content_type[index].split(';')[0]
        if content_parts not in supported_content_types:
            raise NonRetriableError(f"Unsupported file type for {file_name}: {content_type[index]}")
    
    # set page_numbers from page_number array
    page_numbers = task.document.get('page_number')

    # Process page numbers
    if page_numbers is not None:
        if not isinstance(page_numbers, list):
            raise NonRetriableError("Page numbers must be a list.")
        
        # Check if the number of page number lists is the same as the number of filenames
        if len(page_numbers) != len(filename):
            raise NonRetriableError("Filename and page numbers lists must be of the same size.")

    # set the output field
    if not task.document.get(output_field):
        task.document[output_field] = []

    import fitz
    # loop over the filenames
    for index, file_name in enumerate(filename):
        if "application/pdf" in content_type[index]:
                # Get the document from Google Cloud Storage
                gcs = storage.Client()
                bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
                blob = bucket.blob(f"{uid}/{file_name}")
                pdf_content = blob.download_as_bytes()

                # Create a BytesIO object for the PDF content
                pdf_content_stream = BytesIO(pdf_content)

                # Open the PDF with fitz
                doc = fitz.open(stream=pdf_content_stream, filetype="pdf")

                num_pdf_pages = len(doc)

                # Build a list of page numbers to process
                index_pages = []
                if page_numbers:
                    if page_numbers[index] < 1:
                        raise Exception("Page numbers must be whole numbers > 0.")
                    if page_numbers[index] > num_pdf_pages:
                        raise Exception(f"Page number ({page_numbers[index]}) is larger than the number of pages ({num_pdf_pages}).")
                    index_pages.append(page_numbers[index]-1)
                else:
                    index_pages = list(range(num_pdf_pages))

                texts = []

                # Extract text from specified pages
                for page_num in index_pages:
                    page = doc.load_page(page_num)
                    text = page.get_text()
                    texts.append(text)
                # Assuming task.document[output_field] is a list where you want to store the extracted texts
                task.document[output_field].extend(texts)

                # TODO ensure we extracted the texts and if we didn't, be sure that jump task processors can know this
        
        elif "text/plain" in content_type[index]:
            # grab document
            gcs = storage.Client()
            bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
            blob = bucket.blob(f"{uid}/{file_name}")
            text = blob.download_as_text()

            # split on words
            words = text.split()
            chunks = []
            current_chunk = []

            # set the page chunk size (number of characters per page)
            page_chunk_size = task.document.get('page_chunk_size', 1536)

            # build the chunks
            for word in words:
                current_chunk.append(word)
                if len(current_chunk) >= page_chunk_size:
                    chunks.append(' '.join(current_chunk))
                    current_chunk = []

            # append any leftovers
            if current_chunk:
                chunks.append(' '.join(current_chunk))

            texts = chunks
            
            # update document
            task.document[output_field].extend(texts)

        elif "application/json" in content_type[index]:
            # grab JSON document as text
            gcs = storage.Client()
            bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
            blob = bucket.blob(f"{uid}/{file_name}")
            texts = blob.download_as_text()
            try:
                json_data = json.loads(texts)
            except:
                raise NonRetriableError("Unable to read the file's JSON data.")

            # append the JSON to the document
            if 'json_data' not in task.document or not task.document['json_data']:
                task.document['json_data'] = [json_data]
            else:
                if not isinstance(task.document['json_data'], list):
                    task.document['json_data'] = [task.document['json_data']]
                
                task.document['json_data'].append(json_data)

            task.document[output_field].append("Data exported to 'json_data'")

        elif "text/csv" in content_type[index]:
            import pandas as pd
            # check for prepend string
            if task.document.get('prepend_string'):
                prepend_string = task.document.get('prepend_string')
            else:
                prepend_string = ""

            # Get the document
            gcs = storage.Client()
            bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
            blob = bucket.blob(f"{uid}/{file_name}")
            file_content = blob.download_as_bytes()

            if task.document.get('split_num'):
                split_num = int(task.document.get('split_num'))
                if task.document.get('split_start'):
                    split_start = int(task.document.get('split_start'))
                else:
                    split_start = 0
            else:
                split_num = 0
                split_start = 0

            # put the max threshold in config at some point
            if not split_num and len(file_content) > 800000:
                task.document['max_split_size_limit'] = 800000
                raise NonRetriableError("Maximum task size approached. You may want to use the 'split_num' and 'split_start' keys in the document to address this.")

            # Read the CSV content into DataFrame without headers initially
            df = pd.read_csv(BytesIO(file_content), header=None)

            # Find the first row with valid data to be used as headers
            first_valid_header_index = df.apply(lambda row: row.notna().all(), axis=1).idxmax()
            headers = df.iloc[first_valid_header_index]

            # Check if the length of headers matches the number of columns
            if len(headers) == df.shape[1]:
                # Set the headers
                df.columns = headers
                # Drop the header row from the DataFrame
                df = df.drop(first_valid_header_index)
            else:
                # Fallback to default naming if headers don't match
                df.columns = ['column_' + str(i) for i in range(1, df.shape[1] + 1)]

            # Replace spaces with underscores in column names and handle empty rows
            df.columns = [prepend_string + col.replace(' ', '_') for col in df.columns]
            df.dropna(how='all', inplace=True)
            df = df.reset_index(drop=True)

            # Process rows based on split_start and split_num
            if split_start > 0:
                df = df.iloc[split_start:]

            if split_num > 0:
                df = df.head(split_num)

            # Replace NaN values with None
            df = df.where(pd.notna(df), None)

            # Drop rows where all elements are None
            df.dropna(how='all', inplace=True)

            # process empty items for string, int and floats - open a ticket for more types
            data_dict = {}
            texts = []

            # patch all the None fields
            for index, row in df.to_dict(orient='list').items():
                row_data = []
                row_type = None  # Reset row_type for each row 

                # Determine the row_type by scanning the entire column if needed
                for col_index, item in enumerate(row):
                    if row_type is None and (pd.isna(item) or item is None):
                        # Scan the entire column for a valid data type
                        for col_item in df.iloc[:, col_index]:
                            if not pd.isna(col_item) and col_item is not None:
                                if isinstance(col_item, str):
                                    row_type = 'string'
                                elif isinstance(col_item, int):
                                    row_type = 'int'
                                elif isinstance(col_item, float):
                                    row_type = 'float'
                                break  # Break after finding the valid data type

                row_index = 0
                for col_index, item in enumerate(row):
                    # limit to the split_num
                    if row_index > split_num and split_num > 0:
                        break

                    # Determine the type based on the first non-null, non-NaN item
                    if row_type is None and not pd.isna(item) and item is not None:
                        if isinstance(item, str):
                            row_type = 'string'
                        elif isinstance(item, int):
                            row_type = 'int'
                        elif isinstance(item, float):
                            row_type = 'float'

                    if isinstance(item, str):
                        try:
                            converted_item = int(item)
                            row_type = 'int'
                        except ValueError:
                            try:
                                converted_item = float(item)
                                row_type = 'float'
                            except ValueError:
                                converted_item = item
                        row_data.append(converted_item)  
                    elif pd.isna(item) or item is None:
                        # Replace None based on the determined type
                        if row_type == 'int':
                            row_data.append(0)
                        elif row_type == 'float':
                            row_data.append(0.0)
                        elif row_type == 'string':
                            row_data.append("")
                        else:
                            row_data.append(None)
                    else:
                        row_data.append(item)

                    # add to the row index
                    row_index = row_index + 1

                # push the data into the return values
                data_dict[index] = row_data
                
            # Add the values to the document
            texts = []
            for key, value in data_dict.items():
                task.document[key] = value
                texts.append(f"{key}:{','.join(map(str, value))}")
            
            # update document
            task.document[output_field].extend(texts)
        else:
            raise NonRetriableError("Processor read_file supports text/plain, application/pdf, application/json, and text/csv content types only.")

    return task


@processor
def read_uri(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')
    
    # use the first output field TODO FIX THIS
    try:
        output_fields = template.get('output_fields')
        output_field = output_fields[0].get('name')
    except:
        output_field = "texts"

    uri = task.document.get('uri')

    if isinstance(uri, str):
        uri = [uri]

    method = task.document.get('method')
    if isinstance(method, str):
        method = [method]

    if not uri or not method:
        raise NonRetriableError("URI and method are required in extras or POST fields defined in input_fields.")

    if len(uri) != len(method):
        raise NonRetriableError("URI and method lists must be the same size.")

    # Assuming 'bearer_token' is also a part of input_fields when needed
    bearer_token = task.document.get('bearer_token')
    if isinstance(bearer_token, str):
        bearer_token = [bearer_token]

    # check if filename and content_type are set
    filename = task.document.get('filename')
    if isinstance(filename, str):
        filename = [filename]

    content_type = task.document.get('content_type')
    if isinstance(content_type, str):
        content_type = [content_type]

    if content_type and filename: 
        if (len(content_type) != len(filename)) and (len(filename) != len(uri)):
            raise NonRetriableError("The URI, content_type, filename, and method list must be the same size.")

    # response objects (wipes any existing filename and content_type set in document)
    task.document['filename'] = []
    task.document['content_type'] = []

    if bearer_token and (len(bearer_token) != len(uri)):
        raise NonRetriableError("URI, method, and bearer_token lists must be the same size.")

    for index in range(len(uri)):
        # Now, you can proceed to build the request based on the method and URI
        if method[index] == 'GET':
            # Perform a GET request
            if bearer_token:
                headers = {'Authorization': f'Bearer {bearer_token[index]}'}
                response = requests.get(uri[index], headers=headers)
            else:
                response = requests.get(uri[index])

        elif method[index] == 'POST':
            data = {}
            for field in task.document.get('data_fields'):
                data[field] = task.document[field]
            
            # Perform a POST request
            if bearer_token:
                headers = {'Authorization': f'Bearer {bearer_token[index]}'}
                response = requests.post(uri[index], headers=headers, json=data, stream=True, allow_redirects=True)

            else:
                response = requests.post(uri[index], json=data, stream=True, allow_redirects=True)

        else:
            raise NonRetriableError("Request must contain a 'method' key that is one of: ['GET','POST'].")

        if response.status_code != 200:
            raise NonRetriableError(f"Request failed with status code: {response.status_code}")

        # Check if the Content-Disposition header is present
        if 'Content-Type' in response.headers:
            _content_type = response.headers['Content-Type']
        else:
            if not content_type:
                raise NonRetriableError(f"Unable to determine content type. The URL ({uri[index]}) will require passing in the filename and content_type fields.")
            else:
                _content_type = content_type[index]

        # if filename is not set, or empty, we'll generate one from the inferred content type
        if not filename:
            file_extension = get_file_extension(_content_type)

            if not file_extension:
                raise NonRetriableError("This URL will require using the filename and content_type fields.")
            _filename = f"{random_string(16)}.{file_extension}"
        else:
            print(filename)
            _filename = filename[index]

        bucket_uri = upload_to_storage_requests(uid, _filename, response.content, _content_type)

        task.document['filename'].append(_filename)
        task.document['content_type'].append(_content_type)

    return task


@processor
def aispeech(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))

    output_fields = template.get('output_fields')
    # Check that there is no more than one output field
    if len(output_fields) > 1:
        raise NonRetriableError("Only one output field is allowed in 'output_fields'.")

    # use the first output field, or set one
    try:
        output_field = output_fields[0].get('name')
    except:
        output_field = "mitta_uri"

    input_fields = template.get('input_fields')

    if not input_fields:
        raise NonRetriableError("You must have 'input_fields' defined for this processor.")

    # needs to be moved
    # scan for required fields in the input
    for field in input_fields:
        field_name = field['name']
        if field_name not in task.document:
            raise NonRetriableError(f"Input field '{field_name}' is not present in the document.")
    
    # user stuff, arguable we need it
    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')

    # grab the first input field name that isn't the filename
    uses_filename = False
    for _input_field in input_fields:
        if 'filename' in _input_field.get('name'):
            uses_filename = True
            continue
        else:
            input_field = _input_field.get('name')

    # set the filename from the document
    filename = task.document.get('filename')
    if uses_filename and 'mp3' not in filename:
        filename = task.document.get('filename')
        if not filename:
            raise NonRetriableError("If you specify an input field for filename, you must provide one for use in this node.")
        if isinstance(filename, list):
            filename = filename[0]
    else:
        rand_name = random_name(2)
        filename = f"{rand_name}-mitta-aispeech.mp3"

    # lets support only a list of strings
    if isinstance(task.document.get(input_field), list):
        items = task.document.get(input_field)
        if isinstance(items[0], list):
            raise NonRetriableError(f"Input field {input_field} needs to be a list of strings. Found a list of lists instead.")
    else:
        items = [task.document.get(input_field)]

    model = task.document.get('model')
    if not model:
        raise NonRetriableError("A key for 'model' must be defined and be one of ['tts-1','eleven_multilingual_v2','eleven_monolingual_v1'].")
    
    new_filenames = []
    # loop through items to process
    for index, item in enumerate(items):
        # template the string, if needed
        template_text = Template.remove_fields_and_extras(item)
        template_text = template_text.strip()

        try:
            if template_text:
                jinja_template = env.from_string(template_text)
                item = jinja_template.render(task.document)
        except:
            pass

        if isinstance(task.document.get('voice'), list):
            voice = task.document.get('voice')[index]
        elif isinstance(task.document.get('voice'), str):
            voice = task.document.get('voice')
        else:
            voice = False

        if "tts" in model:
            openai.api_key = task.document.get('openai_token')
            if not voice:
                voice = "alloy"
            response = openai.audio.speech.create(model=model, voice=voice, input=item)
            
            # Assuming 'response.content' contains the binary content of the audio file
            audio_data = response.content

        elif "eleven" in model:
            try:
                from elevenlabs import voices, generate, set_api_key
                set_api_key(task.document.get('elevenlabs_token'))
                if not voice:
                    voice = "Nicole"

                audio_data = generate(text=item, voice=voice, model=model)
            except Exception as ex:
                app.logger.info(f"Error with EL: {ex}")
                raise NonRetriableError("Something went wrong wih the call to ElevenLabs.")

        # save audio file
        new_filename = add_index_to_filename(filename, index)
        
        content_type = 'audio/mpeg'  # Set the appropriate content type for the audio file
        bucket_uri = upload_to_storage_requests(uid, new_filename, audio_data, content_type)

        access_uri = f"https://{app.config.get('APP_DOMAIN')}/d/{user.get('name')}/{new_filename}"

        if not task.document.get(output_field):
            task.document[output_field] = []
        task.document[output_field].append(access_uri)

        new_filenames.append(new_filename)

    if new_filenames:
        task.document['filename'] = new_filenames
    return task


# audio input, text output
@processor
def aiaudio(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    # OpenAI only for now
    openai.api_key = task.document.get('openai_token')

    if not template:
        raise TemplateNotFoundError(template_id=node.get('template_id'))
    
    # use the first output field
    try:
        output_fields = template.get('output_fields')
        output_field = output_fields[0].get('name')
    except:
        output_field = "texts"

    user = User.get_by_uid(uid=task.user_id)
    uid = user.get('uid')
    
    filename = task.document.get('filename')
    content_type = task.document.get('content_type')

    # Check if 'filename' is a list, and if so, get the first element
    if isinstance(filename, list) and len(filename) > 0:
        filename = filename[0]

    # Check if 'content_type' is a list, and if so, get the first element
    if isinstance(content_type, list) and len(content_type) > 0:
        content_type = content_type[0]

    # Get the document
    gcs = storage.Client()
    bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
    blob = bucket.blob(f"{uid}/{filename}")
    audio_file = BytesIO()

    audio_file.name = f"{filename}"

    # uri for google, if used
    uri = f"gs://{app.config['CLOUD_STORAGE_BUCKET']}/{uid}/{filename}"

    # download to file, for openai if used
    blob.download_to_file(audio_file)
    audio_file.content_type = content_type
    
    # must seek to the start
    audio_file.seek(0)

    # Get the file size using the BytesIO object's getbuffer method
    file_size = len(audio_file.getbuffer())

    # Check file size limit (25 MB)
    max_original_file_size = 25 * 1024 * 1024  # 25 MB in bytes
    if file_size > max_original_file_size:
        raise NonRetriableError("Original file size exceeds the 25 MB limit.")

    # for now, just do one up to 25MB
    audio_chunks = [audio_file]

    # Iterate through each chunk and send it to Whisper
    for chunk_stream in audio_chunks:
        # process the audio
        model = task.document.get('model', "whisper-1")
        if "whisper" in model:
            # Check if the mime type is supported
            supported_content_types = ['audio/mpeg', 'audio/mpeg3', 'audio/x-mpeg-3', 'audio/mp3', 'audio/mpeg-3', 'audio/wav', 'audio/webm', 'audio/mp4', 'audio/x-m4a', 'audio/m4a', 'audio/x-wav']
            
            for supported_type in supported_content_types:
                if supported_type in content_type:
                    break
            else:
                raise NonRetriableError(f"Unsupported file type: {content_type}")

            transcript = openai.audio.transcriptions.create(model=model, file=chunk_stream)
            transcript_text = transcript.text
        elif "gc_speech" in model:
            # Check if the mime type is supported
            supported_content_types = [
                'audio/flac',
                'audio/l16',
                'audio/x-l16',
                'audio/linear',
                'audio/amr',
                'audio/amr-wb',
                'audio/ogg',
                'application/ogg',
                'audio/speex',
                'audio/webm',
                'audio/wav',
                'audio/mpeg',
                'audio/mpeg3',
                'audio/x-mpeg-3',
                'audio/mp3',
                'audio/mpeg-3'
            ]

            for supported_type in supported_content_types:
                if supported_type in content_type:
                    break
            else:
                raise NonRetriableError(f"Unsupported file type: {content_type}")

            from google.cloud.speech_v2 import SpeechClient
            from google.cloud.speech_v2.types import cloud_speech

            client = SpeechClient()

            features = cloud_speech.RecognitionFeatures(
                enable_automatic_punctuation=True  # Enable automatic punctuation
            )

            # Configuration for Google Cloud Speech-to-Text
            config = cloud_speech.RecognitionConfig(
                auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                language_codes=["en-US"],
                model="latest_long",
                features=features
            )

            # Create the RecognizeRequest using the bytes content
            request = cloud_speech.RecognizeRequest(
                recognizer=f"projects/sloth-ai/locations/global/recognizers/_",
                config=config,
                content=chunk_stream.read()
            )

            response = client.recognize(request=request)
            transcript_text = ""
            for result in response.results:
                # return only the first transcript
                transcript_text = transcript_text + result.alternatives[0].transcript
        else:
            raise NonRetriableError("Model must be one of 'whisper' or 'gc_speech'.")

        # split on words
        words = transcript_text.split(" ")
        chunks = []
        current_chunk = []

        # set the page chunk size (number of characters per page)
        page_chunk_size = int(task.document.get('page_chunk_size', 1536))

        # build the chunks
        for word in words:
            current_chunk.append(word)
            if len(current_chunk) >= page_chunk_size:
                chunks.append(' '.join(current_chunk))
                current_chunk = []

        # append any leftovers
        if current_chunk:
            chunks.append(' '.join(current_chunk))

    # list of strings
    task.document[output_field] = chunks
        
    # Return the modified task
    return task


@processor
def mod_store(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    user = User.get_by_uid(task.user_id)
    
    # create template service
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    if "weaviate" in task.document.get('model'):
        # Weaviate authentication
        weaviate_url = task.document.get('weaviate_url')
        weaviate_token = task.document.get('weaviate_token')
        
        if not weaviate_url or not weaviate_token:
            raise NonRetriableError("The 'weaviate' storage model needs a 'weaviate_url' and 'weaviate_token'.")
        else:
            auth = {"weaviate_url": weaviate_url, "weaviate_token": weaviate_token}
        
        # Weaviate collection (table object)
        weaviate_collection = task.document.get('table')
        if not weaviate_collection:
            weaviate_collection = task.document.get('collection')
        if not weaviate_collection:
            raise NonRetriableError("The `weaviate` storage model needs a 'table' or 'collection' name.")

        if weaviate_delete_collection(weaviate_collection, auth):
            app.logger.debug(f"Weaviate collection '{weaviate_collection}' flushed.")
            task.document['mod_store_result'] = ["success"]
        else:
            app.logger.debug(f"Weaviate collection '{weaviate_collection}' not flushed.")
            task.document['mod_store_result'] = ["failed"]

    return task


@processor
def read_store(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    user = User.get_by_uid(task.user_id)
    
    # create template service
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    if "weaviate" in task.document.get('model'):
        # let extract warn them about not having either
        success, result = extract_weaviate_params(task.document)
        if success:
            weaviate_params = result
        else:
            error_message = result["error"]
            raise NonRetriableError(error_message)

        if "weaviate-similarity" in task.document.get('model'):
            results = []
            for i in range(len(weaviate_params["queries"])):
                result = weaviate_similarity(
                    weaviate_params["weaviate_collection"],
                    weaviate_params["query_vectors"][i],
                    limit=weaviate_params["limits"][i],
                    offset=weaviate_params["offsets"][i],
                    filters=weaviate_params["filters"][i],
                    keyterms=weaviate_params["keyterms_list"][i],
                    auth=weaviate_params["auth"]
                )
                results.append(result)

            properties_lists = {}
            for res in result:
                if 'properties' in res:
                    properties = res['properties']
                    for key in properties.keys():
                        if key not in properties_lists:
                            properties_lists[key] = []
                        properties_lists[key].append(properties[key])

            for key, value in properties_lists.items():
                if key not in task.document:
                    task.document[key] = []
                task.document[key].append(value)

            task.document['weaviate_results'] = results
            return task

        if "weaviate-hybrid" in task.document.get('model'):
            results = []
            for i in range(len(weaviate_params["queries"])):
                result = weaviate_hybrid_search(
                    weaviate_params["weaviate_collection"],
                    weaviate_params["queries"][i],
                    query_vector=weaviate_params["query_vectors"][i],
                    alpha=weaviate_params["alphas"][i],
                    limit=weaviate_params["limits"][i],
                    offset=weaviate_params["offsets"][i],
                    fusion_type=weaviate_params["fusion_types"][i],
                    filters=weaviate_params["filters"][i],
                    keyterms=weaviate_params["keyterms_list"][i],
                    auth=weaviate_params["auth"]
                )
                results.append(result)

            properties_lists = {}
            for res in result:
                if 'properties' in res:
                    properties = res['properties']
                    for key in properties.keys():
                        if key not in properties_lists:
                            properties_lists[key] = []
                        properties_lists[key].append(properties[key])

            for key, value in properties_lists.items():
                if key not in task.document:
                    task.document[key] = []
                task.document[key].append(value)

            task.document['weaviate_results'] = results
            return task
   
    else:
        # FeatureBase handles it
        # if the user has a dbid, then use their database
        if user.get('dbid'):    
            doc = {
                "dbid": user.get('dbid'),
                "db_token": user.get('db_token'),
                "sql": task.document['sql']
            }
        else:
            # use a shared database
            if task.document.get('table'):
                try:
                    # swap the table name on the fly
                    table = task.document.get('table')
                    sql = task.document.get('sql')
                    username = user.get('name')
                    pattern = f'\\b{table}\\b'
                    sql = re.sub(pattern, f"{username}_{table}", sql)

                    doc = {
                        "dbid": app.config['SHARED_FEATUREBASE_ID'],
                        "db_token": app.config['SHARED_FEATUREBASE_TOKEN'],
                        "sql": sql
                    }
                except:
                    raise NonRetriableError("Unable to template your SQL to the shared database. Check syntax.")
            else:
                raise NonRetriableError("Specify a 'table' key and value and template the table in your SQL.")


        # Check if the query matches "show tables" but not "show create table"
        pattern_show_tables = r'\bshow\s+tables\b'
        pattern_show_create_table = r'\bshow\s+create\s+table\b'

        # Convert SQL to lowercase to make regex search case-insensitive
        sql_lower = sql.lower()

        # First, check if the allowed phrase "show create table" is in the query
        if re.search(pattern_show_create_table, sql_lower):
            # This is an allowed query, so you might not want to do anything, or process it as valid.
            pass
        else:
            # If the allowed phrase is not found, then check for "show tables"
            if re.search(pattern_show_tables, sql_lower):
                # If "show tables" is found and it's not part of "show create table", block the query
                raise NonRetriableError("SHOW TABLE functions are disabled for shared database access. Add a FeatureBase account to settings to enable advanced queries.")

        resp, err = featurebase_query(document=doc)
        if err:
            if "exception" in err:
                raise RetriableError(err)
            else:
                # if dropping and doesn't exist
                if "DROP" in err and "not found" in err:
                    return task
                # good response from the server but query error
                raise NonRetriableError(err)

        # response data
        fields = []
        data = {}

        for field in resp.schema['fields']:
            fields.append(field['name'])
            data[field['name']] = []

        for tuple in resp.data:
            for i, value in enumerate(tuple):
                data[fields[i]].append(value)
        
        _keys = template.get('output_fields')
        if _keys:
            keys = [n['name'] for n in _keys]
            task.document.update(transform_data(keys, data))
        else:
            task.document.update(data)

        return task

# alias old name
read_fb = read_store

from SlothAI.lib.schemar import Schemar

@processor
def write_store(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    user = User.get_by_uid(task.user_id)
    
    # create template service
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))

    if task.document.get('model') == "weaviate":
        weaviate_url = task.document.get('weaviate_url')
        weaviate_token = task.document.get('weaviate_token')

        if not weaviate_url or not weaviate_token:
            return NonRetriableError("The 'weaviate' storage model needs a 'weaviate_url' and 'weaviate_token'.")
        else:
            auth = {"weaviate_url": weaviate_url, "weaviate_token": weaviate_token}

        weaviate_collection = task.document.get('table')
        if not weaviate_collection:
            weaviate_collection = task.document.get('collection')
            if not weaviate_collection:
                raise NonRetriableError("The `weaviate` storage model needs a 'table' or 'collection' name.")

        # insert defined input fields
        _keys = template.get('input_fields')
        keys = [n['name'] for n in _keys]

        data = {}
        for key in keys:
            if key in task.document:
                data[key] = task.document[key]
            else:
                raise NonRetriableError(f"Key '{key}' not in document. Check outputs and inputs.")

        # Check if all keys have values of equal length lists
        list_lengths = {key: len(value) for key, value in data.items() if isinstance(value, list)}
        if len(set(list_lengths.values())) != 1:
            raise NonRetriableError("All input fields must have lists of equal size.")

        # update into weaviate
        weaviate_response = weaviate_batch(weaviate_collection, data, auth)
        if weaviate_response.get('status') == "error":
            raise NonRetriableError(f"Weaviate insert failed: {weaviate_response.get('message')}")

        task.document['weaviate_uuids'] = weaviate_response.get('uuids')
        return task

    else: # Featurebase
        # if the user has a dbid, then use their database
        if user.get('dbid'):    
            # auth = {"dbid": task.document['DATABASE_ID'], "db_token": task.document['X-API-KEY']}
            auth = {
                "dbid": user.get('dbid'),
                "db_token": user.get('db_token')
            }
            table = task.document['table']
        else:
            # use a shared database
            if task.document.get('table'):
                auth = {
                    "dbid": app.config['SHARED_FEATUREBASE_ID'],
                    "db_token": app.config['SHARED_FEATUREBASE_TOKEN']
                }
            else:
                raise NonRetriableError("Specify a 'table' key and value and template the table in your SQL.")
            table = f"{user.get('name')}_{task.document.get('table')}"

        # check for auto detect
        if task.document.get('auto_fields'):
            data = auto_field_data(task.document)
        else:
            _keys = template.get('input_fields') # must be input fields but not enforced
            keys = [n['name'] for n in _keys]
            data = get_values_by_json_paths(keys, task.document)

        # check table
        tbl_exists, err = table_exists(table, auth)
        if err:
            raise NonRetriableError("Can't connect to database. Check your FeatureBase connection.")
        
        # if it doesn't exists, create it
        if not tbl_exists:
            create_schema = Schemar(data=data).infer_create_table_schema() # check data.. must be lists
            err = create_table(table, create_schema, auth)
            if err:
                if "already exists" in err:
                    # between checking if the table existed and trying to create the
                    # table, the table was created.
                    pass
                elif "exception" in err:
                    # issue connecting to FeatureBase cloud
                    raise RetriableError(err)
                else:
                    # good response from the server but there was a query error.
                    raise NonRetriableError(f"FeatureBase returned: {err}. Check your fields are valid with a callback.")
                
        # get columns from the table
        column_type_map, task.document['error'] = get_columns(table, auth)
        if task.document.get("error", None):
            raise Exception("unable to get columns from table in FeatureBase cloud")

        columns = [k for k in column_type_map.keys()]

        # add columns if data key cannot be found as an existing column
        for key in data.keys():
            if key not in columns:
                if not task.document.get("schema", None):
                    task.document['schema'] = Schemar(data=data).infer_schema()

                err = add_column(table, {'name': key, 'type': task.document["schema"][key]}, auth)
                if err:
                    if "exception" in err:
                        raise RetriableError(err)
                    else:
                        # good response from the server but query error
                        raise NonRetriableError(err)

                column_type_map[key] = task.document["schema"][key]

        columns, records = process_data_dict_for_insert(data, column_type_map, table)

        sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES {','.join(records)};"

        _, err = featurebase_query({"sql": sql, "dbid": auth.get('dbid'), "db_token": auth.get('db_token')})
        if err:
            if "exception" in err:
                raise RetriableError(err)
            else:
                # good response from the server but query error
                raise NonRetriableError(err)
        
        return task

# alias old name
write_fb = write_store


# helper functions
# ================
def process_input_fields(task_document, input_fields):
    updated_document = task_document
    
    for field in input_fields:
        field_name = field['name']
        if field_name in updated_document:
            # Check if the field is present in the document
            value = updated_document[field_name]
            if not isinstance(value, list):
                # If it's not already a list, replace it with a list containing the value
                updated_document[field_name] = [value]
    
    return updated_document


# Function to encode the image
def encode_image(image_file):
    return base64.b64encode(image_file.read()).decode('utf-8')


def validate_document(node, task: Task, validate: DocumentValidator):
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=node.get('template_id'))
    fields = template.get(validate)
    if fields:
        missing_key = validate_dict_structure(template.get('input_fields'), task.document)
        if missing_key:
            return missing_key
    
    return None


def evaluate_extras(node, task) -> Dict[str, any]:
    # get the node's current extras, which may be templated
    extras = node.get('extras', {})

    # combine with document (extras in node will overwrite entries in document)
    combined_dict = task.document.copy()
    combined_dict.update(extras)

    # we used to do it the other way around
    # combined_dict = extras.copy()
    # combined_dict.update(task.document)

    user = User.get_by_uid(task.user_id)
    combined_dict['username'] = user.get('name')

    # eval the extras from inputs_fields first
    extras_template = env.from_string(str(combined_dict))
    extras_from_template = extras_template.render(combined_dict)
    extras_eval = ast.literal_eval(extras_from_template)

    # remove the keys that were in the document
    # extras_eval = {key: value for key, value in extras_eval.items() if key not in task.document}
    # instead, leave the keys

    return extras_eval


def add_index_to_filename(filename, index):
    name, ext = filename.rsplit('.', 1)
    return f"{name}_{index}.{ext}"


def clean_extras(extras: Dict[str, any], task: Task):
    if extras:
        for k in extras.keys():
            if k in task.document.keys():
                for item in ['secret', 'token', 'password']:
                    if item in k:
                        del task.document[k]
    return task


def all_equal(iterable):
    g = groupby(iterable)
    return next(g, True) and not next(g, False)