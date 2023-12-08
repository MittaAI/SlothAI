import zlib

# Specify the paths for the input and output files
compressed_file_path = 'english.pickle.z'
uncompressed_file_path = 'english.pickle'

# Open the compressed file for reading in binary mode
with open(compressed_file_path, 'rb') as compressed_file:
    # Read the compressed data
    compressed_data = compressed_file.read()

# Decompress the data using zlib
uncompressed_data = zlib.decompress(compressed_data)

# Write the uncompressed data to a new file
with open(uncompressed_file_path, 'wb') as uncompressed_file:
    uncompressed_file.write(uncompressed_data)
