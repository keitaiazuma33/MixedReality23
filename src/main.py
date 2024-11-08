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
from . import generate_pairs
from third_party.colmap_310.pycolmap import custom_incremental_mapping


def delete_directory_if_exists(directory_path):
    if directory_path.exists():
        shutil.rmtree(directory_path)
        print(f"Deleted directory: {directory_path}")
    else:
        print(f"Directory does not exist: {directory_path}")

def init_reconstruction(
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

    reconstruction = custom_incremental_mapping.main(database, image_dir, sfm_dir)[0]
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
):
    database = sfm_dir / "database.db"

    db_editor.import_new_images(image_dir, database, camera_mode, image_list, image_options)
    image_ids = get_image_ids(database)  # returns a map of image name to image id
    db_editor.import_new_features(
        image_dir, image_ids, database, features)
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
    parser.add_argument('--scene_name', type=str, nargs='?',
                        default='sacre_coeur', help='Name of the scene')
    parser.add_argument('--resume', action='store_true',
                        help='Flag to indicate if the process should resume')
    args = parser.parse_args()

    scene_name = args.scene_name
    resume = args.resume

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
    model_path = sfm_dir / "0"
    database_path = sfm_dir / "database.db"

    feature_conf = extract_features.confs['superpoint_aachen']
    matcher_conf = match_features.confs['superpoint+lightglue']

    # 1. Feature extraction and matching
    references = sorted([str(p.relative_to(image_dir))
                        for p in image_dir.iterdir()])
    print(f"References: {references}")

    if not resume:
        print(f"Generating Exhaustive pairs...")    # Creates pairs-sfm.txt
        pairs_from_exhaustive.main(sfm_pairs, image_list=references)
        print(f"Extracting Features for images...")  # Creates features.h5
        extract_features.main(feature_conf, image_dir,
                              image_list=references, feature_path=features)
        print(f"Matching extracted features...")    # Creates matches.h5
        match_features.main(matcher_conf, sfm_pairs,
                            features=features, matches=matches)
        # 2. Generate 3D reconstruction
        recon = init_reconstruction(sfm_dir, image_dir, sfm_pairs, features, matches, image_list=references)

        reconstruction_manager, mapper = instantiate_reconstruction_manager(database_path, image_dir, model_path)
        ply_file_path = f'/local/home/kazuma/Desktop/MixedReality23/temp/myoutput/{args.scene_name}'
        export_iter = 0
    
    while True:
        print(f"Press 'r' to add one more image or 'e' to export PLY file and text.")
        key = input().strip().lower()
        if key == 'r':
            resume = on_key_event()
            if resume:
                print(f"Resuming from existing pairs-sfm.txt...")
                break
        elif key == 'e':
            guru.info("Exporting PLY file and text")
            assert(reconstruction_manager.size() <= 1)
            current_recon = reconstruction_manager.get(0)
            ply_file_dir = f"{ply_file_path}/iter{export_iter}"
            os.makedirs(ply_file_dir, exist_ok=True)
            current_recon.export_PLY(f"{ply_file_dir}/reconstruction.ply")
            current_recon.write_text(ply_file_dir)
            export_iter += 1
        elif key == 'd':
            mvs_path = Path(f'{ply_file_path}/mvs')
            pycolmap.undistort_images(mvs_path, f"{output_path}/sfm/0", image_dir)
            pycolmap.patch_match_stereo(mvs_path)  # requires compilation with CUDA
            pycolmap.stereo_fusion(mvs_path / "dense.ply", mvs_path)
        else:
            print("Invalid key. Please press 'r' to add one more image or 'e' to export PLY file and text.")

    if resume:
         # 1. Feature extraction and matching
        references = sorted([str(p.relative_to(image_dir)) for p in image_dir.iterdir()])
        print(f"References: {references}")
        
        print(f"Resuming from existing pairs-sfm.txt...")
        sfm_new_pairs = output_path / 'pairs-sfm_new.txt'
        generate_pairs.generate_new_pairs(
            sfm_pairs, sfm_new_pairs, image_list=references, ref_list=references)
        append_new_pairs(sfm_pairs, sfm_new_pairs)
        print(f"Extracting Features for new images...")  # Creates features.h5
        extract_features.main(feature_conf, image_dir,
                              image_list=references, feature_path=features)
        print(f"Matching extracted features...")    # Creates matches.h5
        match_features.main(matcher_conf, sfm_new_pairs,
                            features=features, matches=matches, overwrite=True)
        
        new_sfm_dir = output_path / 'sfm_new'
        #update_database(sfm_dir, new_sfm_dir, image_dir, sfm_new_pairs, features, matches, image_list=references)
        overwrite_database(sfm_dir, image_dir, sfm_new_pairs, features, matches, image_list=references)
        # 2. Generate 3D reconstruction
        # recon = update_reconstruction(
        #     sfm_dir, image_dir, sfm_new_pairs, features, matches, image_list=references)

        new_database_path = new_sfm_dir / "database.db"
        model_path = sfm_dir / "0"
        recon = my_reconstruction.main(database_path, sfm_dir, reconstruction_manager, mapper)[0]
        if recon is not None:
            guru.info(
                f"Reconstruction statistics:\n{recon.summary()}"
            )
        reset_files()

    # De-register image: removes points associated with the image(?)
    de_reg_images = []

    print(f"De-registering an image (image_id = {recon.reg_image_ids()[-1]})...")
    image_ids = recon.reg_image_ids()
    for i in range(1,4):
        recon.deregister_image(image_ids[i])
        de_reg_images.append(image_ids[i])
    print(recon.summary())
    
    recon = my_reconstruction.main(database_path, sfm_dir, reconstruction_manager, mapper, image_to_register=de_reg_images[0:2])[0]
    if recon is not None:
        guru.info(
            f"Reconstruction statistics:\n{recon.summary()}"
        )
    # # Re-register image: does NOT recompute the points associated with the image
    # print(f"Re-registering an image...")
    # recon.register_image(image_ids[0])
    # print(recon.summary())

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
