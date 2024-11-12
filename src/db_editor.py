import argparse
import multiprocessing
import shutil
from pathlib import Path
from tqdm import tqdm
import collections.abc as collections
from typing import Any, Dict, List, Optional, Union

from third_party.Hierarchical_Localization.hloc.utils.database import COLMAPDatabase
from third_party.Hierarchical_Localization.hloc.utils.io import get_keypoints
from third_party.Hierarchical_Localization.hloc.utils.parsers import parse_image_lists

import pycolmap

from loguru import logger as guru

def import_new_images(
    image_dir: Path,
    new_image_list: Union[Path, List[str]],
    database_path: Path,
    camera_mode: pycolmap.CameraMode,
    image_list: Optional[List[str]] = None,
    options: Optional[Dict[str, Any]] = None,
):
    guru.info("Importing new images into the database...")
    if options is None:
        options = {}
    if len(new_image_list) != 0:
        if isinstance(new_image_list, (str, Path)):
            new_images = parse_image_lists(new_image_list)
        elif isinstance(new_image_list, collections.Iterable):
            new_images = list(new_image_list)
        else:
            raise ValueError(f"Unknown type for image list: {new_image_list}")
    else:
        raise IOError(f"No new image(s) given.")

    with pycolmap.ostream():
        db = COLMAPDatabase.connect(database_path)
        db.create_tables()

        for new_image in new_images:
            # Assuming the camera parameters are known and fixed
            new_image_path = str(Path(image_dir) / new_image)
            camera = pycolmap.infer_camera_from_image(new_image_path)
            camera_id = db.add_camera(
                camera.model.value,
                camera.width,
                camera.height,
                camera.params,
                prior_focal_length=True,
            )
            db.add_image(new_image, camera_id)
        db.commit()
        db.close()

def import_new_features(
    new_image_list: Union[Path, List[str]],
    image_ids: Dict[str, int],
    database_path: Path,
    features_path: Path
):
    guru.info("Importing new features into the database...")

    if len(new_image_list) != 0:
        if isinstance(new_image_list, (str, Path)):
            new_images = parse_image_lists(new_image_list)
        elif isinstance(new_image_list, collections.Iterable):
            new_images = list(new_image_list)
        else:
            raise ValueError(f"Unknown type for image list: {new_image_list}")
    else:
        raise IOError(f"No new image(s) given.")
    
    db = COLMAPDatabase.connect(database_path)
    for image_name, image_id in tqdm(image_ids.items()):
        if image_name in new_images:
            keypoints = get_keypoints(features_path, image_name)
            keypoints += 0.5  # COLMAP origin
            db.add_keypoints(image_id, keypoints)

    db.commit()
    db.close()