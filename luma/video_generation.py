import asyncio
from typing import Any

from griptape.artifacts import ImageUrlArtifact, VideoUrlArtifact
from griptape_nodes.exe_types.core_types import (
    Parameter,
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


class LumaVideoGeneration(ControlNode):
    """Luma Labs Ray video generation node supporting text-to-video and image-to-video."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

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
                traits={
                    Options(
                        choices=[
                            "1:1",
                            "3:4",
                            "4:3",
                            "9:16",
                            "16:9",
                            "21:9",
                        ]
                    )
                },
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

        # Start frame with public URL support
        self._public_start_frame_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="start_frame",
                tooltip="Optional: Starting frame image for image-to-video generation",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageUrlArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.OUTPUT},
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the image for video generation.",
        )
        self._public_start_frame_parameter.add_input_parameters()

        # End frame with public URL support
        self._public_end_frame_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="end_frame",
                tooltip="Optional: Ending frame image for controlled video generation",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageUrlArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.OUTPUT},
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the image for video generation.",
        )
        self._public_end_frame_parameter.add_input_parameters()

        self.add_parameter(
            Parameter(
                name="loop",
                tooltip="Whether to generate a looping video",
                type=ParameterTypeBuiltin.BOOL.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=False,
                ui_options={"display_name": "Loop Video"},
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

        prompt = self.get_parameter_value("prompt")
        if not prompt:
            errors.append(ValueError(f"{self.name}: Provide a prompt for video generation."))

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
        """Generate video using Luma async API."""
        client = None
        try:
            api_key = self._get_api_key()
            client = AsyncLuma(auth_token=api_key)

            prompt = self.get_parameter_value("prompt")
            if not prompt:
                raise ValueError("Prompt is required and cannot be empty")

            model = self.get_parameter_value("model")
            aspect_ratio = self.get_parameter_value("aspect_ratio")
            resolution = self.get_parameter_value("resolution")
            duration = self.get_parameter_value("duration")
            loop_video = self.get_parameter_value("loop")

            self.append_value_to_parameter("status", "Creating generation request...\n")

            # Build request parameters for the video generation type
            params = {
                "type": "video",
                "prompt": prompt.strip(),
                "model": model,
            }

            if aspect_ratio:
                params["aspect_ratio"] = aspect_ratio

            # Video-specific output settings live under the `video` options object
            video_options: dict = {
                "resolution": resolution,
                "duration": duration,
            }

            # Add loop if enabled
            if loop_video:
                video_options["loop"] = True
                self.append_value_to_parameter("status", "Loop mode enabled\n")

            # Add optional start and end frames
            start_frame = self.get_parameter_value("start_frame")
            if start_frame:
                # Convert serialized dicts back to artifacts if needed
                if isinstance(start_frame, dict) and start_frame.get("value"):
                    start_frame = ImageUrlArtifact(
                        value=start_frame["value"], name=start_frame.get("name", "start_frame")
                    )
                    self.set_parameter_value("start_frame", start_frame)

                start_frame_url = self._public_start_frame_parameter.get_public_url_for_parameter()
                if start_frame_url:
                    video_options["start_frame"] = {"url": start_frame_url}
                    self.append_value_to_parameter("status", f"Using start frame: {start_frame_url}\n")

            end_frame = self.get_parameter_value("end_frame")
            if end_frame:
                # Convert serialized dicts back to artifacts if needed
                if isinstance(end_frame, dict) and end_frame.get("value"):
                    end_frame = ImageUrlArtifact(value=end_frame["value"], name=end_frame.get("name", "end_frame"))
                    self.set_parameter_value("end_frame", end_frame)

                end_frame_url = self._public_end_frame_parameter.get_public_url_for_parameter()
                if end_frame_url:
                    video_options["end_frame"] = {"url": end_frame_url}
                    self.append_value_to_parameter("status", f"Using end frame: {end_frame_url}\n")

            params["video"] = video_options

            # Create generation
            generation = await client.generations.create(**params)
            generation_id = generation.id

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")

            # Poll for completion
            self.append_value_to_parameter("status", "Waiting for generation to complete...\n")

            completed = False
            max_attempts = 200
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(3)
                attempt += 1

                generation = await client.generations.get(generation_id=generation_id)

                if generation.state == "completed":
                    completed = True
                    self.append_value_to_parameter("status", f"Attempt {attempt}: Completed!\n")
                elif generation.state == "failed":
                    raise RuntimeError(f"Generation failed: {generation.failure_reason}")
                else:
                    self.append_value_to_parameter("status", f"Attempt {attempt}: {generation.state}\n")

            if not completed:
                raise TimeoutError(f"Generation timed out after {max_attempts} attempts")

            # Download and save video from the generation output list
            video_url = generation.output[0].url

            self.append_value_to_parameter("status", "Downloading generated video...\n")
            video_bytes = self._download_video(video_url)

            # Save to project files
            dest = self._output_file.build_file()
            saved = dest.write_bytes(video_bytes)

            video_artifact = VideoUrlArtifact(value=saved.location)
            self.parameter_output_values["video"] = video_artifact
            self.publish_update_to_parameter("video", video_artifact)

            self.append_value_to_parameter(
                "status",
                f"✅ Generation completed successfully!\nOriginal URL: {video_url}\n",
            )

        except Exception as e:
            error_msg = f"❌ Generation failed: {str(e)}\n"
            self.append_value_to_parameter("status", error_msg)
            raise
        finally:
            # Close the async client while the event loop is still alive to avoid
            # "Event loop is closed" errors when httpx is finalized during GC.
            if client is not None:
                await client.close()
            # Cleanup uploaded artifacts
            self._public_start_frame_parameter.delete_uploaded_artifact()
            self._public_end_frame_parameter.delete_uploaded_artifact()

    def _download_video(self, video_url: str) -> bytes:
        """Download video from URL and return bytes."""
        return File(video_url).read_bytes()
