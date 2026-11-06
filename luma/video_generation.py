import asyncio
from pathlib import Path
from typing import Any

from griptape.artifacts import ImageUrlArtifact, VideoUrlArtifact
from griptape_nodes.exe_types.core_types import (
    NodeError,
    Parameter,
    ParameterList,
    ParameterMode,
    ParameterTypeBuiltin,
)
from griptape_nodes.exe_types.node_types import SuccessFailureNode
from griptape_nodes.exe_types.param_components.artifact_url.public_artifact_url_parameter import (
    PublicArtifactUrlParameter,
)
from griptape_nodes.exe_types.param_components.project_file_parameter import ProjectFileParameter
from griptape_nodes.files.file import File
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.options import Options
from luma_agents import AsyncLuma
from luma_utils.luma_errors import (
    error_from_api_exception,
    generation_error,
    generation_failed_error,
    input_error,
    missing_key_error,
)
from luma_utils.public_url_utils import build_public_url_list, cleanup_uploaded_paths

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMA_AGENTS_API_KEY"
MAX_KEYFRAMES = 64


class LumaVideoGeneration(SuccessFailureNode):
    """Luma Labs Ray video generation node supporting text-to-video and image-to-video."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        self._keyframe_uploaded_paths: list[Path] = []

        self.add_parameter(
            Parameter(
                name="prompt",
                tooltip="Text description of the desired video",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Describe the video you want to generate...",
                },
            )
        )

        self.add_parameter(
            Parameter(
                name="model",
                tooltip="Ray model to use for video generation.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="ray-3.2",
                traits={Options(choices=["ray-3.2"])},
                ui_options={"display_name": "Model"},
            )
        )

        self.add_parameter(
            Parameter(
                name="aspect_ratio",
                tooltip="Video aspect ratio",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="16:9",
                traits={Options(choices=["1:1", "3:4", "4:3", "9:16", "16:9", "21:9"])},
                ui_options={"display_name": "Aspect Ratio"},
            )
        )

        self.add_parameter(
            Parameter(
                name="resolution",
                tooltip="Video resolution. Higher resolutions take longer to generate.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="720p",
                traits={Options(choices=["360p", "540p", "720p", "1080p"])},
                ui_options={"display_name": "Resolution"},
            )
        )

        self.add_parameter(
            Parameter(
                name="duration",
                tooltip="Video duration in seconds",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="5s",
                traits={Options(choices=["5s", "10s"])},
                ui_options={"display_name": "Duration"},
            )
        )

        self.add_parameter(
            Parameter(
                name="image_input_mode",
                tooltip=(
                    "How to anchor reference images to the video.\n"
                    "none — text-to-video, no image anchors\n"
                    "start_end_frame — anchor the first and/or last frame\n"
                    "keyframes — place images at specific frame positions (mutually exclusive with loop; "
                    "indexes are 0–120 for 5 s, 0–240 for 10 s at 24 fps)"
                ),
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="none",
                traits={Options(choices=["none", "start_end_frame", "keyframes"])},
                ui_options={"display_name": "Image Input"},
            )
        )

        # --- Start / End frame section (shown when image_input_mode == "start_end_frame") ---
        self._public_start_frame_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="start_frame",
                tooltip="Starting frame image for image-to-video generation",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageUrlArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.OUTPUT},
                ui_options={"hide": True},
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the image for video generation.",
        )
        self._public_start_frame_parameter.add_input_parameters()

        # End frame with public URL support
        self._public_end_frame_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="end_frame",
                tooltip="Ending frame image for controlled video generation",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageUrlArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.OUTPUT},
                ui_options={"hide": True},
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the image for video generation.",
        )
        self._public_end_frame_parameter.add_input_parameters()

        # --- Keyframes section (shown when image_input_mode == "keyframes") ---
        # Two parallel lists: Nth image pairs with Nth index.
        self._keyframe_images_list = ParameterList(
            name="keyframe_images",
            tooltip=(
                "Keyframe image. Each entry pairs by position with the corresponding Keyframe Index.\n"
                "Local images are automatically uploaded to Griptape Cloud for Luma API access."
            ),
            input_types=["ImageArtifact", "ImageUrlArtifact"],
            type="ImageUrlArtifact",
            allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            max_items=MAX_KEYFRAMES,
            display_name="Keyframe Images",
            hide=True,
        )
        self.add_parameter(self._keyframe_images_list)
        self._keyframe_images_list.set_badge(
            variant="cloud-upload",
            title="Media Upload",
            message=self._public_start_frame_parameter.get_help_message(),
            hide_clear_button=False,
        )

        self._keyframe_indexes_list = ParameterList(
            name="keyframe_indexes",
            tooltip=(
                "Frame position for the paired keyframe image.\n"
                "Range: 0–120 for 5 s video, 0–240 for 10 s video (24 fps). Values must be unique."
            ),
            type=ParameterTypeBuiltin.INT.value,
            allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            default_value=0,
            max_items=MAX_KEYFRAMES,
            display_name="Keyframe Indexes",
            hide=True,
        )
        self.add_parameter(self._keyframe_indexes_list)

        # Loop — hidden when keyframes mode is active (mutually exclusive per API)
        self.add_parameter(
            Parameter(
                name="loop",
                tooltip="Generate a seamlessly looping video (not available in keyframes mode)",
                type=ParameterTypeBuiltin.BOOL.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=False,
                ui_options={"display_name": "Loop Video"},
            )
        )

        self.add_parameter(
            Parameter(
                name="hdr",
                tooltip="Enable HDR-encoded MP4 output. Requires 720p or 1080p resolution.",
                type=ParameterTypeBuiltin.BOOL.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=False,
                ui_options={"display_name": "HDR Output"},
            )
        )

        self.add_parameter(
            Parameter(
                name="video",
                tooltip="Generated video",
                output_type="VideoUrlArtifact",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
                ui_options={"pulse_on_run": True},
                settable=False,
            )
        )

        self.add_parameter(
            Parameter(
                name="status",
                tooltip="Generation status and progress",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"multiline": True, "pulse_on_run": True},
            )
        )

        self._output_file = ProjectFileParameter(
            node=self,
            name="output_file",
            default_filename="luma_video.mp4",
        )
        self._output_file.add_parameter()
        self._create_status_parameters()

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        if parameter.name == "image_input_mode":
            self._apply_image_input_mode(value)

    def _apply_image_input_mode(self, mode: str) -> None:
        if mode == "start_end_frame":
            self.show_parameter_by_name(["start_frame", "end_frame"])
            self.hide_parameter_by_name(["keyframe_images", "keyframe_indexes"])
            self.show_parameter_by_name(["loop"])
        elif mode == "keyframes":
            self.hide_parameter_by_name(["start_frame", "end_frame"])
            self.show_parameter_by_name(["keyframe_images", "keyframe_indexes"])
            self.hide_parameter_by_name(["loop"])
        else:  # "none"
            self.hide_parameter_by_name(["start_frame", "end_frame"])
            self.hide_parameter_by_name(["keyframe_images", "keyframe_indexes"])
            self.show_parameter_by_name(["loop"])

    def _get_api_key(self) -> str:
        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            raise missing_key_error()
        return api_key

    def validate_before_node_run(self) -> list[Exception] | None:
        # A missing key is reported first and alone, so the Settings link is the only thing on the node header.
        if not GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR):
            return [missing_key_error()]

        errors: list[Exception] = []
        errors.extend(super().validate_before_node_run() or [])

        prompt = self.get_parameter_value("prompt")
        if not prompt:
            errors.append(input_error("Enter a prompt in 'Prompt'.", "prompt"))

        hdr = self.get_parameter_value("hdr")
        if hdr and self.get_parameter_value("resolution") not in {"720p", "1080p"}:
            errors.append(input_error("'HDR Output' needs 'Resolution' set to 720p or 1080p.", "hdr"))

        loop = self.get_parameter_value("loop")
        duration = self.get_parameter_value("duration") or "5s"
        if loop and duration == "10s":
            errors.append(
                input_error("'Loop Video' is not supported with a 10s 'Duration'. Choose 5s or turn Loop off.", "loop")
            )
        if loop and hdr:
            errors.append(input_error("'Loop Video' is not supported with 'HDR Output'. Turn one of them off.", "loop"))

        mode = self.get_parameter_value("image_input_mode")
        if mode == "keyframes":
            image_count = len(self._keyframe_images_list.get_child_parameters())
            index_count = len(self._keyframe_indexes_list.get_child_parameters())
            if image_count == 0:
                errors.append(
                    input_error(
                        "Add at least one image to 'Keyframe Images' when 'Image Input' is keyframes.",
                        "keyframe_images",
                    )
                )
            elif image_count != index_count:
                msg = (
                    f"'Keyframe Images' has {image_count} items and 'Keyframe Indexes' has {index_count}. "
                    "Give both lists the same number of items."
                )
                errors.append(input_error(msg, "keyframe_indexes"))
            else:
                index_children = self._keyframe_indexes_list.get_child_parameters()
                index_values = [
                    int(v) if (v := self.get_parameter_value(p.name)) is not None else 0 for p in index_children
                ]

                # Uniqueness check
                if len(index_values) != len(set(index_values)):
                    seen: set[int] = set()
                    dupes: set[int] = set()
                    for v in index_values:
                        (dupes if v in seen else seen).add(v)
                    msg = f"'Keyframe Indexes' must be unique. These repeat: {sorted(dupes)}."
                    errors.append(input_error(msg, "keyframe_indexes"))

                # Range check (24 fps: 5 s → 0–120, 10 s → 0–240)
                duration = self.get_parameter_value("duration") or "5s"
                max_index = 120 if duration == "5s" else 240
                out_of_range = [v for v in index_values if not (0 <= v <= max_index)]
                if out_of_range:
                    msg = (
                        f"'Keyframe Indexes' must be between 0 and {max_index} for a {duration} video. "
                        f"These are out of range: {sorted(out_of_range)}."
                    )
                    errors.append(input_error(msg, "keyframe_indexes"))

        return errors or None

    async def aprocess(self) -> None:
        """Generate video using Luma async API."""
        self._clear_execution_status()
        client = None
        try:
            api_key = self._get_api_key()
            client = AsyncLuma(auth_token=api_key)

            prompt = self.get_parameter_value("prompt")
            if not prompt:
                raise input_error("Enter a prompt in 'Prompt'.", "prompt")

            model = self.get_parameter_value("model")
            aspect_ratio = self.get_parameter_value("aspect_ratio")
            resolution = self.get_parameter_value("resolution")
            duration = self.get_parameter_value("duration")
            mode = self.get_parameter_value("image_input_mode")

            self.append_value_to_parameter("status", "Creating generation request...\n")

            # Build request parameters for the video generation type
            params: dict = {
                "type": "video",
                "prompt": prompt.strip(),
                "model": model,
            }

            if aspect_ratio:
                params["aspect_ratio"] = aspect_ratio

            hdr = self.get_parameter_value("hdr")

            # Video-specific output settings live under the `video` options object
            video_options: dict = {
                "resolution": resolution,
                "duration": duration,
            }

            if hdr:
                video_options["hdr"] = True
                self.append_value_to_parameter("status", "HDR output enabled\n")

            if mode == "start_end_frame":
                loop_video = self.get_parameter_value("loop")
                # Add loop if enabled
                if loop_video:
                    video_options["loop"] = True
                    self.append_value_to_parameter("status", "Loop mode enabled\n")

                # Add optional start and end frames
                # Convert serialized dict back to artifact if needed
                start_frame = self.get_parameter_value("start_frame")
                if start_frame:
                    if isinstance(start_frame, dict) and start_frame.get("value"):
                        start_frame = ImageUrlArtifact(
                            value=start_frame["value"], name=start_frame.get("name", "start_frame")
                        )
                        self.set_parameter_value("start_frame", start_frame)
                    # Let PublicArtifactUrlParameter handle getting and converting the artifact
                    try:
                        start_frame_url = self._public_start_frame_parameter.get_public_url_for_parameter()
                    except NodeError:
                        raise
                    except Exception as e:
                        msg = f"Could not prepare 'Start Frame' for Luma: {e}"
                        raise input_error(msg, "start_frame") from e
                    if start_frame_url:
                        video_options["start_frame"] = {"url": start_frame_url}
                        self.append_value_to_parameter("status", f"Using start frame: {start_frame_url}\n")

                # Convert serialized dict back to artifact if needed
                end_frame = self.get_parameter_value("end_frame")
                if end_frame:
                    if isinstance(end_frame, dict) and end_frame.get("value"):
                        end_frame = ImageUrlArtifact(value=end_frame["value"], name=end_frame.get("name", "end_frame"))
                        self.set_parameter_value("end_frame", end_frame)
                    # Let PublicArtifactUrlParameter handle getting and converting the artifact
                    try:
                        end_frame_url = self._public_end_frame_parameter.get_public_url_for_parameter()
                    except NodeError:
                        raise
                    except Exception as e:
                        msg = f"Could not prepare 'End Frame' for Luma: {e}"
                        raise input_error(msg, "end_frame") from e
                    if end_frame_url:
                        video_options["end_frame"] = {"url": end_frame_url}
                        self.append_value_to_parameter("status", f"Using end frame: {end_frame_url}\n")

            elif mode == "keyframes":
                try:
                    keyframes, keyframe_indexes = self._build_keyframe_params()
                except NodeError:
                    raise
                except Exception as e:
                    msg = f"Could not prepare 'Keyframe Images' for Luma: {e}"
                    raise input_error(msg, "keyframe_images") from e
                if keyframes:
                    video_options["keyframes"] = keyframes
                    video_options["keyframe_indexes"] = keyframe_indexes
                    self.append_value_to_parameter("status", f"Using {len(keyframes)} keyframe anchor(s)\n")

            else:  # "none"
                loop_video = self.get_parameter_value("loop")
                if loop_video:
                    video_options["loop"] = True
                    self.append_value_to_parameter("status", "Loop mode enabled\n")

            params["video"] = video_options

            # Create generation
            try:
                generation = await client.generations.create(**params)
                generation_id = generation.id
            except Exception as e:
                raise error_from_api_exception(e) from e

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")
            self.append_value_to_parameter("status", "Waiting for generation to complete...\n")

            # Poll for completion
            completed = False
            max_attempts = 200
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(3)
                attempt += 1

                try:
                    generation = await client.generations.get(generation_id=generation_id)
                except Exception as e:
                    raise error_from_api_exception(e, generation_id=generation_id) from e

                if generation.state == "completed":
                    completed = True
                    self.append_value_to_parameter("status", f"Attempt {attempt}: Completed!\n")
                elif generation.state == "failed":
                    raise generation_failed_error(generation)
                else:
                    self.append_value_to_parameter("status", f"Attempt {attempt}: {generation.state}\n")

            if not completed:
                raise generation_error(
                    generation,
                    f"Luma was still working after {max_attempts * 3} seconds, so the node stopped waiting. Run the node again, or try a simpler request.",
                )

            # Download and save video from the generation output list
            if not generation.output:
                raise generation_error(
                    generation,
                    "Luma reported the generation as completed but returned no output file. Run the node again.",
                )
            video_url = ""
            try:
                video_url = generation.output[0].url
                self.append_value_to_parameter("status", "Downloading generated video...\n")
                video_bytes = self._download_video(video_url)
                # Save to project files
                dest = self._output_file.build_file()
                saved = dest.write_bytes(video_bytes)
                video_artifact = VideoUrlArtifact(value=saved.location)
                self.parameter_output_values["video"] = video_artifact
                self.publish_update_to_parameter("video", video_artifact)
            except Exception as e:
                msg = f"Could not download or save the file Luma produced: {e}"
                raise NodeError(msg, fields={"generation_id": generation_id}) from e

            self.append_value_to_parameter(
                "status",
                f"✅ Generation completed successfully!\nOriginal URL: {video_url}\n",
            )
            self._set_status_results(was_successful=True, result_details="Generation completed successfully.")

        except Exception as e:
            self.append_value_to_parameter("status", f"❌ Generation failed: {str(e)}\n")
            self._set_status_results(was_successful=False, result_details=str(e))
            self._handle_failure_exception(e)
        finally:
            if client is not None:
                await client.close()
            # Cleanup uploaded artifacts
            self._public_start_frame_parameter.delete_uploaded_artifact()
            self._public_end_frame_parameter.delete_uploaded_artifact()
            self._cleanup_keyframe_uploads()

    def _build_keyframe_params(self) -> tuple[list[dict], list[int]]:
        """Build keyframes and keyframe_indexes arrays for the Luma API."""
        image_children = self._keyframe_images_list.get_child_parameters()
        index_children = self._keyframe_indexes_list.get_child_parameters()
        storage_driver = self._public_start_frame_parameter._storage_driver

        valid_image_names: list[str] = []
        valid_indexes: list[int] = []
        for img_param, idx_param in zip(image_children, index_children, strict=True):
            if self.get_parameter_value(img_param.name) is not None:
                valid_image_names.append(img_param.name)
                idx_value = self.get_parameter_value(idx_param.name)
                valid_indexes.append(int(idx_value) if idx_value is not None else 0)

        keyframes, self._keyframe_uploaded_paths = build_public_url_list(
            self, valid_image_names, storage_driver, list_name="keyframe_images", list_label="Keyframe Images"
        )
        return keyframes, valid_indexes

    def _cleanup_keyframe_uploads(self) -> None:
        cleanup_uploaded_paths(self._public_start_frame_parameter._storage_driver, self._keyframe_uploaded_paths)
        self._keyframe_uploaded_paths = []

    def _download_video(self, video_url: str) -> bytes:
        """Download video from URL and return bytes."""
        return File(video_url).read_bytes()
