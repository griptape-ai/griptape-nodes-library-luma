import asyncio
import time
from typing import Any, Dict

import requests
from griptape.artifacts import ImageUrlArtifact, ImageArtifact
from griptape_nodes.exe_types.core_types import (
    Parameter,
    ParameterMode,
    ParameterTypeBuiltin,
)
from griptape_nodes.exe_types.node_types import ControlNode, AsyncResult
from griptape_nodes.traits.options import Options
from griptape_nodes.traits.slider import Slider
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from lumaai import AsyncLumaAI

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMAAI_API_KEY"


class LumaImageGeneration(ControlNode):
    """Luma Labs Photon image generation node supporting text-to-image, image references, style references, character references, and image modification."""

    def __init__(self, name: str, metadata: Dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

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
                            "9:21",
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
                tooltip="Type of reference image to use for generation",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="none",
                traits={
                    Options(
                        choices=[
                            "none",
                            "image_reference",
                            "style_reference",
                            "character_reference",
                            "modify_image",
                        ]
                    )
                },
                ui_options={"display_name": "Reference Type"},
            )
        )

        self.add_parameter(
            Parameter(
                name="reference_image",
                tooltip="Optional: Reference image (type determined by Reference Type above)",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageArtifact",
                allowed_modes={ParameterMode.INPUT, ParameterMode.OUTPUT},
                ui_options={"hide": True},
            )
        )

        self.add_parameter(
            Parameter(
                name="reference_weight",
                tooltip="Weight/influence of reference image (0.0-1.0). Not used for character reference.",
                type=ParameterTypeBuiltin.FLOAT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=0.85,
                traits={Slider(min_val=0.0, max_val=1.0)},
                ui_options={"hide": True},
            )
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

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        """Update reference weight default and parameter visibility when reference type changes."""
        if parameter.name == "reference_type":
            if value == "none":
                # Hide both parameters when none is selected
                self.hide_parameter_by_name(["reference_image", "reference_weight"])
            
            elif value == "character_reference":
                # Show only reference_image for character reference (doesn't use weight)
                self.show_parameter_by_name(["reference_image"])
                self.hide_parameter_by_name(["reference_weight"])
            
            elif value in ["image_reference", "style_reference", "modify_image"]:
                # Show both parameters for these reference types
                self.show_parameter_by_name(["reference_image", "reference_weight"])
                
                # Set appropriate default weight based on reference type
                if value == "image_reference":
                    self.set_parameter_value("reference_weight", 0.85)
                elif value == "style_reference":
                    self.set_parameter_value("reference_weight", 0.8)
                elif value == "modify_image":
                    self.set_parameter_value("reference_weight", 1.0)

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
            filename = f"luma_ref_{timestamp}.jpg"
            return GriptapeNodes.StaticFilesManager().save_static_file(image_bytes, filename)
        
        elif isinstance(image_artifact, ImageUrlArtifact):
            url = image_artifact.value
            # Check if localhost URL - needs conversion to public URL
            if 'localhost' in url or '127.0.0.1' in url:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                image_bytes = response.content
                timestamp = int(time.time() * 1000)
                filename = f"luma_ref_{timestamp}.jpg"
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
                ValueError(f"{self.name}: Provide a prompt for image generation.")
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
        """Generate image using Luma async API."""
        try:
            api_key = self._get_api_key()
            client = AsyncLumaAI(auth_token=api_key)

            prompt = self.get_parameter_value("prompt")
            if not prompt:
                raise ValueError("Prompt is required and cannot be empty")

            model = self.get_parameter_value("model")
            aspect_ratio = self.get_parameter_value("aspect_ratio")

            self.append_value_to_parameter("status", "Creating generation request...\n")

            # Build request parameters
            params = {
                "prompt": prompt.strip(),
                "model": model,
                "aspect_ratio": aspect_ratio,
            }

            # Add reference image based on selected type
            reference_type = self.get_parameter_value("reference_type")
            reference_image = self.get_parameter_value("reference_image")
            
            if reference_type != "none" and reference_image:
                reference_url = self._get_image_url_for_api(reference_image)
                if reference_url:
                    reference_weight = self.get_parameter_value("reference_weight")
                    
                    if reference_type == "image_reference":
                        params["image_ref"] = [
                            {
                                "url": reference_url,
                                "weight": reference_weight,
                            }
                        ]
                        self.append_value_to_parameter(
                            "status", f"Using image reference: {reference_url}\n"
                        )
                    
                    elif reference_type == "style_reference":
                        params["style_ref"] = [
                            {
                                "url": reference_url,
                                "weight": reference_weight,
                            }
                        ]
                        self.append_value_to_parameter(
                            "status", f"Using style reference: {reference_url}\n"
                        )
                    
                    elif reference_type == "character_reference":
                        params["character_ref"] = {
                            "identity0": {"images": [reference_url]}
                        }
                        self.append_value_to_parameter(
                            "status", f"Using character reference: {reference_url}\n"
                        )
                    
                    elif reference_type == "modify_image":
                        params["modify_image_ref"] = {
                            "url": reference_url,
                            "weight": reference_weight,
                        }
                        self.append_value_to_parameter(
                            "status", f"Modifying image: {reference_url}\n"
                        )

            # Create generation
            generation = await client.generations.image.create(**params)
            generation_id = generation.id

            self.append_value_to_parameter(
                "status", f"Request created with ID: {generation_id}\n"
            )

            # Poll for completion
            self.append_value_to_parameter(
                "status", "Waiting for generation to complete...\n"
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

            # Download and save image
            image_url = generation.assets.image

            self.append_value_to_parameter("status", "Downloading generated image...\n")
            image_bytes = self._download_image(image_url)

            # Save to static files
            timestamp = int(time.time() * 1000)
            filename = f"luma_photon_{timestamp}.jpg"
            static_url = GriptapeNodes.StaticFilesManager().save_static_file(
                image_bytes, filename
            )

            image_artifact = ImageUrlArtifact(
                value=static_url, name=f"luma_photon_{timestamp}"
            )
            self.parameter_output_values["image"] = image_artifact

            self.append_value_to_parameter(
                "status",
                f"✅ Generation completed successfully!\nOriginal URL: {image_url}\n",
            )

        except Exception as e:
            error_msg = f"❌ Generation failed: {str(e)}\n"
            self.append_value_to_parameter("status", error_msg)
            raise

    def _download_image(self, image_url: str) -> bytes:
        """Download image from URL and return bytes."""
        try:
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise ValueError(f"Failed to download image from URL: {str(e)}")

