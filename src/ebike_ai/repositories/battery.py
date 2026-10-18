"""Battery reads inside a caller-owned transaction."""


class BatteryRepository:
    def __init__(self, connection):
        self.connection = connection

    def get_by_id_for_update(self, battery_id: int) -> dict | None:
        """Lock the battery row until the caller commits or rolls back."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, vehicle_id FROM battery WHERE id = %s FOR UPDATE",
                (battery_id,),
            )
            return cursor.fetchone()
