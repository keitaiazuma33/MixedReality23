import argparse
import multiprocessing
import shutil
from pathlib import Path
from tqdm import tqdm
from typing import Any, Dict, List, Optional

from third_party.Hierarchical_Localization.hloc.utils.database import COLMAPDatabase
from third_party.Hierarchical_Localization.hloc.utils.io import get_keypoints

import pycolmap

from loguru import logger as guru

def import_new_images(
    image_dir: Path,
    database_path: Path,
    camera_mode: pycolmap.CameraMode,
    image_list: Optional[List[str]] = None,
    options: Optional[Dict[str, Any]] = None,
):
    guru.info("Importing new image into the database...")
    if options is None:
        options = {}
    images = sorted(list(image_dir.iterdir()))
    if len(images) == 0:
        raise IOError(f"No images found in {image_dir}.")
    
    last_image = images[-1]

    with pycolmap.ostream():
        db = COLMAPDatabase.connect(database_path)
        db.create_tables()

        # Assuming the camera parameters are known and fixed
        camera = pycolmap.infer_camera_from_image(last_image)
        camera_id = db.add_camera(
            camera.model.value,
            camera.width,
            camera.height,
            camera.params,
            prior_focal_length=True,
        )
        db.add_image(last_image.name, camera_id)
        db.commit()
        db.close()

def import_new_features(
    image_dir: Path,
    image_ids: Dict[str, int],
    database_path: Path,
    features_path: Path
):
    guru.info("Importing new features into the database...")
    db = COLMAPDatabase.connect(database_path)

    images = sorted(list(image_dir.iterdir()))
    if len(images) == 0:
        raise IOError(f"No images found in {image_dir}.")
    
    last_image = images[-1]

    for image_name, image_id in tqdm(image_ids.items()):
        if image_name == last_image.name:
            keypoints = get_keypoints(features_path, image_name)
            keypoints += 0.5  # COLMAP origin
            db.add_keypoints(image_id, keypoints)

    db.commit()
    db.close()