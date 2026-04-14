from fastapi import FastAPI

from app.bootstrap import init_db
from app.routes.agent import router as agent_router
from app.routes.auth import router as auth_router
from app.routes.compliance import router as compliance_router
from app.routes.dashboard import router as dashboard_router
from app.routes.oauth import router as oauth_router


def create_multi_tenant_app() -> FastAPI:
    app = FastAPI(title="MailAI Multi-Tenant")

    @app.on_event("startup")
    def _startup():
        init_db()

    app.include_router(auth_router)
    app.include_router(oauth_router)
    app.include_router(dashboard_router)
    app.include_router(agent_router)
    app.include_router(compliance_router)
    return app

