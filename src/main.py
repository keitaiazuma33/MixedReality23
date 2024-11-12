import pycolmap
from pycolmap import logging
import argparse
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
from third_party.Hierarchical_Localization.hloc.reconstruction import create_empty_db, import_images, get_image_ids, run_reconstruction
from . import db_editor
from . import my_reconstruction
from third_party.Hierarchical_Localization.hloc.triangulation import OutputCapture, import_features, import_matches, estimation_and_geometric_verification, parse_option_args
from .generate_pairs import generate_new_pairs
from third_party.colmap_310.pycolmap import custom_incremental_mapping


def delete_directory_if_exists(directory_path):
    if directory_path.exists():
        shutil.rmtree(directory_path)
        print(f"Deleted directory: {directory_path}")
    else:
        print(f"Directory does not exist: {directory_path}")

def init_reconstruction(
    recon_dir: Path,
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
    """
    Initializes a pycolmap.Reconstruction object sing hloc functions to create a database,
    import features and matches, and then run the custom incremental mapper from hloc.

    Parameters:
    - recon_dir (Path): Directory to store the reconstruction results.
    - image_dir (Path): Directory containing the input images.
    - pairs (Path): Path to the file containing image pairs.
    - features (Path): Path to the file containing extracted features.
    - matches (Path): Path to the file containing feature matches.
    - camera_mode (pycolmap.CameraMode): Camera mode for importing images.
    - verbose (bool): If True, enables verbose output.
    - skip_geometric_verification (bool): If True, skips geometric verification of matches.
    - min_match_score (Optional[float]): Minimum match score to consider.
    - image_list (Optional[List[str]]): List of images to include in the reconstruction.
    - image_options (Optional[Dict[str, Any]]): Additional options for image import.
    - mapper_options (Optional[Dict[str, Any]]): Additional options for the mapper.

    Returns:
    - pycolmap.Reconstruction: The resulting reconstruction object.
    """
    assert features.exists(), features
    assert pairs.exists(), pairs
    assert matches.exists(), matches

    recon_dir.mkdir(parents=True, exist_ok=True)
    database = recon_dir / "database.db"

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

    reconstruction = custom_incremental_mapping.main(database, image_dir, recon_dir)[0]
    if reconstruction is not None:
        guru.info(
            f"Reconstruction statistics:\n{reconstruction.summary()}"
            + f"\n\tnum_input_images = {len(image_ids)}"
        )
    return reconstruction

def update_database(
    sfm_dir: Path,
    new_sfm_dir: Path,
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
):
    new_sfm_dir.mkdir(parents=True, exist_ok=True)
    old_database = sfm_dir / "database.db"
    new_database = new_sfm_dir / "database.db"
    shutil.copy(old_database, new_database)

    db_editor.import_new_images(
        image_dir, new_database, camera_mode, image_list, image_options)
    image_ids = get_image_ids(new_database)
    db_editor.import_new_features(
        image_dir, image_ids, new_database, features)
    import_matches(
        image_ids,
        new_database,
        pairs,
        matches,
        min_match_score,
        skip_geometric_verification,
    )
    if not skip_geometric_verification:
        estimation_and_geometric_verification(new_database, pairs, verbose)

def overwrite_database(
    image_dir: Path,
    recon_dir: Path,
    new_images: List[str],
    new_pairs_file: Path,
    features: Path,
    matches: Path,
    camera_mode: pycolmap.CameraMode = pycolmap.CameraMode.AUTO,
    verbose: bool = False,
    skip_geometric_verification: bool = False,
    min_match_score: Optional[float] = None,
    image_list: Optional[List[str]] = None,
    image_options: Optional[Dict[str, Any]] = None,
):
    database = recon_dir / "database.db"

    db_editor.import_new_images(image_dir, new_images, database, camera_mode, image_list, image_options)
    image_ids = get_image_ids(database)  # returns a map of image name to image id
    db_editor.import_new_features(new_images, image_ids, database, features)
    import_matches(
        image_ids,
        database,
        new_pairs_file,
        matches,
        min_match_score,
        skip_geometric_verification,
    )
    if not skip_geometric_verification:
        estimation_and_geometric_verification(database, new_pairs_file, verbose)

def append_new_pairs(sfm_pairs_path, sfm_new_pairs_path):
    # ファイルパスをPathオブジェクトに変換
    sfm_pairs = Path(sfm_pairs_path)
    sfm_new_pairs = Path(sfm_new_pairs_path)

    with sfm_pairs.open('r') as f:
        sfm_pairs_content = f.readlines()

    with sfm_new_pairs.open('r') as f:
        sfm_new_pairs_content = f.readlines()

    if sfm_pairs_content and not sfm_pairs_content[-1].endswith('\n'):
        sfm_pairs_content.append('\n')

    sfm_pairs_content.extend(sfm_new_pairs_content)

    # sfm_pairsファイルを上書き保存
    with sfm_pairs.open('w') as f:
        f.writelines(sfm_pairs_content)

def instantiate_reconstruction_manager(
        database_path,
        image_path,
        model_path,
        options=pycolmap.IncrementalPipelineOptions(),
    ):
    if not database_path.exists():
        logging.fatal(f"Database path does not exist: {database_path}")
    if not image_path.exists():
        logging.fatal(f"Image path does not exist: {image_path}")
    reconstruction_manager = pycolmap.ReconstructionManager()
    if model_path is not None and model_path != "":
        reconstruction_manager.read(model_path)
    mapper = pycolmap.IncrementalMapperController(
        options, image_path, database_path, reconstruction_manager
    )
    return reconstruction_manager, mapper

def on_key_event():
    print("Adding one image extra...")
    
    # 移動元と移動先のディレクトリ
    src_dir = "temp/images"
    dest_dir = "temp/images/sacre_coeur"

    # 移動元ディレクトリ内の.jpgファイルを検索
    for file_name in os.listdir(src_dir):
        if file_name.endswith(".jpg"):
            src_file = os.path.join(src_dir, file_name)
            dest_file = os.path.join(dest_dir, file_name)
            shutil.move(src_file, dest_file)
            print(f"Moved {src_file} to {dest_file}")
            return True

def reset_files():
    dest_dir = Path("temp/images")
    sfm_dir = Path("temp/images/sacre_coeur")

    # dest_dir内のファイルを取得し、ソートして一番最後のファイルを特定
    files = sorted(sfm_dir.iterdir(), key=lambda x: x.name)
    if not files:
        print("No files found in dest_dir.")
        return

    last_file = files[-1]

    # 移動先のパスを定義
    destination_file = dest_dir / last_file.name

    # ファイルを移動
    shutil.move(last_file, destination_file)

    print(f"Moved {last_file} to {destination_file}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scene_name', type=str, nargs='?', default='test', help='Name of the scene')
    parser.add_argument('--feature_extractor', type=str, nargs='?', default='superpoint_aachen', help=f'Name of feature extractor. Choose from {list(extract_features.confs.keys())}')
    parser.add_argument('--feature_matcher', type=str, nargs='?', default='superpoint+lightglue', help=f'Name of feature matcher. Choose from {list(match_features.confs.keys())}')
    args = parser.parse_args()

    scene_name = args.scene_name
    feature_extractor = args.feature_extractor
    feature_matcher = args.feature_matcher

    image_dir = Path(f'temp/images/{scene_name}')
    output_path = Path(f'temp/outputs/{scene_name}')
    delete_directory_if_exists(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    sfm_pairs = output_path / 'pairs-sfm.txt'
    loc_pairs = output_path / 'pairs-loc.txt'
    recon_dir = output_path / 'reconstruction'
    features_file = output_path / 'features.h5'
    matches_file = output_path / 'matches.h5'
    model_path = recon_dir / "0"
    database_path = recon_dir / "database.db"

    feature_conf = extract_features.confs[feature_extractor]
    matcher_conf = match_features.confs[feature_matcher]

    # 1. Feature extraction and matching
    references = sorted([str(p.relative_to(image_dir)) for p in image_dir.iterdir()])
    processed_images = set(references)
    print(f"References: {references}")

    print(f"Generating Exhaustive pairs...")    # Creates pairs-sfm.txt
    pairs_from_exhaustive.main(sfm_pairs, image_list=references)
    print(f"Extracting Features for images...") # Creates features.h5
    extract_features.main(feature_conf, image_dir, image_list=references, feature_path=features_file)
    print(f"Matching extracted features...")    # Creates matches.h5
    match_features.main(matcher_conf, sfm_pairs, features=features_file, matches=matches_file)
    
    # 2. Generate 3D reconstruction
    recon = init_reconstruction(recon_dir, image_dir, sfm_pairs, features_file, matches_file, image_list=references)

    reconstruction_manager, mapper = instantiate_reconstruction_manager(database_path, image_dir, model_path)
    export_iter = 0
    de_reg_images = []
    
    while True:
        print(f"Please press 'n', 'r', 'a', 'e', 'd', 'q', or 'h' for help.")
        key = input().strip().split()
        if key[0] == 'n':
            print("\n" + "="*30)
            print("ADDING NEW IMAGES...")
            print("="*30 + "\n")

            print(f"Resuming from existing pairs-sfm.txt...")
            # 1. Feature extraction and matching
            references = sorted([str(p.relative_to(image_dir)) for p in image_dir.iterdir()])
            new_images = [img for img in references if img not in processed_images]
            
            print(f"Resuming from existing pairs-sfm.txt...")
            sfm_new_pairs = output_path / 'pairs-sfm_new.txt'
            generate_new_pairs(sfm_pairs, sfm_new_pairs, new_image_list=new_images, ref_list=references)
            append_new_pairs(sfm_pairs, sfm_new_pairs)
            print(f"Extracting Features for new images...")  # Creates features.h5
            extract_features.main(feature_conf, image_dir, image_list=references, feature_path=features_file)
            print(f"Matching extracted features...")    # Creates matches.h5
            match_features.main(matcher_conf, sfm_new_pairs, features=features_file, matches=matches_file, overwrite=True)
            
            #update_database(recon_dir, new_recon_dir, image_dir, sfm_new_pairs, features, matches, image_list=references)
            overwrite_database(image_dir, recon_dir, new_images, sfm_new_pairs, features_file, matches_file, image_list=references)
            # 2. Generate 3D reconstruction
            # recon = update_reconstruction(
            #     recon_dir, image_dir, sfm_new_pairs, features, matches, image_list=references)

            model_path = recon_dir / "0"
            recon = my_reconstruction.main(database_path, recon_dir, reconstruction_manager, mapper)[0]
            if recon is not None:
                guru.info(
                    f"Reconstruction statistics:\n{recon.summary()}"
                )
            processed_images.update(new_images)
        elif key[0] == 'r':
            print("\n" + "="*30)
            print("REMOVING SPECIFIED IMAGES...")
            print("="*30 + "\n")
            # De-register image: removes points associated with the image
            image_names = key[1:]
            image_ids = get_image_ids(database_path)
            to_de_reg_image_ids = [image_ids[name] for name in image_names]
            assert (all(image_id not in de_reg_images for image_id in to_de_reg_image_ids))

            print(f"De-registering images (image_ids = {to_de_reg_image_ids})...")
            recon = reconstruction_manager.get(0)
            for image_id in to_de_reg_image_ids:
                assert (image_id not in de_reg_images)
                recon.deregister_image(image_id)
                de_reg_images.append(image_id)
            print(f"{recon.reg_image_ids()=}")
            print(recon.summary())
        elif key[0] == 'a':
            print("\n" + "="*30)
            print("ADDING BACK SPECIFIED IMAGES...")
            print("="*30 + "\n")
            # Re-register image and more
            print(f"Re-registering an image...")
            image_names = key[1:]
            image_ids = get_image_ids(database_path)
            to_reg_image_ids = [image_ids[name] for name in image_names]
            assert (all(image_id in de_reg_images for image_id in to_reg_image_ids))

            de_reg_images = [element for element in de_reg_images if element not in to_reg_image_ids]
            recon = my_reconstruction.main(database_path, recon_dir, reconstruction_manager, mapper, image_to_register=to_reg_image_ids)[0]

            if recon is not None:
                guru.info(
                    f"Reconstruction statistics:\n{recon.summary()}"
                )
            print(recon.summary())
        elif key[0] == 'e':
            print("\n" + "="*30)
            print("EXPORTING...")
            print("="*30 + "\n")

            guru.info("Exporting PLY file and text")
            assert(reconstruction_manager.size() <= 1)
            current_recon = reconstruction_manager.get(0)
            ply_file_dir = f"{output_path}/iter{export_iter}"
            os.makedirs(ply_file_dir, exist_ok=True)
            current_recon.export_PLY(f"{ply_file_dir}/reconstruction.ply")
            current_recon.write_text(ply_file_dir)
            export_iter += 1
        elif key[0] == 'd':
            print("\n" + "="*30)
            print("DENSE RECONSTRUCTION...")
            print("="*30 + "\n")

            mvs_path = Path(f'{output_path}/mvs')
            pycolmap.undistort_images(mvs_path, f"{output_path}/sfm/0", image_dir)
            pycolmap.patch_match_stereo(mvs_path)  # requires compilation with CUDA
            pycolmap.stereo_fusion(mvs_path / "dense.ply", mvs_path)
        elif key[0] == 'q':
            print("Quitting...")
            break
        elif key[0] == 'h':
            print("\n" + "="*30)
            print("HELP")
            print("="*30 + "\n")
            print("Press 'n' after adding one new image.\n")
            print("Enter 'r [...]' to remove specified images.\n")
            print("Enter 'a [...]' to add back specified images.\n")
            print("Press 'e' to export PLY file and text.\n")
            print("Press 'd' to perform dense reconstruction.\n")
            print("Press 'q' to quit.\n")
        else:
            print("Invalid key. Please press 'h' for help.\n")
    

    """
    # 3. Visualization
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
