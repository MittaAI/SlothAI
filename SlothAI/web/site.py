import json
import datetime
import io
import requests

from google.cloud import ndb

from flask import Blueprint, render_template, jsonify, send_from_directory
from flask import redirect, url_for, abort
from flask import request, send_file, Response
from flask import current_app as app

import flask_login
from flask_login import current_user

from google.cloud import storage

from SlothAI.lib.util import random_name, gpt_dict_completion, build_mermaid, load_template, load_from_storage, merge_extras, should_be_service_token, callback_extras
from SlothAI.web.models import Pipeline, Node, Log, User, Token

site = Blueprint('site', __name__, static_folder='static')

# client connection
client = ndb.Client()

# hard coded, for now
processors = [
    {"value": "jinja2", "label": "Jinja2 Processor", "icon": "file"},
    {"value": "callback", "label": "Callback Processor", "icon": "ethernet"},
    {"value": "read_file", "label": "Read Processor (File)", "icon": "book-reader"},
    {"value": "read_uri", "label": "Read Processor (URI)", "icon": "file-word"},
    {"value": "info_file", "label": "Info Processor (File)", "icon": "info"},
    {"value": "read_fb", "label": "Read Processor (FeatureBase)", "icon": "database"},
    {"value": "split_task", "label": "Split Task Processor", "icon": "columns"},
    {"value": "write_fb", "label": "Write Processor (FeatureBase)", "icon": "database"},
    {"value": "aidict", "label": "Generative Completion Processor", "icon": "code"},
    {"value": "aichat", "label": "Generative Chat Processor", "icon": "comment-dots"},
    {"value": "aiimage", "label": "Generative Image Processor", "icon": "images"},
    {"value": "embedding", "label": "Embedding Vectors Processor", "icon": "table"},
    {"value": "aivision", "label": "Vision Processor", "icon": "glasses"},
    {"value": "aiaudio", "label": "Audio Processor", "icon": "headphones"},
    {"value": "aispeech", "label": "Speech Processor", "icon": "volume-down"}
]

# template examples
template_examples = [
    {"name": "Start with a callback", "template_name": "get_started_callback", "processor_type": "callback"},
    {"name": "Generate random words", "template_name": "get_started_random_word", "processor_type": "jinja2"},
    {"name": "Convert text to embedding", "template_name": "text_to_embedding", "processor_type": "embedding"},
    {"name": "Convert text to an OpenAI embedding", "template_name": "text_to_ada_embedding", "processor_type": "embedding"},
    {"name": "Write to table", "template_name": "write_table", "processor_type": "write_fb"},
    {"name": "Write file chunks to a table", "template_name": "chunks_embeddings_pages_to_table", "processor_type": "write_fb"},
    {"name": "Read from table", "template_name": "read_table", "processor_type": "read_fb"},
    {"name": "Read embedding distance from a table", "template_name": "read_embedding_from_table", "processor_type": "read_fb"},
    {"name": "Drop a table", "template_name": "drop_table", "processor_type": "read_fb"},
    {"name": "Read PDF or text file and convert to text", "template_name": "pdf_to_text", "processor_type": "read_file"},
    {"name": "Serialize arrays from read file output", "template_name": "serialize_arrays", "processor_type": "jinja2"},
    {"name": "Read file content_type, size, num_pages, ttl", "template_name": "info_file", "processor_type": "info_file"},
    {"name": "Deserialize a PDF to pages and convert to text", "template_name": "deserialized_pdf_to_text", "processor_type": "read_file"},
    {"name": "Download file from URI with GET", "template_name": "uri_to_file", "processor_type": "read_uri"},
    {"name": "POST data to URI", "template_name": "json_to_uri", "processor_type": "read_uri"},
    {"name": "Split a document into page numbers for split tasks", "template_name": "filename_to_splits", "processor_type": "jinja2"},
    {"name": "Convert page text into chunks", "template_name": "text_filename_to_chunks", "processor_type": "jinja2"},
    {"name": "Convert page text into chunks w/loop", "template_name": "text_filename_to_chunks_loop", "processor_type": "jinja2"},
    {"name": "Split tasks", "template_name": "split_tasks", "processor_type": "split_task"},
    {"name": "Generate keyterms from text", "template_name": "text_to_keyterms", "processor_type": "aidict"},
    {"name": "Generate a question from text and keyterms", "template_name": "text_keyterms_to_question", "processor_type": "aidict"},
    {"name": "Generate a summary from text", "template_name": "text_to_summary", "processor_type": "aidict"},
    {"name": "Generate image prompt from words", "template_name": "words_to_prompt", "processor_type": "aidict"},
    {"name": "Generate text sentiment", "template_name": "text_to_sentiment", "processor_type": "aidict"},
    {"name": "Generate answers from chunks and a query", "template_name": "chunks_query_to_answer", "processor_type": "aidict"},
    {"name": "Generate chat from texts", "template_name": "text_to_chat", "processor_type": "aichat"},
    {"name": "Generate an image from text", "template_name": "text_to_image", "processor_type": "aiimage"},
    {"name": "Find objects in image (Google Vision)", "template_name": "image_to_objects", "processor_type": "aivision"},
    {"name": "Find text in image (Google Vision)", "template_name": "image_to_text", "processor_type": "aivision"},
    {"name": "Generate scene text from image (OpenAI GPT)", "template_name": "image_to_scene", "processor_type": "aivision"},
    {"name": "Transcribe audio to text pages", "template_name": "audio_to_text", "processor_type": "aiaudio"},
    {"name": "Convert text to speech audio", "template_name": "text_to_speech", "processor_type": "aispeech"},
]

def get_brand(app):
    # brand setup
    brand = {}
    brand['name'] = app.config['BRAND']
    brand['favicon'] = app.config['BRAND_FAVICON']
    brand['color'] = app.config['BRAND_COLOR']
    brand['service'] = app.config['BRAND_SERVICE']
    brand['service_url'] = app.config['BRAND_SERVICE_URL']
    brand['twitter_handle'] = app.config['BRAND_X_HANDLE']
    brand['github_url'] = app.config['BRAND_GITHUB_URL']
    brand['discord_url'] = app.config['BRAND_DISCORD_URL']
    brand['youtube_url'] = app.config['BRAND_YOUTUBE_URL']
    return brand


@site.route('/sitemap.txt')
def sitemap():
    brand = get_brand(app)
    return render_template('pages/sitemap.txt', brand=brand)

# static handling
cache_control_max_age = 3600
@site.route('/css/<path:filename>')
def serve_css(filename):
    response = send_from_directory(f"{app.static_folder}/css/", filename)
    response.headers['Cache-Control'] = f'public, max-age={cache_control_max_age}'
    return response

@site.route('/fonts/<path:filename>')
def serve_fonts(filename):
    response = send_from_directory(f"{app.static_folder}/fonts/", filename)
    response.headers['Cache-Control'] = f'public, max-age={cache_control_max_age}'
    return response

@site.route('/images/<path:filename>')
def serve_images(filename):
    response = send_from_directory(f"{app.static_folder}/images/", filename)
    response.headers['Cache-Control'] = f'public, max-age={cache_control_max_age}'
    return response

@site.route('/js/<path:filename>')
def serve_js(filename):
    response = send_from_directory(f"{app.static_folder}/js/", filename)
    response.headers['Cache-Control'] = f'public, max-age={cache_control_max_age}'
    return response

@site.route('/templates/<path:filename>')
def serve_templates(filename):
    response = send_from_directory(f"{app.static_folder}/templates/", filename)
    response.headers['Cache-Control'] = f'public, max-age={cache_control_max_age}'
    return response

@site.route('/webfonts/<path:filename>')
def serve_webfonts(filename):
    response = send_from_directory(f"{app.static_folder}/webfonts/", filename)
    response.headers['Cache-Control'] = f'public, max-age={cache_control_max_age}'
    return response


@site.route('/logs', methods=['GET'])
@flask_login.login_required
def logs():
    # get the user and their tables
    username = current_user.name
    hostname = request.host

    logs = Log.fetch(uid=current_user.uid)

    return render_template('pages/logs.html', brand=get_brand(app), username=username, hostname=hostname, logs=logs)


@site.route('/', methods=['GET'])
def home():
    try:
        username = current_user.name
    except:
        username = "anonymous"

    return render_template('pages/index.html', username=username, brand=get_brand(app))


@site.route('/legal', methods=['GET'])
def legal():
    try:
        username = current_user.name
    except:
        username = "anonymous"

    return render_template('pages/privacy.html', username=username, dev=app.config['DEV'], brand=get_brand(app))


@site.route('/about', methods=['GET'])
def about():
    try:
        username = current_user.name
    except:
        username = "anonymous"

    return render_template('pages/about.html', username=username, dev=app.config['DEV'], brand=get_brand(app))

@site.route('/cookbooks', methods=['GET'])
def cookbooks():
    try:
        username = current_user.name
    except:
        username = "anonymous"

    return render_template('pages/cookbooks.html', username=username, dev=app.config['DEV'], brand=get_brand(app))


@site.route('/pipelines', methods=['GET'])
@flask_login.login_required
def pipelines():
    # get the user and their tables
    username = current_user.name
    hostname = request.host
    pipelines = Pipeline.fetch(uid=current_user.uid)
    nodes = Node.fetch(uid=current_user.uid)
    template_service = app.config['template_service']
    templates = template_service.fetch_template(user_id=current_user.uid)

    # add input and output fields, plus templates
    _nodes = []
    for node in nodes:
        for template in templates:
            if template.get('template_id') == node.get('template_id'):
                node['template_name'] = template.get('name')
                node['input_fields'] = template.get('input_fields')
                node['output_fields'] = template.get('output_fields')
                break

        for key in node.get('extras').keys():
            if 'token' in key or 'password' in key:
                node['extras'][key] = '[secret]'

        _nodes.append(node)
    
    _nodes_sorted_by_processor = sorted(_nodes, key=lambda x: x.get('processor'))

    return render_template('pages/pipelines.html', brand=get_brand(app), username=username, hostname=hostname, pipelines=pipelines, nodes=_nodes_sorted_by_processor, processors=processors)


@site.route('/pipelines/<pipe_id>', methods=['GET'])
@flask_login.login_required
def pipeline_view(pipe_id):
    # get the user and their tables
    username = current_user.name
    token = current_user.api_token
    template_service = app.config['template_service']
    templates = template_service.fetch_template(user_id=current_user.uid)
    nodes = Node.fetch(uid=current_user.uid)

    pipeline = Pipeline.get(uid=current_user.uid, pipe_id=pipe_id)
    
    if not pipeline:
        return redirect(url_for('site.pipelines'))

    # add input and output fields, plus template name
    _nodes = []

    # build two lists, one of the ones in the pipeline, another of all nodes
    for node in nodes:
        for template in templates:
            if template.get('template_id') == node.get('template_id'):
                node['template_name'] = template.get('name')
                node['input_fields'] = template.get('input_fields')
                node['output_fields'] = template.get('output_fields')
                break

        for key in node.get('extras').keys():
            if 'token' in key or 'password' in key:
                node['extras'][key] = '[secret]'

        if node.get('node_id') in pipeline.get('node_ids'):
            _nodes.append(node)

    # sort the list based on the current order in the pipeline
    node_order_mapping = {node_id: index for index, node_id in enumerate(pipeline.get('node_ids'))}
    def custom_sort_key(item):
        return node_order_mapping.get(item['node_id'], len(pipeline.get('node_ids')))
    _nodes = sorted(_nodes, key=custom_sort_key)

    # build the graph for inspection
    mermaid_string = build_mermaid(pipeline, _nodes)

    # build an example POST usin generative AI
    head_input_fields = _nodes[0].get('input_fields', [])
    try:
        head_field_names = [f"{field.get('name')} of type {field.get('type')}" for field in head_input_fields]
    except:
        head_field_names = ["extra_field of type strings"]

    if not head_field_names:
        head_field_names = ["extra_field of type strings"]

    head_processor = _nodes[0].get('processor')

    # Create a dictionary to store the template substitution values
    substitution_values = {
        "pipe_id": pipe_id,
        "pipe_name": pipeline.get('name'),
        "hostname": request.host,
        "token": token,
        "head_processor": head_processor,
        "head_field_names": head_field_names
    }

    # set protocol
    if "localhost" in request.host:
        substitution_values['protocol'] = "http"
    else:
        substitution_values['protocol'] = "https"

    # Loop over the input fields and add them to the substitution dictionary
    ai_dict = gpt_dict_completion(substitution_values, template='form_example')

    if not ai_dict:
        ai_dict = {"texts": ["There was a knock at the door, then silence.","Bob was there, wanting to tell Alice about an organization."]}
        substitution_values['filename'] = "animate.pdf"
        substitution_values['content_type'] = "application/pdf"
    else:
        substitution_values.update(ai_dict)

    # failsafe for setting content type and filename for a few processor templates
    substitution_values.setdefault('content_type', "application/pdf")
    substitution_values.setdefault('filename', "animate.pdf")

    # load the json string
    json_string = json.dumps(ai_dict)
    json_string = json_string.replace("'", '"')
    substitution_values['json_string'] = json_string

    python_template = load_template(f'{head_processor}_python')
    curl_template = load_template(f'{head_processor}_curl')

    if not python_template or not curl_template:
        python_template = load_template('jinja2_python')
        curl_template = load_template('jinja2_curl')

    python_code = python_template.substitute(substitution_values)
    curl_code = curl_template.substitute(substitution_values)

    _nodes_sorted_by_processor = sorted(nodes, key=lambda x: x.get('processor'))

    # render the page
    return render_template('pages/pipeline.html', brand=get_brand(app), username=username, pipeline=pipeline, nodes=_nodes, all_nodes=_nodes_sorted_by_processor,  curl_code=curl_code, python_code=python_code, mermaid_string=mermaid_string, processors=processors)


@site.route('/nodes', methods=['GET'])
@flask_login.login_required
def nodes():
    # get the user and their tables
    username = current_user.name
    nodes = Node.fetch(uid=current_user.uid)

    template_service = app.config['template_service']
    templates = template_service.fetch_template(user_id=current_user.uid)

    template_lookup = {template['template_id']: template['name'] for template in templates}

    name_random = random_name(2).split('-')[1]

    tokens = Token.get_all_by_uid(current_user.uid)

    """
    # hide the tokens and passwords
    for node in nodes:
        extras = node.get('extras', None)  
        if extras:
            for key in extras.keys():
                if 'token' in key or 'password' in key or 'secret' in key:
                    extras[key] = f'[{key}]'
    """

    # update the template names
    _nodes = []
    for node in nodes:
        if node.get('template_id'):
            for template in templates:
                if template.get('template_id') == node.get('template_id'):
                    node['template'] = template
                    break

        _nodes.append(node)

    return render_template(
        'pages/nodes.html', username=username, brand=get_brand(app), dev=app.config['DEV'], nodes=_nodes, name_random=name_random, templates=templates, processors=processors
    )


@site.route('/nodes/new/<template_id>', methods=['GET'])
@site.route('/nodes/<node_id>', methods=['GET'])
@flask_login.login_required
def node_detail(node_id=None, template_id=None):
    # get the user
    username = current_user.name
    uid = current_user.uid

    # get the template service
    template_service = app.config['template_service']

    # get the tokens
    tokens = Token.get_all_by_uid(current_user.uid)

    # get the node, if any
    node = Node.get(node_id=node_id, uid=uid)

    # new node, if no node
    if not node:
        if not template_id:
            abort(404)

        # get the template
        template = template_service.get_template(template_id=template_id, user_id=current_user.uid)
        if not template:
            abort(404)

        # processor
        processor = template.get('extras').get('processor')
        if not processor:
            processor = template.get('processor')
            if not processor:
                processor = "jinja2"

        # merge extras
        merged_extras = merge_extras(template.get('extras', {}), {})

        # populate any local callback extras
        merged_extras, update = callback_extras(merged_extras)

        # deal with service tokens and locally populated callback info
        _extras = {}
        for key, value in merged_extras.items():
            if "callback_token" in key and update:
                Token.create(uid, key, value)
                value = f"[{key}]"
            elif should_be_service_token(key):
                token = Token.get_by_uid_name(uid, key)
                if token:
                    # set it so it can be used later
                    value = f"[{key}]"

            _extras[key] = value
            
        # create a new node
        node = Node.create(
            name=random_name(2).split('-')[1],
            uid=uid,
            extras=_extras,
            processor=processor,
            template_id=template.get('template_id')
        )

        # redirect to ourselves
        return redirect(url_for('site.node_detail', node_id=node.get('node_id')))


    pipelines = Pipeline.get_by_uid_node_id(uid, node.get('node_id'))
    if pipelines:
        pipelines_ids = [pipeline['pipe_id'] for pipeline in pipelines]
    else:
        pipeline_ids = []

    add_pipelines = Pipeline.fetch(uid=uid)

    # Filter out pipelines already in `pipelines`, unless it's a callback
    if "callback" in node.get('processor') or not pipelines:
        filtered_pipelines = add_pipelines
    else:
        filtered_pipelines = [pipeline for pipeline in add_pipelines if pipeline['pipe_id'] not in pipelines_ids]

    # we have a node, so get the template
    template = template_service.get_template(template_id=node.get('template_id'), user_id=current_user.uid)

    return render_template(
        'pages/node.html', username=username, brand=get_brand(app), dev=app.config['DEV'], node=node, template=template, processors=processors, pipelines=pipelines, filtered_pipelines=filtered_pipelines
    )


@site.route('/templates')
@flask_login.login_required
def templates():
    username = current_user.name
    template_service = app.config['template_service']
    templates = template_service.fetch_template(user_id=current_user.uid)

    if not templates:
        return redirect(url_for('site.template_detail'))  # Adjust 'template_detail' to your route name

    return render_template(
        'pages/templates.html', username=username, brand=get_brand(app), templates=templates, processors=processors
    )


@site.route('/templates/new')
@site.route('/templates/<template_id>', methods=['GET'])
@flask_login.login_required
def template_detail(template_id="new"):
    # get the user and their tables
    username = current_user.name
    api_token = current_user.api_token
    dbid = current_user.dbid
    template_service = app.config['template_service']
    template = template_service.get_template(template_id=template_id, user_id=current_user.uid)
        
    # test if there are more templates
    has_templates = False
    template_service = app.config['template_service']
    templates = template_service.fetch_template(user_id=current_user.uid)
    if templates:
        has_templates = True

    hostname = request.host

    # get short name
    for x in range(20):
        name_random = random_name(2).split('-')[0]
        if len(name_random) < 9:
            break

    empty_template = '{# This is a reference jinja2 processor template #}\n\n{# Input Fields #}\ninput_fields = [{"name": "input_key", "type": "strings"}]\n\n{# Output Fields #}\noutput_fields = [{"name": "output_key", "type": "strings"}]\n\n{# Extras are required. #}\nextras = {"processor": "jinja2", "static_value": "String for static value.", "dynamic_value": None, "referenced_value": "{{static_value}}"}\n\n{"dict_key": "{{dynamic_value}}"}'

    return render_template(
        'pages/template.html', username=username, brand=get_brand(app), dev=app.config['DEV'], api_token=api_token, dbid=dbid, template=template, has_templates=has_templates, hostname=hostname, name_random=name_random, template_examples=template_examples, empty_template=empty_template
    )


@site.route('/logs', methods=["DELETE"])
@flask_login.login_required
def delete_logs():
    Log.delete_all(current_user.uid)
    return jsonify({"result": "success"})


@site.route('/tasks')
@flask_login.login_required
def tasks():
    tasks = app.config['task_service'].fetch_tasks(user_id=current_user.uid)
    nodes = Node.fetch(uid=current_user.uid)
    pipelines = Pipeline.fetch(uid=current_user.uid)

    # add names
    for index, task in enumerate(tasks):
        for node in nodes:
            if node.get('node_id') == task.get('current_node_id'):
                tasks[index]['node_name'] = node.get('name')
                break
        for pipeline in pipelines:
            if pipeline.get('pipe_id') == task.get('pipe_id'):  
                tasks[index]['pipeline_name'] = pipeline.get('name')
                break

        # update timestamps
        created_at_str = task.get('created_at').strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        created_at = datetime.datetime.strptime(created_at_str, '%Y-%m-%dT%H:%M:%S.%fZ')
        timestring = "%Y-%m-%d %H:%M:%SGMT"
        timestamp = created_at.strftime(timestring)
        tasks[index]['created'] = timestamp

    username = current_user.name
    return render_template(
        'pages/tasks.html', tasks=tasks, username=username, brand=get_brand(app)
    )


# main route
@site.route('/settings', methods=['GET'])
@flask_login.login_required
def settings():
    # get the user and their tables
    username = current_user.name
    api_token = current_user.api_token
    dbid = current_user.dbid

    tokens = Token.get_all_by_uid(current_user.uid)

    return render_template(
        'pages/settings.html', username=username, brand=get_brand(app), api_token=api_token, dbid=dbid, tokens=tokens
    )

# image serving
@site.route('/d/<name>/<filename>')
@flask_login.login_required
def serve(name, filename):
    if name != current_user.name:
        abort(404) 

    user = User.get_by_uid(current_user.uid)
    if not user:
        abort(404)

    # set up bucket on google cloud
    gcs = storage.Client()
    bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
    blob = bucket.blob("%s/%s" % (current_user.uid, filename))
    
    buffer = io.BytesIO()
    blob.download_to_file(buffer)
    buffer.seek(0)

    return send_file(
        buffer, 
        download_name=filename,
        as_attachment=False,
        mimetype=blob.content_type # and there it is
    )

    return Response(blob)


# cookbooks
@site.route('/cookbooks/<cookbook_name>/<filename>', methods=['GET'])
def download_file(cookbook_name, filename):
    base_url = "https://raw.githubusercontent.com/MittaAI/mitta-community/main"
    file_url = f"{base_url}/cookbooks/{cookbook_name}/{filename}"

    response = requests.get(file_url)
    if response.status_code == 200:
        return Response(
            response.content,
            headers={"Content-Disposition": f"attachment;filename={filename}"},
            mimetype='application/octet-stream'
        )
    else:
        return "File not found", 404