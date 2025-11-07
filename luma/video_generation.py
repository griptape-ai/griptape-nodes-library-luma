import asyncio
import time
from typing import Any, Dict

import requests
from griptape.artifacts import VideoUrlArtifact, ImageArtifact, ImageUrlArtifact
from griptape_nodes.exe_types.core_types import (
    Parameter,
    ParameterMode,
    ParameterTypeBuiltin,
)
from griptape_nodes.exe_types.node_types import ControlNode, AsyncResult
from griptape_nodes.traits.options import Options
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from lumaai import AsyncLumaAI

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMAAI_API_KEY"


class LumaVideoGeneration(ControlNode):
    """Luma Labs Ray 2 video generation node supporting text-to-video and image-to-video."""

    def __init__(self, name: str, metadata: Dict[Any, Any] | None = None) -> None:
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
                tooltip="Ray 2 model to use. Ray 2 is higher quality, Ray 2 Flash is faster.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="ray-2",
                traits={Options(choices=["ray-2", "ray-flash-2", "ray-1-6"])},
                ui_options={"display_name": "Model"},
            )
        )

        self.add_parameter(
            Parameter(
                name="resolution",
                tooltip="Video resolution. Higher resolutions take longer to generate.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="720p",
                traits={Options(choices=["540p", "720p", "1080p", "4k"])},
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
                name="start_frame",
                tooltip="Optional: Starting frame image for image-to-video generation",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.OUTPUT},
            )
        )

        self.add_parameter(
            Parameter(
                name="end_frame",
                tooltip="Optional: Ending frame image for controlled video generation",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.OUTPUT},
            )
        )

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

    def _get_api_key(self) -> str:
        """Retrieve the Luma API key from configuration."""
        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            raise ValueError(
                f"Luma API key not found. Please set the {API_KEY_ENV_VAR} environment variable.\n"
                "Get your API key from: https://lumalabs.ai/dream-machine/api/keys"
            )
        return api_key

    def _get_image_url_for_api(self, image_artifact: ImageArtifact | ImageUrlArtifact | None) -> str | None:
        """Convert ImageArtifact or ImageUrlArtifact to a public URL for Luma API."""
        if image_artifact is None:
            return None
        
        if isinstance(image_artifact, ImageArtifact):
            # Save artifact bytes to get public URL
            image_bytes = image_artifact.to_bytes()
            timestamp = int(time.time() * 1000)
            filename = f"luma_frame_{timestamp}.jpg"
            return GriptapeNodes.StaticFilesManager().save_static_file(image_bytes, filename)
        
        elif isinstance(image_artifact, ImageUrlArtifact):
            url = image_artifact.value
            # Check if localhost URL - needs conversion to public URL
            if 'localhost' in url or '127.0.0.1' in url:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                image_bytes = response.content
                timestamp = int(time.time() * 1000)
                filename = f"luma_frame_{timestamp}.jpg"
                return GriptapeNodes.StaticFilesManager().save_static_file(image_bytes, filename)
            # Public URL - use directly
            return url
        
        return None

    def validate_before_node_run(self) -> list[Exception] | None:
        """Validate node configuration before execution."""
        errors = []

        prompt = self.get_parameter_value("prompt")
        if not prompt:
            errors.append(
                ValueError(f"{self.name}: Provide a prompt for video generation.")
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
        """Generate video using Luma async API."""
        try:
            api_key = self._get_api_key()
            client = AsyncLumaAI(auth_token=api_key)

            prompt = self.get_parameter_value("prompt")
            if not prompt:
                raise ValueError("Prompt is required and cannot be empty")

            model = self.get_parameter_value("model")
            resolution = self.get_parameter_value("resolution")
            duration = self.get_parameter_value("duration")
            loop_video = self.get_parameter_value("loop")

            self.append_value_to_parameter("status", "Creating generation request...\n")

            # Build request parameters
            params = {
                "prompt": prompt.strip(),
                "model": model,
            }

            # Add resolution and duration for Ray 2 models
            if model in ["ray-2", "ray-flash-2"]:
                params["resolution"] = resolution
                params["duration"] = duration

            # Add loop if enabled
            if loop_video:
                params["loop"] = True
                self.append_value_to_parameter("status", "Loop mode enabled\n")

            # Build keyframes if start or end frame provided
            keyframes = {}
            start_frame = self.get_parameter_value("start_frame")
            end_frame = self.get_parameter_value("end_frame")

            if start_frame:
                start_frame_url = self._get_image_url_for_api(start_frame)
                if start_frame_url:
                    keyframes["frame0"] = {"type": "image", "url": start_frame_url}
                    self.append_value_to_parameter(
                        "status", f"Using start frame: {start_frame_url}\n"
                    )

            if end_frame:
                end_frame_url = self._get_image_url_for_api(end_frame)
                if end_frame_url:
                    keyframes["frame1"] = {"type": "image", "url": end_frame_url}
                    self.append_value_to_parameter(
                        "status", f"Using end frame: {end_frame_url}\n"
                    )

            if keyframes:
                params["keyframes"] = keyframes

            # Create generation
            generation = await client.generations.create(**params)
            generation_id = generation.id

            self.append_value_to_parameter(
                "status", f"Request created with ID: {generation_id}\n"
            )

            # Poll for completion
            self.append_value_to_parameter(
                "status", "Waiting for generation to complete...\n"
            )

            completed = False
            max_attempts = 200
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(3)
                attempt += 1

                generation = await client.generations.get(id=generation_id)

                if generation.state == "completed":
                    completed = True
                    self.append_value_to_parameter(
                        "status", f"Attempt {attempt}: Completed!\n"
                    )
                elif generation.state == "failed":
                    raise RuntimeError(
                        f"Generation failed: {generation.failure_reason}"
                    )
                else:
                    self.append_value_to_parameter(
                        "status", f"Attempt {attempt}: {generation.state}\n"
                    )

            if not completed:
                raise TimeoutError(
                    f"Generation timed out after {max_attempts} attempts"
                )

            # Download and save video
            video_url = generation.assets.video

            self.append_value_to_parameter("status", "Downloading generated video...\n")
            video_bytes = self._download_video(video_url)

            # Save to static files
            timestamp = int(time.time() * 1000)
            filename = f"luma_ray2_{timestamp}.mp4"
            static_url = GriptapeNodes.StaticFilesManager().save_static_file(
                video_bytes, filename
            )

            video_artifact = VideoUrlArtifact(value=static_url)
            self.parameter_output_values["video"] = video_artifact

            self.append_value_to_parameter(
                "status",
                f"✅ Generation completed successfully!\nOriginal URL: {video_url}\n",
            )

        except Exception as e:
            error_msg = f"❌ Generation failed: {str(e)}\n"
            self.append_value_to_parameter("status", error_msg)
            raise

    def _download_video(self, video_url: str) -> bytes:
        """Download video from URL and return bytes."""
        try:
            response = requests.get(video_url, timeout=60)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise ValueError(f"Failed to download video from URL: {str(e)}")

