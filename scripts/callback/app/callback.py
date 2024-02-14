from flask import Flask, request

app = Flask(__name__)

@app.route('/json', methods=['POST'])
def receive_json():
    try:
        data = request.get_json()
        if 'texts' in data:  # Check if 'texts' key exists in the JSON data
            for text in data['texts']:  # Iterate over each item in the 'texts' array
                print(text)  # Print each text to the console
            return "Texts received and printed to console\n", 200
        else:
            return "JSON data received, but no 'texts' key found\n", 400
    except Exception as e:
        return f"Error: {str(e)}\n", 400

if __name__ == '__main__':
    app.run(debug=True)
