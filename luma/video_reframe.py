import asyncio
import mimetypes
from typing import Any

from griptape.artifacts import VideoUrlArtifact
from griptape_nodes.exe_types.core_types import (
    Parameter,
    ParameterGroup,
    ParameterMode,
    ParameterTypeBuiltin,
)
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.exe_types.param_components.artifact_url.public_artifact_url_parameter import (
    PublicArtifactUrlParameter,
)
from griptape_nodes.exe_types.param_components.project_file_parameter import ProjectFileParameter
from griptape_nodes.files.file import File
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.options import Options
from luma_agents import AsyncLuma

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMA_AGENTS_API_KEY"


class LumaVideoReframe(ControlNode):
    """Luma Labs Ray video reframing node for changing aspect ratios and extending videos."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        # Input video with public URL support
        self._public_input_video_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="input_video",
                tooltip="Input video to reframe (max 18s, 100 MB max)",
                input_types=["VideoUrlArtifact", "UrlArtifact"],
                type="VideoUrlArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "clickable_file_browser": True,
                    "expander": True,
                    "file_browser_options": {
                        "extensions": [".mp4", ".mov", ".avi", ".webm"],
                        "allow_multiple": False,
                    },
                },
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the video for reframing.",
        )
        self._public_input_video_parameter.add_input_parameters()

        self.add_parameter(
            Parameter(
                name="model",
                tooltip="Ray model to use for video reframing.",
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
                tooltip="Target aspect ratio for the reframed video",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="16:9",
                traits={Options(choices=["1:1", "4:3", "3:4", "16:9", "9:16", "21:9"])},
                ui_options={"display_name": "Aspect Ratio"},
            )
        )

        self.add_parameter(
            Parameter(
                name="prompt",
                tooltip="Optional: Text prompt to steer what content goes into the reframed new area",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="",
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Optional: Describe how to fill the new area...",
                },
            )
        )

        # Advanced source-position controls. These define the normalized rectangle the source
        # video occupies inside the output canvas. Leave all at 0 to let the model choose the
        # default centered-fit crop.
        with ParameterGroup(name="Advanced") as advanced_group:
            Parameter(
                name="x_norm",
                tooltip="Left edge of the source rectangle, as a fraction of canvas width (may be negative).",
                type=ParameterTypeBuiltin.FLOAT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0.0,
            )

            Parameter(
                name="y_norm",
                tooltip="Top edge of the source rectangle, as a fraction of canvas height (may be negative).",
                type=ParameterTypeBuiltin.FLOAT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0.0,
            )

            Parameter(
                name="w_norm",
                tooltip="Source rectangle width, as a fraction of canvas width (up to 2.0). 0 uses the default crop.",
                type=ParameterTypeBuiltin.FLOAT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0.0,
            )

            Parameter(
                name="h_norm",
                tooltip="Source rectangle height, as a fraction of canvas height (up to 2.0). 0 uses the default crop.",
                type=ParameterTypeBuiltin.FLOAT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0.0,
            )

        advanced_group.ui_options = {"collapsed": True}
        self.add_node_element(advanced_group)

        self.add_parameter(
            Parameter(
                name="output_video",
                tooltip="Reframed video",
                output_type="VideoUrlArtifact",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
                ui_options={"pulse_on_run": True},
                settable=False,
            )
        )

        self.add_parameter(
            Parameter(
                name="status",
                tooltip="Reframe status and progress",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"multiline": True, "pulse_on_run": True},
            )
        )

        self._output_file = ProjectFileParameter(
            node=self,
            name="output_file",
            default_filename="luma_reframe.mp4",
        )
        self._output_file.add_parameter()

    def _get_api_key(self) -> str:
        """Retrieve the Luma API key from configuration."""
        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            raise ValueError(
                f"Luma API key not found. Please set the {API_KEY_ENV_VAR} environment variable.\n"
                "Get your API key from: https://platform.lumalabs.ai"
            )
        return api_key

    def validate_before_node_run(self) -> list[Exception] | None:
        """Validate node configuration before execution."""
        errors = []

        input_video = self.get_parameter_value("input_video")
        if not input_video:
            errors.append(ValueError(f"{self.name}: Provide an input video to reframe."))

        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            errors.append(
                ValueError(
                    f"{self.name}: Luma API key not found. Please set the {API_KEY_ENV_VAR} environment variable."
                )
            )

        return errors if errors else None

    def validate_before_workflow_run(self) -> list[Exception] | None:
        return self.validate_before_node_run()

    def process(self) -> AsyncResult[None]:
        """Non-blocking entry point for Griptape engine."""
        yield lambda: self._process_sync()

    def _process_sync(self) -> None:
        """Synchronous wrapper that runs async code."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._process_async())
        finally:
            loop.close()

    async def _process_async(self) -> None:
        """Reframe video using Luma async API."""
        try:
            api_key = self._get_api_key()
            client = AsyncLuma(auth_token=api_key)

            # Convert serialized dict back to artifact if needed
            input_video = self.get_parameter_value("input_video")
            if isinstance(input_video, dict) and input_video.get("value"):
                # Create proper artifact from serialized dict
                input_video = VideoUrlArtifact(value=input_video["value"], name=input_video.get("name", "input_video"))
                # Update the parameter with the artifact object
                self.set_parameter_value("input_video", input_video)

            # Let PublicArtifactUrlParameter handle getting and converting the artifact
            video_url = self._public_input_video_parameter.get_public_url_for_parameter()
            if not video_url:
                raise ValueError("Input video is required")

            model = self.get_parameter_value("model")
            aspect_ratio = self.get_parameter_value("aspect_ratio")
            prompt = self.get_parameter_value("prompt")

            self.append_value_to_parameter("status", f"Using input video: {video_url}\n")
            self.append_value_to_parameter("status", "Creating reframe request...\n")

            # Build request parameters for the video_reframe generation type
            params = {
                "type": "video_reframe",
                "model": model,
                "aspect_ratio": aspect_ratio,
                "source": {"url": video_url, "media_type": mimetypes.guess_type(video_url)[0] or "video/mp4"},
            }

            # Add optional prompt
            if prompt:
                params["prompt"] = prompt.strip()
                self.append_value_to_parameter("status", f"Using prompt: {prompt.strip()}\n")

            # Add optional source position (normalized rectangle) if a width/height is provided
            w_norm = self.get_parameter_value("w_norm")
            h_norm = self.get_parameter_value("h_norm")
            if w_norm != 0 or h_norm != 0:
                source_position = {
                    "x_norm": self.get_parameter_value("x_norm"),
                    "y_norm": self.get_parameter_value("y_norm"),
                    "w_norm": w_norm,
                    "h_norm": h_norm,
                }
                params["video"] = {"source_position": source_position}
                self.append_value_to_parameter("status", f"Using source position: {source_position}\n")

            # Create reframe generation
            generation = await client.generations.create(**params)
            generation_id = generation.id

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")

            # Poll for completion
            self.append_value_to_parameter("status", "Waiting for reframe to complete...\n")

            completed = False
            max_attempts = 180  # Videos take longer than images
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(3)  # Longer wait for videos
                attempt += 1

                generation = await client.generations.get(generation_id=generation_id)

                if generation.state == "completed":
                    completed = True
                    self.append_value_to_parameter("status", f"Attempt {attempt}: Completed!\n")
                elif generation.state == "failed":
                    raise RuntimeError(f"Reframe failed: {generation.failure_reason}")
                else:
                    self.append_value_to_parameter("status", f"Attempt {attempt}: {generation.state}\n")

            if not completed:
                raise TimeoutError(f"Reframe timed out after {max_attempts} attempts")

            # Get video URL from the generation output list
            video_url = generation.output[0].url

            self.append_value_to_parameter("status", "Downloading reframed video...\n")
            video_bytes = self._download_video(video_url)

            # Save to project files
            dest = self._output_file.build_file()
            saved = dest.write_bytes(video_bytes)

            video_artifact = VideoUrlArtifact(value=saved.location)
            self.parameter_output_values["output_video"] = video_artifact
            self.publish_update_to_parameter("output_video", video_artifact)

            self.append_value_to_parameter(
                "status",
                f"✅ Reframe completed successfully!\nOriginal URL: {video_url}\n",
            )

        except Exception as e:
            error_msg = f"❌ Reframe failed: {str(e)}\n"
            self.append_value_to_parameter("status", error_msg)
            raise
        finally:
            # Cleanup uploaded artifacts
            self._public_input_video_parameter.delete_uploaded_artifact()

    def _download_video(self, video_url: str) -> bytes:
        """Download video from URL and return bytes."""
        return File(video_url).read_bytes()
