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

"""
@custom_commands.app_template_global()
def chunk_with_page_filename(texts, filename, length=512, start_page=1, overlap=0, tokenizer_path='./SlothAI/static/english.pickle'):
    if isinstance(texts, str):
        raise TypeError("The value for 'texts' needs to be an array of strings.")

    if isinstance(texts, list):
        if all(isinstance(item, str) for item in texts):
            pass
        elif len(texts) == 1 and isinstance(texts[0], list) and all(isinstance(item, str) for item in texts[0]):
            texts = texts[0]
        else:
            raise TypeError("The value for 'texts' should be a list of strings or a list containing a single list of strings.")

    if isinstance(filename, list):
        if len(filename) > 1:
            raise TypeError("The value for filename can be a string, or a list with a single string in it.")
        filename = filename[0]

    tokenizer = load_tokenizer(tokenizer_path)
    texts_chunks = []

    for text in texts:
        preprocessed_text = preprocess_text(text)
        tokenized_text = tokenizer.tokenize(preprocessed_text)
        chunks = create_chunks(tokenized_text, length)
        if overlap:
            chunks = create_overlapping_chunks(chunks, overlap)
        texts_chunks.append(chunks)

    segmented_texts = []
    page_numbers = []
    chunk_numbers = []
    filenames = []

    current_page_number = start_page
    current_chunk_number = 1

    for page_chunks in texts_chunks:
        for chunk in page_chunks:
            segmented_texts.append(' '.join(chunk))
            page_numbers.append(current_page_number)
            chunk_numbers.append(current_chunk_number)
            filenames.append(filename)
            current_chunk_number += 1
        current_page_number += 1

    return {
        "chunks": segmented_texts,
        "page_nums": page_numbers,
        "chunk_nums": chunk_numbers,
        "filenames": filenames
    }

# multi-chunker
@custom_commands.app_template_global()
def chunk_with_page_filename(texts, filenames, length=512, start_page=1, overlap=0, tokenizer_path='./SlothAI/static/english.pickle'):
    if not isinstance(texts, list) or not isinstance(filenames, list):
        raise TypeError("The values for 'texts' and 'filenames' need to be lists.")

    if len(texts) != len(filenames):
        raise ValueError("The lengths of 'texts' and 'filenames' should be the same.")

    tokenizer = load_tokenizer(tokenizer_path)
    all_texts_chunks = []

    for texts, filename in zip(texts, filenames):
        if isinstance(texts, str):
            raise TypeError("The elements in 'texts' need to be lists of strings.")

        if not isinstance(texts, list) or not all(isinstance(item, str) for item in texts):
            raise TypeError("The elements in 'texts' should be lists of strings.")

        texts_chunks = []

        for text in texts:
            preprocessed_text = preprocess_text(text)
            tokenized_text = tokenizer.tokenize(preprocessed_text)
            chunks = create_chunks(tokenized_text, length)
            if overlap:
                chunks = create_overlapping_chunks(chunks, overlap)
            texts_chunks.append(chunks)

        all_texts_chunks.append(texts_chunks)

    segmented_texts = []
    page_numbers = []
    chunk_numbers = []
    filenames_out = []

    current_page_number = start_page
    current_chunk_number = 1

    for texts_chunks, filename in zip(all_texts_chunks, filenames):
        for page_chunks in texts_chunks:
            for chunk in page_chunks:
                segmented_texts.append(' '.join(chunk))
                page_numbers.append(current_page_number)
                chunk_numbers.append(current_chunk_number)
                filenames_out.append(filename)
                current_chunk_number += 1
            current_page_number += 1

    return {
        "chunks": segmented_texts,
        "page_nums": page_numbers,
        "chunk_nums": chunk_numbers,
        "filenames": filenames_out
    }

"""

def chunk_with_page_filename(texts, filenames, length=512, start_page=1, overlap=0, tokenizer_path='./SlothAI/static/english.pickle'):
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
            texts_chunks.extend(chunks)

        all_texts_chunks.append(texts_chunks)

    segmented_texts = []
    page_numbers = []
    chunk_numbers = []
    filenames_out = []

    current_page_number = start_page
    current_chunk_number = 1

    for texts_chunks, filename in zip(all_texts_chunks, filenames):
        for chunk in texts_chunks:
            segmented_texts.append(' '.join(chunk))
            page_numbers.append(current_page_number)
            chunk_numbers.append(current_chunk_number)
            filenames_out.append(filename)
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
        "filenames": expanded_filenames
    }