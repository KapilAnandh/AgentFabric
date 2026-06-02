from __future__ import annotations

from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from memory.config_loader import get_config


_tracer = trace.get_tracer("arp")
_initialized = False


def init_tracer(service_name: str = "arp"):
    global _tracer, _initialized

    if _initialized:
        return _tracer

    config = get_config()
    otel_endpoint = config["observability"]["otel_endpoint"]
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=otel_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    _initialized = True
    return _tracer


def get_tracer():
    if not _initialized:
        init_tracer()
    return _tracer


@contextmanager
def trace_operation(name, attributes=None):
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            span.set_attribute(key, value)
        yield span
