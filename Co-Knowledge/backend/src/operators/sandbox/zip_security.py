"""
Zip security utilities for RAG Knowledge Base Service.

This module provides security functions to detect and prevent zip bomb attacks
by validating zip files before extraction.
"""
import os
import zipfile
from pathlib import Path
from typing import Tuple, Optional

from infrastructure.logging.logutil import log

# Zip Boom detection defaults
DEFAULT_MAX_FILE_COUNT = 100000
DEFAULT_MAX_TOTAL_SIZE_GB = 10
DEFAULT_MAX_COMPRESS_RATIO = 1000
G_TO_BYTE_RATE = 1024 * 1024 * 1024


def _get_max_file_count() -> int:
    """Get max file count from environment or use default."""
    try:
        return int(os.environ.get('MAX_FILE_NUM', DEFAULT_MAX_FILE_COUNT))
    except (ValueError, TypeError):
        return DEFAULT_MAX_FILE_COUNT


def _get_max_total_size() -> int:
    """Get max total uncompressed size in bytes from environment or use default."""
    try:
        return int(os.environ.get('MAX_TOTAL_UNCOMP_GB', DEFAULT_MAX_TOTAL_SIZE_GB)) * G_TO_BYTE_RATE
    except (ValueError, TypeError):
        return DEFAULT_MAX_TOTAL_SIZE_GB * G_TO_BYTE_RATE


def _get_max_compress_ratio() -> int:
    """Get max single file compression ratio from environment or use default."""
    try:
        return int(os.environ.get('MAX_SINGLE_COMP_RATIO', DEFAULT_MAX_COMPRESS_RATIO))
    except (ValueError, TypeError):
        return DEFAULT_MAX_COMPRESS_RATIO


def check_zip_bomb(zip_path: Path, max_file_count: Optional[int] = None,
                   max_total_size: Optional[int] = None,
                   max_compress_ratio: Optional[int] = None) -> Tuple[bool, str]:
    """
    Check if a zip file is a potential zip bomb.

    This function checks:
    1. Total number of files (limit: 30000 by default)
    2. Total uncompressed size (limit: 10GB by default)
    3. Compression ratio for individual files (limit: 1000:1 by default)

    Args:
        zip_path: Path to the zip file
        max_file_count: Maximum number of files allowed (default: 30000)
        max_total_size: Maximum total uncompressed size in bytes (default: 10GB)
        max_compress_ratio: Maximum compression ratio (default: 1000)

    Returns:
        Tuple of (is_bomb: bool, reason: str or None)
    """
    if max_file_count is None:
        max_file_count = _get_max_file_count()
    if max_total_size is None:
        max_total_size = _get_max_total_size()
    if max_compress_ratio is None:
        max_compress_ratio = _get_max_compress_ratio()

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            total_file_count = 0
            total_uncompressed_size = 0

            for member in zip_ref.namelist():
                if member.endswith('/'):
                    continue

                total_file_count += 1
                if total_file_count > max_file_count:
                    log.warning(f"[ZipSecurity] File count {total_file_count} exceeds limit {max_file_count}")
                    return True, f"File count {total_file_count} exceeds limit {max_file_count}"

                info = zip_ref.getinfo(member)
                total_uncompressed_size += info.file_size

                if total_uncompressed_size > max_total_size:
                    log.warning(f"[ZipSecurity] Total uncompressed size {total_uncompressed_size} exceeds limit {max_total_size}")
                    return True, f"Total uncompressed size {total_uncompressed_size} exceeds limit {max_total_size}"

                # Check individual compression ratio
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > max_compress_ratio:
                        log.warning(f"[ZipSecurity] Compression ratio {ratio:.2f} for {member} exceeds limit {max_compress_ratio}")
                        return True, f"Compression ratio {ratio:.2f} for {member} exceeds limit {max_compress_ratio}"

            log.info(f"[ZipSecurity] Zip file validation passed: {total_file_count} files, {total_uncompressed_size} bytes total")
            return False, None

    except zipfile.BadZipFile as e:
        log.warn(f"[ZipSecurity] Invalid zip file {zip_path}: {e}")
        return True, f"Invalid zip file: {e}"
    except Exception as e:
        log.error(f"[ZipSecurity] Error checking zip file {zip_path}: {e}")
        return True, f"Error checking zip file: {e}"
