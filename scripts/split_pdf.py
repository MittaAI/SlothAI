import PyPDF2
import os

def split_pdf(file_path, output_prefix):
    with open(file_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        total_pages = len(reader.pages)
        start_page = 0

        while start_page < total_pages:
            writer = PyPDF2.PdfWriter()
            end_page = min(start_page + 50, total_pages)

            for page in range(start_page, end_page):
                writer.add_page(reader.pages[page])

            output_filename = os.path.join(os.path.dirname(file_path), f"{output_prefix}_pages_{start_page + 1}_to_{end_page}.pdf")
            with open(output_filename, 'wb') as output_file:
                writer.write(output_file)
            
            start_page += 50

if __name__ == "__main__":
    default_directory = os.path.expanduser("~/Desktop/mitta/")
    file_name = input("Enter the file name (e.g., filename.pdf): ")
    file_path = os.path.join(default_directory, file_name)
    output_prefix = input("Enter the prefix for the output files: ")
    split_pdf(file_path, output_prefix)
