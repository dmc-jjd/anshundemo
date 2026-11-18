"""Application factory. Routes keep request-time main-module dependency lookup."""
from fastapi import FastAPI

from .runtime import Services, ServiceContextMiddleware
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    from .main import app as source

    settings = settings or Settings()
    result = FastAPI(title=source.title, version=source.version,
                     description=source.description,
                     routes=list(source.router.routes),
                     docs_url=None, redoc_url=None, openapi_url=None)
    # Documentation routes are already included in the copied route table.
    result.openapi_url = source.openapi_url
    result.exception_handlers.update(source.exception_handlers)
    result.state.settings = settings
    result.state.services = Services.create(settings)
    result.add_middleware(ServiceContextMiddleware, services=result.state.services,
                          settings=settings)
    return result
