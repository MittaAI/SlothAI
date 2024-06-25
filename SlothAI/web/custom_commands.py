from flask import Blueprint, render_template
from flask import current_app as app
from faker import Faker
from SlothAI.lib.util import random_string

import random
import requests

custom_commands = Blueprint('custom_commands', __name__)

@custom_commands.app_template_global()
def filter_shuffle(seq):
    try:
        result = list(seq)
        random.shuffle(result)
        return result
    except:
        return seq

@custom_commands.app_template_global()
def reverse_word(word):
    reversed_word = word[::-1]
    return reversed_word

@custom_commands.app_template_global()
def random_word():
    fake = Faker()
    return fake.word()

@custom_commands.app_template_global()
def random_chars(len=13):
    return random_string(len)

@custom_commands.app_template_global()
def random_entry(texts):
    if texts and isinstance(texts, list) and len(texts) > 0:
        return random.choice(texts)
    else:
        return texts

@custom_commands.app_template_global()
def random_sentence():
    fake = Faker()
    return fake.sentence()

def load_tokenizer(tokenizer_path):
    return nltk.data.load(tokenizer_path)

def preprocess_text(text):
    return text.replace("\n", " ").replace("\r", " ").replace("\t", " ") \
               .replace("\\", " ").strip()

def create_chunks(tokenized_text, length, min_length):
    chunks = []
    current_chunk = []

    for token in tokenized_text:
        if len(' '.join(current_chunk) + ' ' + token) <= length:
            current_chunk.append(token)
        else:
            chunks.append(current_chunk)
            current_chunk = [token]

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

def create_overlapping_chunks(chunks, overlap):
    overlapped_chunks = []

    for i in range(len(chunks)):
        if i == 0:
            overlapped_chunks.append(chunks[i])
        else:
            overlapped_chunk = chunks[i-1][-overlap:] + chunks[i]
            overlapped_chunks.append(overlapped_chunk)

    return overlapped_chunks


def chunk_with_page_filename(texts, filenames, length=512, min_length=100, start_page=1, overlap=0, flatten_output=False):
    if not isinstance(texts, list) or not isinstance(filenames, list):
        raise TypeError("The values for 'texts' and 'filename' need to be lists.")

    if not all(isinstance(item, str) or isinstance(item, list) for item in texts):
        raise TypeError("The elements in 'texts' should be either strings or lists of strings.")

    # If texts is a single list, convert it to a list of lists
    if isinstance(texts[0], str):
        texts = [texts]

    # If filenames is a single string, convert it to a list with one element
    if isinstance(filenames, str):
        filenames = [filenames]

    if len(filenames) != len(texts):
        raise ValueError("When 'texts' is a list of lists, the outer list length should match the length of 'filenames'.")

    chunker_url = app.config["CHUNKER_URL"]
    
    payload = {
        "texts": texts,
        "filenames": filenames,
        "length": length,
        "min_length": min_length,
        "start_page": start_page,
        "overlap": overlap,
        "flatten_output": flatten_output
    }

    try:
        response = requests.post(chunker_url, json=payload)
        response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
        result = response.json()
        
        return {
            "chunks": result["chunks"],
            "page_nums": result["page_nums"],
            "chunk_nums": result["chunk_nums"],
            "filenames": result["filenames"]
        }
    
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error occurred while making request to chunker service: {str(e)}")
        raise
    except ValueError as e:
        app.logger.error(f"Error occurred while parsing JSON response: {str(e)}")
        raise
    except KeyError as e:
        app.logger.error(f"Expected key not found in chunker service response: {str(e)}")
        raise