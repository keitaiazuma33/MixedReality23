import requests
import json
import io
import zipfile
from pathlib import Path
import glob
import os

# Define server endpoint
url = "http://127.0.0.1:5000/process"

# Prepare metadata and image
metadata = {
    "description": "Send image and get results",
    "task": None,
    "full_pipeline": False,
    "continue": False
}
# Replace with your image path
image_path = Path(__file__).parent.parent / 'run/images/test/image01.jpg'

def send_request(metadata, image_path=None):
    # Send POST request with metadata and image
    with open(image_path, 'rb') as img_file:
        files = {
            "metadata": (None, json.dumps(metadata), "application/json"),
            "image": (image_path.name, img_file, "image/jpeg")
        }
        response = requests.post(url, files=files)

    print("Sent image and metadata to server")

    # Handle the multipart response
    if response.status_code == 200:
        content_type = response.headers.get("Content-Type", "")
        boundary = content_type.split(
            "boundary=")[1] if "boundary=" in content_type else None
        if boundary:
            # Ensure the boundary starts with "--"
            boundary = f"--{boundary}".encode()

            # Split the response content by the boundary and remove the first and last empty parts
            parts = response.content.split(boundary)
            # Clean parts and remove empty ones
            parts = [part.strip()
                    for part in parts if (part.strip() and part.strip() != b'--')]
            print(f"{len(parts)} parts received")

            for part in parts:
                # Handle JSON metadata
                if b"application/json" in part:
                    # Split header and body and decode the JSON
                    header_end = part.find(b"\r\n\r\n")
                    if header_end != -1:
                        json_data = part[header_end + 4:].strip()  # Skip header
                        metadata = json.loads(json_data.decode())
                        print("Received JSON metadata:", metadata)

                # Handle ZIP file
                elif b"application/zip" in part:
                    header_end = part.find(b"\r\n\r\n")
                    if header_end != -1:
                        zip_data = part[header_end + 4:].strip()  # Skip header
                        try:
                            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                                zf.extractall("downloaded_files")
                            print("Extracted files to 'downloaded_files' folder")
                        except zipfile.BadZipFile:
                            print("Error: Invalid zip file received")
                else:
                    print("Unknown part received:", part)
    else:
        print(f"Error: {response.status_code}")

if __name__ == "__main__":
    while True:
        # Accept user input for task
        user_input = input("Enter a task (or 'exit' to quit): ")
        
        image_directory = Path(__file__).parent.parent / 'temp/images/client'
        image_files = sorted(glob.glob(str(image_directory / '*')))
        print(image_files)
        if image_files:
            image_path = Path(image_files[-1])
        else:
            print("Waiting for images to be added to the 'temp/images/run' folder...")
            continue

        if user_input.lower() == 'exit':
            break
        metadata['task'] = user_input

        # Accept user input for full pipeline
        while True:
            user_input = input("Select between running the full pipeline (y/[n]): ")
            if user_input in ['y', 'Y', 'yes', 'Yes']:
                metadata['full_pipeline'] = True
                break
            elif user_input in ['n', 'N', 'no', 'No', '']:
                metadata['full_pipeline'] = False
                break
            else:
                print("Invalid input. Please try again.")
        
        # Accept user input for continuing COLMAP Pipeline
        while True:
            user_input = input("Select between skipping or not skipping pipeline component (y/[n]): ")
            if user_input in ['y', 'Y', 'yes', 'Yes']:
                metadata['skip'] = True
                print("Setting data['skip'] to True")
                break
            elif user_input in ['n', 'N', 'no', 'No', '']:
                metadata['skip'] = False
                print("Setting data['skip'] to False")
                break
            else:
                print("Invalid input. Please try again.")
        
        print(f"Sending image {image_path} with metadata {metadata}")
        send_request(metadata, image_path)
        
        metadata['task'] = None
        metadata['full_pipeline'] = False
        metadata['skip'] = False