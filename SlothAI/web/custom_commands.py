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


def chunk_with_page_filename(texts, filenames, length=512, min_length=100, start_page=1, overlap=0, tokenizer_path='./SlothAI/static/english.pickle', flatten_output=False):
    if not isinstance(texts, list) or not isinstance(filenames, list):
        raise TypeError("The values for 'texts' and 'filename' need to be lists.")

    if not all(isinstance(item, str) or isinstance(item, list) for item in texts):
        raise TypeError("The elements in 'texts' should be either strings or lists of strings.")

    if isinstance(texts[0], str) and len(filenames) != 1:
        raise ValueError("When 'texts' is a list of strings, 'filenames' should contain only one filename.")

    if isinstance(texts[0], list) and len(texts) != len(filenames):
        raise ValueError("When 'texts' is a list of lists, the outer list length should match the length of 'filenames'.")

    tokenizer = load_tokenizer(tokenizer_path)
    all_texts_chunks = []  # This will be a list of lists

    for text_list, filename in zip(texts, filenames):
        texts_chunks = []
        carry_forward_chunk = []

        for text in text_list:
            preprocessed_text = preprocess_text(text)
            tokenized_text = tokenizer.tokenize(preprocessed_text)
            chunks = create_chunks(tokenized_text, length, min_length)

            if carry_forward_chunk:
                chunks[0] = carry_forward_chunk + chunks[0]
                carry_forward_chunk = []

            for chunk in chunks:
                if len(' '.join(chunk)) < min_length:
                    carry_forward_chunk.extend(chunk)
                else:
                    texts_chunks.append(chunk)

        if carry_forward_chunk:
            texts_chunks.append(carry_forward_chunk)

        if overlap:
            texts_chunks = create_overlapping_chunks(texts_chunks, overlap)

        all_texts_chunks.append(texts_chunks)

    segmented_texts = []
    page_numbers = []
    chunk_numbers = []
    filenames_out = []

    current_page_number = start_page

    for texts_chunks, filename in zip(all_texts_chunks, filenames):
        page_chunks = []  # List to hold chunks for the current page
        current_chunk_number = 1

        for chunk in texts_chunks:
            page_chunks.append(' '.join(chunk))
            page_numbers.append(current_page_number)
            chunk_numbers.append(current_chunk_number)
            filenames_out.append(filename)
            current_chunk_number += 1

        segmented_texts.append(page_chunks)
        current_page_number += 1

    if flatten_output:
        segmented_texts = [chunk for page_chunks in segmented_texts for chunk in page_chunks]
        page_numbers = [page_num for page_nums in page_numbers for page_num in [page_nums]]
        chunk_numbers = [chunk_num for chunk_nums in chunk_numbers for chunk_num in [chunk_nums]]
        filenames_out = [filename for filenames in filenames_out for filename in [filenames]]
    else:
        # Adjust the output to match the new structure
        expanded_filenames = [[filename] * len(chunks) for filename, chunks in zip(filenames, all_texts_chunks)]
        expanded_page_numbers = [[page_num] * len(chunks) for page_num, chunks in zip(range(start_page, start_page + len(all_texts_chunks)), all_texts_chunks)]
        expanded_chunk_numbers = [list(range(1, len(chunks) + 1)) for chunks in all_texts_chunks]

        segmented_texts = expanded_filenames
        page_numbers = expanded_page_numbers
        chunk_numbers = expanded_chunk_numbers
        filenames_out = expanded_filenames

    return {
        "chunks": segmented_texts,
        "page_nums": page_numbers,
        "chunk_nums": chunk_numbers,
        "filenames": filenames_out
    }