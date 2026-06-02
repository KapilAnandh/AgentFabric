from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server


tasks_total = Counter("arp_tasks_total", "Total tasks", ["status", "task_type"])
task_duration = Histogram("arp_task_duration_seconds", "Task duration", ["task_type", "model"])
active_agents = Gauge("arp_active_agents", "Currently active agents")
vram_used_gb = Gauge("arp_vram_used_gb", "VRAM currently used")
token_budget_used = Gauge("arp_token_budget_used", "Token budget consumed")
queue_size = Gauge("arp_queue_size", "Tasks waiting in queue")


def record_task_start(task_type):
    tasks_total.labels(status="started", task_type=task_type).inc()


def record_task_complete(task_type, model, duration_seconds):
    tasks_total.labels(status="completed", task_type=task_type).inc()
    task_duration.labels(task_type=task_type, model=model).observe(duration_seconds)


def record_task_fail(task_type):
    tasks_total.labels(status="failed", task_type=task_type).inc()


def update_system_metrics(active_agents_value, vram_gb, queue_size_value):
    active_agents.set(active_agents_value)
    vram_used_gb.set(vram_gb)
    queue_size.set(queue_size_value)


def start_metrics_server(port):
    start_http_server(port)
