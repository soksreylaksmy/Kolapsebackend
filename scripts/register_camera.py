import secrets

from app.db.session import SessionLocal
from app.models.entities import Camera, Elder


ELDER_ID = 1
CAMERA_NAME = "Room 101 Camera"
CAMERA_LOCATION = "Room 101"


def main():
    db = SessionLocal()

    try:
        elder = db.get(Elder, ELDER_ID)

        if not elder:
            print(f"Elder {ELDER_ID} not found.")
            return

        device_key = secrets.token_urlsafe(32)

        camera = Camera(
            elder_id=elder.id,
            name=CAMERA_NAME,
            location=CAMERA_LOCATION,
            device_key=device_key,
            is_active=True,
        )

        db.add(camera)
        db.commit()
        db.refresh(camera)

        print()
        print("KOLAPSE CAMERA REGISTERED")
        print("-------------------------")
        print(f"Camera ID: {camera.id}")
        print(f"Camera Name: {camera.name}")
        print(f"Location: {camera.location}")
        print(f"Elder ID: {elder.id}")
        print(f"Elder Name: {elder.name}")
        print(f"Caregiver ID: {elder.caregiver_id}")
        print()
        print("DEVICE KEY:")
        print(camera.device_key)
        print()
        print("Keep this key private.")

    finally:
        db.close()


if __name__ == "__main__":
    main()