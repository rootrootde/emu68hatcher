"""
build workflow orchestration for Emu68 Hatcher

coordinates the complete build process:
1. validate configuration
2. download required packages
3. extract archives
4. create disk image
5. install Workbench
6. install packages
7. configure system
8. finalize image
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from emu68hatcher.builder.errors import BuildError, BuildCancelledError
from emu68hatcher.config.schema import BuildConfig
from emu68hatcher.extractor.adf import WorkbenchDiskSet, IdentifiedInstallMedia
from emu68hatcher.utils.logging import get_logger


class BuildStage(str, Enum):
    """stages of the build process"""

    INIT = "init"
    VALIDATE = "validate"
    DOWNLOAD = "download"
    EXTRACT = "extract"
    CREATE_IMAGE = "create_image"
    PARTITION = "partition"
    INSTALL_WORKBENCH = "install_workbench"
    INSTALL_PACKAGES = "install_packages"
    CONFIGURE = "configure"
    FINALIZE = "finalize"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class BuildState:
    """current state of the build process"""

    stage: BuildStage = BuildStage.INIT
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None

    # paths
    work_dir: Optional[Path] = None
    image_path: Optional[Path] = None
    staging_dir: Optional[Path] = None
    downloads_dir: Optional[Path] = None
    extracted_dir: Optional[Path] = None
    workbench_dir: Optional[Path] = None

    # resolved paths (auto-detected from directories)
    resolved_rom_path: Optional[Path] = None
    resolved_rom_info: Optional[dict] = None  # includes fat32_name for boot partition
    rom_boot_filename: str = "kick.rom"  # filename of ROM on boot partition for config.txt
    resolved_workbench_disks: Optional["WorkbenchDiskSet"] = None
    # hash-identified install media (ADFs, ISOs) - more reliable than filename detection
    resolved_install_media: list["IdentifiedInstallMedia"] = field(default_factory=list)
    missing_install_media: list[str] = field(default_factory=list)

    # downloaded files: package_name -> local_path
    downloaded_files: dict[str, Path] = field(default_factory=dict)
    # extracted paths: package_name -> extracted_dir
    extracted_paths: dict[str, Path] = field(default_factory=dict)
    # PFS3AIO handler path (downloaded in DOWNLOAD stage, used by CREATE_IMAGE)
    pfs3_handler_path: Optional[Path] = None

    # statistics
    packages_downloaded: int = 0
    packages_total: int = 0
    files_copied: int = 0
    files_total: int = 0


# progress callback type
BuildProgressCallback = Callable[[BuildState], None]
# log callback type: (stage_name, message)
BuildLogCallback = Callable[[str, str], None]


@dataclass
class BuildResult:
    """result of a build operation"""

    success: bool
    output_path: Optional[Path] = None
    error: Optional[str] = None
    duration: float = 0.0
    stages_completed: list[BuildStage] = field(default_factory=list)

    @property
    def output_size(self) -> int:
        """get output file size in bytes"""
        if self.output_path and self.output_path.exists():
            return self.output_path.stat().st_size
        return 0


class BuildWorkflow:
    """
    orchestrates the complete build process

    creates Amiga disk images from a BuildConfig, handling all stages
    from download to final image creation.
    """

    def __init__(
        self,
        config: BuildConfig,
        progress_callback: Optional[BuildProgressCallback] = None,
        log_callback: Optional[BuildLogCallback] = None,
        gui_mode: bool = False,
    ):
        self.config = config
        self.progress_callback = progress_callback
        self._log_callback = log_callback
        self.gui_mode = gui_mode
        self.state = BuildState()
        self.logger = get_logger()
        self._cancelled = False

    def cancel(self) -> None:
        """request cancellation of the build"""
        self._cancelled = True

    def _update_state(
        self,
        stage: Optional[BuildStage] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
    ) -> None:
        """update build state and notify callback"""
        if stage is not None:
            self.state.stage = stage
        if progress is not None:
            self.state.progress = progress
        if message is not None:
            self.state.message = message

        if self.progress_callback:
            self.progress_callback(self.state)

    def _log(self, message: str) -> None:
        """emit a discrete log event (one per logical unit of work)

        also updates state.message so the status label reflects the latest
        event and CLI consumers (which don't subscribe to log_callback) still
        see it through progress_callback.
        """
        self._update_state(message=message)
        if self._log_callback is not None:
            self._log_callback(self.state.stage.value, message)

    def _check_cancelled(self) -> None:
        """check if build was cancelled and raise if so"""
        if self._cancelled:
            raise BuildCancelledError("Build was cancelled by user")

    # =========================================================================
    # stage Delegation (each stage lives in builder/stages/)
    # =========================================================================

    def _stage_validate(self) -> None:
        from emu68hatcher.builder.stages.validate import stage_validate
        stage_validate(self)

    def _stage_setup_workspace(self) -> None:
        from emu68hatcher.builder.stages.download import stage_setup_workspace
        stage_setup_workspace(self)

    def _stage_download(self) -> None:
        from emu68hatcher.builder.stages.download import stage_download
        stage_download(self)

    def _stage_extract(self) -> None:
        from emu68hatcher.builder.stages.download import stage_extract
        stage_extract(self)

    def _stage_create_image(self) -> None:
        from emu68hatcher.builder.stages.create_image import stage_create_image
        stage_create_image(self)

    def _stage_install_workbench(self) -> None:
        from emu68hatcher.builder.stages.install_workbench import stage_install_workbench
        stage_install_workbench(self)

    def _stage_install_packages(self) -> None:
        from emu68hatcher.builder.stages.install_packages import stage_install_packages
        stage_install_packages(self)

    def _stage_configure(self) -> None:
        from emu68hatcher.builder.stages.configure import stage_configure
        stage_configure(self)

    def _stage_finalize(self) -> None:
        from emu68hatcher.builder.stages.finalize import stage_finalize
        stage_finalize(self)

    # =========================================================================
    # main Build Method
    # =========================================================================

    def build(self) -> BuildResult:
        """
        execute the complete build process synchronously"""
        import time

        start_time = time.time()
        stages_completed = []

        try:
            # validation
            self._stage_validate()
            stages_completed.append(BuildStage.VALIDATE)
            self._check_cancelled()

            # setup
            self._stage_setup_workspace()
            stages_completed.append(BuildStage.INIT)
            self._check_cancelled()

            # downloads
            self._stage_download()
            stages_completed.append(BuildStage.DOWNLOAD)
            self._check_cancelled()

            # extract
            self._stage_extract()
            stages_completed.append(BuildStage.EXTRACT)
            self._check_cancelled()

            # create image
            self._stage_create_image()
            stages_completed.append(BuildStage.CREATE_IMAGE)
            self._check_cancelled()

            # install Workbench
            self._stage_install_workbench()
            stages_completed.append(BuildStage.INSTALL_WORKBENCH)
            self._check_cancelled()

            # install packages
            self._stage_install_packages()
            stages_completed.append(BuildStage.INSTALL_PACKAGES)
            self._check_cancelled()

            # configure
            self._stage_configure()
            stages_completed.append(BuildStage.CONFIGURE)
            self._check_cancelled()

            # finalize
            self._stage_finalize()
            stages_completed.append(BuildStage.FINALIZE)

            self._update_state(BuildStage.COMPLETE, 100.0)
            self._log("Build successful!")

            return BuildResult(
                success=True,
                output_path=Path(self.config.output.path) if self.config.output else None,
                duration=time.time() - start_time,
                stages_completed=stages_completed,
            )

        except BuildCancelledError:
            self._update_state(BuildStage.FAILED)
            self._log("Build cancelled")
            return BuildResult(
                success=False,
                error="Build cancelled by user",
                duration=time.time() - start_time,
                stages_completed=stages_completed,
            )

        except BuildError as e:
            self.state.error = str(e)
            self._update_state(BuildStage.FAILED)
            self._log(str(e))
            return BuildResult(
                success=False,
                error=str(e),
                duration=time.time() - start_time,
                stages_completed=stages_completed,
            )

        except Exception as e:
            self.state.error = str(e)
            self._update_state(BuildStage.FAILED)
            self._log(f"Unexpected error: {e}")
            return BuildResult(
                success=False,
                error=str(e),
                duration=time.time() - start_time,
                stages_completed=stages_completed,
            )
