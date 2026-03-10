"""
Workflow Execution Engine
Parses React Flow graphs (nodes and edges) and executes them topologically.
"""

import logging
from typing import Any, Dict, List
import json

from packages.agents.crew import run_crew
from packages.tools.exec import run_command

logger = logging.getLogger(__name__)

class WorkflowEngine:
    def __init__(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]):
        self.nodes = {n["id"]: n for n in nodes}
        self.edges = edges
        self.adjacency = {n["id"]: [] for n in nodes}
        self.in_degree = {n["id"]: 0 for n in nodes}
        
        for edge in edges:
            src = edge["source"]
            tgt = edge["target"]
            if src in self.adjacency and tgt in self.in_degree:
                self.adjacency[src].append(tgt)
                self.in_degree[tgt] += 1

    def _topological_sort(self) -> List[str]:
        queue = [n for n, deg in self.in_degree.items() if deg == 0]
        sorted_nodes = []
        
        while queue:
            curr = queue.pop(0)
            sorted_nodes.append(curr)
            for neighbor in self.adjacency[curr]:
                self.in_degree[neighbor] -= 1
                if self.in_degree[neighbor] == 0:
                    queue.append(neighbor)
                    
        if len(sorted_nodes) != len(self.nodes):
            raise ValueError("Cycle detected in workflow graph! Execution halted.")
            
        return sorted_nodes

    async def _execute_node(self, node: Dict[str, Any], context: Dict[str, Any]) -> Any:
        ntype = node.get("type")
        nlabel = node.get("data", {}).get("label", "Unknown")
        config = node.get("data", {}).get("config", {})
        
        logger.info(f"Executing Node > [{ntype}] {nlabel}")

        if ntype == "trigger":
            # Just pass the initial context through
            return {"status": "triggered"}
            
        elif ntype == "agent":
            # For this prototype, we just pass the cumulative context to the agent
            message = f"Execute visual workflow node: {nlabel}.\nContext:\n{json.dumps(context, indent=2)}"
            model = config.get("model", "local")
            result = await run_crew(user_message=message, user_id="default", model=model)
            return result.get("response", "Agent finished with no response.")
            
        elif ntype == "tool":
            tool_name = config.get("toolName", "Generic Tool")
            if tool_name == "toolExecCommand":
                # Hardcoded dummy command for the prototype execution if no config
                cmd = config.get("command", "echo 'Hello from Visual Tool Node'")
                result = await run_command(cmd)
                return result
            else:
                return {"error": f"Tool {tool_name} execution not fully implemented"}
                
        return {"status": "skipped"}

    async def run(self) -> Dict[str, Any]:
        try:
            order = self._topological_sort()
            logger.info(f"Workflow Execution Order: {order}")
        except Exception as e:
            return {"success": False, "error": str(e)}

        global_context = {}
        execution_trace = []

        for node_id in order:
            node = self.nodes[node_id]
            try:
                res = await self._execute_node(node, global_context)
                execution_trace.append({"node_id": node_id, "result": res})
                global_context[node_id] = res
            except Exception as e:
                logger.error(f"Node execution failed: {e}")
                execution_trace.append({"node_id": node_id, "error": str(e)})
                return {"success": False, "trace": execution_trace, "error": str(e)}

        return {"success": True, "trace": execution_trace}

