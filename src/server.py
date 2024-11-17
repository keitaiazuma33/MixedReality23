from flask import Flask, request, jsonify
import threading
import requests

app = Flask(__name__)
user_action = None
input_event = threading.Condition()

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
        url = 'http://localhost:7777/action'
        response = requests.post(url, json={'action': action})
        return jsonify(response.json()), response.status_code
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400

@app.route('/input_request', methods=['POST'])
def input_request():
    data = request.json
    step_name = data.get('step_name')
    if step_name:
        print(f"Input requested for step: {step_name}")
        with input_event:
            input_event.wait()  # イベントがセットされるまで待機
            response_data = {"input": user_input}
            user_input = None  # 入力をリセット
        return jsonify(response_data), 200
    else:
        return jsonify({"status": "error", "message": "Invalid step name"}), 400

@app.route('/set_input', methods=['POST'])
def set_input():
    global user_input
    data = request.json
    user_input = data.get('input')
    if user_input:
        with input_event:
            input_event.notify()  # イベントを通知
        return jsonify({"status": "success", "message": "Input received"}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid input"}), 400

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7007)