from flask import Flask, request, jsonify
import threading
import os
import signal
from src.main import MyReconstructionManager

app = Flask(__name__)
reconstruction_manager = MyReconstructionManager()

@app.route('/start', methods=['POST'])
def start_reconstruction():
    data = request.json
    if data.get('command') == 'start':
        threading.Thread(target=run_main_script).start()
        return jsonify({"status": "success", "message": "Reconstruction started"}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid command"}), 400

@app.route('/action', methods=['POST'])
def action():
    data = request.json
    action = data.get('action')
    if action:
        if not reconstruction_manager.process_action(action):
            return jsonify({"status": "success", "message": "Quitting..."}), 200
        return jsonify({"status": "success", "message": "Action processed"}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400

def run_main_script():
    reconstruction_manager.main()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7777)