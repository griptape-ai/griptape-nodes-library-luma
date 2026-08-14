import asyncio
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

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMA_AGENTS_API_KEY"
MAX_PROMPT_LEN = 500


class LumaImageLayer(SuccessFailureNode):
    """Decompose a source image into 1–10 semantic RGBA PNG layers using the Luma Labs layering API."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        self.add_parameter(
            Parameter(
                name="prompt",
                tooltip=f"Optional text description to guide how layers are separated. Maximum {MAX_PROMPT_LEN} characters.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Optionally describe how to separate the layers...",
                },
            )
        )

        # Source image — required
        self._public_source_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="source_image",
                tooltip="Source image to decompose into layers.",
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
                    "display_name": "Source Image",
                },
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the source image for layering.",
        )
        self._public_source_parameter.add_input_parameters()

        self.add_parameter(
            Parameter(
                name="resolution",
                tooltip="Output resolution for the generated layers.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="1k",
                traits={Options(choices=["1k", "2k"])},
                ui_options={"display_name": "Resolution"},
            )
        )

        # Dynamic output layers — populated after generation completes
        self._layers_list = ParameterList(
            name="layers",
            tooltip="Output RGBA PNG layers produced by the Luma layering API (1–10 layers).",
            output_type="ImageUrlArtifact",
            allowed_modes={ParameterMode.OUTPUT},
            display_name="Output Layers",
        )
        self.add_parameter(self._layers_list)

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
            default_filename="luma_layer.png",
        )
        self._output_file.add_parameter()
        self._create_status_parameters()

    def _get_api_key(self) -> str:
        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            raise ValueError(
                f"Luma API key not found. Please set the {API_KEY_ENV_VAR} environment variable.\n"
                "Get your API key from: https://platform.lumalabs.ai"
            )
        return api_key

    def validate_before_node_run(self) -> list[Exception] | None:
        errors = []

        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        if not api_key:
            errors.append(
                ValueError(
                    f"{self.name}: Luma API key not found. Please set the {API_KEY_ENV_VAR} environment variable."
                )
            )

        source_image = self.get_parameter_value("source_image")
        if not source_image:
            errors.append(ValueError(f"{self.name}: A source image is required for layering."))

        prompt = self.get_parameter_value("prompt") or ""
        if len(prompt) > MAX_PROMPT_LEN:
            errors.append(
                ValueError(f"{self.name}: Prompt exceeds {MAX_PROMPT_LEN} character limit ({len(prompt)} characters).")
            )

        return errors if errors else None

    def validate_before_workflow_run(self) -> list[Exception] | None:
        return self.validate_before_node_run()

    async def aprocess(self) -> None:
        """Decompose image into semantic layers using Luma async API."""
        self._clear_execution_status()
        client = None
        try:
            try:
                api_key = self._get_api_key()
                client = AsyncLuma(auth_token=api_key)
            except Exception as e:
                raise RuntimeError(f"Setup failed: {e}") from e

            prompt = self.get_parameter_value("prompt") or ""
            resolution = self.get_parameter_value("resolution") or "1k"

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

            self.append_value_to_parameter("status", "Creating layering request...\n")

            # Build request parameters for the layering generation type
            params: dict[str, Any] = {
                "type": "layering",
                "model": "uni-1",
                "source": {"url": source_url},
                "layering": {"resolution": resolution},
            }

            # Add optional prompt
            if prompt.strip():
                params["prompt"] = prompt.strip()

            try:
                generation = await client.generations.create(**params)
                generation_id = generation.id
            except Exception as e:
                raise RuntimeError(f"API request failed: {e}") from e

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")
            self.append_value_to_parameter("status", "Waiting for layering to complete...\n")

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

            # Sort layers by index and download each to the project file store
            sorted_outputs: list = []
            try:
                outputs = generation.output or []
                sorted_outputs = sorted(outputs, key=lambda o: o.layer.index if o.layer else 0)
                self.append_value_to_parameter("status", f"Downloading {len(sorted_outputs)} layer(s)...\n")
                self._layers_list.clear_list()
                for i, output in enumerate(sorted_outputs):
                    layer_bytes = File(output.url).read_bytes()
                    dest = self._output_file.build_file(_index=i + 1)
                    saved = dest.write_bytes(layer_bytes)
                    layer_artifact = ImageUrlArtifact(value=saved.location, name=saved.name)
                    child = self._layers_list.add_child_parameter()
                    self.set_parameter_value(child.name, layer_artifact)
                    if output.layer:
                        self.append_value_to_parameter(
                            "status",
                            f"Layer {output.layer.index}: {output.layer.label} — {output.layer.description}\n",
                        )
                    else:
                        self.append_value_to_parameter("status", f"Layer {i + 1}: saved\n")
            except Exception as e:
                raise RuntimeError(f"Failed to save output layers: {e}") from e

            self.append_value_to_parameter(
                "status",
                f"✅ Layering completed! {len(sorted_outputs)} layer(s) produced.\n",
            )
            self._set_status_results(
                was_successful=True,
                result_details=f"Layering completed. {len(sorted_outputs)} layer(s) produced.",
            )

        except Exception as e:
            self.append_value_to_parameter("status", f"❌ Layering failed: {str(e)}\n")
            self._set_status_results(was_successful=False, result_details=str(e))
            self._handle_failure_exception(e)
        finally:
            if client is not None:
                await client.close()
            # Cleanup uploaded artifacts
            self._public_source_parameter.delete_uploaded_artifact()
