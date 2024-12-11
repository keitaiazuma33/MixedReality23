"""
Python reimplementation of the C++ incremental mapper with equivalent logic.
"""

import shutil
import time
import urllib.request
import zipfile
import requests
from pathlib import Path

import enlighten
from loguru import logger as guru

import pycolmap
from pycolmap import logging
from third_party.colmap_310.pycolmap import custom_bundle_adjustment
#from src.main import export_ply

from enum import Enum, auto

class ReconstructionStep(Enum):
    WAIT = auto()
    IMAGE_REGISTRATION = auto()
    TRIANGULATION = auto()
    LOCAL_BA = auto()
    GLOBAL_BA = auto()

def extract_colors(image_path, image_id, reconstruction):
    if not reconstruction.extract_colors_for_image(image_id, image_path):
        logging.warning(f"Could not read image {image_id} at path {image_path}")


def write_snapshot(reconstruction, snapshot_path):
    logging.info("Creating snapshot")
    timestamp = time.time() * 1000
    path = snapshot_path / f"{timestamp:010d}"
    path.mkdir(exist_ok=True, parents=True)
    logging.verbose(1, f"=> Writing to {path}")
    reconstruction.write(path)


def iterative_global_refinement(options, mapper_options, mapper):
    logging.info("Retriangulation and Global bundle adjustment")
    # The following is equivalent to mapper.iterative_global_refinement(...)
    custom_bundle_adjustment.iterative_global_refinement(
        mapper,
        options.ba_global_max_refinements,
        options.ba_global_max_refinement_change,
        mapper_options,
        options.get_global_bundle_adjustment(),
        options.get_triangulation(),
    )
    mapper.filter_images(mapper_options)


def initialize_reconstruction(
    controller, mapper, mapper_options, reconstruction
):
    """Equivalent to IncrementalMapperController.initialize_reconstruction(...)"""
    options = controller.options
    init_pair = (options.init_image_id1, options.init_image_id2)

    # Try to find good initial pair
    if not options.is_initial_pair_provided():
        logging.info("Finding good initial image pair")
        ret = mapper.find_initial_image_pair(mapper_options, *init_pair)
        if ret is None:
            logging.info("No good initial image pair found.")
            return pycolmap.IncrementalMapperStatus.NO_INITIAL_PAIR
        init_pair, two_view_geometry = ret
    else:
        if not all(reconstruction.exists_image(i) for i in init_pair):
            logging.info(f"=> Initial image pair {init_pair} does not exist.")
            return pycolmap.IncrementalMapperStatus.BAD_INITIAL_PAIR
        two_view_geometry = mapper.estimate_initial_two_view_geometry(
            mapper_options, *init_pair
        )
        if two_view_geometry is None:
            logging.info("Provided pair is insuitable for initialization")
            return pycolmap.IncrementalMapperStatus.BAD_INITIAL_PAIR
    logging.info(f"Initializing with image pair {init_pair}")
    mapper.register_initial_image_pair(
        mapper_options, two_view_geometry, *init_pair
    )
    logging.info("Global bundle adjustment")
    # The following is equivalent to: mapper.adjust_global_bundle(...)
    custom_bundle_adjustment.adjust_global_bundle(
        mapper, mapper_options, options.get_global_bundle_adjustment()
    )
    reconstruction.normalize()
    mapper.filter_points(mapper_options)
    mapper.filter_images(mapper_options)

    # Initial image pair failed to register
    if (
        reconstruction.num_reg_images() == 0
        or reconstruction.num_points3D() == 0
    ):
        return pycolmap.IncrementalMapperStatus.BAD_INITIAL_PAIR
    if options.extract_colors:
        extract_colors(controller.image_path, init_pair[0], reconstruction)
    return pycolmap.IncrementalMapperStatus.SUCCESS

def report_statistics(message, reconstruction):
    guru.info(f"{message}\n{reconstruction.summary()}")

def print_instructions(step, cv=None, data=None, recommended_by_colmap=True):
    skip = False

    if data['full_pipeline'] == False:
        if recommended_by_colmap:
            message = f"COLMAP is suggesting to perform {step.name}\nDo you want to skip this step? (y/n)"
        else:
            message = f"COLMAP is suggesting to SKIP {step.name}\nDo you want to skip this step? (y/n)"
        print(message)
        data["user_message"] += message

    else:
        message = f"Proceeding with {step.name} as per user request ({data['full_pipeline']=}).\n"
        print(message)
        data["user_message"] += message
        skip = not recommended_by_colmap
        return skip

    data['recon_done'] = True
    data['new_request'] = False
    cv.notify()

    print("Waiting for new request...")
    while data['new_request'] == False:
        cv.wait()

    skip = data['skip']
    
    return skip

def reconstruct_sub_model(manager_instance, controller, mapper, mapper_options, reconstruction, image_to_register=None, cv=None, data=None):
    """Equivalent to IncrementalMapperController.reconstruct_sub_model(...)"""
    current_step = ReconstructionStep.WAIT
    # register initial pair
    mapper.begin_reconstruction(reconstruction)
    if reconstruction.num_reg_images() == 0:
        init_status = initialize_reconstruction(
            controller, mapper, mapper_options, reconstruction
        )
        if init_status != pycolmap.IncrementalMapperStatus.SUCCESS:
            return init_status
        controller.callback(
            pycolmap.IncrementalMapperCallback.INITIAL_IMAGE_PAIR_REG_CALLBACK
        )

    # incremental mapping
    options = controller.options
    snapshot_prev_num_reg_images = reconstruction.num_reg_images()
    ba_prev_num_reg_images = reconstruction.num_reg_images()
    ba_prev_num_points = reconstruction.num_points3D()
    reg_next_success, prev_reg_next_success = True, True
    image_to_register = list(set(image_to_register) - set(reconstruction.reg_image_ids()))
    print(f"{image_to_register=}")
    let_colmap_choose_order = data['let_colmap_choose_order']
    while True:
        current_step = ReconstructionStep.IMAGE_REGISTRATION
        if not (reg_next_success or prev_reg_next_success):
            break
        prev_reg_next_success = reg_next_success
        reg_next_success = False
        if let_colmap_choose_order:
            colmap_order = mapper.find_next_images(mapper_options)
            print(f"{colmap_order=}")
            print(f"{image_to_register=}")
            image_to_register = [i for i in colmap_order if i in image_to_register]
            print(f"{image_to_register=}")
        next_images = image_to_register
        print(f"{next_images=}")
        if len(next_images) == 0:
            break
        for reg_trial in range(len(next_images)):
            next_image_id = next_images[reg_trial]
            logging.info(
                f"Registering image #{next_image_id} "
                f"({reconstruction.num_reg_images() + 1})"
            )
            num_vis = mapper.observation_manager.num_visible_points3D(
                next_image_id
            )
            num_obs = mapper.observation_manager.num_observations(next_image_id)
            logging.info(f"=> Image sees {num_vis} / {num_obs} points")

            print(f"{reconstruction.reg_image_ids()=}")

            reg_next_success = mapper.register_next_image(
                mapper_options, next_image_id
            )
            if reg_next_success:
                print(f"Registered image {next_image_id}")
                if image_to_register is not None:
                    del image_to_register[reg_trial]
                    print(f"{image_to_register=}")
                manager_instance.export_ply(reconstruction, current_step.name)
                current_step = ReconstructionStep.TRIANGULATION
                break
            else:
                logging.info("=> Could not register, trying another image.")
            # If initial pair fails to continue for some time,
            # abort and try different initial pair.
            kMinNumInitialRegTrials = 30
            if (
                reg_trial >= kMinNumInitialRegTrials
                and reconstruction.num_reg_images() < options.min_model_size
            ):
                current_step = ReconstructionStep.WAIT
                break
        if reg_next_success:
            report_statistics("<<<Reconstrctuion after registering image>>>", reconstruction)
            assert current_step == ReconstructionStep.TRIANGULATION
            skip = print_instructions(current_step, cv, data)
            if not skip:
                mapper.triangulate_image(options.get_triangulation(), next_image_id)
                manager_instance.export_ply(reconstruction, current_step.name)
                report_statistics("<<<Reconstrctuion after triangulation>>>", reconstruction)
                current_step = ReconstructionStep.LOCAL_BA
            else:
                guru.info("Skipping triangulation")
                current_step = ReconstructionStep.LOCAL_BA
            
            ### Local BA ###
            assert current_step == ReconstructionStep.LOCAL_BA
            skip = print_instructions(current_step, cv, data)
            if not skip:
                # The following is equivalent to mapper.iterative_local_refinement(...)
                custom_bundle_adjustment.iterative_local_refinement(
                    mapper,
                    options.ba_local_max_refinements,
                    options.ba_local_max_refinement_change,
                    mapper_options,
                    options.get_local_bundle_adjustment(),
                    options.get_triangulation(),
                    next_image_id,
                )
                manager_instance.export_ply(reconstruction, current_step.name)
                report_statistics("<<<Reconstrctuion after local BA>>>", reconstruction)
                guru.info("Checking for global refinement...")
                if controller.check_run_global_refinement(
                    reconstruction, ba_prev_num_reg_images, ba_prev_num_points
                ):
                    guru.info("Global refinement is needed")
                    current_step = ReconstructionStep.GLOBAL_BA
                else:
                    guru.info("Global refinement can be skipped")
                    # Ask User if they want to skip global refinement anyways
                    current_step = ReconstructionStep.GLOBAL_BA
            else:
                guru.info("Skipped Local BA but continuing with Global BA")
                current_step = ReconstructionStep.GLOBAL_BA

            ### Global BA ###
            if current_step == ReconstructionStep.GLOBAL_BA:
                assert current_step == ReconstructionStep.GLOBAL_BA
                skip = print_instructions(current_step, cv, data, recommended_by_colmap=controller.check_run_global_refinement(reconstruction, ba_prev_num_reg_images, ba_prev_num_points))
                if not skip:
                    iterative_global_refinement(options, mapper_options, mapper)
                    ba_prev_num_points = reconstruction.num_points3D()
                    ba_prev_num_reg_images = reconstruction.num_reg_images()
                    manager_instance.export_ply(reconstruction, current_step.name)
                    report_statistics("<<<Reconstrctuion after Global BA>>>", reconstruction)
                    current_step = ReconstructionStep.WAIT
                else:
                    guru.info("Skipping global BA")
                    current_step = ReconstructionStep.WAIT
            
            if options.extract_colors:
                extract_colors(
                    controller.image_path, next_image_id, reconstruction
                )
            if (
                options.snapshot_images_freq > 0
                and reconstruction.num_reg_images()
                >= options.snapshot_images_freq + snapshot_prev_num_reg_images
            ):
                snapshot_prev_num_reg_images = reconstruction.num_reg_images()
                write_snapshot(reconstruction, Path(options.snapshot_path))
            controller.callback(
                pycolmap.IncrementalMapperCallback.NEXT_IMAGE_REG_CALLBACK
            )
        if mapper.num_shared_reg_images() >= int(options.max_model_overlap):
            break
        if (not reg_next_success) and prev_reg_next_success:
            data["user_message"] = f"COLMAP is suggesting to perform {ReconstructionStep.GLOBAL_BA.name} because the last image registration failed.\n"
            skip = print_instructions(ReconstructionStep.GLOBAL_BA, cv, data)
            if not skip:
                current_step = ReconstructionStep.GLOBAL_BA
                iterative_global_refinement(options, mapper_options, mapper)
                manager_instance.export_ply(reconstruction, current_step.name)
                report_statistics("<<<Reconstrctuion after Global BA>>>", reconstruction)
                current_step = ReconstructionStep.WAIT

    if (
        reconstruction.num_reg_images() >= 2
        and reconstruction.num_reg_images() != ba_prev_num_reg_images
        and reconstruction.num_points3D != ba_prev_num_points
    ):
        data["user_message"] = f"COLMAP is suggesting to perform {ReconstructionStep.GLOBAL_BA.name} because reconstruction has changed.\n"
        skip = print_instructions(ReconstructionStep.GLOBAL_BA, cv, data)
        if not skip:
            current_step = ReconstructionStep.GLOBAL_BA
            iterative_global_refinement(options, mapper_options, mapper)
            manager_instance.export_ply(reconstruction, current_step.name)
            report_statistics("<<<Reconstrctuion after Global BA>>>", reconstruction)
            current_step = ReconstructionStep.WAIT
    return pycolmap.IncrementalMapperStatus.SUCCESS


def reconstruct(manager_instance, controller, mapper_options, image_to_register=None, cv=None, data=None):
    """Equivalent to IncrementalMapperController.reconstruct(...)"""
    options = controller.options
    reconstruction_manager = controller.reconstruction_manager
    database_cache = controller.database_cache
    mapper = pycolmap.IncrementalMapper(database_cache)
    initial_reconstruction_given = reconstruction_manager.size() > 0
    if reconstruction_manager.size() > 1:
        logging.fatal(
            "Can only resume from a single reconstruction, but multiple are given"
        )
    for num_trials in range(options.init_num_trials):
        if (not initial_reconstruction_given) or num_trials > 0:
            reconstruction_idx = reconstruction_manager.add()
        else:
            reconstruction_idx = 0
        reconstruction = reconstruction_manager.get(reconstruction_idx)
        status = reconstruct_sub_model(
            manager_instance, controller, mapper, mapper_options, reconstruction, image_to_register=image_to_register, cv =cv, data=data
        )
        if status == pycolmap.IncrementalMapperStatus.INTERRUPTED:
            mapper.end_reconstruction(False)
        elif status in (
            pycolmap.IncrementalMapperStatus.NO_INITIAL_PAIR,
            pycolmap.IncrementalMapperStatus.BAD_INITIAL_PAIR,
        ):
            mapper.end_reconstruction(True)
            reconstruction_manager.delete(reconstruction_idx)
            if options.is_initial_pair_provided():
                return
        elif status == pycolmap.IncrementalMapperStatus.SUCCESS:
            total_num_reg_images = mapper.num_total_reg_images()
            min_model_size = min(
                0.8 * database_cache.num_images(), options.min_model_size
            )
            if (
                options.multiple_models
                and reconstruction_manager.size() > 1
                and (
                    reconstruction.num_reg_images() < min_model_size
                    or reconstruction.num_reg_images() == 0
                )
            ):
                mapper.end_reconstruction(True)
                reconstruction_manager.delete(reconstruction_idx)
            else:
                mapper.end_reconstruction(False)
            controller.callback(
                pycolmap.IncrementalMapperCallback.LAST_IMAGE_REG_CALLBACK
            )
            if (
                initial_reconstruction_given
                or (not options.multiple_models)
                or reconstruction_manager.size() >= options.max_num_models
                or total_num_reg_images >= database_cache.num_images() - 1
            ):
                return
        else:
            logging.fatal(f"Unknown reconstruction status: {status}")


def main_incremental_mapper(manager_instance, controller, image_to_register=None, cv=None, data=None):
    """Equivalent to IncrementalMapperController.run()"""
    timer = pycolmap.Timer()
    timer.start()
    if not controller.load_database():
        return
    init_mapper_options = controller.options.get_mapper()
    reconstruct(manager_instance, controller, init_mapper_options, image_to_register, cv, data)

    for i in range(2):  # number of relaxations
        if controller.reconstruction_manager.size() > 0:
            break
        logging.info("=> Relaxing the initialization constraints")
        init_mapper_options.init_min_num_inliers = int(
            init_mapper_options.init_min_num_inliers / 2
        )
        reconstruct(manager_instance, controller, init_mapper_options, image_to_register, cv, data)
        if controller.reconstruction_manager.size() > 0:
            break
        logging.info("=> Relaxing the initialization constraints")
        init_mapper_options.init_min_tri_angle /= 2
        reconstruct(manager_instance, controller, init_mapper_options, image_to_register, cv, data)
    timer.print_minutes()


def main(
    manager_instance,
    database_path,
    output_path,
    reconstruction_manager,
    mapper,
    image_to_register=None,
    cv=None,
    data=None,
):
    output_path.mkdir(exist_ok=True, parents=True)

    # main runner
    num_images = pycolmap.Database(database_path).num_images
    for i in range(num_images):
        mapper.add_callback(
            pycolmap.IncrementalMapperCallback.INITIAL_IMAGE_PAIR_REG_CALLBACK,
            lambda: print("Initial image pair registered"),
        )
        mapper.add_callback(
            pycolmap.IncrementalMapperCallback.NEXT_IMAGE_REG_CALLBACK,
            lambda: print("Next image registered"),
        )
        main_incremental_mapper(manager_instance, mapper, image_to_register, cv, data)

    # write and output
    reconstruction_manager.write(output_path)
    reconstructions = {}
    for i in range(reconstruction_manager.size()):
        reconstructions[i] = reconstruction_manager.get(i)
    return reconstructions
