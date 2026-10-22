"""在调用方管理的事务中查询电池。"""


class BatteryRepository:
    def __init__(self, connection):
        self.connection = connection

    def get_by_id_for_update(self, battery_id: int) -> dict | None:
        """锁定电池记录，直到调用方提交或回滚事务。"""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, vehicle_id FROM battery WHERE id = %s FOR UPDATE",
                (battery_id,),
            )
            return cursor.fetchone()
