from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.errors import AppError
from core.logging import setup_logging
from routers import auth, health, legs, trips

setup_logging()

app = FastAPI(title="Travel Agency API")
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(trips.router)
app.include_router(legs.router)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )
