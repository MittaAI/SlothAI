#!/usr/bin/env python

import zlib

# Prompt for the filename to compress
filename = input("Enter the filename to compress: ")

# Read the content of the input file
with open(filename, "rb") as input_file:
    input_data = input_file.read()

# Compress the data using zlib
compressed_data = zlib.compress(input_data, level=zlib.Z_BEST_COMPRESSION)

# Define the output file path for the compressed data
output_file_path = f"{filename}.z"

# Write the compressed data to the output file
with open(output_file_path, "wb") as output_file:
    output_file.write(compressed_data)

print(f"File '{filename}' has been compressed and saved as '{output_file_path}'.")

