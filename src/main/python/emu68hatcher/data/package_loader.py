"""
YAML package loader

loads package definitions from individual YAML files in the packages/ directory.
also loads ADF extraction rules from adf_rules.yaml.
"""

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from emu68hatcher.data.package_schema import Package, PACKAGE_GROUPS, ADFRule

logger = logging.getLogger(__name__)

# package definitions directory
_PACKAGES_DIR = Path(__file__).parent / "packages"

# local packages directory (bundled Amiga files and scripts)
LOCAL_PACKAGES_DIR = Path(__file__).parent / "local_packages"


def get_local_packages_dir() -> Path:
    """get the local packages directory"""
    return LOCAL_PACKAGES_DIR


# ADF rules file
_ADF_RULES_PATH = Path(__file__).parent / "reference" / "adf_rules.yaml"

# caches
_adf_rules_cache: Optional[dict[str, list[ADFRule]]] = None
_packages_cache: Optional[list[Package]] = None


def invalidate_package_cache() -> None:
    """clear the cached package list. call after changing _PACKAGES_DIR in tests"""
    global _packages_cache
    _packages_cache = None


def get_packages_dir() -> Path:
    """get the directory containing package YAML files"""
    return _PACKAGES_DIR


def load_package(yaml_path: Path) -> Optional[Package]:
    """
    load a single package from a YAML file"""
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return None

        return Package.model_validate(data)

    except (yaml.YAMLError, ValidationError) as e:
        logger.warning(f"Error loading {yaml_path}: {e}")
        return None


def load_all_packages() -> list[Package]:
    """
    load all packages from the packages/ directory

    returns cached results on subsequent calls."""
    global _packages_cache

    if _packages_cache is not None:
        return _packages_cache

    packages = []

    if not _PACKAGES_DIR.exists():
        return packages

    for yaml_file in sorted(_PACKAGES_DIR.glob("*.yaml")):
        pkg = load_package(yaml_file)
        if pkg:
            packages.append(pkg)

    _packages_cache = packages
    return _packages_cache


def get_packages_for_version(kickstart_version: str) -> list[Package]:
    """
    get all packages compatible with a Kickstart version"""
    packages = load_all_packages()
    compatible = [p for p in packages if p.matches_version(kickstart_version)]

    # sort by group order, then by name
    def sort_key(pkg: Package) -> tuple:
        try:
            group_idx = PACKAGE_GROUPS.index(pkg.group)
        except ValueError:
            group_idx = len(PACKAGE_GROUPS)  # unknown groups at end
        return (group_idx, pkg.name)

    return sorted(compatible, key=sort_key)


def get_mandatory_packages(kickstart_version: str) -> list[Package]:
    """
    get packages that must be installed for a version

    this includes:
    - all packages in the "System" group (always mandatory)
    - any package with mandatory=True
    """
    packages = get_packages_for_version(kickstart_version)
    return [
        p for p in packages
        if p.mandatory or p.group == "System"
    ]


def get_default_packages(kickstart_version: str) -> list[Package]:
    """get packages enabled by default for a version"""
    return [
        p for p in get_packages_for_version(kickstart_version) if p.default
    ]


def get_package_by_name(name: str) -> Optional[Package]:
    """
    get a specific package by name"""
    for pkg in load_all_packages():
        if pkg.name == name:
            return pkg
    return None


def get_groups(kickstart_version: str = "") -> list[str]:
    """
    get all package groups that have packages"""
    if kickstart_version:
        packages = get_packages_for_version(kickstart_version)
    else:
        packages = load_all_packages()

    groups = set(p.group for p in packages)
    # return in defined order
    return [g for g in PACKAGE_GROUPS if g in groups]


# =============================================================================
# ADF Rules Loading
# =============================================================================


def load_adf_rules() -> dict[str, list[ADFRule]]:
    """
    load all ADF extraction rules from adf_rules.yaml."""
    global _adf_rules_cache

    if _adf_rules_cache is not None:
        return _adf_rules_cache

    _adf_rules_cache = {}

    if not _ADF_RULES_PATH.exists():
        return _adf_rules_cache

    try:
        with open(_ADF_RULES_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return _adf_rules_cache

        for version, rules_data in data.items():
            rules = []
            for rule_dict in rules_data:
                try:
                    rule = ADFRule.model_validate(rule_dict)
                    rules.append(rule)
                except ValidationError as e:
                    logger.warning(f"Error parsing ADF rule for {version}: {e}")
            _adf_rules_cache[str(version)] = rules

    except yaml.YAMLError as e:
        logger.warning(f"Error loading ADF rules: {e}")

    return _adf_rules_cache


def get_adf_rules_for_version(kickstart_version: str) -> list[ADFRule]:
    """
    get ADF extraction rules for a specific Kickstart version"""
    all_rules = load_adf_rules()

    # try exact version match first
    if kickstart_version in all_rules:
        return all_rules[kickstart_version]

    # fall back to major.minor version (e.g., "3.2.3" -> "3.2")
    parts = kickstart_version.split(".")
    if len(parts) >= 2:
        base_version = f"{parts[0]}.{parts[1]}"
        if base_version in all_rules:
            return all_rules[base_version]

    return []


def get_filtered_adf_rules(
    kickstart_version: str,
    enabled_packages: set[str],
    icon_set: str = "Standard",
) -> list[ADFRule]:
    """
    get ADF rules filtered by enabled packages and icon set"""
    rules = get_adf_rules_for_version(kickstart_version)
    filtered = []

    for rule in rules:
        # check icon set filter
        if rule.icon_set and rule.icon_set.lower() != icon_set.lower():
            continue

        # check package association
        if rule.package:
            if rule.mandatory:
                # mandatory package - always include
                filtered.append(rule)
            elif rule.package.lower() in enabled_packages:
                # optional package that user enabled
                filtered.append(rule)
            # else: optional package not enabled, skip
        else:
            # no package association - always include
            filtered.append(rule)

    # sort by sequence
    return sorted(filtered, key=lambda r: r.sequence)
