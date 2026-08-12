import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.exe_types.core_types import (
    Parameter,
    ParameterList,
    ParameterMode,
    ParameterTypeBuiltin,
)
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.exe_types.param_components.artifact_url.public_artifact_url_parameter import (
    PublicArtifactUrlParameter,
)
from griptape_nodes.exe_types.param_components.project_file_parameter import ProjectFileParameter
from griptape_nodes.files.file import File
from griptape_nodes.retained_mode.events.connection_events import DeleteConnectionRequest
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.options import Options
from luma_agents import AsyncLuma

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMA_AGENTS_API_KEY"


class LumaImageGeneration(ControlNode):
    """Luma Labs image generation node supporting text-to-image, image references, and image editing."""

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
                tooltip="How to use the reference image: as style/content guidance, or as the source to edit.",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="none",
                traits={
                    Options(
                        choices=[
                            "none",
                            "image_reference",
                            "modify_image",
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

        # --- modify_image mode: single source image sent as source ---
        self._public_reference_image_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=Parameter(
                name="reference_image",
                tooltip="Source image to edit (used in Modify Image mode)",
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
                    "hide": True,
                },
            ),
            disclaimer_message="The Luma API service utilizes this URL to access the reference image for generation.",
        )
        self._public_reference_image_parameter.add_input_parameters()

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

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        if parameter.name == "reference_type":
            self._apply_reference_type(value)

    def _disconnect_incoming(self, param_name: str) -> None:
        param = self.get_parameter_by_name(param_name)
        if param is None:
            return
        conns = GriptapeNodes.FlowManager().get_connections().get_incoming_connections_to_parameter(self, param)
        for conn in conns:
            GriptapeNodes.handle_request(
                DeleteConnectionRequest(
                    source_node_name=conn.source_node.name,
                    source_parameter_name=conn.source_parameter.name,
                    target_node_name=self.name,
                    target_parameter_name=param_name,
                )
            )

    def _disconnect_param_list_incoming(self, param_list: ParameterList) -> None:
        for child in param_list.get_child_parameters():
            self._disconnect_incoming(child.name)

    def _apply_reference_type(self, mode: str) -> None:
        if mode == "image_reference":
            self._disconnect_incoming("reference_image")
            self.hide_parameter_by_name(["reference_image"])
            self.show_parameter_by_name(["image_refs"])
        elif mode == "modify_image":
            self._disconnect_param_list_incoming(self._image_refs_list)
            self.hide_parameter_by_name(["image_refs"])
            self.show_parameter_by_name(["reference_image"])
        else:  # "none"
            self._disconnect_incoming("reference_image")
            self._disconnect_param_list_incoming(self._image_refs_list)
            self.hide_parameter_by_name(["reference_image", "image_refs"])

    def _build_image_ref_params(self) -> list[dict]:
        """Build image_ref array for the Luma API, uploading local images as needed."""
        children = self._image_refs_list.get_child_parameters()
        self._image_ref_uploaded_paths = []
        refs: list[dict] = []
        storage_driver = self._public_reference_image_parameter._storage_driver

        for child in children:
            img_value = self.get_parameter_value(child.name)
            if img_value is None:
                continue
            if isinstance(img_value, dict) and img_value.get("value"):
                img_value = ImageUrlArtifact(value=img_value["value"], name=img_value.get("name", "ref"))

            url = img_value.value if isinstance(img_value, ImageUrlArtifact) else str(img_value)

            if not (url.startswith(("http://", "https://")) and "localhost" not in url):
                file_contents = File(url).read_bytes()
                filename = Path(urlparse(url).path).name
                gtc_path = Path("artifact_url_storage") / uuid4().hex / filename
                url = storage_driver.upload_file(path=gtc_path, file_content=file_contents)
                self._image_ref_uploaded_paths.append(gtc_path)

            refs.append({"url": url})

        return refs

    def _cleanup_image_ref_uploads(self) -> None:
        if not self._image_ref_uploaded_paths:
            return
        storage_driver = self._public_reference_image_parameter._storage_driver
        for path in self._image_ref_uploaded_paths:
            storage_driver.delete_file(path)
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
        client = None
        try:
            api_key = self._get_api_key()
            client = AsyncLuma(auth_token=api_key)

            prompt = self.get_parameter_value("prompt")
            if not prompt:
                raise ValueError("Prompt is required and cannot be empty")

            model = self.get_parameter_value("model")
            aspect_ratio = self.get_parameter_value("aspect_ratio")

            self.append_value_to_parameter("status", "Creating generation request...\n")

            # Build request parameters. Default to a text-to-image generation.
            params = {
                "type": "image",
                "prompt": prompt.strip(),
                "model": model,
                "aspect_ratio": aspect_ratio,
            }

            # Add reference image based on selected type
            reference_type = self.get_parameter_value("reference_type")

            if reference_type == "image_reference":
                image_refs = self._build_image_ref_params()
                if image_refs:
                    params["image_ref"] = image_refs
                    self.append_value_to_parameter("status", f"Using {len(image_refs)} reference image(s)\n")
                else:
                    self.append_value_to_parameter(
                        "status",
                        "⚠️ Reference type set to 'image_reference' but no images provided. Proceeding without reference.\n",
                    )

            elif reference_type == "modify_image":
                reference_image = self.get_parameter_value("reference_image")
                if not reference_image:
                    self.append_value_to_parameter(
                        "status",
                        "⚠️ Reference type set to 'modify_image' but no source image provided. Proceeding without reference.\n",
                    )
                else:
                    if isinstance(reference_image, dict) and reference_image.get("value"):
                        reference_image = ImageUrlArtifact(
                            value=reference_image["value"], name=reference_image.get("name", "reference_image")
                        )
                        self.set_parameter_value("reference_image", reference_image)
                    reference_url = self._public_reference_image_parameter.get_public_url_for_parameter()
                    if reference_url:
                        params["type"] = "image_edit"
                        params["source"] = {"url": reference_url}
                        self.append_value_to_parameter("status", f"Modifying image: {reference_url}\n")

            # Create generation
            generation = await client.generations.create(**params)
            generation_id = generation.id

            self.append_value_to_parameter("status", f"Request created with ID: {generation_id}\n")

            # Poll for completion
            self.append_value_to_parameter("status", "Waiting for generation to complete...\n")

            completed = False
            max_attempts = 120
            attempt = 0

            while not completed and attempt < max_attempts:
                await asyncio.sleep(2)
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

            # Download and save image from the generation output list
            image_url = generation.output[0].url

            self.append_value_to_parameter("status", "Downloading generated image...\n")
            image_bytes = self._download_image(image_url)

            # Save to project files
            dest = self._output_file.build_file()
            saved = dest.write_bytes(image_bytes)

            image_artifact = ImageUrlArtifact(value=saved.location, name=saved.name)
            self.set_parameter_value("image", image_artifact)

            self.append_value_to_parameter(
                "status",
                f"✅ Generation completed successfully!\nOriginal URL: {image_url}\n",
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
            self._public_reference_image_parameter.delete_uploaded_artifact()
            self._cleanup_image_ref_uploads()

    def _download_image(self, image_url: str) -> bytes:
        """Download image from URL and return bytes."""
        return File(image_url).read_bytes()
