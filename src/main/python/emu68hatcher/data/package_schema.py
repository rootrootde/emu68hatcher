"""
pydantic models for package YAML definitions

this replaces the legacy CSV-based package system with a cleaner YAML format.
each package is defined in its own YAML file with clear structure.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """package download source types"""

    AMINET = "aminet"
    GITHUB = "github"
    WEB = "web"
    LOCAL = "local"


class ScriptAction(str, Enum):
    """script modification actions"""

    APPEND = "append"
    PREPEND = "prepend"
    INJECT = "inject"  # inject at specific marker


class DownloadInfo(BaseModel):
    """download configuration for a package"""

    source: SourceType

    # for aminet/web sources
    path: Optional[str] = None  # aminet path like "util/libs/mui38usr.lha"
    url: Optional[str] = None  # full URL for web downloads
    backup_url: Optional[str] = None  # fallback URL if primary fails

    # for Aminet search-based packages
    search: Optional[str] = None  # search term for Aminet
    exclude: Optional[str] = None  # exclusion term for search results

    # for GitHub sources
    repo: Optional[str] = None  # format: "owner/repo"
    asset_pattern: Optional[str] = None  # regex to match release asset
    version: Optional[str] = None  # tag/version to download (None = latest)

    # verification
    hash: Optional[str] = None  # MD5 hash for verification
    filename: Optional[str] = None  # expected filename after download

    # nested archives (e.g., LHA inside ZIP)
    nested_archive: Optional[str] = None


class InstallRule(BaseModel):
    """rule for installing files from an extracted package"""

    # source pattern (glob) within extracted archive
    source: str = Field(alias="from")

    # destination path on Amiga filesystem (relative to System:)
    dest: str = Field(alias="to")

    # options
    recursive: bool = False
    uncompress_z: bool = False  # for Workbench 3.2.x .Z files
    rename: Optional[str] = None  # rename file on install

    class Config:
        populate_by_name = True


class ScriptModification(BaseModel):
    """script modification to apply during installation"""

    target: str  # script path like "S/User-Startup"
    action: ScriptAction = ScriptAction.APPEND
    content: str  # content to add to script
    marker: Optional[str] = None  # for inject action, marker to find


class Package(BaseModel):
    """complete package definition"""

    # identity
    name: str  # internal identifier (lowercase, no spaces)
    friendly_name: str  # display name in UI
    group: str  # category group (System, Applications, Internet, etc.)
    description: str  # tooltip description

    # compatibility
    versions: list[str] = Field(default_factory=list)  # kickstart versions

    # installation behavior
    mandatory: bool = False  # must be installed
    default: bool = False  # pre-selected in UI

    # download configuration (None for local-only packages)
    download: Optional[DownloadInfo] = None

    # installation rules
    install: list[InstallRule] = Field(default_factory=list)

    # script modifications
    scripts: list[ScriptModification] = Field(default_factory=list)

    def matches_version(self, kickstart_version: str) -> bool:
        """check if package is compatible with a Kickstart version"""
        if not self.versions:
            return True  # no version restriction
        return kickstart_version in self.versions


# groups for organizing packages in UI
PACKAGE_GROUPS = [
    "System",
    "Applications",
    "Utilities",
    "Internet",
    "Development",
    "Games",
    "Locale",
]


# =============================================================================
# ADF Extraction Rules
# =============================================================================


class ADFRule(BaseModel):
    """rule for extracting files from an ADF disk image"""

    # source ADF identifier (e.g., "Workbench3_1", "Storage3_2")
    adf: str

    # source pattern within ADF (glob)
    source: str = Field(alias="from")

    # destination path on Amiga filesystem
    dest: str = Field(alias="to")

    # target drive (System -> SDH0, Work -> SDH1)
    drive: str = "System"

    # options
    recursive: bool = False
    rename: Optional[str] = None

    # ordering
    sequence: int = 0

    # optional package association (if set, only extract if package enabled)
    package: Optional[str] = None

    # mandatory flag - if False and package is set, only include if package enabled
    mandatory: bool = False

    # icon set filter (if set, only include for this icon set)
    icon_set: Optional[str] = None

    class Config:
        populate_by_name = True
