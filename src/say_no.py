import requests

def send_input(input_value):
    url = 'http://localhost:7007/set_input'
    data = {'input': input_value}
    response = requests.post(url, json=data)
    print(response.json())

if __name__ == '__main__':
    while True:
        user_input = input("Enter your input (y/n): ")
        send_input(user_input)
        if user_input == 'exit':
            break