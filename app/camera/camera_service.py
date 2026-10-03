import threading
import time

import cv2
import numpy as np


class CameraService:
    """
    Stores the latest AI-annotated frame separately
    for every registered KOLAPSE camera.

    Example:

        Camera ID 1
            -> latest frame for Grandma Sok

        Camera ID 2
            -> latest frame for another elder

        Camera ID 3
            -> latest frame for another location

    The physical camera is NOT opened here.

    Flow:

        CCTV / Webcam / IP Camera
                |
                v
            ai_runner.py
                |
                v
          AI processing
                |
                v
        X-Device-Key
                |
                v
        KOLAPSE Backend
                |
                v
          Camera database
                |
                v
          CameraService
                |
                v
        Correct dashboard
    """

    def __init__(self):

        # Structure:
        #
        # {
        #     camera_id: {
        #         "jpeg": bytes,
        #         "last_update": float,
        #         "frame_count": int,
        #     }
        # }

        self.cameras = {}

        self.lock = threading.Lock()

    # =====================================================
    # CREATE CAMERA MEMORY IF NEEDED
    # =====================================================

    def _ensure_camera(
        self,
        camera_id: int,
    ):

        if camera_id not in self.cameras:

            self.cameras[camera_id] = {
                "jpeg": None,
                "last_update": None,
                "frame_count": 0,
            }

    # =====================================================
    # RECEIVE OPENCV FRAME
    # =====================================================

    def update_frame(
        self,
        camera_id: int,
        frame,
    ) -> bool:

        """
        Receive an OpenCV frame and store it for
        one specific registered camera.
        """

        if frame is None:
            return False

        success, encoded_frame = cv2.imencode(
            ".jpg",
            frame,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                80,
            ],
        )

        if not success:
            return False

        jpeg_bytes = (
            encoded_frame.tobytes()
        )

        with self.lock:

            self._ensure_camera(
                camera_id
            )

            camera = (
                self.cameras[camera_id]
            )

            camera["jpeg"] = jpeg_bytes

            camera["last_update"] = (
                time.time()
            )

            camera["frame_count"] += 1

        return True

    # =====================================================
    # RECEIVE JPEG BYTES
    # =====================================================

    def update_jpeg(
        self,
        camera_id: int,
        jpeg_bytes: bytes,
    ) -> bool:

        """
        Receive an already encoded JPEG from
        ai_runner.py and store it for the
        correct registered camera.
        """

        if not jpeg_bytes:
            return False

        # -------------------------------------------------
        # Validate JPEG
        # -------------------------------------------------

        image_array = np.frombuffer(
            jpeg_bytes,
            dtype=np.uint8,
        )

        frame = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR,
        )

        if frame is None:
            return False

        # -------------------------------------------------
        # Store by camera ID
        # -------------------------------------------------

        with self.lock:

            self._ensure_camera(
                camera_id
            )

            camera = (
                self.cameras[camera_id]
            )

            camera["jpeg"] = bytes(
                jpeg_bytes
            )

            camera["last_update"] = (
                time.time()
            )

            camera["frame_count"] += 1

        return True

    # =====================================================
    # GET LATEST JPEG FOR ONE CAMERA
    # =====================================================

    def get_jpeg_frame(
        self,
        camera_id: int,
    ):

        with self.lock:

            camera = self.cameras.get(
                camera_id
            )

            if not camera:
                return None

            return camera.get(
                "jpeg"
            )

    # =====================================================
    # CHECK CAMERA AVAILABILITY
    # =====================================================

    def is_available(
        self,
        camera_id: int,
    ) -> bool:

        with self.lock:

            camera = self.cameras.get(
                camera_id
            )

            if not camera:
                return False

            latest_jpeg = camera.get(
                "jpeg"
            )

            last_update = camera.get(
                "last_update"
            )

            if (
                latest_jpeg is None
                or last_update is None
            ):
                return False

            return (
                time.time()
                - last_update
            ) < 5.0

    # =====================================================
    # STATUS FOR ONE CAMERA
    # =====================================================

    def get_status(
        self,
        camera_id: int,
    ):

        with self.lock:

            camera = self.cameras.get(
                camera_id
            )

            if not camera:

                return {
                    "camera_id": camera_id,
                    "available": False,
                    "source": (
                        "KOLAPSE AI Camera"
                    ),
                    "frame_count": 0,
                    "last_frame_age_seconds": None,
                }

            last_update = camera.get(
                "last_update"
            )

            age = None

            if last_update is not None:

                age = (
                    time.time()
                    - last_update
                )

            available = (
                camera.get("jpeg")
                is not None
                and age is not None
                and age < 5.0
            )

            return {
                "camera_id": camera_id,
                "available": available,
                "source": (
                    "KOLAPSE AI Camera"
                ),
                "frame_count": camera.get(
                    "frame_count",
                    0,
                ),
                "last_frame_age_seconds": (
                    round(age, 2)
                    if age is not None
                    else None
                ),
            }

    # =====================================================
    # CLEAR ONE CAMERA
    # =====================================================

    def clear(
        self,
        camera_id: int,
    ):

        with self.lock:

            if camera_id in self.cameras:

                del self.cameras[
                    camera_id
                ]

    # =====================================================
    # CLEAR ALL CAMERAS
    # =====================================================

    def clear_all(self):

        with self.lock:

            self.cameras.clear()


camera_service = CameraService()
