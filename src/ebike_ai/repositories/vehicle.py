"""Vehicle persistence for the Day 11 schema, without business workflow policy."""


class VehicleRepository:
    def __init__(self, connection):
        self.connection = connection

    def create(self, vehicle_code: str, *, brand=None, model=None, notes=None) -> int:
        """Insert inside the caller's transaction and return the generated ID."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO vehicle (vehicle_code, brand, model, notes) VALUES (%s, %s, %s, %s)",
                (vehicle_code, brand, model, notes),
            )
            return cursor.lastrowid

    def get_by_id(self, vehicle_id: int) -> dict | None:
        """Return all stored vehicle fields, or None when the ID does not exist."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, vehicle_code, brand, model, notes, created_at, updated_at "
                "FROM vehicle WHERE id = %s",
                (vehicle_id,),
            )
            return cursor.fetchone()
