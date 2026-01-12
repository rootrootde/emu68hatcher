"""script injection for Amiga startup scripts

this module injects modifications into existing Amiga scripts (extracted from ADFs)
rather than generating complete scripts from scratch. this preserves the original
amigaOS initialization logic while adding our customizations.

actions:
- add: Append content to end of script
- InjectBefore: Insert content before a matching line
- InjectAfter: Insert content after a matching line
- remove: Remove content between start/end markers
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class InjectionAction(Enum):
    """type of script modification"""
    ADD = "Add"
    INJECT_BEFORE = "InjectBefore"
    INJECT_AFTER = "InjectAfter"
    REMOVE = "Remove"


@dataclass
class ScriptInjection:
    """definition of a script injection"""
    target_script: str  # relative path like "S/Startup-Sequence"
    action: InjectionAction
    content_file: Optional[str] = None  # path to content to inject
    content: Optional[str] = None  # or inline content
    start_pattern: Optional[str] = None  # regex for injection point
    end_pattern: Optional[str] = None  # for Remove action
    name: str = ""  # comment marker name
    is_arexx: bool = False  # use AREXX comment style


def read_amiga_script(path: Path) -> list[str]:
    """read an Amiga script file, handling encoding"""
    try:
        # try ISO-8859-1 first (Amiga standard)
        with open(path, "r", encoding="iso-8859-1") as f:
            return f.read().splitlines()
    except Exception:
        # fallback to UTF-8
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()


def write_amiga_script(path: Path, lines: list[str]) -> None:
    """write an Amiga script file with proper line endings"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="iso-8859-1", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")


def inject_script(
    target_path: Path,
    injection: ScriptInjection,
    content_base_path: Optional[Path] = None,
) -> bool:
    """
    apply an injection to a script file"""
    # read the original script
    if not target_path.exists():
        # create empty file if it doesn't exist (like User-Startup)
        logger.info(f"Creating new script: {target_path}")
        original_lines = []
    else:
        original_lines = read_amiga_script(target_path)

    # get content to inject
    if injection.content:
        content_lines = injection.content.splitlines()
    elif injection.content_file and content_base_path:
        content_path = content_base_path / injection.content_file
        if not content_path.exists():
            logger.error(f"Content file not found: {content_path}")
            return False
        content_lines = read_amiga_script(content_path)
    else:
        content_lines = []

    # build the injection block with markers
    injection_block = _build_injection_block(
        content_lines, injection.name, injection.is_arexx
    )

    # apply the injection
    if injection.action == InjectionAction.ADD:
        result_lines = _action_add(original_lines, injection_block)
    elif injection.action == InjectionAction.INJECT_BEFORE:
        result_lines = _action_inject_before(
            original_lines, injection_block, injection.start_pattern
        )
    elif injection.action == InjectionAction.INJECT_AFTER:
        result_lines = _action_inject_after(
            original_lines, injection_block, injection.start_pattern
        )
    elif injection.action == InjectionAction.REMOVE:
        result_lines = _action_remove(
            original_lines, injection.start_pattern, injection.end_pattern, injection.name
        )
    else:
        logger.error(f"Unknown injection action: {injection.action}")
        return False

    # write the modified script
    write_amiga_script(target_path, result_lines)
    logger.info(f"Applied injection '{injection.name}' to {target_path}")
    return True


def _build_injection_block(
    content_lines: list[str], name: str, is_arexx: bool
) -> list[str]:
    """build injection block with comment markers"""
    block = []

    if name:
        block.append("")
        if is_arexx:
            block.append("/*")
            block.append(f"{name} - Added by Emu68 Hatcher - BEGIN")
            block.append("*/")
        else:
            block.append(f";{name} - Added by Emu68 Hatcher - BEGIN")
        block.append("")

    block.extend(content_lines)

    if name:
        block.append("")
        if is_arexx:
            block.append("/*")
            block.append(f"{name} - Added by Emu68 Hatcher - END")
            block.append("*/")
        else:
            block.append(f";{name} - Added by Emu68 Hatcher - END")
        block.append("")

    return block


def _action_add(original: list[str], block: list[str]) -> list[str]:
    """append block to end of script"""
    return original + block


def _action_inject_before(
    original: list[str], block: list[str], pattern: str
) -> list[str]:
    """insert block before first line matching pattern"""
    if not pattern:
        logger.warning("InjectBefore requires start_pattern")
        return original

    result = []
    inserted = False
    regex = re.compile(pattern, re.IGNORECASE)

    for line in original:
        if not inserted and regex.search(line):
            result.extend(block)
            inserted = True
        result.append(line)

    if not inserted:
        logger.warning(f"Pattern '{pattern}' not found, appending to end")
        result.extend(block)

    return result


def _action_inject_after(
    original: list[str], block: list[str], pattern: str
) -> list[str]:
    """insert block after first line matching pattern"""
    if not pattern:
        logger.warning("InjectAfter requires start_pattern")
        return original

    result = []
    inserted = False
    regex = re.compile(pattern, re.IGNORECASE)

    for line in original:
        result.append(line)
        if not inserted and regex.search(line):
            result.extend(block)
            inserted = True

    if not inserted:
        logger.warning(f"Pattern '{pattern}' not found, appending to end")
        result.extend(block)

    return result


def _action_remove(
    original: list[str], start_pattern: str, end_pattern: str, name: str
) -> list[str]:
    """remove lines between start and end patterns"""
    if not start_pattern or not end_pattern:
        logger.warning("Remove requires both start_pattern and end_pattern")
        return original

    result = []
    removing = False
    start_regex = re.compile(start_pattern, re.IGNORECASE)
    end_regex = re.compile(end_pattern, re.IGNORECASE)

    for line in original:
        if not removing and start_regex.search(line):
            # if end pattern also matches this same line, treat as single-line removal
            if end_regex.search(line):
                result.append("")
                result.append(f";{name} - Section Removed by Emu68 Hatcher")
                result.append("")
                continue
            removing = True
            result.append("")
            result.append(f";{name} - Section Removed by Emu68 Hatcher")
            result.append("")
            continue

        if removing and end_regex.search(line):
            removing = False
            continue

        if not removing:
            result.append(line)

    return result


# standard injections for Emu68 Hatcher
# NOTE: InjectAfter BindDrivers inserts right after the anchor, so later entries
# in the list end up closer to BindDrivers. list in reverse desired execution order
# desired execution order after BindDrivers:
#   1. REXXMAST    (must be first - starts ARexx interpreter)
#   2. iconlib     (RemLib icon.library for non-3.2)
#   3. OneTimeRun  (first-boot scripts)
#   4. UAEGFX      (persistent monitor driver swap)
STARTUP_SEQUENCE_INJECTIONS = [
    # remove ROM CheckInstall section - not needed for Emu68 (runs from ROM directly,
    # no module patching required). LoadModule fails because L: update files aren't
    # extracted, and Version ram-handler check can QUIT the script
    # removes from section comment through SetPatch (which is re-added by content)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.REMOVE,
        start_pattern=r";-+\s*ROM CheckInstall",
        end_pattern=r"^SetPatch",
        name="ROM CheckInstall (not needed for Emu68)",
    ),
    # re-add SetPatch after ROM CheckInstall removal (consumed by end pattern)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.INJECT_BEFORE,
        content="SetPatch >NIL:",
        start_pattern=r";-+\s*CPU CheckInstall|FailAt 10",
        name="SetPatch",
    ),
    # remove CPU CHECKINSTALL section - not needed for Emu68 (causes error on 68040)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.REMOVE,
        start_pattern=r";-+\s*CPU CheckInstall",
        end_pattern=r";-+\s*End of CPU CheckInstall",
        name="CPU CheckInstall (not needed for Emu68)",
    ),
    # remove the original RexxMast invocation - we start it earlier (after BindDrivers)
    # so OneTimeRun scripts can use ARexx. the original runs after FailAt 10 which
    # makes RexxMast's RC 20 ("already running") fatal
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.REMOVE,
        start_pattern=r"If EXISTS SYS:System/RexxMast",
        end_pattern=r"EndIf",
        name="Original RexxMast (moved to after BindDrivers)",
    ),
    # UAEGFX persistent monitor swap (runs 4th, furthest from anchor)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.INJECT_AFTER,
        content_file="S/Startup-Sequence_UAEGFX",
        start_pattern=r"BindDrivers",
        name="UAEGFX Monitor Swap",
    ),
    # main OneTimeRun section (runs 3rd)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.INJECT_AFTER,
        content_file="S/Startup-Sequence_OneTimeRun",
        start_pattern=r"BindDrivers",
        name="OneTimeRun Section",
    ),
    # iconlib - RemLib icon.library for non-3.2 Kickstarts (runs 2nd)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.INJECT_AFTER,
        content_file="S/Startup-Sequence_Iconlib",
        start_pattern=r"BindDrivers",
        name="Iconlib",
    ),
    # RexxMast - start ARexx interpreter (runs 1st, closest to anchor)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.INJECT_AFTER,
        content_file="S/Startup-Sequence_REXXMAST",
        start_pattern=r"BindDrivers",
        name="RexxMast",
    ),
    # suppress "Device SD0: is already mounted" error from stock Mount line
    # on second+ boots, BindDrivers loads SD0 from Devs:DOSDrivers/ before
    # the Mount glob runs, causing a visible error. add >NIL: to suppress
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.REMOVE,
        start_pattern=r"^Mount DEVS:DOSDrivers",
        end_pattern=r"^Mount DEVS:DOSDrivers",
        name="Mount redirect",
    ),
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.INJECT_BEFORE,
        content="Mount >NIL: DEVS:DOSDrivers/~(#?.info)",
        start_pattern=r"LoadMonDrvs",
        name="Mount DOSDrivers (with >NIL:)",
    ),
]

USER_STARTUP_INJECTIONS = [
    ScriptInjection(
        target_script="S/User-Startup",
        action=InjectionAction.ADD,
        content_file="S/User-Startup_MUI38",
        name="MUI 3.8",
    ),
    ScriptInjection(
        target_script="S/User-Startup",
        action=InjectionAction.ADD,
        content_file="S/User-Startup_AmiSSL",
        name="AmiSSL",
    ),
    ScriptInjection(
        target_script="S/User-Startup",
        action=InjectionAction.ADD,
        content_file="S/User-Startup_Roadshow",
        name="Roadshow TCP/IP",
    ),
    ScriptInjection(
        target_script="S/User-Startup",
        action=InjectionAction.ADD,
        content_file="S/User-Startup_Picasso96",
        name="Picasso96 RTG",
    ),
]


def apply_standard_injections(
    staging_dir: Path,
    content_base_path: Path,
    enabled_packages: Optional[set[str]] = None,
) -> int:
    """
    apply standard script injections to staged files"""
    count = 0

    # always apply Startup-Sequence injections
    for injection in STARTUP_SEQUENCE_INJECTIONS:
        target = staging_dir / injection.target_script
        if inject_script(target, injection, content_base_path):
            count += 1

    # apply User-Startup injections based on enabled packages
    package_to_injection = {
        "mui38": "S/User-Startup_MUI38",
        "amissl": "S/User-Startup_AmiSSL",
        "roadshow": "S/User-Startup_Roadshow",
        "picasso96": "S/User-Startup_Picasso96",
    }

    for injection in USER_STARTUP_INJECTIONS:
        # check if the package is enabled
        package_name = None
        for pkg, content_file in package_to_injection.items():
            if injection.content_file == content_file:
                package_name = pkg
                break

        if enabled_packages and package_name and package_name not in enabled_packages:
            continue

        target = staging_dir / injection.target_script
        if inject_script(target, injection, content_base_path):
            count += 1

    return count
