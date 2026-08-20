import asyncio
from pathlib import Path
from typing import Any

from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.exe_types.core_types import (
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
from luma_utils.public_url_utils import build_public_url_list, cleanup_uploaded_paths

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMA_AGENTS_API_KEY"


class LumaImageEdit(SuccessFailureNode):
    """Edit a source image with Luma Labs AI using a prompt and optional additional reference images."""

    MAX_IMAGE_REFS = 8

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        self._image_ref_uploaded_paths: list[Path] = []

        self.add_parameter(
            Parameter(
                name="prompt",
                tooltip="Text description of the desired edit",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Describe how to edit the image...",
                },
            )
        )

        self.add_parameter(
            Parameter(
                name="model",
                tooltip="Image model to use. uni-1 is the default tier; uni-1-max is higher quality.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="uni-1",
                traits={Options(choices=["uni-1", "uni-1-max"])},
                ui_options={"display_name": "Model"},
            )
        )

        self.add_parameter(
            Parameter(
                name="output_format",
                tooltip="Output image format. jpeg produces smaller files; png supports lossless quality.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="jpeg",
                traits={Options(choices=["jpeg", "png"])},
                ui_options={"display_name": "Output Format"},
            )
        )

        # Source image — required. Aspect ratio is derived from the source image by the API.
        self._public_source_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="source_image",
                tooltip="Source image to edit. The output aspect ratio is derived from this image.",
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
                    "display_name": "Source Image",
                },
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the source image for editing.",
        )
        self._public_source_parameter.add_input_parameters()

        # Optional additional reference images to guide the edit (up to 8)
        self._image_refs_list = ParameterList(
            name="image_refs",
            tooltip=(
                "Optional additional reference images to guide the edit.\n"
                "Local images are automatically uploaded to Griptape Cloud for Luma API access.\n"
                "Up to 8 images supported."
            ),
            input_types=["ImageArtifact", "ImageUrlArtifact"],
            type="ImageUrlArtifact",
            allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            max_items=self.MAX_IMAGE_REFS,
            display_name="Additional References",
        )
        self.add_parameter(self._image_refs_list)
        self._image_refs_list.set_badge(
            variant="cloud-upload",
            title="Media Upload",
            message=self._public_source_parameter.get_help_message(),
            hide_clear_button=False,
        )

        self.add_parameter(
            Parameter(
                name="image",
                tooltip="Edited image",
                output_type="ImageUrlArtifact",
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
            default_filename="luma_image_edit.jpg",
        )
        self._output_file.add_parameter()
        self._create_status_parameters()

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        if parameter.name == "output_format":
            self._update_output_file_extension(value)

    def _update_output_file_extension(self, output_format: str) -> None:
        ext = ".png" if output_format == "png" else ".jpg"
        current = self.get_parameter_value("output_file") or self._output_file._default_filename
        if isinstance(current, str):
            p = Path(current)
            # Strip only known image extensions to avoid eating dotted stems (e.g. "render.v2")
            stem = p.with_suffix("").name if p.suffix.lower() in {".jpg", ".png"} else p.name
            new_name = stem + ext
            self._output_file._default_filename = new_name
            self.set_parameter_value("output_file", new_name)

    def _build_image_ref_params(self) -> list[dict]:
        """Build image_ref array for the Luma API, uploading local images as needed."""
        param_names = [p.name for p in self._image_refs_list.get_child_parameters()]
        storage_driver = self._public_source_parameter._storage_driver
        refs, self._image_ref_uploaded_paths = build_public_url_list(self, param_names, storage_driver)
        return refs

    def _cleanup_image_ref_uploads(self) -> None:
        cleanup_uploaded_paths(self._public_source_parameter._storage_driver, self._image_ref_uploaded_paths)
        self._image_ref_uploaded_paths = []

    def _get_api_key(self) -> str:
        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            raise ValueError(
                f"Luma API key not found. Please set the {API_KEY_ENV_VAR} environment variable.\n"
                "Get your API key from: https://platform.lumalabs.ai"
            )
        return api_key

    def validate_before_node_run(self) -> list[Exception] | None:
        errors = super().validate_before_node_run() or []

        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            errors.append(
                ValueError(
                    f"{self.name}: Luma API key not found. Please set the {API_KEY_ENV_VAR} environment variable."
                )
            )

        source_image = self.get_parameter_value("source_image")
        if not source_image:
            errors.append(ValueError(f"{self.name}: A source image is required for image editing."))

        return errors if errors else None

    def validate_before_workflow_run(self) -> list[Exception] | None:
        return self.validate_before_node_run()

    async def aprocess(self) -> None:
        """Edit image using Luma async API."""
        self._clear_execution_status()
        client = None
        try:
            try:
                api_key = self._get_api_key()
                client = AsyncLuma(auth_token=api_key)
            except Exception as e:
                raise RuntimeError(f"Setup failed: {e}") from e

            prompt = self.get_parameter_value("prompt") or ""
            model = self.get_parameter_value("model")
            output_format = self.get_parameter_value("output_format") or "jpeg"

            self.append_value_to_parameter("status", "Uploading source image...\n")
            try:
                source_image_val = self.get_parameter_value("source_image")
                if isinstance(source_image_val, dict) and source_image_val.get("value"):
                    source_image_val = ImageUrlArtifact(
                        value=source_image_val["value"], name=source_image_val.get("name", "source_image")
                    )
                    self.set_parameter_value("source_image", source_image_val)
                source_url = self._public_source_parameter.get_public_url_for_parameter()
                if not source_url:
                    raise ValueError("Source image is required and could not be resolved to a URL.")
            except Exception as e:
                raise RuntimeError(f"Failed to prepare source image: {e}") from e

            self.append_value_to_parameter("status", "Creating edit request...\n")

            # Build request parameters for the image_edit generation type
            params: dict[str, Any] = {
                "type": "image_edit",
                "model": model,
                "source": {"url": source_url},
                "output_format": output_format,
            }

            if prompt.strip():
                params["prompt"] = prompt.strip()

            # Add optional reference images
            try:
                image_refs = self._build_image_ref_params()
            except Exception as e:
                raise RuntimeError(f"Failed to prepare reference images: {e}") from e
            if image_refs:
                params["image_ref"] = image_refs
                self.append_value_to_parameter("status", f"Using {len(image_refs)} additional reference image(s)\n")

            try:
                generation = await client.generations.create(**params)
                generation_id = generation.id
            except Exception as e:
                raise RuntimeError(f"API request failed: {e}") from e

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")
            self.append_value_to_parameter("status", "Waiting for generation to complete...\n")

            # Poll for completion
            completed = False
            max_attempts = 120
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(2)
                attempt += 1

                try:
                    generation = await client.generations.get(generation_id=generation_id)
                except Exception as e:
                    raise RuntimeError(f"Polling error (attempt {attempt}): {e}") from e

                if generation.state == "completed":
                    completed = True
                    self.append_value_to_parameter("status", f"Attempt {attempt}: Completed!\n")
                elif generation.state == "failed":
                    raise RuntimeError(f"Generation failed: {generation.failure_reason}")
                else:
                    self.append_value_to_parameter("status", f"Attempt {attempt}: {generation.state}\n")

            if not completed:
                raise TimeoutError(f"Generation timed out after {max_attempts} attempts")

            # Get image URL from the generation output list
            image_url = ""
            try:
                image_url = generation.output[0].url
                self.append_value_to_parameter("status", "Downloading edited image...\n")
                image_bytes = File(image_url).read_bytes()
                # Save to project files — extension already synced by _update_output_file_extension
                dest = self._output_file.build_file()
                saved = dest.write_bytes(image_bytes)
                image_artifact = ImageUrlArtifact(value=saved.location, name=saved.name)
                self.set_parameter_value("image", image_artifact)
            except Exception as e:
                raise RuntimeError(f"Failed to save output: {e}") from e

            self.append_value_to_parameter(
                "status",
                f"✅ Edit completed successfully!\nOriginal URL: {image_url}\n",
            )
            self._set_status_results(was_successful=True, result_details="Edit completed successfully.")

        except Exception as e:
            self.append_value_to_parameter("status", f"❌ Edit failed: {str(e)}\n")
            self._set_status_results(was_successful=False, result_details=str(e))
            self._handle_failure_exception(e)
        finally:
            if client is not None:
                await client.close()
            # Cleanup uploaded artifacts
            self._public_source_parameter.delete_uploaded_artifact()
            self._cleanup_image_ref_uploads()
