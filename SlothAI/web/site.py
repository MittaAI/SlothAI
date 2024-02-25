import json
import datetime
import io
import requests
import htmlmin

from google.cloud import ndb

from flask import Blueprint, render_template, jsonify, send_from_directory
from flask import redirect, url_for, abort, flash
from flask import request, send_file, Response
from flask import current_app as app

import flask_login
from flask_login import current_user

from google.cloud import storage

from SlothAI.lib.util import email_user, random_name, gpt_dict_completion, build_mermaid, github_cookbooks, load_template, load_from_storage, merge_extras, should_be_service_token, callback_extras
from SlothAI.web.models import Pipeline, Node, Log, User, Token

site = Blueprint('site', __name__, static_folder='static')

# client connection
client = ndb.Client()

# date for base pages cards
current_date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")

# hard coded, for now
processors = [
    {"value": "jinja2", "label": "Jinja2 Processor", "icon": "file"},
    {"value": "callback", "label": "Callback Processor", "icon": "ethernet"},
    {"value": "read_file", "label": "Read Processor (File)", "icon": "book-reader"},
    {"value": "read_uri", "label": "Read Processor (URI)", "icon": "globe"},
    {"value": "aigrub", "label": "Read Processor (URI)", "icon": "desktop"},
    {"value": "aiffmpeg", "label": "FFmpeg Processor", "icon": "photo-video"},
    {"value": "info_file", "label": "Info Processor (File)", "icon": "info"},
    {"value": "read_fb", "label": "Read Processor (FeatureBase)", "icon": "database"},
    {"value": "split_task", "label": "Split Task Processor", "icon": "columns"},
    {"value": "halt_task", "label": "Halt Task Processor", "icon": "stop-circle"},
    {"value": "jump_task", "label": "Jump Task Processor", "icon": "code-branch"},
    {"value": "write_fb", "label": "Write Processor (FeatureBase)", "icon": "database"},
    {"value": "aidict", "label": "Generative Completion Processor", "icon": "code"},
    {"value": "aistruct", "label": "Generative Structure Processor", "icon": "building"},
    {"value": "aichat", "label": "Generative Chat Processor", "icon": "comment-dots"},
    {"value": "aiimage", "label": "Generative Image Processor", "icon": "images"},
    {"value": "embedding", "label": "Embedding Vectors Processor", "icon": "table"},
    {"value": "aivision", "label": "Vision Processor", "icon": "glasses"},
    {"value": "aiaudio", "label": "Audio Processor", "icon": "headphones"},
    {"value": "aispeech", "label": "Speech Processor", "icon": "volume-down"}
]

# template examples
template_examples = [
    {"name": "Generate random words", "template_name": "get_started_random_word", "processor_type": "jinja2"},
    {"name": "Generate sentence from words (OpenAI)", "template_name": "words_to_sentence", "processor_type": "aichat"},
    {"name": "Return data with a callback", "template_name": "get_started_callback", "processor_type": "callback"},
    {"name": "Convert text to embedding", "template_name": "text_to_embedding", "processor_type": "embedding"},
    {"name": "Convert text to a Gemini embedding", "template_name": "text_to_gemini_embedding", "processor_type": "embedding"},
    {"name": "Convert text to a Mistral embedding", "template_name": "text_to_mistral_embedding", "processor_type": "embedding"},
    {"name": "Convert text to an OpenAI embedding", "template_name": "text_to_ada_embedding", "processor_type": "embedding"},
    {"name": "Write to table", "template_name": "write_table", "processor_type": "write_fb"},
    {"name": "Write file chunks to a table", "template_name": "chunks_embeddings_pages_to_table", "processor_type": "write_fb"},
    {"name": "Read from table", "template_name": "read_table", "processor_type": "read_fb"},
    {"name": "Read embedding distance from a table", "template_name": "read_embedding_from_table", "processor_type": "read_fb"},
    {"name": "Drop a table", "template_name": "drop_table", "processor_type": "read_fb"},
    {"name": "Read PDF or text file and convert to text", "template_name": "pdf_to_text", "processor_type": "read_file"},
    {"name": "Read a CSV and serialize to arrays", "template_name": "read_csv", "processor_type": "read_file"},
    {"name": "Serialize arrays from read file output", "template_name": "serialize_arrays", "processor_type": "jinja2"},
    {"name": "Read file content_type, size, num_pages, ttl", "template_name": "info_file", "processor_type": "info_file"},
    {"name": "Deserialize a PDF to pages and convert to text", "template_name": "deserialized_pdf_to_text", "processor_type": "read_file"},
    {"name": "Download file from URI with GET", "template_name": "uri_to_file", "processor_type": "read_uri"},
    {"name": "POST data to URI", "template_name": "json_to_uri", "processor_type": "read_uri"},
    {"name": "Screenshot a website", "template_name": "uri_to_image", "processor_type": "aigrub"},
    {"name": "Convert images, sounds, movies", "template_name": "file_to_file", "processor_type": "aiffmpeg"},
    {"name": "Split a document into page numbers for split tasks", "template_name": "filename_to_splits", "processor_type": "jinja2"},
    {"name": "Convert page text into chunks", "template_name": "text_filename_to_chunks", "processor_type": "jinja2"},
    {"name": "Convert page text into chunks w/loop", "template_name": "text_filename_to_chunks_loop", "processor_type": "jinja2"},
    {"name": "Split task", "template_name": "split_task", "processor_type": "split_task"},
    {"name": "Halt task", "template_name": "halt_task", "processor_type": "halt_task"},
    {"name": "Jump task", "template_name": "jump_task", "processor_type": "jump_task"},
    {"name": "Generate lists of keys from input", "template_name": "text_to_struct", "processor_type": "aistruct"},
    {"name": "Generate keyterms from text", "template_name": "text_to_keyterms", "processor_type": "aidict"},
    {"name": "Generate a question from text and keyterms", "template_name": "text_keyterms_to_question", "processor_type": "aidict"},
    {"name": "Generate a summary from text", "template_name": "text_to_summary", "processor_type": "aidict"},
    {"name": "Generate image prompt from words", "template_name": "words_to_prompt", "processor_type": "aidict"},
    {"name": "Generate text sentiment", "template_name": "text_to_sentiment", "processor_type": "aidict"},
    {"name": "Generate answers from chunks and a query", "template_name": "chunks_query_to_answer", "processor_type": "aidict"},
    {"name": "Generate a pirate chat from texts (OpenAI)", "template_name": "text_to_chat", "processor_type": "aichat"},
    {"name": "Generate a pirate thoughts from texts (OpenAI)", "template_name": "text_to_chat_plain", "processor_type": "aichat"},
    {"name": "Generate chat from texts (Gemini)", "template_name": "text_to_chat_gemini", "processor_type": "aichat"},
    {"name": "Generate chat from texts (Mistral)", "template_name": "text_to_mistral_chat", "processor_type": "aichat"},
    {"name": "Generate chat from texts (Together)", "template_name": "text_to_together_chat", "processor_type": "aichat"},
    {"name": "Generate chat from texts (Perplexity)", "template_name": "text_to_chat_perplexity", "processor_type": "aichat"},
    {"name": "Generate an image from text", "template_name": "text_to_image", "processor_type": "aiimage"},
    {"name": "Find objects in image (Google Vision)", "template_name": "image_to_objects", "processor_type": "aivision"},
    {"name": "Find text in image (Google Vision)", "template_name": "image_to_text", "processor_type": "aivision"},
    {"name": "Generate scene text from image (Gemini)", "template_name": "image_to_text_gemini", "processor_type": "aivision"},
    {"name": "Generate scene text from image (OpenAI GPT)", "template_name": "image_to_scene", "processor_type": "aivision"},
    {"name": "Transcribe audio to text pages", "template_name": "audio_to_text", "processor_type": "aiaudio"},
    {"name": "Convert text to speech (OpenAI)", "template_name": "text_to_speech", "processor_type": "aispeech"},
    {"name": "Convert text to speech (ElevenLabs)", "template_name": "text_to_speech_el", "processor_type": "aispeech"},
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
    brand['slack_url'] = app.config['BRAND_SLACK_URL']
    brand['youtube_url'] = app.config['BRAND_YOUTUBE_URL']
    return brand

@site.route("/_ah/warmup")
def warmup():
    return "", 200, {}

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


@site.route('/task_log/count')
@flask_login.login_required
def task_log_count():
    log_count = Log.count(user_id=current_user.uid)

    # doesn't work, so fix
    # tasks = app.config['task_service'].fetch_tasks(user_id=current_user.uid, state="running")
    tasks = app.config['task_service'].fetch_tasks(user_id=current_user.uid)

    running_task_count = 0
    failed_task_count = 0
    active_nodes = []
    for task in tasks:
        if task.get('state') == 'running':
            node_info = {
                'node_id': task.get('current_node_id'),
                'pipe_id': task.get('pipe_id')
            }
            active_nodes.append(node_info)

            running_task_count += 1
        if task.get('state') == 'failed':
            failed_task_count += 1

    # Format the numbers with commas
    formatted_log_count = "{:,}".format(log_count)
    formatted_running_task_count = "{:,}".format(running_task_count)
    formatted_failed_task_count = "{:,}".format(failed_task_count)

    # Create a dictionary with the formatted values
    response_data = {
        "log_count": formatted_log_count,
        "task_count": formatted_running_task_count,
        "failed_count": formatted_failed_task_count,
        "active_nodes": active_nodes
    }

    # Use json.dumps to format the dictionary with commas
    return jsonify(response_data)


# simple log api
@site.route('/logs/<log_id>', methods=['GET'])
@flask_login.login_required
def logs_api(log_id):
    if log_id == "all":
        # Fetch all logs for the current user
        raw_logs = Log.fetch(uid=current_user.uid)
        logs_json = [
            {
                "log_id": log["log_id"],
                "created": log["created"].strftime("%Y-%m-%d %H:%M:%S"),  # Format datetime as string
                "log_data": json.loads(log["line"])  # Assuming log data is stored as a JSON string in 'line'
            }
            for log in raw_logs
        ]
        return jsonify(logs_json)
    else:
        # Fetch log details for the specified log_id for the current user
        logs = Log.fetch(log_id=log_id, uid=current_user.uid)
        if logs:
            log_details = logs[0]
        else:
            log_details = None

        if log_details:
            log_line_dict = json.loads(log_details['line'])
            decoded_log_line = {key: value.encode('utf-8').decode('unicode-escape') if isinstance(value, str) else value for key, value in log_line_dict.items()}
            return jsonify(decoded_log_line)
        else:
            return jsonify({"error": "Log not found"}), 404


@site.route('/logs', methods=['GET'])
@flask_login.login_required
def logs():
    # Fetch logs for the current user
    raw_logs = Log.fetch(uid=current_user.uid)

    # Prepare logs metadata for the template
    prepared_logs = []
    for log in raw_logs:
        prepared_logs.append({
            "log_id": log["log_id"],
            "created": log["created"]
        })

    # Other user details
    username = current_user.name
    email = current_user.email
    hostname = request.host

    return render_template('pages/logs.html', brand=get_brand(app), username=username, email=email, hostname=hostname, logs=prepared_logs)


@site.route('/', methods=['GET'])
def home():
    try:
        username = current_user.name
        email = current_user.email
    except:
        username = "anonymous"
        email = "anonymous"

    rendered_html = render_template('pages/index.html', username=username, email=email, brand=get_brand(app), dev=app.config['DEV'], current_date=current_date)
    minified_html = htmlmin.minify(rendered_html, remove_empty_space=True)
    return Response(minified_html, mimetype='text/html')


@site.route('/pro', methods=['GET'])
def pro():
    try:
        username = current_user.name
        email = current_user.email
    except:
        username = "anonymous"
        email = "anonymous"
    return render_template('pages/pro.html', username=username, email=email, brand=get_brand(app), dev=app.config['DEV'])


@site.route('/pro', methods=['POST'])
def postpro():
    # get form fields, if any
    email = request.form.get('email')
    name = request.form.get('name')
    company = request.form.get('company')
    phone = request.form.get('phone')
    why = request.form.get('why')

    message = ""

    if email != "" and name != "" and company != "" and phone != "" and why != "":
        message = message + "<div>email: %s</div>" % email
        message = message + "<div>name: %s</div>" % name
        message = message + "<div>company: %s</div>" % company
        message = message + "<div>phone: %s</div>" % phone
        message = message + "<div>why: %s</div>" % why

        email_user("kord@mitta.ai", subject="pro request", html_content=message)
        return render_template(
            'pages/donepro.html',
            brand=get_brand(app),
            dev=app.config['DEV']
        )
    else:
        flash("We need all these fields filed out, please.")

    return render_template(
        'pages/pro.html',
        email=email,
        name=name,
        company=company,
        phone=phone,
        why=why,
        brand=get_brand(app), 
        dev=app.config['DEV'],
        current_date=current_date
    )


@site.route('/legal', methods=['GET'])
def legal():
    try:
        username = current_user.name
        email = current_user.email
    except:
        username = "anonymous"
        email = "anonymous"

    return render_template('pages/privacy.html', username=username, email=email, dev=app.config['DEV'], brand=get_brand(app), current_date=current_date)


@site.route('/about', methods=['GET'])
def about():
    try:
        username = current_user.name
        email = current_user.email
    except:
        username = "anonymous"
        email = "anonymous"

    return render_template('pages/about.html', username=username, email=email, dev=app.config['DEV'], brand=get_brand(app), current_date=current_date)


@site.route('/pricing', methods=['GET'])
def pricing():
    try:
        username = current_user.name
        email = current_user.email
    except:
        username = "anonymous"
        email = "anonymous"
    return render_template('pages/pricing.html', username=username, email=email, dev=app.config['DEV'], brand=get_brand(app), current_date=current_date)


@site.route('/cookbooks', methods=['GET'])
def cookbooks():
    cookbooks = github_cookbooks("MittaAI/mitta-community", "cookbooks")

    for cookbook in cookbooks:
        for card in cookbook['cookbook_cards']:
            # Update image src
            github_base_url = card['links']['github']['href'].replace('/tree/', '/')
            card['image']['src'] = github_base_url + '/' + card['image']['src']

            # Update install href
            card['links']['install']['href'] = github_base_url + '/' + card['links']['install']['href']

            # Transform URLs to raw content URLs
            card['image']['src'] = card['image']['src'].replace("github.com", "raw.githubusercontent.com").replace("/tree/", "/")
            card['links']['install']['href'] = card['links']['install']['href'].replace("github.com", "raw.githubusercontent.com").replace("/tree/", "/")

    try:
        username = current_user.name
        email = current_user.email
    except:
        username = "anonymous"
        email = "anonymous"

    return render_template('pages/cookbooks.html', username=username, email=email, dev=app.config['DEV'], brand=get_brand(app), cookbooks=cookbooks, current_date=current_date)


@site.route('/pipelines', methods=['GET'])
@flask_login.login_required
def pipelines():
    # get the user and their tables
    username = current_user.name
    email = current_user.email
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

    return render_template('pages/pipelines.html', brand=get_brand(app), username=username, email=email, hostname=hostname, pipelines=pipelines, nodes=_nodes_sorted_by_processor, processors=processors)


@site.route('/pipelines/<pipe_id>', methods=['GET'])
@flask_login.login_required
def pipeline_view(pipe_id):
    # get the user and their tables
    username = current_user.name
    email = current_user.email
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
    return render_template('pages/pipeline.html', brand=get_brand(app), username=username, email=email, pipeline=pipeline, nodes=_nodes, all_nodes=_nodes_sorted_by_processor,  curl_code=curl_code, python_code=python_code, mermaid_string=mermaid_string, processors=processors)


@site.route('/nodes', methods=['GET'])
@flask_login.login_required
def nodes():
    # get the user and their tables
    username = current_user.name
    email = current_user.email

    nodes = Node.fetch(uid=current_user.uid)
   
    template_service = app.config['template_service']
    templates = template_service.fetch_template(user_id=current_user.uid)

    name_random = random_name(2).split('-')[1]

    tokens = Token.get_all_by_uid(current_user.uid)

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
        'pages/nodes.html', username=username, email=email, brand=get_brand(app), dev=app.config['DEV'], nodes=_nodes, name_random=name_random, templates=templates, processors=processors
    )


@site.route('/nodes/new/<template_id>', methods=['GET'])
@site.route('/nodes/<node_id>', methods=['GET'])
@flask_login.login_required
def node_detail(node_id=None, template_id=None):
    # get the user
    username = current_user.name
    email = current_user.email

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
    add_pipelines = sorted(add_pipelines, key=lambda x: x.get('name', ''))

    # Filter out pipelines already in `pipelines`, unless it's a callback
    if "callback" in node.get('processor') or not pipelines:
        filtered_pipelines = add_pipelines
    else:
        filtered_pipelines = [pipeline for pipeline in add_pipelines if pipeline['pipe_id'] not in pipelines_ids]

    # we have a node, so get the template
    template = template_service.get_template(template_id=node.get('template_id'), user_id=current_user.uid)

    return render_template(
        'pages/node.html', username=username, email=email, brand=get_brand(app), dev=app.config['DEV'], node=node, template=template, processors=processors, pipelines=pipelines, filtered_pipelines=filtered_pipelines
    )

@site.route('/templates')
@flask_login.login_required
def templates():
    username = current_user.name
    email = current_user.email
    template_service = app.config['template_service']
    templates = template_service.fetch_template(user_id=current_user.uid)

    if not templates:
        return redirect(url_for('site.template_detail'))  # Adjust 'template_detail' to your route name

    rendered_html = render_template(
        'pages/templates.html', username=username, email=email, brand=get_brand(app), templates=templates, processors=processors
    )
    minified_html = htmlmin.minify(rendered_html, remove_empty_space=True)
    return Response(minified_html, mimetype='text/html')


@site.route('/templates/new')
@site.route('/templates/<template_id>', methods=['GET'])
@flask_login.login_required
def template_detail(template_id="new"):
    # get the user and their tables
    username = current_user.name
    email = current_user.email

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

    # get nodes, if any
    if template_id:
        nodes = Node.fetch(template_id=template_id)
    else:
        nodes = []

    # get short name
    while True:
        for x in range(20):
            name_random = random_name(2).split('-')[0]
            if len(name_random) < 9:
                break

        # check the template name doesn't exist (finally fixing this weird issue)
        if not template_service.get_template(user_id=current_user.uid, name=name_random):
            break

    empty_template = '{# This is a reference jinja2 processor template #}\n\n{# Input Fields #}\ninput_fields = [{"name": "input_key", "type": "strings"}]\n\n{# Output Fields #}\noutput_fields = [{"name": "output_key", "type": "strings"}]\n\n{# Extras are required. #}\nextras = {"processor": "jinja2", "static_value": "String for static value.", "dynamic_value": None, "referenced_value": "{{static_value}}"}\n\n{"dict_key": "{{dynamic_value}}"}'

    return render_template(
        'pages/template.html', username=username, email=email, brand=get_brand(app), dev=app.config['DEV'], api_token=api_token, dbid=dbid, template=template, has_templates=has_templates, name_random=name_random, template_examples=template_examples, empty_template=empty_template, nodes=nodes
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
    email = current_user.email

    return render_template(
        'pages/tasks.html', tasks=tasks, username=username, email=email, brand=get_brand(app)
    )


# main route
@site.route('/settings', methods=['GET'])
@flask_login.login_required
def settings():
    # get the user and their tables
    username = current_user.name
    email = current_user.email

    api_token = current_user.api_token
    dbid = current_user.dbid

    tokens = Token.get_all_by_uid(current_user.uid)

    return render_template(
        'pages/settings.html', username=username, email=email, brand=get_brand(app), api_token=api_token, dbid=dbid, tokens=tokens
    )


# image serving with token or non-decorator based flask_login
@site.route('/d/<name>/<filename>')
def serve(name, filename):
    token = request.args.get('token')
    user = None

    if token:
        # If a token is present, attempt to authenticate using the token
        user = User.get_by_token(token)
    else:
        # If no token is provided, use the current_user from flask_login
        if current_user.is_authenticated and current_user.name == name:
            user = User.get_by_uid(current_user.uid)
        else:
            # If the current_user is not authenticated or the name doesn't match, abort with 404
            abort(404)

    if not user or name != user.get('name'):
        # If no user is found with the token or the name doesn't match the user's name, abort with 404
        abort(404)

    # set up bucket on google cloud
    gcs = storage.Client()
    bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
    blob = bucket.blob("%s/%s" % (user.get('uid'), filename))
    
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