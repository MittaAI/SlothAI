import re
import random
import json
import requests
import string
import secrets
import socket
import ast
import copy
import io
import zlib
import base64

import slack

import openai

from coolname import generate_slug

from flask import current_app as app
from flask import request
from flask_login import current_user

from google.cloud import storage

# don't call yer methods Client, dorks
from twilio.rest import Client as Twilio

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# random crap
def random_number(size=6, chars=string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def random_string(size=6, chars=string.ascii_letters + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def random_name(size=3):
    return generate_slug(size)


def generate_token(size=30):
    # generate a secrets token, less the dashes for better copy pasta
    return secrets.token_urlsafe(size).replace('-','')


# sms user
def sms_user(phone_e164, message="Just saying Hi!"):
    if app.config['DEV'] == "True":
        print(phone_e164)
        print(message)
        response = {'status': "success", 'message': "sending code via dev console"}
    else:
        response = {'status': "success", 'message': "sending code via twilio"}
        try:
            client = Twilio(app.config['TWILIO_ACCOUNT_SID'], app.config['TWILIO_AUTH_TOKEN'])
            message = client.messages.create(
                body = message,
                from_ = app.config['TWILIO_NUMBER'],
                to = phone_e164
            )
            return True
        except Exception as ex:
            if app.config['DEV'] == "True":
                print(ex)
            else:
                response = {'status': "failed", 'message': "sending code via twilio"}

    return response


# email user
def email_user(email, subject="subject", html_content="content"):
    if app.config['DEV'] == "True":
        response = {'status': "success", 'message': "sending code via dev console"}
        print(f"would email {email}")
    else:
        response = {'status': "success", 'message': "sending code via sendmail"}
        message = Mail(
            from_email='noreply@%s' % app.config['APP_DOMAIN'],
            to_emails=email,
            subject='%s' % subject,
            html_content=html_content
        )
        try:
            sg = SendGridAPIClient(app.config['SENDGRID_API_KEY'])
            response = sg.send(message)

        except Exception as ex:
            if app.config['DEV'] == "True":
                print(ex)
            
            response = {'status': "fail", 'message': "exception was %s" % ex}

    return response


# slack connection (for Mitta's slack, not the bot)
def slacker(channel="growth", text="text"):
    try:
        client = slack.WebClient(token=app.config['SLACK_TOKEN'])
        text = f"Incoming message from MittaAI: {text} \n"
        client.chat_postMessage(channel="growth", text=text)
    except Exception as ex:
        print(ex)
        pass


def handle_quotes(object):
    if isinstance(object, str):
        pattern = r"(?<!')'(?!')"
        object = re.sub(pattern, "''", object)
        object = object.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
    if isinstance(object, list):
        for i, _ in enumerate(object):
            object[i] = handle_quotes(object[i])
    return object


def check_webserver_connection(host, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((host, port))
        s.close()
        return True
    except Exception as e:
        return False


def upload_to_storage(uid, filename, uploaded_file):
    # set up bucket on google cloud
    gcs = storage.Client()
    bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
    blob = bucket.blob("%s/%s" % (uid, filename))

    # load content type
    content_type = uploaded_file.content_type

    # upload file to storage
    uploaded_file.stream.seek(0)
    blob.upload_from_file(uploaded_file.stream, content_type=content_type)

    # Construct and return the full bucket URI
    bucket_uri = f"gs://{app.config['CLOUD_STORAGE_BUCKET']}/{uid}/{filename}"
    return bucket_uri
    

def upload_to_storage_requests(uid, filename, data, content_type):
    # Set up bucket on Google Cloud
    gcs = storage.Client()
    bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
    blob = bucket.blob("%s/%s" % (uid, filename))

    # Upload the bytes data to storage
    blob.upload_from_string(data, content_type=content_type)

    # Construct and return the full bucket URI
    bucket_uri = f"gs://{app.config['CLOUD_STORAGE_BUCKET']}/{uid}/{filename}"
    return bucket_uri


def storage_pickle(uid, task_document, task_id, node_id):
    """
    Serializes a task document and uploads it to cloud storage.

    Parameters:
    - uid (str): The user ID associated with the task.
    - task_document (dict): The document/data associated with the task.
    - task_id (str): The unique identifier of the task.

    Returns:
    - str: The URI of the uploaded document in the storage bucket.
    """
    # Add the node_id to the document's task_node_id'
    task_document['task_node_id'] = node_id
    
    # Serialize task_document to JSON
    json_storage_dict = json.dumps(task_document)

    # Create a filename for the JSON storage document
    json_filename = f'json_data_{task_id}.json'

    # Convert the JSON string to bytes
    data_bytes = json_storage_dict.encode('utf-8')

    # Set content type to JSON
    content_type = 'application/json'

    # Call upload_to_storage_requests to save the document
    bucket_uri = upload_to_storage_requests(uid, json_filename, data_bytes, content_type)

    return bucket_uri


def load_from_storage(uid, filename):
    # set up bucket on google cloud
    gcs = storage.Client()
    bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
    blob = bucket.blob("%s/%s" % (uid, filename))
    
    buffer = io.BytesIO()
    blob.download_to_file(buffer)
    buffer.seek(0)

    return buffer

def download_as_bytes(uid, filename):
    gcs = storage.Client()
    bucket = gcs.bucket(app.config['CLOUD_STORAGE_BUCKET'])
    blob = bucket.get_blob(f"{uid}/{filename}")
    
    # Download the file contents as bytes
    content = blob.download_as_bytes()
    return content


def split_image_by_height(image_bytesio, output_format='PNG', segment_height=4096, overlap_ratio=0.02):
    from PIL import Image
    from io import BytesIO

    """
    Splits an image stored in a BytesIO object by height into segments with slight overlap.

    Args:
        image_bytesio (BytesIO): BytesIO object containing the image.
        output_format (str): Output format for segmented images (e.g., 'PNG', 'JPEG').
        segment_height (int): Desired height of each segment.
        overlap_ratio (float): Ratio of overlap between segments (default: 0.02).

    Returns:
        List of BytesIO objects containing segmented images.
    """
    # Open the image from BytesIO
    image = Image.open(image_bytesio)

    # Get the image dimensions
    width, total_height = image.size

    # Calculate the overlap in pixels based on the overlap ratio
    overlap_pixels = int(segment_height * overlap_ratio)

    # Calculate the number of segments
    num_segments = (total_height + segment_height - overlap_pixels - 1) // (segment_height - overlap_pixels)

    # Initialize a list to store segmented images
    segmented_images = []

    for segment_index in range(num_segments):
        # Calculate the cropping box for the current segment with overlap
        top = max(segment_index * (segment_height - overlap_pixels), 0)
        bottom = min((segment_index + 1) * segment_height - segment_index * overlap_pixels, total_height)

        # Crop the segment
        segment = image.crop((0, top, width, bottom))

        # Create a BytesIO object to store the segmented image
        output_bytesio = BytesIO()
        segment.save(output_bytesio, format=output_format)
        output_bytesio.seek(0)

        # Append the segmented image to the list
        segmented_images.append(output_bytesio)

    return segmented_images


# load template
def load_template(name="default"):
    from string import Template

    # file path
    file_path = "./SlothAI/templates/prompts/%s.txt" % (name)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            template = Template(f.read())
    except Exception as ex:
        template = None
    return template


from requests.exceptions import RequestException

def cast_iching(model="gpt-3.5-turbo"):
    url = "https://www.random.org/integers/?num=6&min=0&max=15&col=1&base=10&format=plain&rnd=new"
    try:
        response = requests.get(url)
        response.raise_for_status()  # This will raise an HTTPError if the HTTP request returned an unsuccessful status code.
        data = response.text.strip().split("\n")
        throws = [int(i) for i in data]
    except RequestException as e:
        # Fallback to local randomness if there's any issue with the request
        import secrets
        throws = [secrets.randbelow(16) for _ in range(6)]

    # Convert throws to their corresponding I Ching values
    prob = [6, 7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8, 9, 9, 9]
    hexagram = [prob[i] for i in throws]

    # Convert hexagram to binary representation
    binary_hexagram = ''.join(['1' if x in (7, 9) else '0' for x in hexagram])

    # Construct the GPT-3 prompt
    prompt = f"I Ching casting resulted in: {binary_hexagram}. What does it mean?"

    # call gpt-3.5-turbo
    openai.api_key = app.config['OPENAI_TOKEN']

    completion = openai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You produce a detailed I Ching reading."},
            {"role": "user", "content": prompt}
        ]
    )

    answer = f"{prompt}\n{completion.choices[0].message.content}"

    return answer


def gpt_completion(document=None, template="just_a_dict", model="gpt-3.5-turbo"):
    # Load OpenAI key
    try:
        openai.api_key = app.config['OPENAI_TOKEN']
    except:
        openai.api_key = alt_token

    try:
        template = load_template(template)
        prompt = template.substitute(document)
    except Exception as ex:
        print(ex)
        return None

    completion = openai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You do what you are told, step by step."},
            {"role": "user", "content": prompt}
        ]
    )

    answer = completion.choices[0].message.content
    return answer


# called only by our stuff
def gpt_dict_completion(document=None, template="just_a_dict", model="gpt-3.5-turbo-1106", alt_token=""):
    
    # load openai key then drop it from the document
    try:
        openai.api_key = app.config['OPENAI_TOKEN']
    except:
        openai.api_key = alt_token

    # substitute things
    try:
        template = load_template(template)
        prompt = template.substitute(document)
    except Exception as ex:
        return {}

    if model == "gpt-3.5-turbo-1106" and "JSON" in prompt:
        system_content = "You write JSON for the user. Watch your quoting."
        response_format = {'type': "json_object"}
    else:
        system_content = "You write python dictionaries for the user. You don't write code, use preambles, text markup, or any text other than the output requested, which is a python dictionary."
        response_format = None

    try:
        completion = openai.chat.completions.create(
            model = model,
            response_format = response_format,
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt}
            ]
        )

        answer = completion.choices[0].message.content

        ai_dict_str = answer.replace("\n", "").replace("\t", "")
        ai_dict_str = re.sub(r'\s+', ' ', ai_dict_str).strip()
        ai_dict_str = ai_dict_str.strip('ai_dict = ')
    
    except Exception as ex:
        print(ex)
        ai_dict_str = "{}"

    try:
        ai_dict = eval(ai_dict_str)
        if ai_dict.get('ai_dict'):
            ai_dict = ai_dict.get('ai_dict')

    except (ValueError, SyntaxError):
        print("Error: Invalid format in ai_dict_str for internal completion use (util.py).")
        ai_dict = {}

    return ai_dict


def strip_secure_fields(document):
    document_copy = copy.deepcopy(document)  # Make a deep copy of the dictionary
    keys_to_remove = []

    for key in document_copy.keys():
        if "token" in key.lower() or "password" in key.lower() or "X-API-KEY" in key or "DATABASE_ID" in key:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        document_copy.pop(key)

    return document_copy


def filter_document(document, keys_to_keep):
    return {key: value for key, value in document.items() if key in keys_to_keep}


# scrub the data for tokens, passwords, secrets
def deep_scrub(data):
    if isinstance(data, dict):
        for key in list(data.keys()):
            if any(word in key.lower() for word in ['secret', 'password', 'token']):
                # redact things that are secrets
                data[key] = f"[{key}]"
            else:
                deep_scrub(data[key])
    elif isinstance(data, list):
        for item in data:
            deep_scrub(item)


def should_be_service_token(name):
    token_strings = ["password", "secret", "token"]
    for token_string in token_strings:
        if token_string in name:
            return True
    else:
        return False

def local_callback_url(username, api_token):
    # hostname and protocol
    if app.config['DEV'] == "True":
        protocol = "http"
        hostname = request.host
    else:
        protocol = "https"
        hostname = app.config['APP_DOMAIN']

    callback_uri =  f"{protocol}://{hostname}/{username}/callback?token={api_token}"
    return callback_uri


def callback_extras(extras):
    # hostname and protocol
    hostname = request.host
    if "localhost" in hostname:
        protocol = "http"
    else:
        protocol = "https"

    localCallback = False
    update = False

    # Check for callback_uri and ensure it's not None or empty
    callback_uri = extras.get('callback_uri')
    if callback_uri:
        # Now check if the placeholder is in the value
        if "[callback_uri]" in callback_uri:
            localCallback = True
            extras['callback_uri'] = protocol + "://" + request.host + "/{{username}}/callback?token={{callback_token}}"
    
    # Check for callback_token and ensure localCallback is true before proceeding
    if localCallback:
        callback_token = extras.get('callback_token')
        if callback_token:
            # Now check if the placeholder is in the value
            if "[callback_token]" in callback_token:
                update = True
                # Assuming current_user.api_token is always available; otherwise, add a check
                extras['callback_token'] = current_user.api_token

    return extras, update
    

# handles merging the extras in from template, user and system definitions
def merge_extras(template_extras, node_extras):
    # Make a copy of template_extras to avoid modifying it directly
    merged_extras = template_extras.copy()

    if node_extras:
        for key, value in node_extras.items():
            if key in merged_extras:
                merged_extras[key] = node_extras[key]
            else:
                merged_extras[key] = value

    return merged_extras


def transform_single_items_to_lists(input_dict):
    for key, value in input_dict.items():
        # Check if the value is neither a list nor a dictionary
        if not isinstance(value, (list, dict)):
            # If it's not already a list or a dictionary, replace it with a list containing the value
            input_dict[key] = [value]
    return input_dict


import mimetypes

def get_file_extension(content_type):
    # Create a mapping of content types to file extensions
    content_type_to_extension = {
        'application/json': 'json',
        'application/pdf': 'pdf',
        'text/plain': 'txt',
        'text/html': 'html',
        'text/css': 'css',
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'audio/mpeg': 'mp3',
        'audio/mp4': 'mp4',
        'audio/mpeg': 'mpeg',
        'audio/mpeg': 'mpga',
        'audio/wav': 'wav',
        'audio/ogg': 'ogg',
        'audio/webm': 'webm',
        'text/markdown': 'md',
        'text/csv': 'csv',
    }

    # Use the provided content_type to determine the file extension
    file_extension = content_type_to_extension.get(content_type.split(';')[0])

    return file_extension


# maybe not used due to remove_fields_and_extras
def jinja_from_template(template):
    if not isinstance(template, str):
        return ""

    jinja = template[:]
    
    input_content, output_content = fields_text_from_template(template)
    extras_content = extras_from_template(template)

    # remove jinja comments
    jinja = re.sub(r'{#.*?#}', '', jinja)
    jinja = re.sub(r'{#.*?#}', '', jinja)
    jinja = re.sub(r'{#.*?#}', '', jinja)
    inp = re.compile(r'\s*input_fields\s*=\s*')
    out = re.compile(r'\s*output_fields\s*=\s*')
    jin = re.compile(r'\s*extras\s*=\s*')
    jinja = re.sub(inp, '', jinja)
    jinja = re.sub(out, '', jinja)
    jinja = re.sub(jin, '', jinja)
    if input_content:
        jinja = jinja.replace(input_content, '')
    if output_content:
        jinja = jinja.replace(output_content, '')
    if extras_content:
        jinja = jinja.replace(extras_content, '')

    return jinja


def compress_text(text):
    compressed_bytes = zlib.compress(text.encode('utf-8'))
    return base64.b64encode(compressed_bytes).decode('utf-8')


def decompress_text(compressed_text):
    compressed_bytes = base64.b64decode(compressed_text.encode('utf-8'))
    decompressed_bytes = zlib.decompress(compressed_bytes)
    return decompressed_bytes.decode('utf-8')


def get_raw_content_from_github(url):
    raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/tree/", "/")

    response = requests.get(raw_url)
    if response.status_code == 200:
        return response.text
    else:
        return None


def github_cookbooks(repo, path):
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    response = requests.get(api_url)

    cookbooks = []
    if response.status_code == 200:
        contents = response.json()
        for content in contents:
            try:
                url = f"{content.get('html_url')}/mitta_config.json"
                json_content = json.loads(get_raw_content_from_github(url))
                if json_content:
                    cookbooks.append(json_content)
            except Exception as ex:
                pass

    return cookbooks