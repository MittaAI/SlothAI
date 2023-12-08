from flask import Blueprint, render_template
from flask import current_app as app
from faker import Faker

import random

import nltk
tokenizer = nltk.data.load('./SlothAI/static/english.pickle')

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
def random_sentence():
    fake = Faker()
    return fake.sentence()


@custom_commands.app_template_global()
def chunk_with_page_filename(texts, filename, length=512, start_page=1, overlap=0):

    # Check if texts is a string
    if isinstance(texts, str):
        raise TypeError("The value for 'texts' needs to be an array of strings.")

    # Check if texts is a list
    if isinstance(texts, list):
        # Check if the list contains strings
        if all(isinstance(item, str) for item in texts):
            pass  # This is a valid case
        # Check if the list contains a single list of strings
        elif len(texts) == 1 and isinstance(texts[0], list) and all(isinstance(item, str) for item in texts[0]):
            texts = texts[0]
        else:
            raise TypeError("The value for 'texts' should be a list of strings or a list containing a single list of strings.")

    # main object
    texts_chunks = []
    
    if isinstance(filename, list):
        if len(filename) > 1:
            raise TypeError("The value for filename can be a string, or a list with a single string in it.")
        filename = filename[0]
    

    # main object
    texts_chunks = []

    # loop over page's texts

    for text in texts:
        # lists for page_chunks and sub_chunks
        page_chunks = []
        sub_chunks = []

        # Loop over the tokenized text for the page
        for i, entry in enumerate(tokenizer.tokenize(text)):
            if entry.strip():
                # Remove extra whitespace and newline characters
                entry = entry.replace("\n"," ").replace("\r"," ").replace("\t"," ").replace('"','``').replace("'","`").replace("\\"," ").strip()

                if not i and len(' '.join(sub_chunks)) + len(entry) > length:
                     sub_chunks.append(entry)
                     sub_chunks = []

                # if current chunks + new entry's length is > length, we append to the chunks
                elif len(' '.join(sub_chunks)) + len(entry) > length:
                    # Append the current segment to the list
                    page_chunks.append(sub_chunks)
                    sub_chunks = []

                # Add the entry to the current chunks
                sub_chunks.append(entry)

        # Append the last segment to the list if it's not empty
        if sub_chunks:
            page_chunks.append(sub_chunks)

        if page_chunks:
            texts_chunks.append(page_chunks)

    if overlap:
        texts_chunks_copy = []
        for texts_chunk in texts_chunks:
            for i in range(1, len(texts_chunk)):
                prev_last_strings = texts_chunk[i-1][-overlap:]
                current_first_strings = texts_chunk[i][:overlap]
     
                for string in current_first_strings:
                    texts_chunk[i-1].append(string)
     

                for string in prev_last_strings:
                    texts_chunk[i].insert(0, string)

            texts_chunks_copy.append(texts_chunk)

        texts_chunks = texts_chunks_copy

        # Loop over the pages, starting from the second page (index 1)
        for i in range(1, len(texts_chunks)):
            # Find the last `overlap` strings from the previous page
            prev_last_strings = find_last_strings(texts_chunks[i-1], num=overlap)
            
            # Find the first `overlap` strings from the current page
            current_first_strings = find_first_strings(texts_chunks[i], num=overlap)
            
            # Prepend the last strings of the previous page to the beginning of the current page
            texts_chunks[i][0] = prev_last_strings + texts_chunks[i][0]
            
            # Append the first strings of the current page to the end of the last chunk of the previous page
            texts_chunks[i-1][-1] = texts_chunks[i-1][-1] + current_first_strings

    segmented_texts = []
    page_numbers = []
    chunk_numbers = []
    filenames = []

    current_page_number = start_page
    current_chunk_number = 1

    for text in texts_chunks:
        for te in text:
            segmented_texts.append(' '.join(te))
            page_numbers.append(current_page_number)
            chunk_numbers.append(current_chunk_number)
            filenames.append(filename)

            current_chunk_number = current_chunk_number + 1

        current_page_number = current_page_number + 1

    return({
        "chunks": segmented_texts,
        "page_nums": page_numbers,
        "chunk_nums": chunk_numbers,
        "filenames": filenames
    })


def find_last_strings(data, num):
    last_strings = []
    def recursive_traverse(data):
        for item in data:
            if isinstance(item, list):
                recursive_traverse(item)
            elif isinstance(item, str):
                last_strings.append(item)
    recursive_traverse(data)
    return last_strings[-num:]

def find_first_strings(data, num):
    first_strings = []
    def recursive_traverse(data):
        for item in data:
            if isinstance(item, list):
                recursive_traverse(item)
            elif isinstance(item, str):
                first_strings.append(item)
                if len(first_strings) >= num:
                    return
    recursive_traverse(data)
    return first_strings[:num]
