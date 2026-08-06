from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from packages.connector_management.exceptions import ConnectorManagementError
from packages.database.exceptions import DatabaseUnavailableError


def error_payload(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConnectorManagementError)
    async def handle_management_error(
        request: Request, exc: ConnectorManagementError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        details = [
            {
                "path": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_payload("validation_error", "请求字段校验失败", details),
        )

    @app.exception_handler(DatabaseUnavailableError)
    async def handle_database_unavailable(
        request: Request, exc: DatabaseUnavailableError
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=503,
            content=error_payload("database_unavailable", "数据库暂不可用"),
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_operation(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=503,
            content=error_payload("database_operation_failed", "数据库操作暂时失败"),
        )
