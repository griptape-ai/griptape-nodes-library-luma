import asyncio
from typing import Any, Dict

from griptape_nodes.exe_types.core_types import (
    Parameter,
    ParameterMode,
    ParameterTypeBuiltin,
)
from griptape_nodes.exe_types.node_types import ControlNode, AsyncResult
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from lumaai import AsyncLumaAI

SERVICE = "Luma Labs"
API_KEY_ENV_VAR = "LUMAAI_API_KEY"


class LumaListConcepts(ControlNode):
    """List all available concepts that can be used in Luma video generation."""

    def __init__(self, name: str, metadata: Dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)

        self.add_parameter(
            Parameter(
                name="concepts",
                tooltip="List of available concepts for video generation",
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
        """Fetch list of concepts from Luma API."""
        try:
            api_key = self._get_api_key()
            client = AsyncLumaAI(auth_token=api_key)

            self.append_value_to_parameter("status", "Fetching available concepts...\n")

            # Get list of concepts
            concepts = await client.generations.concepts.list()

            # Convert to list if needed
            concepts_list = list(concepts) if concepts else []

            self.parameter_output_values["concepts"] = concepts_list

            self.append_value_to_parameter(
                "status",
                f"✅ Successfully retrieved {len(concepts_list)} concept(s):\n"
                + "\n".join(f"  - {concept}" for concept in concepts_list)
                + "\n",
            )

        except Exception as e:
            error_msg = f"❌ Failed to fetch concepts: {str(e)}\n"
            self.append_value_to_parameter("status", error_msg)
            raise

