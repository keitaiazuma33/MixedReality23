from flask import Flask, request, jsonify, Response
import os
import io
import zipfile
import json
from pathlib import Path
from werkzeug.datastructures import Headers
import uuid
import threading

def create_flask_server(cv, data):

    app = Flask(__name__)
    UPLOAD_FOLDER = Path(__file__).parent.parent / 'temp/images/run'
    OUTPUT_FOLDER = Path(__file__).parent.parent / 'temp/outputs/run/PLY/iter0'
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    @app.route('/process', methods=['POST'])
    def process_request():
        # Handle metadata
        if 'metadata' not in request.form:
            return jsonify({"error": "Metadata not provided"}), 400
        metadata = json.loads(request.form['metadata'])
        print(f"Received metadata: {metadata}")

        # Handle optional image
        if 'image' in request.files:
            image = request.files['image']
            image_path = UPLOAD_FOLDER / image.filename
            image.save(image_path)
            print(f"Image saved to {image_path}")
        else:
            print("No image provided in the request.")
            image_path = None            

        with cv:
            # Modify shared resource data to add new request
            data['task'] = metadata["task"]
            data['full_pipeline'] = metadata["full_pipeline"]
            data['skip'] = metadata["skip"]
            data['let_colmap_choose_order'] = metadata["let_colmap_choose_order"]
            
            if image_path is not None:
                data['num_images'] = data['num_images'] + 1

            data['new_request'] = True
            data['recon_done'] = False
            if data['num_images'] < 2:
                data['user_message'] = "Please upload at least 2 images to start the reconstruction."
            cv.notify()

            while not (data['recon_done'] or data['num_images'] < 2):
                print("Waiting for COLMAP to produce recon...")
                cv.wait() # wait for COLMAP to produce recon

        # Process image and metadata (dummy processing here)
        response_metadata = {
            "status": "success",
            "description": "Processing complete",
            "user_message": data['user_message'],
            "files": ["cameras.txt", "images.txt", "points3D.txt", "reconstruction.ply"]
        }

        data["user_message"] = ""

        # Create a zip archive for the response files
        zip_memory = io.BytesIO()
        with zipfile.ZipFile(zip_memory, "w") as zf:
            for filename in response_metadata["files"]:
                file_path = OUTPUT_FOLDER / filename
                if file_path.exists():
                    # Add the file to the zip archive by reading the file content
                    # arcname avoids writing full path in zip
                    zf.write(file_path, arcname=filename)
                else:
                    print(f"Warning: File {filename} not found.")

        zip_memory.seek(0)

        # Generate a unique boundary for multipart
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"

        # Create a multipart response generator
        def generate():
            # Part 1: JSON metadata
            yield f"--{boundary}\r\n".encode()
            yield b"Content-Type: application/json\r\n\r\n"
            yield f"{json.dumps(response_metadata)}\r\n".encode()

            # Part 2: Zipped files
            yield f"--{boundary}\r\n".encode()
            yield b"Content-Type: application/zip\r\n"
            yield b"Content-Disposition: attachment; filename=response_files.zip\r\n\r\n"
            yield zip_memory.read()

            # End of multipart response
            # Corrected: ending boundary with \r\n
            yield f"--{boundary}--\r\n".encode()

        # Set proper headers for multipart response
        headers = Headers()
        headers.add("Content-Type", f"multipart/mixed; boundary={boundary}")

        return Response(generate(), headers=headers)

    app.run(debug=False, use_reloader=False)


    # def run_server():

    # if __name__ == "__main__":
    #     run_server()