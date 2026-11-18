"""Request-local services while preserving the main module's injection surface."""
from contextvars import ContextVar
from dataclasses import dataclass

from core import paths
from core.package_store import PackageStores
from .workflow import Dependencies


@dataclass
class Services:
    store: PackageStores
    deps: Dependencies

    @classmethod
    def create(cls, settings):
        store = PackageStores(settings.data_root)
        return cls(store, Dependencies(store))


_default_store = PackageStores()
_default = Services(_default_store, Dependencies(_default_store))
_current = ContextVar('report_application_services', default=_default)


class _ServiceProxy:
    def __init__(self, name):
        object.__setattr__(self, '_name', name)

    def __getattr__(self, name):
        return getattr(getattr(_current.get(), self._name), name)

    def __setattr__(self, name, value):
        setattr(getattr(_current.get(), self._name), name, value)


class _Uploads:
    def __fspath__(self):
        return str(_current.get().store.package_root() / 'uploads')


store = _ServiceProxy('store')
deps = _ServiceProxy('deps')
uploads = _Uploads()


class ServiceContextMiddleware:
    def __init__(self, app, services, settings):
        self.app, self.services, self.settings = app, services, settings

    async def __call__(self, scope, receive, send):
        token = _current.set(self.services)
        try:
            with paths.data_root_context(self.settings.data_root):
                await self.app(scope, receive, send)
        finally:
            _current.reset(token)
