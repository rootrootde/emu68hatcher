"""
file hashing utilities for Emu68 Hatcher

provides functions for calculating and verifying file hashes.
"""

import hashlib
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class HashAlgorithm(str, Enum):
    """supported hash algorithms"""

    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    CRC32 = "crc32"


def calculate_hash(
    path: Path,
    algorithm: HashAlgorithm = HashAlgorithm.MD5,
    chunk_size: int = 65536,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """
    calculate hash of a file"""
    if algorithm == HashAlgorithm.CRC32:
        return _calculate_crc32(path, chunk_size, progress_callback)

    hasher = hashlib.new(algorithm.value)
    file_size = path.stat().st_size
    bytes_read = 0

    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
            bytes_read += len(chunk)
            if progress_callback:
                progress_callback(bytes_read, file_size)

    return hasher.hexdigest()


def _calculate_crc32(
    path: Path,
    chunk_size: int = 65536,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """calculate CRC32 checksum"""
    import zlib

    crc = 0
    file_size = path.stat().st_size
    bytes_read = 0

    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            crc = zlib.crc32(chunk, crc)
            bytes_read += len(chunk)
            if progress_callback:
                progress_callback(bytes_read, file_size)

    return format(crc & 0xFFFFFFFF, "08x")


def verify_hash(
    path: Path,
    expected_hash: str,
    algorithm: Optional[HashAlgorithm] = None,
) -> bool:
    """
    verify a file's hash matches expected value"""
    if algorithm is None:
        algorithm = detect_hash_algorithm(expected_hash)

    if algorithm is None:
        return False

    actual_hash = calculate_hash(path, algorithm)
    return actual_hash.lower() == expected_hash.lower()


def detect_hash_algorithm(hash_string: str) -> Optional[HashAlgorithm]:
    """
    detect hash algorithm from hash string length"""
    length = len(hash_string)

    length_map = {
        8: HashAlgorithm.CRC32,
        32: HashAlgorithm.MD5,
        40: HashAlgorithm.SHA1,
        64: HashAlgorithm.SHA256,
    }

    return length_map.get(length)
