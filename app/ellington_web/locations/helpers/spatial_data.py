"""
GST-specific spatial-data helpers.

find_vector_dataset_file_in_directory searches a directory for the single
vector dataset file matching settings.VALID_VECTOR_FILE_EXTENSIONS.
fix_gadm_null_foreign_keys cleans GADM's literal 'NA' strings into nulls.

Both should eventually move into siege_utilities (siege_utilities#515).
"""

import logging
import pathlib

from django.conf import settings
import geopandas as gpd
import numpy as np

logger = logging.getLogger("django")

GADM_MODEL_FIELD_NAMES = [
    "GID_0",
    "GID_1",
    "GID_2",
    "GID_3",
    "GID_4",
    "GID_5",
]


def find_vector_dataset_file_in_directory(target_directory):
    """
    Search a directory for the single vector-format spatial dataset file
    matching settings.VALID_VECTOR_FILE_EXTENSIONS.

    Returns the matching path, or False on failure / ambiguity.
    """
    try:
        logger.info(f"Retrieving a vector spatial dataset in {target_directory}")
        target_directory = pathlib.Path(target_directory)
        permitted_gdb_substring = "gdb"

        files_in_directory = [
            x
            for x in target_directory.glob("**/*")
            if x.is_file() or permitted_gdb_substring in x.name
        ]

        target_files_list = []
        for f in files_in_directory:
            lowered_file_suffix = str(f.suffix).lower()
            if lowered_file_suffix in settings.VALID_VECTOR_FILE_EXTENSIONS:
                target_files_list.append(f)
                logger.info(f"Added {f} to target_files_list")

        number_of_files = len(target_files_list)

        if number_of_files == 1:
            target_file = target_files_list[0]
            logger.info(
                f"SUCCESS: Found exactly one vector spatial dataset file in "
                f"{target_directory}: {target_file}"
            )
            return target_file

        elif number_of_files > 1:
            # Prefer the file in the root directory whose stem matches the dir name.
            target_dir_name = target_directory.name
            root_files = [f for f in target_files_list if f.parent == target_directory]
            matching_file = next(
                (f for f in root_files if target_dir_name in f.stem), None
            )
            if matching_file:
                logger.info(f"Found primary file: {matching_file}")
                return matching_file
            elif root_files:
                logger.info(f"Using first root file: {root_files[0]}")
                return root_files[0]
            else:
                logger.error(
                    f"Found more than one vector spatial dataset file in "
                    f"{target_directory}: {target_files_list}"
                )
                return False

        else:
            logger.error(
                f"There were problems finding a vector spatial dataset in "
                f"{target_directory}, files list: {files_in_directory}"
            )
            return False

    except Exception as e:
        logger.error(
            f"There was an error retrieving a vector spatial dataset in "
            f"{target_directory}: {e}"
        )
        return False


def fix_gadm_null_foreign_keys(source_gadm_dataset, columns_to_fix=GADM_MODEL_FIELD_NAMES):
    """
    GADM stores 'NA' as a literal string where None is meant. Iterate every
    layer, replace 'NA' with NaN in the named columns, and write a fixed GPKG.
    """
    logger.info(
        "GADM dataset has 'NA' as string for several fields. Fixing via per-layer rewrite."
    )

    try:
        new_gpkg_stem = f"{source_gadm_dataset.stem}_fixed"
        new_gpkg_path = settings.VECTOR_SPATIAL_DATA_SUBDIRECTORY / new_gpkg_stem
        new_gpkg_path.mkdir(parents=True, exist_ok=True)
        new_gpkg_name = f"{new_gpkg_stem}{source_gadm_dataset.suffix}"
        target_gpkg = new_gpkg_path / new_gpkg_name
        logger.info(f"New file and path: {target_gpkg}")

        gadm_layers = gpd.list_layers(source_gadm_dataset)["name"].tolist()

        for g in gadm_layers:
            logger.info(f"Working on layer: {g}")
            gdf = gpd.read_file(source_gadm_dataset, layer=g)
            logger.info(f"Layer {g} has columns: {list(gdf)}")

            for c in columns_to_fix:
                if c in list(gdf):
                    logger.info(f"Layer {g} has a column that needs to be fixed: {c}")
                    gdf[c] = gdf[c].replace("NA", np.nan)
                    result = gdf.to_file(target_gpkg, driver="GPKG", layer=g)
                    logger.info(f"Layer {g} to {target_gpkg}: {result}")

        return target_gpkg

    except Exception as e:
        logger.error(f"Exception trying to replace nulls in layer: {e}")
        return source_gadm_dataset
