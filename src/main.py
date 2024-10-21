import pycolmap
from pathlib import Path

from third_party.Hierarchical_Localization.hloc import extract_features, match_features, reconstruction, visualization, pairs_from_exhaustive
from third_party.Hierarchical_Localization.hloc.visualization import plot_images, read_image
from third_party.Hierarchical_Localization.hloc.utils import viz_3d


def main():
    output_path = Path('temp/output')
    image_dir = Path('temp/images/')

    sfm_pairs = output_path / 'pairs-sfm.txt'
    loc_pairs = output_path / 'pairs-loc.txt'
    sfm_dir = output_path / 'sfm'
    features = output_path / 'features.h5'
    matches = output_path / 'matches.h5'

    feature_conf = extract_features.confs['superpoint_aachen']
    matcher_conf = match_features.confs['superpoint+lightglue']

    # 1. Feature extraction and matching
    references = [str(p.relative_to(image_dir))
                  for p in (image_dir / 'sacre_coeur/').iterdir()]

    print(f"Extracting Features for images...")
    extract_features.main(feature_conf, image_dir,
                          image_list=references, feature_path=features)
    print(f"Generating Exhaustive pairs...")
    pairs_from_exhaustive.main(sfm_pairs, image_list=references)
    print(f"Matching extracted features...")
    match_features.main(matcher_conf, sfm_pairs,
                        features=features, matches=matches)

    # 2. Generate 3D reconstruction
    model = reconstruction.main(
        sfm_dir, image_dir, sfm_pairs, features, matches, image_list=references)

    fig = viz_3d.init_figure()
    viz_3d.plot_reconstruction(
        fig, model, color='rgba(255,0,0,0.5)', name="mapping", points_rgb=True)
    fig.show()

    # output_path.mkdir()
    # mvs_path = output_path / "mvs"
    # database_path = output_path / "database.db"

    # pycolmap.extract_features(database_path, image_dir)
    # pycolmap.match_exhaustive(database_path)
    # maps = pycolmap.incremental_mapping(database_path, image_dir, output_path)
    # maps[0].write(output_path)

    # # dense reconstruction
    # pycolmap.undistort_images(mvs_path, output_path, image_dir)
    # pycolmap.patch_match_stereo(mvs_path)  # requires compilation with CUDA
    # pycolmap.stereo_fusion(mvs_path / "dense.ply", mvs_path)


if __name__ == "__main__":
    main()
