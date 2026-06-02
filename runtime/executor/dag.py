from __future__ import annotations

import json

import networkx as nx

from runtime.lifecycle.states import TaskState


class WorkflowDAG:
    def __init__(self) -> None:
        self.graph = nx.DiGraph()

    def add_task(self, task_id, name, task_type, depends_on: list[str] = []) -> None:
        self.graph.add_node(
            task_id,
            task_id=task_id,
            name=name,
            task_type=task_type,
            status=TaskState.PENDING.value,
        )
        for dependency in depends_on:
            self.graph.add_edge(dependency, task_id)

    def validate(self) -> bool:
        if nx.is_directed_acyclic_graph(self.graph):
            return True

        cycle = nx.find_cycle(self.graph, orientation="original")
        raise ValueError(f"Workflow graph contains a cycle: {cycle}")

    def get_ready_tasks(self) -> list[dict]:
        ready_tasks: list[dict] = []
        for task_id, data in self.graph.nodes(data=True):
            status = data.get("status", TaskState.PENDING.value)
            if status != TaskState.PENDING.value:
                continue

            predecessors = self.graph.predecessors(task_id)
            if all(
                self.graph.nodes[dependency].get("status") == TaskState.COMPLETED.value
                for dependency in predecessors
            ):
                ready_tasks.append(
                    {
                        "task_id": task_id,
                        "name": data["name"],
                        "task_type": data["task_type"],
                    }
                )

        return ready_tasks

    def mark_task_done(self, task_id) -> None:
        self.graph.nodes[task_id]["status"] = TaskState.COMPLETED.value

    def mark_task_failed(self, task_id) -> None:
        self.graph.nodes[task_id]["status"] = TaskState.FAILED.value

    def mark_task_pending(self, task_id) -> None:
        self.graph.nodes[task_id]["status"] = TaskState.PENDING.value

    def to_json(self) -> str:
        payload = {
            "nodes": [
                {"id": task_id, **attributes}
                for task_id, attributes in self.graph.nodes(data=True)
            ],
            "edges": [
                {"source": source, "target": target}
                for source, target in self.graph.edges()
            ],
        }
        return json.dumps(payload)

    @classmethod
    def from_json(cls, json_str) -> WorkflowDAG:
        payload = json.loads(json_str)
        dag = cls()

        for node in payload.get("nodes", []):
            task_id = node["id"]
            attributes = {key: value for key, value in node.items() if key != "id"}
            dag.graph.add_node(task_id, **attributes)

        for edge in payload.get("edges", []):
            dag.graph.add_edge(edge["source"], edge["target"])

        return dag
