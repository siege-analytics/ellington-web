"""
GST-specific file helpers that don't have direct siege_utilities equivalents.

Functions in this module either have GST-specific behavior (unzip-to-own-dir
naming convention; dispatcher-coupled hash checks) or are wrappers around
behavior that may eventually port up to SU (see siege_utilities#515). For
generic file ops (download_file, ensure_path_exists, calculate_file_hash)
use siege_utilities.files.* directly.
"""

import logging
import pathlib
import subprocess
import zipfile

from siege_utilities.files.hashing import calculate_file_hash

logger = logging.getLogger("django")


def run_subprocess(command_list):
    """Run a shell command list; raises on non-zero exit code."""
    p = subprocess.Popen(
        command_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
    )
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        logger.error("SUBPROCESS FAILED!")
        raise Exception("Subprocess failed with error: {}".format(stderr))


def generate_local_path_from_url(url, directory_path, as_string=True):
    """Concatenate the filename from a URL onto a directory path."""
    try:
        remote_file_name = url.split("/")[-1]
        directory_path = pathlib.Path(directory_path)
        new_path = directory_path / remote_file_name
        if as_string is True:
            new_path = str(new_path)
        logger.debug(f"Successfully generated path {new_path}, as_string={as_string}")
        return new_path
    except Exception as e:
        logger.error(f"Exception while generating local path: {e}")
        return False


def unzip_file_to_its_own_directory(path_to_zipfile, new_dir_name=None, new_dir_parent=None):
    """Unzip a file into a sibling directory named after the zip's stem."""
    try:
        path_to_zipfile = pathlib.Path(path_to_zipfile)
        frtz = zipfile.ZipFile(path_to_zipfile)
        if new_dir_name is None:
            new_dir_name = path_to_zipfile.stem
        if new_dir_parent is None:
            new_dir_parent = path_to_zipfile.parent
        target_dir_for_unzipped_files = new_dir_parent / new_dir_name
        pathlib.Path(target_dir_for_unzipped_files).mkdir(parents=True, exist_ok=True)
        frtz.extractall(path=target_dir_for_unzipped_files)
        logger.info(
            f"Just unzipped: \n {path_to_zipfile} \n To: {target_dir_for_unzipped_files}"
        )
        return target_dir_for_unzipped_files
    except Exception as e:
        logger.error(f"There was an error: {e}")
        return False


def add_hash_entry_to_dispatcher(target_file, confirmation_dict):
    """Add or update the SHA256 hash entry for a file in a dispatcher dict."""
    try:
        target_file_path = pathlib.Path(target_file)
        file_name_and_extension = str(target_file_path.name)
        new_hash_for_file = calculate_file_hash(target_file_path)
        confirmation_dict[file_name_and_extension] = new_hash_for_file
        logger.info(
            f"SUCCESS: Set hash for {file_name_and_extension} to {new_hash_for_file}"
        )
        return True
    except Exception as e:
        logger.error(f"FAILURE: Exception while updating hash dispatcher: {e}")
        return False


def check_for_hash_in_dispatcher(target_file_path, testing_hash_string, confirmation_dict):
    """Check whether a file's hash matches the dispatcher's known-good hash."""
    try:
        target_file_path = pathlib.Path(target_file_path)
        file_name_and_extension = str(target_file_path.name)
        if file_name_and_extension in confirmation_dict:
            known_good_hash = confirmation_dict[file_name_and_extension]
            if testing_hash_string == known_good_hash:
                logger.info(
                    f"SUCCESS: hash for {target_file_path} matches dispatcher entry"
                )
                return True
        else:
            logger.error(
                f"FAILURE: No entry for {file_name_and_extension} in dispatcher"
            )
            return False
    except Exception as e:
        logger.error(f"FAILURE: Exception checking dispatcher hash: {e}")
        return False
