"""Agent topology: build graph nodes and edges from directory data."""

from __future__ import annotations

from typing import Any


def build_topology(agent: dict[str, Any], tools: list, skills: list) -> dict:
    """Build a TargetDescriptor.metadata.topology object.

    The topology describes the agent's internal composition as a directed
    graph: the agent root, its skills, workflow nodes and tools, with typed
    edges connecting them. The frontend TargetStructure component renders
    this as an interactive graph.
    """
    agent_id = agent.get("id", "unknown")
    agent_name = agent.get("name", agent_id)
    composition = agent.get("arrangeType") or agent.get("agentType") or "base"

    nodes: list[dict] = [
        {"id": f"{agent_id}", "kind": "agent", "label": agent_name,
         "description": f"被测智能体（{composition}）"}
    ]
    edges: list[dict] = []

    for skill in skills:
        skill_id = skill.get("id", "")
        nodes.append({
            "id": f"{agent_id}:skill:{skill_id}",
            "kind": "skill",
            "label": skill.get("name", skill_id),
            "description": skill.get("description", ""),
        })
        edges.append({
            "source": agent_id,
            "target": f"{agent_id}:skill:{skill_id}",
            "relation": "includes_skill",
        })
        for tool_name in skill.get("tools", []):
            tool_id = f"{agent_id}:tool:{tool_name}"
            if not any(n["id"] == tool_id for n in nodes):
                nodes.append({
                    "id": tool_id,
                    "kind": "tool",
                    "label": tool_name,
                    "description": f"工具：{tool_name}",
                })
            edges.append({
                "source": f"{agent_id}:skill:{skill_id}",
                "target": tool_id,
                "relation": "includes_tool",
            })

    for tool in tools:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        tool_name = function.get("name", tool.get("name", ""))
        if not tool_name:
            continue
        tool_id = f"{agent_id}:tool:{tool_name}"
        if not any(n["id"] == tool_id for n in nodes):
            description = function.get("description", tool.get("description", ""))
            nodes.append({
                "id": tool_id,
                "kind": "tool",
                "label": tool_name,
                "description": description,
            })
            edges.append({
                "source": agent_id,
                "target": tool_id,
                "relation": "includes_tool",
            })

    return {
        "composition": composition,
        "nodes": nodes,
        "edges": edges,
    }
