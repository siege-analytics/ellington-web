"""
Dataset caching utilities. The cache-manifest read/write logic is
GST-specific; the underlying file-hashing is siege_utilities.files.hashing.
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from siege_utilities.files.hashing import calculate_file_hash

logger = logging.getLogger(__name__)


def get_cache_manifest_path(data_dir: Path) -> Path:
    return data_dir / ".cache_manifest.json"


def load_cache_manifest(data_dir: Path) -> Dict[str, Any]:
    """Read the per-dataset cache manifest; return {} when missing or corrupt."""
    manifest_path = get_cache_manifest_path(data_dir)
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Cache manifest corrupted, ignoring: {e}")
        return {}


def save_cache_manifest(data_dir: Path, manifest_data: Dict[str, Any]):
    manifest_path = get_cache_manifest_path(data_dir)
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f, indent=2)
    logger.info(f"Cache manifest saved: {manifest_path}")


def check_if_cleaning_needed(source_file: Path, data_dir: Path):
    """
    Fast metadata check (mtime+size) before hashing. Returns
    (needs_cleaning, cached_clean_path).
    """
    manifest = load_cache_manifest(data_dir)
    if not manifest:
        logger.info("No cache manifest - cleaning needed")
        return True, None

    current_mtime = source_file.stat().st_mtime
    current_size = source_file.stat().st_size
    cached_mtime = manifest.get("source_mtime")
    cached_size = manifest.get("source_size")
    cached_path_str = manifest.get("cleaned_path")

    if cached_mtime == current_mtime and cached_size == current_size:
        if cached_path_str:
            cleaned_path = Path(cached_path_str)
            if cleaned_path.exists():
                logger.info(f"Cache HIT (mtime+size match) - using: {cleaned_path.name}")
                return False, cleaned_path
        logger.info("Metadata matches but cleaned file missing - re-cleaning")
        return True, None

    # Metadata changed; fall back to hash comparison.
    logger.info("File metadata changed - verifying with hash...")
    logger.info(f"  Size: {cached_size} -> {current_size}")
    logger.info(f"  mtime: {cached_mtime} -> {current_mtime}")

    current_hash = calculate_file_hash(source_file)
    cached_hash = manifest.get("source_hash")

    if cached_hash == current_hash:
        logger.info("Hash matches despite metadata change - using cache")
        manifest["source_mtime"] = current_mtime
        manifest["source_size"] = current_size
        save_cache_manifest(data_dir, manifest)
        if cached_path_str:
            return False, Path(cached_path_str)

    logger.info("Hash mismatch - re-cleaning needed")
    return True, None


def update_cache_after_cleaning(source_file: Path, cleaned_file: Path, data_dir: Path):
    """Write the post-cleaning manifest with hashes + metadata for both files."""
    source_stat = source_file.stat()
    cleaned_stat = cleaned_file.stat()

    logger.info("Calculating hashes for cache manifest...")
    source_hash = calculate_file_hash(source_file)
    cleaned_hash = calculate_file_hash(cleaned_file)

    manifest = {
        "source_hash": source_hash,
        "source_file": str(source_file),
        "source_mtime": source_stat.st_mtime,
        "source_size": source_stat.st_size,
        "cleaned_hash": cleaned_hash,
        "cleaned_path": str(cleaned_file),
        "cleaned_mtime": cleaned_stat.st_mtime,
        "cleaned_size": cleaned_stat.st_size,
        "timestamp": datetime.datetime.now().isoformat(),
        "note": "Fast caching: mtime+size first, hash only on change.",
    }

    save_cache_manifest(data_dir, manifest)
    logger.info("Cache updated - future runs check mtime+size first")


def check_if_download_needed(
    url: str, target_file: Path, expected_hash: Optional[str] = None
) -> bool:
    """Skip download if target exists with the expected hash (or just exists)."""
    if not target_file.exists():
        logger.info("File doesn't exist - download needed")
        return True

    if expected_hash:
        actual_hash = calculate_file_hash(target_file)
        if actual_hash == expected_hash:
            logger.info("File exists with correct hash - skipping download")
            return False
        logger.info("File exists but hash mismatch - re-downloading")
        return True

    logger.info("File exists, no hash to verify - using existing file")
    return False
