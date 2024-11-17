from flask import Flask, request, jsonify
import threading
import requests

app = Flask(__name__)
user_action = None

@app.route('/input_request', methods=['POST'])
def input_request():
    data = request.json
    step_name = data.get('step_name')
    if step_name:
        print(f"Input requested for step: {step_name}")
        return jsonify({"input": "n"}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid step name"}), 400

@app.route('/trigger_start', methods=['POST'])
def trigger_start():
    def send_start_command():
        url = 'http://localhost:7777/start'
        data = {'command': 'start'}
        response = requests.post(url, json=data)
        print(response.json())

    threading.Thread(target=send_start_command).start()
    return jsonify({"status": "success", "message": "Start command sent"}), 200

@app.route('/set_action', methods=['POST'])
def set_action():
    global user_action
    data = request.json
    action = data.get('action')
    if action and action[0] in ['n', 'r', 'a', 'e', 'd', 'q', 'h']:
        user_action = action
        return jsonify({"status": "success", "message": "Action set"}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400

@app.route('/get_action', methods=['GET'])
def get_action():
    global user_action
    if user_action:
        action = user_action
        user_action = None  # リセット
        return jsonify({"status": "action specified", "action": action}), 200
    else:
        return jsonify({"status": "waiting", "message": "Waiting for action"}), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7007)