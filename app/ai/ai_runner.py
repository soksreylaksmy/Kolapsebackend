import os
import time
import threading

import cv2
import httpx

from app.ai.ai_processor import ai_processor


# =========================================================
# CAMERA CONFIGURATION
# =========================================================

# Development webcam.
# Later this can become an RTSP URL for a customer camera.
CAMERA_SOURCE = 0

WINDOW_NAME = "KOLAPSE AI Camera"


# =========================================================
# KOLAPSE BACKEND CONFIGURATION
# =========================================================

BACKEND_URL = (
    "http://127.0.0.1:8000/api/v1/activity/log"
)

CAMERA_FRAME_URL = (
    "http://127.0.0.1:8000/api/v1/camera/frame"
)

# Activity/database update interval
SEND_INTERVAL_SECONDS = 2.0

# Dashboard publishing
FRAME_SEND_INTERVAL_SECONDS = 0.05
FRAME_JPEG_QUALITY = 75


# =========================================================
# ENVIRONMENT VALUE LOADER
# =========================================================

def load_env_value(name):

    # First check operating-system environment variables.
    value = os.getenv(name)

    if value:
        return value

    # Otherwise read the local .env file.
    env_path = ".env"

    if not os.path.exists(env_path):
        return None

    with open(
        env_path,
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            line = line.strip()

            if (
                not line
                or line.startswith("#")
                or "=" not in line
            ):
                continue

            env_name, env_value = line.split(
                "=",
                1,
            )

            if env_name.strip() == name:

                return (
                    env_value
                    .strip()
                    .strip('"')
                    .strip("'")
                )

    return None


# =========================================================
# BACKGROUND CAMERA PUBLISHER
# =========================================================

class CameraPublisher:

    def __init__(
        self,
        ai_key,
        device_key,
    ):

        self.ai_key = ai_key
        self.device_key = device_key

        self.latest_frame = None

        self.lock = threading.Lock()

        self.running = False

        self.thread = None

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._publish_loop,
            daemon=True,
        )

        self.thread.start()

        print(
            "Dashboard camera publisher started"
        )

    # -----------------------------------------------------
    # GIVE PUBLISHER THE NEWEST FRAME
    # -----------------------------------------------------

    def update_frame(
        self,
        frame,
    ):

        if frame is None:
            return

        with self.lock:

            # Keep only the newest frame.
            self.latest_frame = frame.copy()

    # -----------------------------------------------------
    # GET NEWEST FRAME
    # -----------------------------------------------------

    def _get_latest_frame(self):

        with self.lock:

            if self.latest_frame is None:
                return None

            frame = self.latest_frame

            # Remove after taking it.
            self.latest_frame = None

            return frame

    # -----------------------------------------------------
    # BACKGROUND PUBLISHING LOOP
    # -----------------------------------------------------

    def _publish_loop(self):

        client = httpx.Client(
            timeout=2.0
        )

        try:

            while self.running:

                frame = (
                    self._get_latest_frame()
                )

                if frame is None:

                    time.sleep(
                        0.005
                    )

                    continue

                # JPEG encoding happens in the
                # background thread.
                success, encoded_frame = (
                    cv2.imencode(
                        ".jpg",
                        frame,
                        [
                            cv2.IMWRITE_JPEG_QUALITY,
                            FRAME_JPEG_QUALITY,
                        ],
                    )
                )

                if not success:
                    continue

                try:

                    client.post(
                        CAMERA_FRAME_URL,
                        content=(
                            encoded_frame.tobytes()
                        ),
                        headers={
                            "Content-Type": "image/jpeg",
                            "X-AI-Key": self.ai_key,
                            "X-Device-Key": self.device_key,
                        },
                    )

                except httpx.RequestError:

                    # Camera publishing failure must
                    # not stop AI processing.
                    pass

                time.sleep(
                    FRAME_SEND_INTERVAL_SECONDS
                )

        finally:

            client.close()

    # -----------------------------------------------------
    # STOP
    # -----------------------------------------------------

    def stop(self):

        self.running = False

        if self.thread is not None:

            self.thread.join(
                timeout=2.0
            )

            self.thread = None

        with self.lock:

            self.latest_frame = None

        print(
            "Dashboard camera publisher stopped"
        )


# =========================================================
# SEND ACTIVITY TO KOLAPSE BACKEND
# =========================================================

def send_activity(
    client,
    ai_key,
    device_key,
    activity,
    confidence,
):

    # elder_id and location are included only because the
    # current ActivityCreate schema still requires them.
    #
    # The backend DOES NOT trust these values anymore.
    # It replaces them using the registered camera record.
    payload = {
        "elder_id": 0,
        "activity": activity,
        "confidence": float(
            confidence
        ),
        "location": "camera",
        "source": "ai",
    }

    try:

        response = client.post(
            BACKEND_URL,
            json=payload,
            headers={
                "X-AI-Key": ai_key,
                "X-Device-Key": device_key,
            },
        )

        if (
            response.status_code
            == 201
        ):

            response_data = (
                response.json()
            )

            actual_elder_id = (
                response_data.get(
                    "elder_id"
                )
            )

            actual_location = (
                response_data.get(
                    "location",
                    "Unknown",
                )
            )

            print(
                f"\nSent to KOLAPSE: "
                f"{activity.upper()} | "
                f"{confidence:.2%} | "
                f"Elder {actual_elder_id} | "
                f"{actual_location}"
            )

            return True

        print(
            f"\nBackend rejected "
            f"activity "
            f"({response.status_code})"
        )

        print(
            response.text
        )

        return False

    except httpx.RequestError as error:

        print(
            "\nCould not connect to "
            "KOLAPSE backend"
        )

        print(
            f"Reason: {error}"
        )

        return False


# =========================================================
# AI RUNNER
# =========================================================

def run_ai():

    # =====================================================
    # LOAD SECURITY CREDENTIALS
    # =====================================================

    ai_key = load_env_value(
        "AI_API_KEY"
    )

    device_key = load_env_value(
        "CAMERA_DEVICE_KEY"
    )

    # =====================================================
    # CHECK AI KEY
    # =====================================================

    if not ai_key:

        print(
            "AI_API_KEY was not found."
        )

        print(
            "Make sure AI_API_KEY exists "
            "inside your .env file."
        )

        return

    # =====================================================
    # CHECK CAMERA DEVICE KEY
    # =====================================================

    if not device_key:

        print(
            "CAMERA_DEVICE_KEY was not found."
        )

        print(
            "Make sure CAMERA_DEVICE_KEY exists "
            "inside your .env file."
        )

        return

    print(
        "AI service authentication loaded"
    )

    print(
        "Camera device authentication loaded"
    )

    # =====================================================
    # OPEN CAMERA
    # =====================================================

    print(
        "Opening camera..."
    )

    camera = cv2.VideoCapture(
        CAMERA_SOURCE
    )

    if not camera.isOpened():

        print(
            "Could not open camera"
        )

        return

    camera.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        640,
    )

    camera.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        480,
    )

    print(
        "Camera opened"
    )

    print(
        "KOLAPSE AI monitoring started"
    )

    print(
        "Camera identity is controlled "
        "by the registered device key"
    )

    print(
        "YOLO device: NVIDIA GPU"
    )

    # =====================================================
    # START BACKGROUND WEB PUBLISHER
    # =====================================================

    camera_publisher = CameraPublisher(
        ai_key=ai_key,
        device_key=device_key,
    )

    camera_publisher.start()

    print(
        "Press Q on the camera window "
        "or Ctrl+C to stop.\n"
    )

    # =====================================================
    # CREATE LOCAL CAMERA WINDOW
    # =====================================================

    cv2.namedWindow(
        WINDOW_NAME,
        cv2.WINDOW_NORMAL,
    )

    last_sent_time = 0.0

    # Used for activity records.
    client = httpx.Client(
        timeout=5.0
    )

    try:

        while True:

            # =================================================
            # 1. READ RAW CAMERA
            # =================================================

            success, frame = (
                camera.read()
            )

            if not success:

                print(
                    "\rCould not read "
                    "camera frame      ",
                    end="",
                )

                time.sleep(
                    0.1
                )

                continue

            # =================================================
            # 2. AI PIPELINE
            #
            # Camera
            #   ->
            # YOLO person detection
            #   ->
            # MediaPipe pose
            #   ->
            # 16 angular features
            #   ->
            # 30-frame sequence
            #   ->
            # CNN-LSTM
            # =================================================

            result = (
                ai_processor.process_frame(
                    frame
                )
            )

            # =================================================
            # 3. DRAW AI RESULT
            # =================================================

            display_frame = (
                ai_processor.draw_result(
                    frame,
                    result,
                )
            )

            # =================================================
            # 4. STATUS + ACTIVITY BACKEND
            # =================================================

            if result is None:

                print(
                    "\rWaiting for AI...       ",
                    end="",
                )

            else:

                status = result.get(
                    "status"
                )

                if status == "no_person":

                    print(
                        "\rNo person detected"
                        "                     ",
                        end="",
                    )

                elif status == "no_pose":

                    print(
                        "\rPerson detected, "
                        "but body pose is not clear"
                        "          ",
                        end="",
                    )

                elif status == "invalid_crop":

                    print(
                        "\rInvalid person crop"
                        "                     ",
                        end="",
                    )

                elif status == "feature_error":

                    print(
                        "\rInvalid AI features"
                        "                     ",
                        end="",
                    )

                elif status == "collecting":

                    current = result.get(
                        "frames",
                        0,
                    )

                    required = result.get(
                        "required_frames",
                        30,
                    )

                    print(
                        f"\rAI calibrating: "
                        f"{current}/{required}"
                        "                     ",
                        end="",
                    )

                elif status == "prediction":

                    activity = result.get(
                        "activity",
                        "unknown",
                    )

                    confidence = float(
                        result.get(
                            "confidence",
                            0.0,
                        )
                    )

                    print(
                        f"\rActivity: "
                        f"{activity.upper():10} | "
                        f"Confidence: "
                        f"{confidence:.2%}"
                        "                     ",
                        end="",
                        flush=True,
                    )

                    # =========================================
                    # ACTIVITY DATABASE UPDATE
                    # =========================================

                    current_time = (
                        time.monotonic()
                    )

                    if (
                        current_time
                        - last_sent_time
                        >= SEND_INTERVAL_SECONDS
                    ):

                        sent = send_activity(
                            client,
                            ai_key,
                            device_key,
                            activity,
                            confidence,
                        )

                        if sent:

                            last_sent_time = (
                                current_time
                            )

                    # =========================================
                    # LOCAL FALL WARNING
                    # =========================================

                    if (
                        activity == "falling"
                        and confidence >= 0.80
                    ):

                        cv2.putText(
                            display_frame,
                            "!!! FALL ALERT !!!",
                            (20, 110),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1.0,
                            (0, 0, 255),
                            3,
                            cv2.LINE_AA,
                        )

            # =================================================
            # 5. SEND NEWEST FRAME TO PUBLISHER
            # =================================================

            camera_publisher.update_frame(
                display_frame
            )

            # =================================================
            # 6. LOCAL AI CAMERA
            # =================================================

            cv2.imshow(
                WINDOW_NAME,
                display_frame,
            )

            # =================================================
            # 7. KEYBOARD
            # =================================================

            key = (
                cv2.waitKey(1)
                & 0xFF
            )

            if (
                key == ord("q")
                or key == 27
            ):

                print(
                    "\nQ pressed - "
                    "stopping KOLAPSE AI"
                )

                break

    except KeyboardInterrupt:

        print(
            "\nAI monitoring stopped"
        )

    except Exception as error:

        print(
            f"\nAI runner error: "
            f"{error}"
        )

        raise

    finally:

        print(
            "\nClosing camera..."
        )

        camera_publisher.stop()

        client.close()

        camera.release()

        cv2.destroyAllWindows()

        ai_processor.close()

        print(
            "Camera released"
        )

        print(
            "KOLAPSE AI stopped"
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    run_ai()