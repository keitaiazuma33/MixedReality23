from pathlib import Path
from typing import List, Optional, Union
import collections.abc as collections

from loguru import logger as guru

from third_party.Hierarchical_Localization.hloc.utils.io import list_h5_names
from third_party.Hierarchical_Localization.hloc.utils.parsers import parse_image_lists

def generate_new_pairs(
    sfm_pairs: Path,
    output: Path,
    new_image_list: Optional[Union[Path, List[str]]] = None,
    features: Optional[Path] = None,
    ref_list: Optional[Union[Path, List[str]]] = None,
    ref_features: Optional[Path] = None,
    ):
    assert sfm_pairs.exists(), f"File not found: {sfm_pairs}"
    if len(new_image_list) != 0:
        if isinstance(new_image_list, (str, Path)):
            new_images = parse_image_lists(new_image_list)
        elif isinstance(new_image_list, collections.Iterable):
            new_images = list(new_image_list)
        else:
            raise ValueError(f"Unknown type for image list: {new_image_list}")
    elif features is not None:
        new_images = list_h5_names(features)
    else:
        raise ValueError("Provide either a list of images or a feature file.")

    self_matching = False
    if ref_list is not None:
        if isinstance(ref_list, (str, Path)):
            names_ref = parse_image_lists(ref_list)
        elif isinstance(ref_list, collections.Iterable):
            names_ref = list(ref_list)
        else:
            raise ValueError(f"Unknown type for reference image list: {ref_list}")
    elif ref_features is not None:
        names_ref = list_h5_names(ref_features)
    else:
        self_matching = True
        names_ref = names_ref

    pairs = []
    existing_pairs = set()

    for n1 in new_images:
        for n2 in names_ref:
            if (n2, n1) not in existing_pairs:
                pairs.append((n1, n2))
                existing_pairs.add((n1, n2))

    guru.info(f"Generated {len(pairs)} new pairs.")
    with open(output, "w") as f:
        f.write("\n".join(" ".join([i, j]) for i, j in pairs))