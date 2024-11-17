from flask import Flask, request, jsonify
import threading
import os
import signal

app = Flask(__name__)

@app.route('/start', methods=['POST'])
def start_reconstruction():
    data = request.json
    if data.get('command') == 'start':
        threading.Thread(target=run_main_script).start()
        return jsonify({"status": "success", "message": "Reconstruction started"}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid command"}), 400

def run_main_script():
    os.kill(os.getpid(), signal.SIGINT)
    os.system('python -m src.main')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7777)