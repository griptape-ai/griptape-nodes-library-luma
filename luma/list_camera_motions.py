import asyncio
from typing import Any, Dict

import httpx
from griptape_nodes.exe_types.core_types import (
    Parameter,
    ParameterMode,
    ParameterTypeBuiltin,
)
from griptape_nodes.exe_types.node_types import ControlNode, AsyncResult
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMAAI_API_KEY"
API_BASE_URL = "https://api.lumalabs.ai/dream-machine/v1"


class LumaListCameraMotions(ControlNode):
    """List all supported camera motions that can be used in Luma video generation prompts."""

    def __init__(self, name: str, metadata: Dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        self.add_parameter(
            Parameter(
                name="camera_motions",
                tooltip="List of supported camera motion strings for video generation",
                output_type="list",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"pulse_on_run": True},
                settable=False,
            )
        )

        self.add_parameter(
            Parameter(
                name="status",
                tooltip="Operation status",
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
        """Fetch list of supported camera motions from Luma API."""
        try:
            api_key = self._get_api_key()

            self.append_value_to_parameter(
                "status", "Fetching supported camera motions...\n"
            )

            # Make direct API call to camera motions endpoint
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{API_BASE_URL}/generations/camera_motion/list",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                camera_motions = response.json()

            # Convert to list if needed
            motions_list = list(camera_motions) if camera_motions else []

            self.parameter_output_values["camera_motions"] = motions_list

            self.append_value_to_parameter(
                "status",
                f"✅ Successfully retrieved {len(motions_list)} camera motion(s):\n"
                + "\n".join(f"  - {motion}" for motion in motions_list)
                + "\n\n"
                + "Note: These camera motion strings can be used in prompts.\n"
                + "Syntactically similar phrases also work, though there can be mismatches sometimes.\n",
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"❌ HTTP error {e.response.status_code}: {e.response.text}\n"
            self.append_value_to_parameter("status", error_msg)
            raise
        except Exception as e:
            error_msg = f"❌ Failed to fetch camera motions: {str(e)}\n"
            self.append_value_to_parameter("status", error_msg)
            raise

