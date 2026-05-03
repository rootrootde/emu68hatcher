"""inject add/before/after/remove edits into existing Amiga startup scripts (preserves original AmigaOS init)"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
    content_file: str | None = None  # path to content to inject
    content: str | None = None  # or inline content
    start_pattern: str | None = None  # regex for injection point
    end_pattern: str | None = None  # for Remove action
    name: str = ""  # comment marker name
    is_arexx: bool = False  # use AREXX comment style


def read_amiga_script(path: Path) -> list[str]:
    """read an Amiga script file (ISO-8859-1 decodes every byte, no fallback needed)"""
    with open(path, encoding="iso-8859-1") as f:
        return f.read().splitlines()


def write_amiga_script(path: Path, lines: list[str]) -> None:
    """write an Amiga script file wiht proper line endings"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="iso-8859-1", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")


def inject_script(
    target_path: Path,
    injection: ScriptInjection,
    content_base_path: Path | None = None,
) -> bool:
    """apply an injection to a script file"""
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
    injection_block = _build_injection_block(content_lines, injection.name, injection.is_arexx)

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


def _build_injection_block(content_lines: list[str], name: str, is_arexx: bool) -> list[str]:
    """build injection block wiht comment markers"""
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


def _action_inject_before(original: list[str], block: list[str], pattern: str) -> list[str]:
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


def _action_inject_after(original: list[str], block: list[str], pattern: str) -> list[str]:
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


# InjectAfter BindDrivers stacks LIFO; list reverse of exec order: UAEGFX, FirstBoot, iconlib, REXXMAST
STARTUP_SEQUENCE_INJECTIONS = [
    # ROM CheckInstall LoadModule fails on Emu68 (no L: update files); also QUITs the script
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.REMOVE,
        start_pattern=r";-+\s*ROM CheckInstall",
        end_pattern=r"^SetPatch",
        name="ROM CheckInstall (not needed for Emu68)",
    ),
    # re-add SetPatch + KEYMAPS assign (consumed by the ROM CheckInstall removal above)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.INJECT_BEFORE,
        content="SetPatch >NIL:\nAssign >NIL: KEYMAPS: DEVS:Keymaps",
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
    # remove the original RexxMast - moved to after BindDrivers so FirstBoot scripts can use ARexx
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
    # main FirstBoot section (runs 3rd)
    ScriptInjection(
        target_script="S/Startup-Sequence",
        action=InjectionAction.INJECT_AFTER,
        content_file="S/Startup-Sequence_FirstBoot",
        start_pattern=r"BindDrivers",
        name="FirstBoot Section",
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
    # second+ boots: BindDrivers loads SD0 before the Mount glob, suppress the duplicate-mount error
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
        content_file="S/User-Startup_SetDST",
        name="SetDST",
    ),
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
    enabled_packages: set[str] | None = None,
) -> int:
    """apply standard script injections to staged files"""
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
