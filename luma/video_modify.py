import asyncio
import mimetypes
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


class LumaVideoModify(ControlNode):
    """Luma Labs Ray video modification node for style transfer and prompt-based editing."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        # Input video with public URL support
        self._public_input_video_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="input_video",
                tooltip="Input video to modify (max 18s, 100 MB max)",
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
            disclaimer_message="The Luma API service utilizes this URL to access the video for modification.",
        )
        self._public_input_video_parameter.add_input_parameters()

        self.add_parameter(
            Parameter(
                name="prompt",
                tooltip="Text description guiding how to modify the video",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Describe how you want to modify the video...",
                },
            )
        )

        self.add_parameter(
            Parameter(
                name="model",
                tooltip="Ray model to use for video editing.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="ray-3.2",
                traits={Options(choices=["ray-3.2"])},
                ui_options={"display_name": "Model"},
            )
        )

        self.add_parameter(
            Parameter(
                name="mode",
                tooltip="Modification mode: Adhere (subtle changes), Flex (balanced), Reimagine (dramatic changes)",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="flex_1",
                traits={
                    Options(
                        choices=[
                            "adhere_1",
                            "adhere_2",
                            "adhere_3",
                            "flex_1",
                            "flex_2",
                            "flex_3",
                            "reimagine_1",
                            "reimagine_2",
                            "reimagine_3",
                        ]
                    )
                },
                ui_options={"display_name": "Mode"},
            )
        )

        # First frame with public URL support
        self._public_first_frame_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="first_frame",
                tooltip="Optional: First frame image to guide the modification",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageUrlArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "clickable_file_browser": True,
                    "expander": True,
                    "file_browser_options": {
                        "extensions": [".png", ".jpg", ".jpeg"],
                        "allow_multiple": False,
                    },
                },
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the first frame image for video modification.",
        )
        self._public_first_frame_parameter.add_input_parameters()

        self.add_parameter(
            Parameter(
                name="output_video",
                tooltip="Modified video",
                output_type="VideoUrlArtifact",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
                ui_options={"pulse_on_run": True},
                settable=False,
            )
        )

        self.add_parameter(
            Parameter(
                name="status",
                tooltip="Modification status and progress",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"multiline": True, "pulse_on_run": True},
            )
        )

        self._output_file = ProjectFileParameter(
            node=self,
            name="output_file",
            default_filename="luma_modify.mp4",
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
            errors.append(ValueError(f"{self.name}: Provide an input video to modify."))

        prompt = self.get_parameter_value("prompt")
        if not prompt:
            errors.append(ValueError(f"{self.name}: Provide a prompt to guide the modification."))

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
        """Modify video using Luma async API."""
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

            prompt = self.get_parameter_value("prompt")
            if not prompt:
                raise ValueError("Prompt is required")

            model = self.get_parameter_value("model")
            mode = self.get_parameter_value("mode")

            self.append_value_to_parameter("status", f"Using input video: {video_url}\n")
            self.append_value_to_parameter("status", "Creating modification request...\n")

            # Build request parameters for the video_edit generation type.
            # The old `mode` values (adhere_/flex_/reimagine_) map 1:1 to the edit strength.
            video_options: dict = {"edit": {"strength": mode}}

            # Add optional first frame
            first_frame = self.get_parameter_value("first_frame")
            if first_frame:
                # Convert serialized dict back to artifact if needed
                if isinstance(first_frame, dict) and first_frame.get("value"):
                    first_frame = ImageUrlArtifact(
                        value=first_frame["value"], name=first_frame.get("name", "first_frame")
                    )
                    self.set_parameter_value("first_frame", first_frame)

                first_frame_url = self._public_first_frame_parameter.get_public_url_for_parameter()
                if first_frame_url:
                    video_options["start_frame"] = {"url": first_frame_url}
                    self.append_value_to_parameter("status", f"Using first frame: {first_frame_url}\n")

            params = {
                "type": "video_edit",
                "prompt": prompt.strip(),
                "model": model,
                "source": {"url": video_url, "media_type": mimetypes.guess_type(video_url)[0] or "video/mp4"},
                "video": video_options,
            }

            self.append_value_to_parameter("status", f"Using prompt: {prompt.strip()}\n")
            self.append_value_to_parameter("status", f"Using mode: {mode}\n")

            # Create modify generation
            generation = await client.generations.create(**params)
            generation_id = generation.id

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")

            # Poll for completion
            self.append_value_to_parameter("status", "Waiting for modification to complete...\n")

            completed = False
            max_attempts = 180  # Videos take longer
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(3)
                attempt += 1

                generation = await client.generations.get(generation_id=generation_id)

                if generation.state == "completed":
                    completed = True
                    self.append_value_to_parameter("status", f"Attempt {attempt}: Completed!\n")
                elif generation.state == "failed":
                    raise RuntimeError(f"Modification failed: {generation.failure_reason}")
                else:
                    self.append_value_to_parameter("status", f"Attempt {attempt}: {generation.state}\n")

            if not completed:
                raise TimeoutError(f"Modification timed out after {max_attempts} attempts")

            # Get video URL from the generation output list
            video_url = generation.output[0].url

            self.append_value_to_parameter("status", "Downloading modified video...\n")
            video_bytes = self._download_video(video_url)

            # Save to project files
            dest = self._output_file.build_file()
            saved = dest.write_bytes(video_bytes)

            video_artifact = VideoUrlArtifact(value=saved.location)
            self.parameter_output_values["output_video"] = video_artifact
            self.publish_update_to_parameter("output_video", video_artifact)

            self.append_value_to_parameter(
                "status",
                f"✅ Modification completed successfully!\nOriginal URL: {video_url}\n",
            )

        except Exception as e:
            error_msg = f"❌ Modification failed: {str(e)}\n"
            self.append_value_to_parameter("status", error_msg)
            raise
        finally:
            # Cleanup uploaded artifacts
            self._public_input_video_parameter.delete_uploaded_artifact()
            self._public_first_frame_parameter.delete_uploaded_artifact()

    def _download_video(self, video_url: str) -> bytes:
        """Download video from URL and return bytes."""
        return File(video_url).read_bytes()
