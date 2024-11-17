import requests

def send_start_command():
    url = 'http://localhost:7007/trigger_start'
    data = {'command': 'start'}
    response = requests.post(url, json=data)
    print(response.json())

def send_action(action):
    url = 'http://localhost:7007/set_action'
    data = {'action': action}
    response = requests.post(url, json=data)
    print(response.json())

if __name__ == '__main__':
    send_start_command()
    while True:
        action = input("Enter action (n, r, a, e, d, q, h + args): ")
        send_action(action)
        if action == 'q':
            break