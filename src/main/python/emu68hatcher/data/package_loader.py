"""YAML package loader - loads packages/*.yaml definitions adn adf_rules.yaml extraction rules"""

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from emu68hatcher.data.package_schema import PACKAGE_GROUPS, ADFRule, Bundle, Package

logger = logging.getLogger(__name__)

_PACKAGES_DIR = Path(__file__).parent / "packages"

# bundled Amiga files + scripts
LOCAL_PACKAGES_DIR = Path(__file__).parent / "local_packages"


def get_local_packages_dir() -> Path:
    return LOCAL_PACKAGES_DIR


_ADF_RULES_PATH = Path(__file__).parent / "reference" / "adf_rules.yaml"
_BUNDLES_PATH = Path(__file__).parent / "reference" / "bundles.yaml"

_adf_rules_cache: dict[str, list[ADFRule]] | None = None
_packages_cache: list[Package] | None = None
_bundles_cache: dict[str, Bundle] | None = None


def invalidate_package_cache() -> None:
    """clear all package data caches (used by tests when reference paths change)"""
    global _packages_cache, _bundles_cache, _adf_rules_cache
    _packages_cache = None
    _bundles_cache = None
    _adf_rules_cache = None


def load_package(yaml_path: Path) -> Package | None:
    """load a single package from a YAML file"""
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return None

        return Package.model_validate(data)

    except (yaml.YAMLError, ValidationError) as e:
        logger.warning(f"Error loading {yaml_path}: {e}")
        return None


def load_all_packages() -> list[Package]:
    """load all packages from the packages/ directory (cached, returns a copy)"""
    global _packages_cache

    if _packages_cache is None:
        packages: list[Package] = []
        if _PACKAGES_DIR.exists():
            for yaml_file in sorted(_PACKAGES_DIR.glob("*.yaml")):
                pkg = load_package(yaml_file)
                if pkg:
                    packages.append(pkg)
        _packages_cache = packages

    # return a copy so callers can't mutate the shared cache
    return list(_packages_cache)


def get_packages_for_version(
    kickstart_version: str, emu68_version: str | None = None
) -> list[Package]:
    """get all packages compatible with a Kickstart version (and optionally an Emu68 release)"""
    packages = load_all_packages()
    compatible = [
        p
        for p in packages
        if p.matches_version(kickstart_version) and p.matches_emu68(emu68_version)
    ]

    # sort by group order, then by name
    def sort_key(pkg: Package) -> tuple:
        try:
            group_idx = PACKAGE_GROUPS.index(pkg.group)
        except ValueError:
            group_idx = len(PACKAGE_GROUPS)  # unknown groups at end
        return (group_idx, pkg.name)

    return sorted(compatible, key=sort_key)


def get_mandatory_packages(
    kickstart_version: str, emu68_version: str | None = None
) -> list[Package]:
    """packages that must be installed for a version (System group + anything mandatory=True)"""
    packages = get_packages_for_version(kickstart_version, emu68_version)
    return [p for p in packages if p.mandatory or p.group == "System"]


def get_default_packages(kickstart_version: str, emu68_version: str | None = None) -> list[Package]:
    """get packages enabled by default for a version"""
    return [p for p in get_packages_for_version(kickstart_version, emu68_version) if p.default]


def get_package_by_name(name: str) -> Package | None:
    """get a specific package by name"""
    for pkg in load_all_packages():
        if pkg.name == name:
            return pkg
    return None


###########
# budnles #
###########


def load_all_bundles() -> dict[str, Bundle]:
    """load bundle definitions from reference/bundles.yaml, validate against packages"""
    global _bundles_cache

    if _bundles_cache is not None:
        return _bundles_cache

    bundles: dict[str, Bundle] = {}

    if _BUNDLES_PATH.exists():
        try:
            with open(_BUNDLES_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for bundle_id, fields in data.items():
                try:
                    bundles[bundle_id] = Bundle.model_validate({"id": bundle_id, **fields})
                except ValidationError as e:
                    logger.warning(f"Error parsing bundle {bundle_id!r}: {e}")
        except yaml.YAMLError as e:
            logger.warning(f"Error loading bundles.yaml: {e}")

    # validate: every package.bundle reference resolves
    referenced = {p.bundle for p in load_all_packages() if p.bundle}
    missing = referenced - bundles.keys()
    if missing:
        raise ValueError(
            f"packages reference undefined bundle ids: {sorted(missing)}. "
            f"add them to bundles.yaml or fix the `bundle:` field."
        )

    _bundles_cache = bundles
    return _bundles_cache


def get_bundles_for_version(kickstart_version: str) -> list[Bundle]:
    """bundles with at least one member compatible with a Kickstart version"""
    bundles = load_all_bundles()
    compatible = {
        p.bundle
        for p in get_packages_for_version(kickstart_version)
        if p.bundle and not p.mandatory
    }

    def sort_key(b: Bundle) -> tuple:
        try:
            group_idx = PACKAGE_GROUPS.index(b.group)
        except ValueError:
            group_idx = len(PACKAGE_GROUPS)
        return (group_idx, b.display_name)

    return sorted((bundles[bid] for bid in compatible), key=sort_key)


def get_bundle_members(bundle_id: str, kickstart_version: str) -> list[Package]:
    """member packages of a bundle compatible with the given Kickstart version"""
    return [
        p
        for p in get_packages_for_version(kickstart_version)
        if p.bundle == bundle_id and not p.mandatory
    ]


#####################
# ADF rules loading #
#####################


def load_adf_rules() -> dict[str, list[ADFRule]]:
    """load all ADF extraction rules from adf_rules.yaml."""
    global _adf_rules_cache

    if _adf_rules_cache is not None:
        return _adf_rules_cache

    _adf_rules_cache = {}

    if not _ADF_RULES_PATH.exists():
        return _adf_rules_cache

    try:
        with open(_ADF_RULES_PATH, encoding="utf-8") as f:
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
    """get ADF extraction rules for a specific Kickstart version"""
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
    """get ADF rules filtered by enabled packages and icon set"""
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
                # optional package taht user enabled
                filtered.append(rule)
            # else: optional package not enabled, skip
        else:
            # no package association - always include
            filtered.append(rule)

    # sort by sequence
    return sorted(filtered, key=lambda r: r.sequence)
