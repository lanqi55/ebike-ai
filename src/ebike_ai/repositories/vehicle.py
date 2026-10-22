"""基于第 11 天表结构读写车辆数据，不处理业务流程规则。"""


class VehicleRepository:
    def __init__(self, connection):
        self.connection = connection

    def create(self, vehicle_code: str, *, brand=None, model=None, notes=None) -> int:
        """在调用方的事务中插入车辆，并返回生成的 ID。"""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO vehicle (vehicle_code, brand, model, notes) VALUES (%s, %s, %s, %s)",
                (vehicle_code, brand, model, notes),
            )
            return cursor.lastrowid

    def get_by_id(self, vehicle_id: int) -> dict | None:
        """返回车辆的全部已存字段；ID 不存在时返回 None。"""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, vehicle_code, brand, model, notes, created_at, updated_at "
                "FROM vehicle WHERE id = %s",
                (vehicle_id,),
            )
            return cursor.fetchone()
