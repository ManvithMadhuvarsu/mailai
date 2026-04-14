import os


def app_mode() -> str:
    return (os.getenv("APP_MODE", "single_user") or "single_user").strip().lower()


def multi_tenant_enabled() -> bool:
    flag = (os.getenv("MULTI_TENANT_ENABLED", "false") or "false").strip().lower()
    return app_mode() == "multi_tenant" and flag in {"1", "true", "yes"}


def database_url() -> str:
    # Railway often provides DATABASE_URL for Postgres.
    return os.getenv("DATABASE_URL", "sqlite:///./data/mailai_multi_tenant.db")

