import asyncio
import time
from typing import Any, Dict

import requests
from griptape.artifacts import VideoUrlArtifact, UrlArtifact
from griptape_nodes.exe_types.core_types import (
    Parameter,
    ParameterMode,
    ParameterTypeBuiltin,
    ParameterGroup,
)
from griptape_nodes.exe_types.node_types import ControlNode, AsyncResult
from griptape_nodes.exe_types.param_components.artifact_url.public_artifact_url_parameter import (
    PublicArtifactUrlParameter,
)
from griptape_nodes.traits.options import Options
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from lumaai import AsyncLumaAI

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMAAI_API_KEY"


class LumaVideoReframe(ControlNode):
    """Luma Labs Ray video reframing node for changing aspect ratios and extending videos."""

    def __init__(self, name: str, metadata: Dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        # Input video with public URL support
        self._public_input_video_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="input_video",
                tooltip="Input video to reframe (max 10s for ray-2, 30s for ray-flash-2, 100 MB max)",
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
                tooltip="Ray model to use. Ray 2 is higher quality (max 10s), Ray 2 Flash is faster (max 30s).",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="ray-2",
                traits={Options(choices=["ray-2", "ray-flash-2"])},
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
                traits={
                    Options(
                        choices=["1:1", "4:3", "3:4", "16:9", "9:16", "21:9", "9:21"]
                    )
                },
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

        # Advanced parameters group
        with ParameterGroup(name="Advanced") as advanced_group:
            Parameter(
                name="grid_position_x",
                tooltip="Grid position X (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="grid_position_y",
                tooltip="Grid position Y (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="x_start",
                tooltip="X coordinate where original video starts (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="x_end",
                tooltip="X coordinate where original video ends (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="y_start",
                tooltip="Y coordinate where original video starts (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="y_end",
                tooltip="Y coordinate where original video ends (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="resized_width",
                tooltip="Resized width of original video (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="resized_height",
                tooltip="Resized height of original video (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
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

    def _get_api_key(self) -> str:
        """Retrieve the Luma API key from configuration."""
        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            raise ValueError(
                f"Luma API key not found. Please set the {API_KEY_ENV_VAR} environment variable.\n"
                "Get your API key from: https://lumalabs.ai/dream-machine/api/keys"
            )
        return api_key


    def validate_before_node_run(self) -> list[Exception] | None:
        """Validate node configuration before execution."""
        errors = []

        input_video = self.get_parameter_value("input_video")
        if not input_video:
            errors.append(
                ValueError(f"{self.name}: Provide an input video to reframe.")
            )

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
            client = AsyncLumaAI(auth_token=api_key)

            # Convert serialized dict back to artifact if needed
            input_video = self.get_parameter_value("input_video")
            if isinstance(input_video, dict) and input_video.get('value'):
                # Create proper artifact from serialized dict
                input_video = VideoUrlArtifact(
                    value=input_video['value'],
                    name=input_video.get('name', 'input_video')
                )
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

            # Build request parameters
            params = {
                "media": {"url": video_url},
                "model": model,
                "aspect_ratio": aspect_ratio,
                "generation_type": "reframe_video",
            }

            # Add optional prompt
            if prompt:
                params["prompt"] = prompt.strip()
                self.append_value_to_parameter(
                    "status", f"Using prompt: {prompt.strip()}\n"
                )

            # Add advanced parameters if set (non-zero values)
            grid_position_x = self.get_parameter_value("grid_position_x")
            grid_position_y = self.get_parameter_value("grid_position_y")
            x_start = self.get_parameter_value("x_start")
            x_end = self.get_parameter_value("x_end")
            y_start = self.get_parameter_value("y_start")
            y_end = self.get_parameter_value("y_end")
            resized_width = self.get_parameter_value("resized_width")
            resized_height = self.get_parameter_value("resized_height")

            advanced_params = {}
            if grid_position_x != 0:
                advanced_params["grid_position_x"] = grid_position_x
            if grid_position_y != 0:
                advanced_params["grid_position_y"] = grid_position_y
            if x_start != 0:
                advanced_params["x_start"] = x_start
            if x_end != 0:
                advanced_params["x_end"] = x_end
            if y_start != 0:
                advanced_params["y_start"] = y_start
            if y_end != 0:
                advanced_params["y_end"] = y_end
            if resized_width != 0:
                advanced_params["resized_width"] = resized_width
            if resized_height != 0:
                advanced_params["resized_height"] = resized_height

            if advanced_params:
                params.update(advanced_params)
                self.append_value_to_parameter(
                    "status", f"Using advanced parameters: {advanced_params}\n"
                )

            # Create reframe generation
            generation = await client.generations.video.reframe(**params)
            generation_id = generation.id

            self.append_value_to_parameter(
                "status", f"Request created with ID: {generation_id}\n"
            )

            # Poll for completion
            self.append_value_to_parameter(
                "status", "Waiting for reframe to complete...\n"
            )

            completed = False
            max_attempts = 180  # Videos take longer than images
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(3)  # Longer wait for videos
                attempt += 1

                generation = await client.generations.get(id=generation_id)

                if generation.state == "completed":
                    completed = True
                    self.append_value_to_parameter(
                        "status", f"Attempt {attempt}: Completed!\n"
                    )
                elif generation.state == "failed":
                    raise RuntimeError(f"Reframe failed: {generation.failure_reason}")
                else:
                    self.append_value_to_parameter(
                        "status", f"Attempt {attempt}: {generation.state}\n"
                    )

            if not completed:
                raise TimeoutError(f"Reframe timed out after {max_attempts} attempts")

            # Get video URL
            video_url = generation.assets.video

            self.append_value_to_parameter("status", "Downloading reframed video...\n")
            video_bytes = self._download_video(video_url)

            # Save to static files
            timestamp = int(time.time() * 1000)
            filename = f"luma_reframe_{timestamp}.mp4"
            static_url = GriptapeNodes.StaticFilesManager().save_static_file(
                video_bytes, filename
            )

            video_artifact = VideoUrlArtifact(value=static_url)
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
        try:
            response = requests.get(video_url, timeout=120)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise ValueError(f"Failed to download video from URL: {str(e)}")

