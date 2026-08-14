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
from utils.connection_utils import disconnect_param_list_incoming
from utils.public_url_utils import build_public_url_list, cleanup_uploaded_paths

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMA_AGENTS_API_KEY"


class LumaImageGeneration(SuccessFailureNode):
    """Generate images with Luma Labs using text prompts and optional style/content reference images."""

    MAX_IMAGE_REFS = 9

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        self._image_ref_uploaded_paths: list[Path] = []

        self.add_parameter(
            Parameter(
                name="prompt",
                tooltip="Text description of the desired image",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Describe the image you want to generate...",
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

        self.add_parameter(
            Parameter(
                name="aspect_ratio",
                tooltip="Desired aspect ratio for the generated image",
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
                name="reference_type",
                tooltip="Use reference images to guide style and content of the generated image.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="none",
                traits={
                    Options(
                        choices=[
                            "none",
                            "image_reference",
                        ]
                    )
                },
                ui_options={"display_name": "Reference Type"},
            )
        )

        # --- image_reference mode: up to 9 images sent as image_ref array ---
        self._image_refs_list = ParameterList(
            name="image_refs",
            tooltip=(
                "Reference images for guided generation. Each image influences the style or content of the output.\n"
                "Local images are automatically uploaded to Griptape Cloud for Luma API access.\n"
                "Up to 9 images supported."
            ),
            input_types=["ImageArtifact", "ImageUrlArtifact"],
            type="ImageUrlArtifact",
            allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            max_items=self.MAX_IMAGE_REFS,
            display_name="Reference Images",
            hide=True,
        )
        self.add_parameter(self._image_refs_list)

        # Internal: not exposed as a node parameter — used only for GTC storage driver access
        # when uploading image_refs list items.
        self._public_reference_image_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="_image_ref_storage",
                type="ImageUrlArtifact",
                allowed_modes=set(),
            ),
            disclaimer_message="",
        )

        self.add_parameter(
            Parameter(
                name="image",
                tooltip="Generated image",
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
            default_filename="luma_image.jpg",
        )
        self._output_file.add_parameter()
        self._create_status_parameters()

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        if parameter.name == "output_format":
            self._update_output_file_extension(value)
        elif parameter.name == "reference_type":
            self._apply_reference_type(value)

    def _update_output_file_extension(self, output_format: str) -> None:
        ext = ".png" if output_format == "png" else ".jpg"
        current = self.get_parameter_value("output_file") or self._output_file._default_filename
        if isinstance(current, str):
            new_name = Path(current).with_suffix(ext).name
            self._output_file._default_filename = new_name
            self.set_parameter_value("output_file", new_name)

    def _apply_reference_type(self, mode: str) -> None:
        if mode == "image_reference":
            self.show_parameter_by_name(["image_refs"])
        else:  # "none"
            disconnect_param_list_incoming(self, self._image_refs_list)
            self.hide_parameter_by_name(["image_refs"])

    def _build_image_ref_params(self) -> list[dict]:
        """Build image_ref array for the Luma API, uploading local images as needed."""
        param_names = [p.name for p in self._image_refs_list.get_child_parameters()]
        storage_driver = self._public_reference_image_parameter._storage_driver
        refs, self._image_ref_uploaded_paths = build_public_url_list(self, param_names, storage_driver)
        return refs

    def _cleanup_image_ref_uploads(self) -> None:
        cleanup_uploaded_paths(self._public_reference_image_parameter._storage_driver, self._image_ref_uploaded_paths)
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
        """Validate node configuration before execution."""
        errors = []

        prompt = self.get_parameter_value("prompt")
        if not prompt:
            errors.append(ValueError(f"{self.name}: Provide a prompt for image generation."))

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

    async def aprocess(self) -> None:
        """Generate image using Luma async API."""
        self._clear_execution_status()
        client = None
        try:
            try:
                api_key = self._get_api_key()
                client = AsyncLuma(auth_token=api_key)
            except Exception as e:
                raise RuntimeError(f"Setup failed: {e}") from e

            prompt = self.get_parameter_value("prompt")
            if not prompt:
                raise ValueError("Prompt is required and cannot be empty")

            model = self.get_parameter_value("model")
            output_format = self.get_parameter_value("output_format") or "jpeg"
            aspect_ratio = self.get_parameter_value("aspect_ratio")

            self.append_value_to_parameter("status", "Creating generation request...\n")

            # Build request parameters. Default to a text-to-image generation.
            params = {
                "type": "image",
                "prompt": prompt.strip(),
                "model": model,
                "aspect_ratio": aspect_ratio,
                "output_format": output_format,
            }

            # Add reference image based on selected type
            reference_type = self.get_parameter_value("reference_type")

            if reference_type == "image_reference":
                # Reference image guides a fresh generation
                try:
                    image_refs = self._build_image_ref_params()
                except Exception as e:
                    raise RuntimeError(f"Failed to prepare reference images: {e}") from e
                if image_refs:
                    params["image_ref"] = image_refs
                    self.append_value_to_parameter("status", f"Using {len(image_refs)} reference image(s)\n")
                else:
                    self.append_value_to_parameter(
                        "status",
                        "⚠️ Reference type set to 'image_reference' but no images provided. Proceeding without reference.\n",
                    )

            # Create generation
            try:
                generation = await client.generations.create(**params)
                generation_id = generation.id
            except Exception as e:
                raise RuntimeError(f"API request failed: {e}") from e

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")

            # Poll for completion
            self.append_value_to_parameter("status", "Waiting for generation to complete...\n")

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

            # Download and save image from the generation output list
            image_url = ""
            try:
                image_url = generation.output[0].url
                self.append_value_to_parameter("status", "Downloading generated image...\n")
                image_bytes = self._download_image(image_url)
                # Save to project files — use extension matching the requested format
                ext = ".png" if output_format == "png" else ".jpg"
                self._output_file._default_filename = f"luma_image{ext}"
                dest = self._output_file.build_file()
                saved = dest.write_bytes(image_bytes)
                image_artifact = ImageUrlArtifact(value=saved.location, name=saved.name)
                self.set_parameter_value("image", image_artifact)
            except Exception as e:
                raise RuntimeError(f"Failed to save output: {e}") from e

            self.append_value_to_parameter(
                "status",
                f"✅ Generation completed successfully!\nOriginal URL: {image_url}\n",
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
            self._cleanup_image_ref_uploads()

    def _download_image(self, image_url: str) -> bytes:
        """Download image from URL and return bytes."""
        return File(image_url).read_bytes()
