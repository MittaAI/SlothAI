from flask import Flask, request

app = Flask(__name__)

@app.route('/json', methods=['POST'])
def receive_json():
    try:
        data = request.get_json()
        print(data)  # Print JSON data to the console
        return "JSON data received and printed to console\n", 200
    except Exception as e:
        return f"Error: {str(e)}\n", 400

if __name__ == '__main__':
    app.run(debug=True)

