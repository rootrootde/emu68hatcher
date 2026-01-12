"""tests for hashing utilities and ROM identification"""

import hashlib
from pathlib import Path

import pytest


class TestHashFunctions:
    """tests for hash computation functions"""

    def test_compute_md5(self, temp_dir):
        """test MD5 hash computation"""
        from emu68hatcher.utils.hashing import calculate_hash, HashAlgorithm

        test_file = temp_dir / "test.bin"
        test_file.write_bytes(b"Hello, World!")

        hash_result = calculate_hash(test_file, HashAlgorithm.MD5)
        expected = hashlib.md5(b"Hello, World!").hexdigest()

        assert hash_result == expected

    def test_compute_sha1(self, temp_dir):
        """test SHA1 hash computation"""
        from emu68hatcher.utils.hashing import calculate_hash, HashAlgorithm

        test_file = temp_dir / "test.bin"
        test_file.write_bytes(b"Test data for SHA1")

        hash_result = calculate_hash(test_file, HashAlgorithm.SHA1)
        expected = hashlib.sha1(b"Test data for SHA1").hexdigest()

        assert hash_result == expected

    def test_compute_sha256(self, temp_dir):
        """test SHA256 hash computation"""
        from emu68hatcher.utils.hashing import calculate_hash, HashAlgorithm

        test_file = temp_dir / "test.bin"
        test_file.write_bytes(b"Test data for SHA256")

        hash_result = calculate_hash(test_file, HashAlgorithm.SHA256)
        expected = hashlib.sha256(b"Test data for SHA256").hexdigest()

        assert hash_result == expected

    def test_compute_crc32(self, temp_dir):
        """test CRC32 computation"""
        from emu68hatcher.utils.hashing import calculate_hash, HashAlgorithm

        test_file = temp_dir / "test.bin"
        test_file.write_bytes(b"CRC32 test data")

        crc = calculate_hash(test_file, HashAlgorithm.CRC32)
        assert isinstance(crc, str)
        assert len(crc) == 8  # CRC32 is 8 hex chars

    def test_hash_nonexistent_file(self, temp_dir):
        """test hashing a file that doesn't exist"""
        from emu68hatcher.utils.hashing import calculate_hash, HashAlgorithm

        nonexistent = temp_dir / "nonexistent.bin"

        with pytest.raises(FileNotFoundError):
            calculate_hash(nonexistent, HashAlgorithm.MD5)


class TestVerifyHash:
    """tests for hash verification"""

    def test_verify_hash_success(self, temp_dir):
        """test successful hash verification"""
        from emu68hatcher.utils.hashing import verify_hash, HashAlgorithm

        test_file = temp_dir / "test.bin"
        content = b"Verification test"
        test_file.write_bytes(content)

        expected_hash = hashlib.md5(content).hexdigest()
        assert verify_hash(test_file, expected_hash, HashAlgorithm.MD5) is True

    def test_verify_hash_failure(self, temp_dir):
        """test failed hash verification"""
        from emu68hatcher.utils.hashing import verify_hash, HashAlgorithm

        test_file = temp_dir / "test.bin"
        test_file.write_bytes(b"Verification test")

        wrong_hash = "0" * 32
        assert verify_hash(test_file, wrong_hash, HashAlgorithm.MD5) is False

    def test_verify_hash_auto_detect(self, temp_dir):
        """test hash verification with auto-detected algorithm"""
        from emu68hatcher.utils.hashing import verify_hash

        test_file = temp_dir / "test.bin"
        content = b"Auto detect test"
        test_file.write_bytes(content)

        # 32 chars = MD5
        md5_hash = hashlib.md5(content).hexdigest()
        assert verify_hash(test_file, md5_hash) is True


class TestKickstartIdentification:
    """tests for Kickstart ROM identification"""

    def test_kickstart_checksums_exist(self):
        """test that Kickstart checksum database exists"""
        from emu68hatcher.data.rom_detection import KICKSTART_CHECKSUMS

        assert len(KICKSTART_CHECKSUMS) > 0

    def test_identify_kickstart_unknown(self, temp_dir):
        """test identifying unknown ROM file"""
        from emu68hatcher.data.rom_detection import identify_kickstart

        # create a fake ROM file (512KB)
        fake_rom = temp_dir / "fake.rom"
        fake_rom.write_bytes(b"\x00" * 524288)

        result = identify_kickstart(fake_rom)
        assert result is None  # unknown ROM

    def test_identify_kickstart_wrong_size(self, temp_dir):
        """test identifying file with wrong size"""
        from emu68hatcher.data.rom_detection import identify_kickstart

        # create file with wrong size
        wrong_size = temp_dir / "wrong.rom"
        wrong_size.write_bytes(b"\x00" * 1000)

        result = identify_kickstart(wrong_size)
        assert result is None

    def test_known_checksums_format(self):
        """test that known checksums have correct format"""
        from emu68hatcher.data.rom_detection import KICKSTART_CHECKSUMS

        for checksum, info in KICKSTART_CHECKSUMS.items():
            # checksum should be 32 hex chars (MD5)
            assert len(checksum) == 32
            assert all(c in "0123456789abcdef" for c in checksum.lower())

            # info should have version
            assert "version" in info


class TestDetectHashAlgorithm:
    """tests for hash algorithm detection"""

    def test_detect_md5_length(self):
        """test detecting MD5 from 32-char string"""
        from emu68hatcher.utils.hashing import detect_hash_algorithm, HashAlgorithm

        result = detect_hash_algorithm("0" * 32)
        assert result == HashAlgorithm.MD5

    def test_detect_sha1_length(self):
        """test detecting SHA1 from 40-char string"""
        from emu68hatcher.utils.hashing import detect_hash_algorithm, HashAlgorithm

        result = detect_hash_algorithm("0" * 40)
        assert result == HashAlgorithm.SHA1

    def test_detect_sha256_length(self):
        """test detecting SHA256 from 64-char string"""
        from emu68hatcher.utils.hashing import detect_hash_algorithm, HashAlgorithm

        result = detect_hash_algorithm("0" * 64)
        assert result == HashAlgorithm.SHA256

    def test_detect_crc32_length(self):
        """test detecting CRC32 from 8-char string"""
        from emu68hatcher.utils.hashing import detect_hash_algorithm, HashAlgorithm

        result = detect_hash_algorithm("0" * 8)
        assert result == HashAlgorithm.CRC32

    def test_detect_unknown_length(self):
        """test unknown hash length returns None"""
        from emu68hatcher.utils.hashing import detect_hash_algorithm

        result = detect_hash_algorithm("0" * 16)  # 16 chars is not standard
        assert result is None
