"""工单 HTTP 接口层；连接和事务由 Service 管理。"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ebike_ai.database import DatabaseConfigError, DatabaseConnectionError
from ebike_ai.services.work_order import (
    BatteryNotFoundError, BatteryVehicleMismatchError, DuplicateWorkOrderError,
    VehicleNotFoundError, WorkOrderCleanupError, WorkOrderCommitUnknownError,
    WorkOrderNotFoundError, WorkOrderPersistenceError, WorkOrderService,
)


logger = logging.getLogger(__name__)
MAX_ID = 2**64 - 1
DatabaseId = Annotated[int, Field(strict=True, gt=0, le=MAX_ID)]
OrderNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
ReportSource = Literal[
    "CUSTOMER_STATEMENT", "TECHNICIAN_OBSERVATION", "HISTORICAL_RECOLLECTION", "IMPORTED_RECORD", "OTHER",
]


class CreateWorkOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_order_no: OrderNumber
    vehicle_id: DatabaseId
    reported_symptom: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    report_source: ReportSource
    battery_id: DatabaseId | None = None
    report_source_note: str | None = None
    received_at: AwareDatetime | None = Field(default=None, description="带时区的 ISO 8601 接车时间；未知时留空")
    notes: str | None = None

    @field_validator("reported_symptom", "report_source_note", "notes")
    @classmethod
    def fits_mysql_text(cls, value):
        # MySQL TEXT 按字节限制长度；只检查字符数无法正确约束中文文本。
        if value is not None and len(value.encode("utf-8")) > 65535:
            raise ValueError("Text must fit within 65535 UTF-8 bytes")
        return value

    @field_validator("received_at", mode="before")
    @classmethod
    def explicit_timestamp(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("Use an ISO 8601 timestamp with a timezone")
        return value

    @field_validator("received_at")
    @classmethod
    def utc_in_mysql_range(cls, value):
        if value is None:
            return None
        try:
            utc = value.astimezone(timezone.utc)
        except (OverflowError, ValueError):
            raise ValueError("Timestamp is outside the MySQL DATETIME range") from None
        if utc.year < 1000:
            raise ValueError("Timestamp is outside the MySQL DATETIME range")
        return utc


class CreatedWorkOrder(BaseModel):
    id: int
    work_order_no: str
    status: Literal["RECEIVED"] = "RECEIVED"
    warning: str | None = None


class WorkOrderDetail(BaseModel):
    id: int
    work_order_no: str
    vehicle_id: int
    battery_id: int | None
    reported_symptom: str
    report_source: ReportSource
    report_source_note: str | None
    status: str
    completion_outcome: str | None
    received_at: datetime | None
    completed_at: datetime | None
    cancel_reason: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("received_at", "completed_at", "created_at", "updated_at")
    @classmethod
    def explicit_utc(cls, value):
        # 数据库连接使用 UTC；PyMySQL 返回的 DATETIME 值不携带时区。
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


ERRORS = (
    (VehicleNotFoundError, 404, "VEHICLE_NOT_FOUND", "车辆不存在"),
    (BatteryNotFoundError, 404, "BATTERY_NOT_FOUND", "电池不存在"),
    (WorkOrderNotFoundError, 404, "WORK_ORDER_NOT_FOUND", "工单不存在"),
    (BatteryVehicleMismatchError, 409, "BATTERY_VEHICLE_MISMATCH", "电池不属于该车辆"),
    (DuplicateWorkOrderError, 409, "DUPLICATE_WORK_ORDER", "工单编号已存在，请查询原单，不要覆盖或盲目更换编号重建"),
    (WorkOrderCommitUnknownError, 503, "COMMIT_OUTCOME_UNKNOWN", "提交结果未知，请按原工单编号核对；不要自动重试创建"),
    (DatabaseConfigError, 503, "DATABASE_NOT_CONFIGURED", "数据库配置不可用"),
    (DatabaseConnectionError, 503, "DATABASE_UNAVAILABLE", "数据库连接不可用"),
    (WorkOrderPersistenceError, 503, "DATABASE_OPERATION_FAILED", "数据库操作未能完成"),
)


def http_error(error):
    for error_type, status, code, message in ERRORS:
        if isinstance(error, error_type):
            return HTTPException(status_code=status, detail={"code": code, "message": message})
    return HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "工单服务异常"})


def get_work_order_service() -> WorkOrderService:
    # 工厂不保存请求状态；实际调用业务方法时才创建数据库连接。
    return WorkOrderService()


router = APIRouter(prefix="/work-orders", tags=["维修工单"], responses={
    404: {"model": ErrorResponse, "description": "车辆、电池或工单不存在"},
    409: {"model": ErrorResponse, "description": "电池归属不符或工单编号重复"},
    503: {"model": ErrorResponse, "description": "数据库不可用或提交结果未知，按 detail.code 区分"},
    500: {"model": ErrorResponse, "description": "未预期错误，响应不包含底层异常"},
})
Service = Annotated[WorkOrderService, Depends(get_work_order_service)]


@router.post("", status_code=201, response_model=CreatedWorkOrder, summary="为已有车辆创建工单")
def create_work_order(request: CreateWorkOrderRequest, service: Service):
    fields = request.model_dump()
    if fields["received_at"] is not None:
        fields["received_at"] = fields["received_at"].replace(tzinfo=None)
    warning = None
    try:
        order_id = service.create_work_order(**fields)
    except WorkOrderCleanupError as error:
        order_id = error.work_order_id
        warning = "工单已保存，但连接清理失败；请按编号查询，不要重复创建"
        logger.warning("Work order committed but connection cleanup failed")
    except Exception as error:
        raise http_error(error) from None
    return CreatedWorkOrder(id=order_id, work_order_no=request.work_order_no, warning=warning)


@router.get("/by-number/{work_order_no:path}", response_model=WorkOrderDetail, summary="按业务编号核对工单")
def get_by_number(work_order_no: OrderNumber, service: Service):
    try:
        return WorkOrderDetail.model_validate(service.get_by_number(work_order_no))
    except Exception as error:
        raise http_error(error) from None


@router.get("/{id}", response_model=WorkOrderDetail, summary="按 ID 查询工单")
def get_by_id(id: Annotated[int, Path(gt=0, le=MAX_ID)], service: Service):
    try:
        return WorkOrderDetail.model_validate(service.get_by_id(id))
    except Exception as error:
        raise http_error(error) from None
