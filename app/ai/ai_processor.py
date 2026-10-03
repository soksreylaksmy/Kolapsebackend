import math
import os
import time

import cv2
import mediapipe as mp
import numpy as np

from ultralytics import YOLO


# =========================================================
# CONFIGURATION
# =========================================================

ACTIONS = [
    "falling",
    "lying",
    "sitting",
    "standing",
]

VIDEO_LENGTH = 30
N_FEATURES = 16

PREDICTION_THRESHOLD = 0.5

CNN_MODEL_PATH = os.path.join(
    "model",
    "fall_model_cnn_lstm.keras",
)

YOLO_MODEL_PATH = os.path.join(
    "model",
    "yolov8n.pt",
)

YOLO_DEVICE = 0


# =========================================================
# ANGLE FUNCTION
# =========================================================

def angle_between(a, b, c):
    """
    Calculate the angle at point B using 2D x/y coordinates.
    """

    a = np.array(a)
    b = np.array(b)
    c = np.array(c)

    ba = a - b
    bc = c - b

    cos_angle = np.dot(ba, bc) / (
        np.linalg.norm(ba)
        * np.linalg.norm(bc)
        + 1e-6
    )

    return math.degrees(
        math.acos(
            np.clip(
                cos_angle,
                -1.0,
                1.0,
            )
        )
    )


# =========================================================
# 16 ANGULAR FEATURES
# =========================================================

def extract_angular_features(
    landmarks,
    prev_spine_angle=None,
):
    lm = landmarks

    def pt(idx):
        return (
            lm[idx].x,
            lm[idx].y,
        )

    def mid(idx1, idx2):
        return (
            (
                lm[idx1].x
                + lm[idx2].x
            )
            / 2,
            (
                lm[idx1].y
                + lm[idx2].y
            )
            / 2,
        )

    shoulder_mid = mid(11, 12)
    hip_mid = mid(23, 24)

    dx = shoulder_mid[0] - hip_mid[0]
    dy = shoulder_mid[1] - hip_mid[1]

    spine_angle = abs(
        math.degrees(
            math.atan2(
                dx,
                dy,
            )
        )
    )

    if prev_spine_angle is not None:
        spine_velocity = abs(
            spine_angle
            - prev_spine_angle
        )
    else:
        spine_velocity = 0.0

    angles = [
        spine_angle,

        angle_between(
            pt(11),
            pt(23),
            pt(25),
        ),

        angle_between(
            pt(12),
            pt(24),
            pt(26),
        ),

        angle_between(
            pt(23),
            pt(25),
            pt(27),
        ),

        angle_between(
            pt(24),
            pt(26),
            pt(28),
        ),

        angle_between(
            pt(25),
            pt(27),
            pt(31),
        ),

        angle_between(
            pt(26),
            pt(28),
            pt(32),
        ),

        angle_between(
            pt(23),
            pt(11),
            pt(13),
        ),

        angle_between(
            pt(24),
            pt(12),
            pt(14),
        ),

        angle_between(
            pt(11),
            pt(13),
            pt(15),
        ),

        angle_between(
            pt(12),
            pt(14),
            pt(16),
        ),

        angle_between(
            pt(13),
            pt(15),
            pt(17),
        ),

        angle_between(
            pt(14),
            pt(16),
            pt(18),
        ),

        angle_between(
            pt(11),
            mid(11, 12),
            pt(12),
        ),

        angle_between(
            pt(23),
            mid(23, 24),
            pt(24),
        ),
    ]

    angles.append(spine_velocity)

    return (
        np.array(
            angles,
            dtype=np.float32,
        ),
        spine_angle,
    )


# =========================================================
# AI PROCESSOR
# =========================================================

class AIProcessor:

    def __init__(self):

        # Load YOLO/PyTorch first. On the Runpod GPU environment,
        # initializing the PyTorch/CUDA side before TensorFlow avoids
        # the CUDA-library initialization conflict seen when TensorFlow
        # is initialized first.
        print("Loading YOLO...")

        self.yolo = YOLO(
            YOLO_MODEL_PATH
        )

        print("YOLO loaded")
        print("YOLO inference device: CUDA GPU 0")

        # Import TensorFlow only after YOLO has initialized.
        # Keeping this import local preserves the working GPU load order:
        # PyTorch/YOLO -> TensorFlow/CNN-LSTM.
        from tensorflow.keras.models import load_model

        print("Loading CNN-LSTM model...")

        self.model = load_model(
            CNN_MODEL_PATH,
            compile=False,
        )

        print("CNN-LSTM loaded")

        self.mp_pose = mp.solutions.pose

        self.pose = self.mp_pose.Pose(
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        self.sequence = []
        self.prev_spine_angle = None

        # Used only for HUD/display stability.
        self.last_prediction = None
        self.last_confidence = 0.0

        # FPS measurement.
        self.previous_frame_time = None
        self.current_fps = 0.0


    # =====================================================
    # FPS
    # =====================================================

    def _update_fps(self):

        current_time = time.perf_counter()

        if self.previous_frame_time is not None:

            elapsed = (
                current_time
                - self.previous_frame_time
            )

            if elapsed > 0:
                instantaneous_fps = (
                    1.0 / elapsed
                )

                # Small amount of smoothing prevents the HUD
                # from changing wildly every frame.
                if self.current_fps <= 0:
                    self.current_fps = instantaneous_fps
                else:
                    self.current_fps = (
                        0.85 * self.current_fps
                        + 0.15 * instantaneous_fps
                    )

        self.previous_frame_time = current_time

        return self.current_fps


    # =====================================================
    # POSTURE LABEL
    # =====================================================

    def _posture_label(
        self,
        spine_angle,
    ):

        if spine_angle is None:
            return "Unknown"

        if spine_angle >= 150:
            return "Upright"

        if spine_angle >= 100:
            return "Leaning"

        return "Fallen"


    # =====================================================
    # PERFORMANCE LABEL
    # =====================================================

    def _performance_label(
        self,
        fps,
    ):

        if fps >= 20:
            return "High FPS (Smooth)"

        if fps >= 10:
            return "Medium FPS (OK)"

        return "Low FPS (Slow)"


    # =====================================================
    # PROCESS ONE FRAME
    # =====================================================

    def process_frame(
        self,
        frame,
    ):

        if frame is None:
            return None

        fps = self._update_fps()

        # =================================================
        # YOLO PERSON DETECTION
        # =================================================

        yolo_results = self.yolo(
            frame,
            classes=[0],
            verbose=False,
            device=YOLO_DEVICE,
        )

        boxes = yolo_results[0].boxes

        crop = frame
        box_coords = None

        # =================================================
        # SELECT LARGEST PERSON
        # =================================================

        if (
            boxes is not None
            and len(boxes) > 0
        ):

            xyxy = boxes.xyxy

            areas = (
                (xyxy[:, 2] - xyxy[:, 0])
                *
                (xyxy[:, 3] - xyxy[:, 1])
            )

            best = int(
                areas.argmax().item()
            )

            selected_box = (
                xyxy[best]
                .detach()
                .cpu()
                .tolist()
            )

            x1, y1, x2, y2 = [
                int(v)
                for v in selected_box
            ]

            pad = 20

            h, w = frame.shape[:2]

            x1 = max(
                0,
                x1 - pad,
            )

            y1 = max(
                0,
                y1 - pad,
            )

            x2 = min(
                w,
                x2 + pad,
            )

            y2 = min(
                h,
                y2 + pad,
            )

            if (
                x2 > x1
                and y2 > y1
            ):

                crop = frame[
                    y1:y2,
                    x1:x2,
                ]

                box_coords = (
                    x1,
                    y1,
                    x2,
                    y2,
                )

        # =================================================
        # MEDIAPIPE
        # =================================================

        crop_rgb = cv2.cvtColor(
            crop,
            cv2.COLOR_BGR2RGB,
        )

        pose_results = self.pose.process(
            crop_rgb
        )

        landmarks_for_display = None

        if pose_results.pose_landmarks:

            (
                features,
                self.prev_spine_angle,
            ) = extract_angular_features(
                pose_results
                .pose_landmarks
                .landmark,
                self.prev_spine_angle,
            )

            landmarks_for_display = (
                pose_results.pose_landmarks
            )

        else:

            features = np.zeros(
                N_FEATURES,
                dtype=np.float32,
            )

            self.prev_spine_angle = None

        # =================================================
        # 30-FRAME SEQUENCE
        # =================================================

        self.sequence.append(
            features
        )

        self.sequence[:] = (
            self.sequence[
                -VIDEO_LENGTH:
            ]
        )

        # =================================================
        # COLLECTING FIRST 30 FRAMES
        # =================================================

        if (
            len(self.sequence)
            < VIDEO_LENGTH
        ):

            return {
                "status": "collecting",

                "frames":
                    len(self.sequence),

                "required_frames":
                    VIDEO_LENGTH,

                "person_box":
                    self._box_dict(
                        box_coords
                    ),

                "landmarks":
                    landmarks_for_display,

                "crop_shape":
                    crop.shape[:2],

                "spine_angle":
                    self.prev_spine_angle,

                "posture":
                    self._posture_label(
                        self.prev_spine_angle
                    ),

                "fps":
                    fps,

                "performance":
                    self._performance_label(
                        fps
                    ),

                "features":
                    features.tolist(),
            }

        # =================================================
        # CNN-LSTM PREDICTION
        # =================================================

        sequence_array = np.array(
            self.sequence,
            dtype=np.float32,
        )

        model_input = np.expand_dims(
            sequence_array,
            axis=0,
        )

        prediction = self.model.predict(
            model_input,
            verbose=0,
        )[0]

        class_index = int(
            np.argmax(
                prediction
            )
        )

        confidence = float(
            np.max(
                prediction
            )
        )

        activity = ACTIONS[
            class_index
        ]

        probabilities = {
            ACTIONS[i]:
                float(
                    prediction[i]
                )

            for i in range(
                len(ACTIONS)
            )
        }

        # =================================================
        # NIKA DISPLAY THRESHOLD
        # =================================================
        #
        # IMPORTANT:
        # We preserve the raw activity/confidence returned
        # to ai_runner so the existing backend integration
        # continues to receive the actual model result.
        #
        # The threshold only stabilizes what is displayed
        # on the camera HUD.
        # =================================================

        if confidence >= PREDICTION_THRESHOLD:

            self.last_prediction = activity
            self.last_confidence = confidence

        return {
            "status": "prediction",

            # Raw current prediction used by existing pipeline.
            "activity":
                activity,

            "confidence":
                confidence,

            "probabilities":
                probabilities,

            # Stable HUD prediction.
            "display_activity":
                self.last_prediction,

            "display_confidence":
                self.last_confidence,

            "person_box":
                self._box_dict(
                    box_coords
                ),

            "landmarks":
                landmarks_for_display,

            "crop_shape":
                crop.shape[:2],

            "spine_angle":
                self.prev_spine_angle,

            "posture":
                self._posture_label(
                    self.prev_spine_angle
                ),

            "fps":
                fps,

            "performance":
                self._performance_label(
                    fps
                ),

            "features":
                features.tolist(),
        }


    # =====================================================
    # BOX HELPER
    # =====================================================

    def _box_dict(
        self,
        box_coords,
    ):

        if box_coords is None:
            return None

        x1, y1, x2, y2 = (
            box_coords
        )

        return {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
        }


    # =====================================================
    # DRAW MEDIAPIPE SKELETON
    # =====================================================

    def _draw_skeleton(
        self,
        display,
        landmarks,
        box,
    ):

        if landmarks is None:
            return

        # Person was cropped by YOLO.
        if box:

            crop_width = (
                box["x2"]
                - box["x1"]
            )

            crop_height = (
                box["y2"]
                - box["y1"]
            )

            points = []

            for landmark in landmarks.landmark:

                px = int(
                    box["x1"]
                    + landmark.x
                    * crop_width
                )

                py = int(
                    box["y1"]
                    + landmark.y
                    * crop_height
                )

                points.append(
                    (px, py)
                )

            for connection in (
                self.mp_pose
                .POSE_CONNECTIONS
            ):

                start_idx = connection[0]
                end_idx = connection[1]

                if (
                    start_idx < len(points)
                    and end_idx < len(points)
                ):

                    cv2.line(
                        display,
                        points[start_idx],
                        points[end_idx],
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )

            for point in points:

                cv2.circle(
                    display,
                    point,
                    3,
                    (0, 255, 255),
                    -1,
                )

        # MediaPipe processed the entire frame.
        else:

            mp.solutions.drawing_utils.draw_landmarks(
                display,
                landmarks,
                self.mp_pose.POSE_CONNECTIONS,
            )


    # =====================================================
    # HUD
    # =====================================================

    def _draw_hud(
        self,
        display,
        result,
    ):

        font = cv2.FONT_HERSHEY_SIMPLEX

        pad = 14
        line_gap = 10

        muted_color = (
            210,
            210,
            210,
        )

        ok_color = (
            90,
            220,
            90,
        )

        warning_color = (
            0,
            200,
            255,
        )

        fall_color = (
            70,
            70,
            255,
        )

        status = result.get(
            "status"
        )

        fps = float(
            result.get(
                "fps",
                0.0,
            )
        )

        performance = result.get(
            "performance",
            self._performance_label(
                fps
            ),
        )

        # =================================================
        # PERFORMANCE LINE
        # =================================================

        if fps >= 20:

            performance_color = (
                ok_color
            )

        elif fps >= 10:

            performance_color = (
                warning_color
            )

        else:

            performance_color = (
                fall_color
            )

        lines = [
            (
                f"{performance}  ({fps:.0f} fps)",
                0.55,
                1,
                performance_color,
            )
        ]

        # =================================================
        # COLLECTING
        # =================================================

        if status == "collecting":

            current = result.get(
                "frames",
                0,
            )

            required = result.get(
                "required_frames",
                VIDEO_LENGTH,
            )

            lines.append(
                (
                    f"AI CALIBRATING {current}/{required}",
                    0.75,
                    2,
                    warning_color,
                )
            )

        # =================================================
        # PREDICTION
        # =================================================

        elif status == "prediction":

            display_activity = result.get(
                "display_activity"
            )

            display_confidence = float(
                result.get(
                    "display_confidence",
                    0.0,
                )
            )

            # Fallback for first prediction if necessary.
            if display_activity is None:

                display_activity = result.get(
                    "activity",
                    "unknown",
                )

                display_confidence = float(
                    result.get(
                        "confidence",
                        0.0,
                    )
                )

            if display_activity == "falling":

                prediction_color = (
                    fall_color
                )

            else:

                prediction_color = (
                    ok_color
                )

            lines.append(
                (
                    (
                        f"{display_activity.upper()}  "
                        f"{display_confidence:.0%}"
                    ),
                    0.9,
                    2,
                    prediction_color,
                )
            )

        # =================================================
        # POSTURE
        # =================================================

        spine_angle = result.get(
            "spine_angle"
        )

        if spine_angle is not None:

            posture = result.get(
                "posture",
                "Unknown",
            )

            if posture == "Upright":

                posture_color = (
                    ok_color
                )

            elif posture == "Leaning":

                posture_color = (
                    warning_color
                )

            else:

                posture_color = (
                    fall_color
                )

            lines.append(
                (
                    (
                        f"Posture: {posture}  "
                        f"({spine_angle:.0f} deg)"
                    ),
                    0.55,
                    1,
                    posture_color,
                )
            )

        # =================================================
        # CALCULATE PANEL SIZE
        # =================================================

        sizes = []

        for (
            text,
            font_scale,
            thickness,
            color,
        ) in lines:

            size = cv2.getTextSize(
                text,
                font,
                font_scale,
                thickness,
            )[0]

            sizes.append(
                size
            )

        if not sizes:
            return display

        panel_width = (
            max(
                width
                for width, height
                in sizes
            )
            + pad * 2
        )

        panel_height = (
            sum(
                height
                for width, height
                in sizes
            )
            + line_gap
            * (len(lines) - 1)
            + pad * 2
        )

        # =================================================
        # TRANSPARENT PANEL
        # =================================================

        overlay = display.copy()

        cv2.rectangle(
            overlay,
            (0, 0),
            (
                panel_width,
                panel_height,
            ),
            (20, 20, 20),
            -1,
        )

        cv2.addWeighted(
            overlay,
            0.55,
            display,
            0.45,
            0,
            display,
        )

        # =================================================
        # TEXT
        # =================================================

        y = pad

        for (
            (
                text,
                font_scale,
                thickness,
                color,
            ),
            (
                width,
                height,
            ),
        ) in zip(
            lines,
            sizes,
        ):

            y += height

            cv2.putText(
                display,
                text,
                (pad, y),
                font,
                font_scale,
                color,
                thickness,
                cv2.LINE_AA,
            )

            y += line_gap

        return display


    # =====================================================
    # DRAW RESULT
    # =====================================================

    def draw_result(
        self,
        frame,
        result,
    ):

        display = frame.copy()

        if result is None:
            return display

        # =================================================
        # YOLO PERSON BOX
        # =================================================

        box = result.get(
            "person_box"
        )

        if box:

            x1 = box["x1"]
            y1 = box["y1"]
            x2 = box["x2"]
            y2 = box["y2"]

            cv2.rectangle(
                display,
                (x1, y1),
                (x2, y2),
                (255, 165, 0),
                2,
            )

            cv2.putText(
                display,
                "PERSON",
                (
                    x1,
                    max(
                        y1 - 10,
                        20,
                    ),
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 165, 0),
                2,
                cv2.LINE_AA,
            )

        # =================================================
        # MEDIAPIPE SKELETON
        # =================================================

        landmarks = result.get(
            "landmarks"
        )

        self._draw_skeleton(
            display,
            landmarks,
            box,
        )

        # =================================================
        # NIKA HUD
        # =================================================

        display = self._draw_hud(
            display,
            result,
        )

        return display


    # =====================================================
    # RESET
    # =====================================================

    def reset_sequence(
        self,
    ):

        self.sequence.clear()

        self.prev_spine_angle = None

        self.last_prediction = None
        self.last_confidence = 0.0

        self.previous_frame_time = None
        self.current_fps = 0.0


    # =====================================================
    # CLOSE
    # =====================================================

    def close(
        self,
    ):

        self.pose.close()

        print(
            "AI processor closed"
        )


# =========================================================
# GLOBAL PROCESSOR
# =========================================================

ai_processor = AIProcessor()