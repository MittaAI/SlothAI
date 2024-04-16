from flask import Blueprint, render_template
from flask import current_app as app
from faker import Faker
from SlothAI.lib.util import random_string

import random
import nltk

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

def create_chunks(tokenized_text, length):
    chunks = []
    current_chunk = []

    for token in tokenized_text:
        if token.strip():
            if len(' '.join(current_chunk)) + len(token) > length:
                chunks.append(current_chunk)
                current_chunk = []
            current_chunk.append(token)

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

def stitch_chunks(chunks, min_chunk_length, max_chunk_length):
    stitched_chunks = []
    current_chunk = []
    original_chunk_numbers = []

    for i, chunk in enumerate(chunks, start=1):
        if len(current_chunk) + len(chunk) <= max_chunk_length:
            current_chunk.extend(chunk)
            original_chunk_numbers.append(i)
        else:
            if len(current_chunk) >= min_chunk_length:
                stitched_chunks.append({"text": current_chunk, "original_chunks": original_chunk_numbers})
            current_chunk = chunk
            original_chunk_numbers = [i]

    if len(current_chunk) >= min_chunk_length:
        stitched_chunks.append({"text": current_chunk, "original_chunks": original_chunk_numbers})

    return stitched_chunks

def chunk_with_page_filename(texts, filenames, length=512, start_page=1, overlap=0, min_chunk_length=100, max_chunk_length=512, tokenizer_path='./SlothAI/static/english.pickle'):
    if not isinstance(texts, list) or not isinstance(filenames, list):
        raise TypeError("The values for 'texts' and 'filenames' need to be lists.")
    if not all(isinstance(item, str) or isinstance(item, list) for item in texts):
        raise TypeError("The elements in 'texts' should be either strings or lists of strings.")
    if isinstance(texts[0], str) and len(filenames) != 1:
        raise ValueError("When 'texts' is a list of strings, 'filenames' should contain only one filename.")
    if isinstance(texts[0], list) and len(texts) != len(filenames):
        raise ValueError("When 'texts' is a list of lists, the outer list length should match the length of 'filenames'.")

    tokenizer = load_tokenizer(tokenizer_path)

    all_texts_chunks = []
    if isinstance(texts[0], str):
        texts = [texts]  # Convert to a list of lists for consistency

    for text_list, filename in zip(texts, filenames):
        texts_chunks = []
        for text in text_list:
            preprocessed_text = preprocess_text(text)
            tokenized_text = tokenizer.tokenize(preprocessed_text)
            chunks = create_chunks(tokenized_text, length)
            if overlap:
                chunks = create_overlapping_chunks(chunks, overlap)
            stitched_chunks = stitch_chunks(chunks, min_chunk_length, max_chunk_length)
            texts_chunks.extend(stitched_chunks)
        all_texts_chunks.append(texts_chunks)

    segmented_texts = []
    page_numbers = []
    chunk_numbers = []
    filenames_out = []
    stitched_chunk_info = []

    current_page_number = start_page
    current_chunk_number = 1

    for texts_chunks, filename in zip(all_texts_chunks, filenames):
        for chunk in texts_chunks:
            segmented_texts.append(' '.join(chunk['text']))
            page_numbers.append(current_page_number)
            chunk_numbers.append(current_chunk_number)
            filenames_out.append(filename)
            stitched_chunk_info.append(chunk['original_chunks'])
            current_chunk_number += 1
        current_page_number += 1

    # Expand filenames_out, page_numbers, and chunk_numbers to match the structure of segmented_texts
    expanded_filenames = [[filename] * len(chunks) for filename, chunks in zip(filenames, all_texts_chunks)]
    expanded_page_numbers = [[page_num] * len(chunks) for page_num, chunks in zip(range(start_page, start_page + len(all_texts_chunks)), all_texts_chunks)]
    expanded_chunk_numbers = [list(range(1, len(chunks) + 1)) for chunks in all_texts_chunks]

    return {
        "chunks": segmented_texts,
        "page_nums": expanded_page_numbers,
        "chunk_nums": expanded_chunk_numbers,
        "filenames": expanded_filenames,
        "stitched_chunk_info": stitched_chunk_info
    }

def stitch_chunks(chunks, min_chunk_length, max_chunk_length):
    stitched_chunks = []
    current_chunk = []
    original_chunk_numbers = []

    for i, chunk in enumerate(chunks, start=1):
        if len(current_chunk) + len(chunk) <= max_chunk_length:
            current_chunk.extend(chunk)
            original_chunk_numbers.append(i)
        else:
            if len(current_chunk) >= min_chunk_length:
                stitched_chunks.append({"text": current_chunk, "original_chunks": original_chunk_numbers})
            current_chunk = chunk
            original_chunk_numbers = [i]

    if len(current_chunk) >= min_chunk_length:
        stitched_chunks.append({"text": current_chunk, "original_chunks": original_chunk_numbers})

    return stitched_chunks