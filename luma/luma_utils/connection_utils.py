"""Shared helpers for managing parameter connections via the engine connection registry."""

from __future__ import annotations

from griptape_nodes.exe_types.core_types import ParameterList
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.retained_mode.events.connection_events import DeleteConnectionRequest
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes


def disconnect_incoming(node: BaseNode, param_name: str) -> None:
    """Disconnect all incoming connections to a named parameter on the given node."""
    param = node.get_parameter_by_name(param_name)
    if param is None:
        return
    conns = GriptapeNodes.FlowManager().get_connections().get_incoming_connections_to_parameter(node, param)
    for conn in conns:
        GriptapeNodes.handle_request(
            DeleteConnectionRequest(
                source_node_name=conn.source_node.name,
                source_parameter_name=conn.source_parameter.name,
                target_node_name=node.name,
                target_parameter_name=param_name,
            )
        )


def disconnect_param_list_incoming(node: BaseNode, param_list: ParameterList) -> None:
    """Disconnect all incoming connections to every child of a ParameterList."""
    for child in param_list.get_child_parameters():
        disconnect_incoming(node, child.name)


def disconnect_outgoing(node: BaseNode, param_name: str) -> None:
    """Disconnect all outgoing connections from a named output parameter on the given node."""
    param = node.get_parameter_by_name(param_name)
    if param is None:
        return
    conns = GriptapeNodes.FlowManager().get_connections().get_outgoing_connections_from_parameter(node, param)
    for conn in conns:
        GriptapeNodes.handle_request(
            DeleteConnectionRequest(
                source_node_name=node.name,
                source_parameter_name=param_name,
                target_node_name=conn.target_node.name,
                target_parameter_name=conn.target_parameter.name,
            )
        )


def disconnect_param_list_outgoing(node: BaseNode, param_list: ParameterList) -> None:
    """Disconnect all outgoing connections from every child of a ParameterList."""
    for child in param_list.get_child_parameters():
        disconnect_outgoing(node, child.name)
