import pycolmap
from pathlib import Path
import shutil
import os
from loguru import logger as guru
from typing import Any, Dict, List, Optional

import multiprocessing

from third_party.Hierarchical_Localization.hloc import extract_features, match_features, reconstruction, visualization, pairs_from_exhaustive
from third_party.Hierarchical_Localization.hloc.visualization import plot_images, read_image
from third_party.Hierarchical_Localization.hloc.utils import viz_3d
from third_party.Hierarchical_Localization.hloc.utils.database import COLMAPDatabase
from third_party.Hierarchical_Localization.hloc.reconstruction import create_empty_db, import_images, get_image_ids
from third_party.Hierarchical_Localization.hloc.triangulation import OutputCapture, import_features, import_matches, estimation_and_geometric_verification, parse_option_args
from . import generate_pairs

def delete_directory_if_exists(directory_path):
    if directory_path.exists():
        shutil.rmtree(directory_path)
        print(f"Deleted directory: {directory_path}")
    else:
        print(f"Directory does not exist: {directory_path}")

def run_reconstruction(
    sfm_dir: Path,
    database_path: Path,
    image_dir: Path,
    verbose: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> pycolmap.Reconstruction:
    models_path = sfm_dir / "models"
    models_path.mkdir(exist_ok=True, parents=True)
    guru.info("Running 3D reconstruction...")
    if options is None:
        options = {}
    options = {"num_threads": min(multiprocessing.cpu_count(), 16), **options}
    with OutputCapture(verbose):
        with pycolmap.ostream():
            reconstructions = pycolmap.incremental_mapping(
                database_path, image_dir, models_path, options=options
            )

    if len(reconstructions) == 0:
        guru.error("Could not reconstruct any model!")
        return None
    guru.info(f"Reconstructed {len(reconstructions)} model(s).")

    largest_index = None
    largest_num_images = 0
    for index, rec in reconstructions.items():
        num_images = rec.num_reg_images()
        if num_images > largest_num_images:
            largest_index = index
            largest_num_images = num_images
    assert largest_index is not None
    guru.info(
        f"Largest model is #{largest_index} " f"with {largest_num_images} images."
    )

    for filename in ["images.bin", "cameras.bin", "points3D.bin"]:
        if (sfm_dir / filename).exists():
            (sfm_dir / filename).unlink()
        shutil.move(str(models_path / str(largest_index) / filename), str(sfm_dir))
    return reconstructions[largest_index]


def reconstruct(
    sfm_dir: Path,
    image_dir: Path,
    pairs: Path,
    features: Path,
    matches: Path,
    camera_mode: pycolmap.CameraMode = pycolmap.CameraMode.AUTO,
    verbose: bool = False,
    skip_geometric_verification: bool = False,
    min_match_score: Optional[float] = None,
    image_list: Optional[List[str]] = None,
    image_options: Optional[Dict[str, Any]] = None,
    mapper_options: Optional[Dict[str, Any]] = None,
) -> pycolmap.Reconstruction:
    assert features.exists(), features
    assert pairs.exists(), pairs
    assert matches.exists(), matches

    sfm_dir.mkdir(parents=True, exist_ok=True)
    database = sfm_dir / "database.db"

    create_empty_db(database)
    import_images(image_dir, database, camera_mode, image_list, image_options)
    image_ids = get_image_ids(database)
    import_features(image_ids, database, features)
    import_matches(
        image_ids,
        database,
        pairs,
        matches,
        min_match_score,
        skip_geometric_verification,
    )
    if not skip_geometric_verification:
        estimation_and_geometric_verification(database, pairs, verbose)
    reconstruction = run_reconstruction(
        sfm_dir, database, image_dir, verbose, mapper_options
    )
    if reconstruction is not None:
        guru.info(
            f"Reconstruction statistics:\n{reconstruction.summary()}"
            + f"\n\tnum_input_images = {len(image_ids)}"
        )
    return reconstruction

def main(
        scene_name: str = 'sacre_coeur',
        resume: bool = True,
        ):
    image_dir = Path(f'temp/images/{scene_name}')
    output_path = Path(f'temp/outputs/{scene_name}')
    if not resume:
        delete_directory_if_exists(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    sfm_pairs = output_path / 'pairs-sfm.txt'
    loc_pairs = output_path / 'pairs-loc.txt'
    sfm_dir = output_path / 'sfm'
    features = output_path / 'features.h5'
    matches = output_path / 'matches.h5'

    feature_conf = extract_features.confs['superpoint_aachen']
    matcher_conf = match_features.confs['superpoint+lightglue']

    # 1. Feature extraction and matching
    references = sorted([str(p.relative_to(image_dir)) for p in image_dir.iterdir()])
    print(f"References: {references}")

    if not resume:
        print(f"Generating Exhaustive pairs...")    # Creates pairs-sfm.txt
        pairs_from_exhaustive.main(sfm_pairs, image_list=references)
        print(f"Extracting Features for images...") # Creates features.h5
        extract_features.main(feature_conf, image_dir, image_list=references, feature_path=features)
        print(f"Matching extracted features...")    # Creates matches.h5
        match_features.main(matcher_conf, sfm_pairs, features=features, matches=matches)
    else:
        print(f"Resuming from existing pairs-sfm.txt...")
        sfm_new_pairs = output_path / 'pairs-sfm_new.txt'
        generate_pairs.generate_new_pairs(sfm_pairs, sfm_new_pairs, image_list=references, ref_list=references)
        print(f"Extracting Features for images...") # Creates features.h5
        extract_features.main(feature_conf, image_dir, image_list=references, feature_path=features)

    # 2. Generate 3D reconstruction
    recon = reconstruct(sfm_dir, image_dir, sfm_pairs, features, matches, image_list=references)

    # De-register image: removes points associated with the image(?)
    print(f"De-registering an image...")
    image_ids = recon.reg_image_ids()
    recon.deregister_image(image_ids[0])
    print(recon.summary())

    # Re-register image: does NOT recompute the points associated with the image
    print(f"Re-registering an image...")
    recon.register_image(image_ids[0])
    print(recon.summary())

    """
    fig = viz_3d.init_figure()
    viz_3d.plot_reconstruction(
        fig, model, color='rgba(255,0,0,0.5)', name="mapping", points_rgb=True)
    fig.show()
    
    print("Operating on pycolmap")
    output_path.mkdir(exist_ok=True)
    mvs_path = output_path / "mvs"
    database_path = output_path / "database.db"

    pycolmap.extract_features(database_path, image_dir)
    pycolmap.match_exhaustive(database_path)
    maps = pycolmap.incremental_mapping(database_path, image_dir, output_path)
    maps[0].write(output_path)

    # dense reconstruction
    pycolmap.undistort_images(mvs_path, output_path, image_dir)
    pycolmap.patch_match_stereo(mvs_path)  # requires compilation with CUDA
    pycolmap.stereo_fusion(mvs_path / "dense.ply", mvs_path)
    """


if __name__ == "__main__":
    main()
