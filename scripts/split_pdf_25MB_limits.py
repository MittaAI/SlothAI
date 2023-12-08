import PyPDF2
import os
from io import BytesIO

def get_pdf_size(writer):
    """Get the size of the PDF currently in the writer."""
    temp_buffer = BytesIO()
    writer.write(temp_buffer)
    size = len(temp_buffer.getvalue())
    return size

def split_pdf(file_path, output_prefix, max_size=25*1024*1024):  # max_size in bytes
    with open(file_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        total_pages = len(reader.pages)
        start_page = 0

        while start_page < total_pages:
            writer = PyPDF2.PdfWriter()
            end_page = start_page
            current_size = 0

            while end_page < total_pages:
                writer.add_page(reader.pages[end_page])
                temp_size = get_pdf_size(writer)

                if temp_size > max_size:
                    if end_page == start_page:
                        # This means a single page is larger than the max size, so we have to include it.
                        end_page += 1
                    break
                else:
                    current_size = temp_size
                    end_page += 1

            output_filename = os.path.join(os.path.dirname(file_path), f"{output_prefix}_pages_{start_page + 1}_to_{end_page}.pdf")
            with open(output_filename, 'wb') as output_file:
                writer.write(output_file)
            
            start_page = end_page

if __name__ == "__main__":
    default_directory = os.path.expanduser("~/Desktop/mitta/")
    file_name = input("Enter the file name (e.g., filename.pdf): ")
    file_path = os.path.join(default_directory, file_name)
    output_prefix = input("Enter the prefix for the output files: ")
    split_pdf(file_path, output_prefix)
