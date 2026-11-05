import asyncio
import mimetypes
from typing import Any

from griptape.artifacts import ImageUrlArtifact, VideoUrlArtifact
from griptape_nodes.exe_types.core_types import (
    NodeError,
    Parameter,
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

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMA_AGENTS_API_KEY"


class LumaVideoModify(SuccessFailureNode):
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
                        "extensions": [".png", ".jpg"],
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
        self._create_status_parameters()

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

        if not self.get_parameter_value("input_video"):
            errors.append(input_error("Connect a video to 'Input Video'.", "input_video"))

        if not self.get_parameter_value("prompt"):
            errors.append(input_error("Enter a prompt in 'Prompt' to describe the change.", "prompt"))

        return errors or None

    async def aprocess(self) -> None:
        """Modify video using Luma async API."""
        self._clear_execution_status()
        client = None
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
            try:
                video_url = self._public_input_video_parameter.get_public_url_for_parameter()
            except NodeError:
                raise
            except Exception as e:
                msg = f"Could not prepare 'Input Video' for Luma: {e}"
                raise input_error(msg, "input_video") from e
            if not video_url:
                raise input_error("Connect a video to 'Input Video'.", "input_video")

            prompt = self.get_parameter_value("prompt")
            if not prompt:
                raise input_error("Enter a prompt in 'Prompt' to describe the change.", "prompt")

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

                try:
                    first_frame_url = self._public_first_frame_parameter.get_public_url_for_parameter()
                except NodeError:
                    raise
                except Exception as e:
                    msg = f"Could not prepare 'First Frame' for Luma: {e}"
                    raise input_error(msg, "first_frame") from e
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
            try:
                generation = await client.generations.create(**params)
                generation_id = generation.id
            except Exception as e:
                raise error_from_api_exception(e) from e

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")

            # Poll for completion
            self.append_value_to_parameter("status", "Waiting for modification to complete...\n")

            completed = False
            max_attempts = 180  # Videos take longer
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

            # Get video URL from the generation output list
            if not generation.output:
                raise generation_error(
                    generation,
                    "Luma reported the generation as completed but returned no output file. Run the node again.",
                )
            output_video_url = ""
            try:
                output_video_url = generation.output[0].url
                self.append_value_to_parameter("status", "Downloading modified video...\n")
                video_bytes = self._download_video(output_video_url)
                # Save to project files
                dest = self._output_file.build_file()
                saved = dest.write_bytes(video_bytes)
                video_artifact = VideoUrlArtifact(value=saved.location)
                self.parameter_output_values["output_video"] = video_artifact
                self.publish_update_to_parameter("output_video", video_artifact)
            except Exception as e:
                msg = f"Could not download or save the file Luma produced: {e}"
                raise NodeError(msg, fields={"generation_id": generation_id}) from e

            self.append_value_to_parameter(
                "status",
                f"✅ Modification completed successfully!\nOriginal URL: {output_video_url}\n",
            )
            self._set_status_results(was_successful=True, result_details="Modification completed successfully.")

        except Exception as e:
            self.append_value_to_parameter("status", f"❌ Modification failed: {str(e)}\n")
            self._set_status_results(was_successful=False, result_details=str(e))
            self._handle_failure_exception(e)
        finally:
            if client is not None:
                await client.close()
            # Cleanup uploaded artifacts
            self._public_input_video_parameter.delete_uploaded_artifact()
            self._public_first_frame_parameter.delete_uploaded_artifact()

    def _download_video(self, video_url: str) -> bytes:
        """Download video from URL and return bytes."""
        return File(video_url).read_bytes()
