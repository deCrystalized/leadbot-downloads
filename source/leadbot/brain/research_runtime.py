"""Server-owned opt-in service registry; no model, endpoint or key defaults.

Only trusted process startup can configure a factory. No HTTP action imports
credentials, constructs a provider or installs this candidate automatically.
"""
import threading

_factory = None
_services = {}
_lock = threading.Lock()


def configure(factory):
    global _factory
    if factory is not None and not callable(factory):
        raise ValueError('A trusted service factory is required')
    with _lock:
        if _services:
            raise ValueError('Service configuration cannot change under active jobs')
        _factory = factory


def service(store):
    with _lock:
        if _factory is None:
            return None
        if store.path not in _services:
            _services[store.path] = _factory(store)
        return _services[store.path]


def configured_services():
    """Trusted local controller only; never exposed as a model/browser tool."""
    with _lock:
        services = tuple(_services.values())
    import native_execution
    return services + native_execution.configured_services()
