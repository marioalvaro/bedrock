from fastapi import APIRouter, Depends

from bedrock.api.deps import require_session
from bedrock.api.v1 import (
    adjustments,
    auth,
    companies,
    corporate_actions,
    flags,
    health,
    multiples,
    qoe_rules,
    ratios,
    segments,
    statements,
)

# Protected by default: a new router goes in `protected`, and only the routes that
# must work without a session go in `public` (guarded by tests/test_route_guard.py).
public = APIRouter()
public.include_router(health.router)
public.include_router(auth.router)

protected = APIRouter(dependencies=[Depends(require_session)])
protected.include_router(auth.session_router)
protected.include_router(companies.router)
protected.include_router(corporate_actions.router)
protected.include_router(adjustments.router)
protected.include_router(statements.router)
protected.include_router(ratios.router)
protected.include_router(multiples.router)
protected.include_router(flags.router)
protected.include_router(qoe_rules.router)
protected.include_router(qoe_rules.custom_router)
protected.include_router(segments.router)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(public)
api_router.include_router(protected)
