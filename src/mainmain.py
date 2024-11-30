import threading
from .main import MyReconstructionManager
from .server_flask import create_flask_server
from pathlib import Path

# Define the IMAGES_FOLDER
IMAGES_FOLDER = Path(__file__).parent.parent / 'temp/images/run'

reconstruction_manager = MyReconstructionManager()

# Shared resource
data = {}
data['num_images'] = sum(1 for file in IMAGES_FOLDER.iterdir() if file.is_file())
data['new_request'] = False
data['recon_done'] = False
data['error'] = None
data['task'] = None
data['full_pipeline'] = False
data['skip'] = False
data['user_message'] = ""
data['let_colmap_choose_order'] = False

# Create a Lock and a Condition Variable
mutex = threading.Lock()
cv = threading.Condition(mutex)

# Create threads
server_thread = threading.Thread(target=create_flask_server, args=(cv, data), daemon=True)
COLMAP_thread = threading.Thread(target=reconstruction_manager.main, args=(cv, data), daemon=True)

# Start threads
server_thread.start()
COLMAP_thread.start()

# Wait for threads to finish
server_thread.join()
COLMAP_thread.join()
