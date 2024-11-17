import requests
import json
import io
import zipfile
from pathlib import Path

# Define server endpoint
url = "http://127.0.0.1:5000/process"

# Prepare metadata and image
metadata = {"task": "process_image",
            "description": "Send image and get results"}
# Replace with your image path
image_path = Path(__file__).parent.parent / 'temp/images/image10.jpg'

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
