"""file hashing utils"""

import hashlib
from collections.abc import Callable
from enum import Enum
from pathlib import Path


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
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    """calculate hash of a file"""
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


def verify_hash(
    path: Path,
    expected: str,
    algorithm: HashAlgorithm = HashAlgorithm.MD5,
) -> bool:
    """case-insensitive check; return False if path missing / hash mismatch"""
    if not path.exists():
        return False
    return calculate_hash(path, algorithm).lower() == expected.lower()


def _calculate_crc32(
    path: Path,
    chunk_size: int = 65536,
    progress_callback: Callable[[int, int], None] | None = None,
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
