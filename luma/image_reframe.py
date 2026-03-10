import asyncio
import time
from typing import Any, Dict

from griptape.artifacts import ImageUrlArtifact, ImageArtifact
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
from griptape_nodes.retained_mode.events.os_events import ExistingFilePolicy
from griptape_nodes.files.file import File, FileLoadError
from lumaai import AsyncLumaAI

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMAAI_API_KEY"


class LumaImageReframe(ControlNode):
    """Luma Labs Photon image reframing node for changing aspect ratios and extending images."""

    def __init__(self, name: str, metadata: Dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        # Input image with public URL support
        self._public_input_image_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="input_image",
                tooltip="Input image to reframe",
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
            disclaimer_message="The Luma API service utilizes this URL to access the image for reframing.",
        )
        self._public_input_image_parameter.add_input_parameters()

        self.add_parameter(
            Parameter(
                name="model",
                tooltip="Photon model to use. photon-1 is default, photon-flash-1 is faster.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="photon-1",
                traits={Options(choices=["photon-1", "photon-flash-1"])},
                ui_options={"display_name": "Model"},
            )
        )

        self.add_parameter(
            Parameter(
                name="aspect_ratio",
                tooltip="Target aspect ratio for the reframed image",
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
                tooltip="X coordinate where original image starts (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="x_end",
                tooltip="X coordinate where original image ends (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="y_start",
                tooltip="Y coordinate where original image starts (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="y_end",
                tooltip="Y coordinate where original image ends (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="resized_width",
                tooltip="Resized width of original image (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

            Parameter(
                name="resized_height",
                tooltip="Resized height of original image (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0,
            )

        advanced_group.ui_options = {"collapsed": True}
        self.add_node_element(advanced_group)

        self.add_parameter(
            Parameter(
                name="output_image",
                tooltip="Reframed image",
                output_type="ImageUrlArtifact",
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

        input_image = self.get_parameter_value("input_image")
        if not input_image:
            errors.append(
                ValueError(f"{self.name}: Provide an input image to reframe.")
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
        """Reframe image using Luma async API."""
        try:
            api_key = self._get_api_key()
            client = AsyncLumaAI(auth_token=api_key)

            # Convert serialized dict back to artifact if needed
            input_image = self.get_parameter_value("input_image")
            if isinstance(input_image, dict) and input_image.get('value'):
                # Create proper artifact from serialized dict
                input_image = ImageUrlArtifact(
                    value=input_image['value'],
                    name=input_image.get('name', 'input_image')
                )
                # Update the parameter with the artifact object
                self.set_parameter_value("input_image", input_image)
            
            # Let PublicArtifactUrlParameter handle getting and converting the artifact
            image_url = self._public_input_image_parameter.get_public_url_for_parameter()
            if not image_url:
                raise ValueError("Input image is required")

            model = self.get_parameter_value("model")
            aspect_ratio = self.get_parameter_value("aspect_ratio")
            prompt = self.get_parameter_value("prompt")

            self.append_value_to_parameter("status", f"Using input image: {image_url}\n")
            self.append_value_to_parameter("status", "Creating reframe request...\n")

            # Build request parameters
            params = {
                "media": {"url": image_url},
                "model": model,
                "aspect_ratio": aspect_ratio,
                "generation_type": "reframe_image",
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
            generation = await client.generations.image.reframe(**params)
            generation_id = generation.id

            self.append_value_to_parameter(
                "status", f"Request created with ID: {generation_id}\n"
            )

            # Poll for completion
            self.append_value_to_parameter(
                "status", "Waiting for reframe to complete...\n"
            )

            completed = False
            max_attempts = 120
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(2)
                attempt += 1

                generation = await client.generations.get(id=generation_id)

                if generation.state == "completed":
                    completed = True
                    self.append_value_to_parameter(
                        "status", f"Attempt {attempt}: Completed!\n"
                    )
                elif generation.state == "failed":
                    raise RuntimeError(
                        f"Reframe failed: {generation.failure_reason}"
                    )
                else:
                    self.append_value_to_parameter(
                        "status", f"Attempt {attempt}: {generation.state}\n"
                    )

            if not completed:
                raise TimeoutError(
                    f"Reframe timed out after {max_attempts} attempts"
                )

            # Download and save image
            image_url = generation.assets.image

            self.append_value_to_parameter("status", "Downloading reframed image...\n")
            image_bytes = self._download_image(image_url)

            # Save to static files
            timestamp = int(time.time() * 1000)
            filename = f"luma_reframe_{timestamp}.jpg"
            static_url = GriptapeNodes.StaticFilesManager().save_static_file(
                image_bytes, filename, ExistingFilePolicy.CREATE_NEW
            )

            image_artifact = ImageUrlArtifact(
                value=static_url, name=f"luma_reframe_{timestamp}"
            )
            self.parameter_output_values["output_image"] = image_artifact
            self.publish_update_to_parameter("output_image", image_artifact)

            self.append_value_to_parameter(
                "status",
                f"✅ Reframe completed successfully!\nOriginal URL: {image_url}\n",
            )

        except Exception as e:
            error_msg = f"❌ Reframe failed: {str(e)}\n"
            self.append_value_to_parameter("status", error_msg)
            raise
        finally:
            # Cleanup uploaded artifacts
            self._public_input_image_parameter.delete_uploaded_artifact()

    def _download_image(self, image_url: str) -> bytes:
        """Download image from URL and return bytes."""
        return File(image_url).read_bytes()

