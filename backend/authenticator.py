import cv2
import asyncio
import os
import base64
import numpy as np
import urllib.request
import sys
import time
from pathlib import Path

class FaceAuthenticator:
    # OpenCV Zoo models: YuNet detects/aligns the face, SFace creates identity embeddings.
    DETECTOR_MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    RECOGNIZER_MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
    DETECTOR_MODEL_PATH = os.path.join(os.path.dirname(__file__), "face_detection_yunet_2023mar.onnx")
    RECOGNIZER_MODEL_PATH = os.path.join(os.path.dirname(__file__), "face_recognition_sface_2021dec.onnx")

    # Backward-compatible aliases used by old tests/helpers.
    MODEL_URL = RECOGNIZER_MODEL_URL
    MODEL_PATH = RECOGNIZER_MODEL_PATH

    FACE_DETECTION_SCORE_THRESHOLD = 0.9
    AUTH_ENGINE = "opencv-yunet-sface-v2"
    FACE_MATCH_THRESHOLD = 0.70
    REQUIRED_CONSECUTIVE_MATCHES = 6
    
    def __init__(self, reference_image_path="reference.jpg", on_status_change=None, on_frame=None):
        """
        :param reference_image_path: Path to the user's reference photo.
        :param on_status_change: Async callback(is_authenticated: bool).
        :param on_frame: Async callback(frame_data_b64: str) to send frames to frontend.
        """
        self.reference_image_path = reference_image_path
        self.on_status_change = on_status_change
        self.on_frame = on_frame
        
        self.authenticated = False
        self.running = False
        self.reference_embedding = None
        self.reference_landmarks = None
        self.face_detector = None
        self.face_recognizer = None
        self._last_similarity_log_at = 0

        print(f"[AUTH] Engine: {self.AUTH_ENGINE}")
        self._ensure_model()
        self._init_face_recognition()
        self._load_reference()

    def _ensure_model(self):
        """Download the OpenCV face identity models if not present."""
        models = [
            (self.DETECTOR_MODEL_URL, self.DETECTOR_MODEL_PATH),
            (self.RECOGNIZER_MODEL_URL, self.RECOGNIZER_MODEL_PATH),
        ]

        for url, path in models:
            if os.path.exists(path):
                continue

            print(f"[AUTH] Downloading face auth model: {os.path.basename(path)}...")
            try:
                tmp_path = f"{path}.tmp"
                urllib.request.urlretrieve(url, tmp_path)
                os.replace(tmp_path, path)
                print(f"[AUTH] [OK] Model downloaded to {path}")
            except Exception as e:
                print(f"[AUTH] [ERR] Failed to download model {path}: {e}")

    def _init_face_recognition(self):
        """Initialize OpenCV's face detector and identity recognizer."""
        if not hasattr(cv2, "FaceDetectorYN_create") or not hasattr(cv2, "FaceRecognizerSF_create"):
            print("[AUTH] [ERR] OpenCV face recognition API not available. Upgrade opencv-python.")
            return

        if not os.path.exists(self.DETECTOR_MODEL_PATH) or not os.path.exists(self.RECOGNIZER_MODEL_PATH):
            print("[AUTH] [ERR] Face auth models not found. Cannot initialize.")
            return

        try:
            detector_model = self._read_binary_buffer(self.DETECTOR_MODEL_PATH)
            recognizer_model = self._read_binary_buffer(self.RECOGNIZER_MODEL_PATH)
            empty_config = np.array([], dtype=np.uint8)

            if detector_model is None or recognizer_model is None:
                print("[AUTH] [ERR] Failed to read face auth model bytes.")
                return

            self.face_detector = cv2.FaceDetectorYN_create(
                "onnx",
                detector_model,
                empty_config,
                (320, 320),
                self.FACE_DETECTION_SCORE_THRESHOLD,
                0.3,
                5000,
            )
            self.face_recognizer = cv2.FaceRecognizerSF_create("onnx", recognizer_model, empty_config)
            print("[AUTH] [OK] Face identity recognizer initialized.")
        except Exception as e:
            print(f"[AUTH] [ERR] Failed to initialize face identity recognizer: {e}")

    @staticmethod
    def _read_binary_buffer(path):
        """Read model bytes using a Unicode-safe path on Windows."""
        try:
            buffer = np.fromfile(Path(path), dtype=np.uint8)
            if buffer.size == 0:
                return None
            return buffer
        except Exception as e:
            print(f"[AUTH] [ERR] Failed to read binary model bytes: {e}")
            return None

    def _detect_single_face(self, image_bgr):
        """Return exactly one detected face row, or None when auth should fail closed."""
        if self.face_detector is None or image_bgr is None:
            return None

        height, width = image_bgr.shape[:2]
        if width <= 0 or height <= 0:
            return None

        try:
            self.face_detector.setInputSize((width, height))
            _, faces = self.face_detector.detect(image_bgr)
        except Exception as e:
            print(f"[AUTH] [ERR] Face detection failed: {e}")
            return None

        if faces is None or len(faces) == 0:
            return None

        if len(faces) > 1:
            print(f"[AUTH] [WARN] Multiple faces detected ({len(faces)}). Refusing to authenticate.")
            return None

        return faces[0]

    def _extract_face_embedding(self, image_bgr):
        """
        Extract an SFace identity embedding from a BGR image.
        Returns a flattened numpy array, or None if no unambiguous face is found.
        """
        if self.face_recognizer is None:
            return None

        face = self._detect_single_face(image_bgr)
        if face is None:
            return None

        try:
            aligned_face = self.face_recognizer.alignCrop(image_bgr, face)
            embedding = self.face_recognizer.feature(aligned_face)
            return np.asarray(embedding, dtype=np.float32).flatten()
        except Exception as e:
            print(f"[AUTH] [ERR] Face embedding extraction failed: {e}")
            return None

    def _extract_landmarks(self, image_rgb):
        """
        Legacy helper kept for older tests/callers.
        The active authenticator now returns identity embeddings, not landmarks.
        """
        if image_rgb is None:
            return None

        try:
            image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        except Exception:
            return None

        return self._extract_face_embedding(image_bgr)

    @staticmethod
    def _cosine_similarity(embedding1, embedding2):
        if embedding1 is None or embedding2 is None:
            return None

        embedding1 = np.asarray(embedding1, dtype=np.float32).flatten()
        embedding2 = np.asarray(embedding2, dtype=np.float32).flatten()

        if embedding1.shape != embedding2.shape:
            return None

        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        if norm1 == 0 or norm2 == 0:
            return None

        return float(np.dot(embedding1, embedding2) / (norm1 * norm2))

    def _compare_embeddings(self, embedding1, embedding2, threshold=FACE_MATCH_THRESHOLD):
        """
        Compare two identity embeddings using cosine similarity.
        Unlocking uses a strict threshold because this protects app access,
        not just a loose face-similarity demo.
        """
        is_match, _ = self._embedding_match_details(embedding1, embedding2, threshold=threshold)
        return is_match

    def _embedding_match_details(self, embedding1, embedding2, threshold=FACE_MATCH_THRESHOLD):
        """Return (is_match, cosine_similarity) for auth decisions and diagnostics."""
        similarity = self._cosine_similarity(embedding1, embedding2)
        if similarity is None:
            return False, None

        return similarity >= threshold, similarity

    def _log_auth_attempt(self, similarity, is_match, consecutive_matches):
        """Throttle similarity logs while still showing every match candidate."""
        now = time.monotonic()
        if not is_match and (now - self._last_similarity_log_at) < 1.0:
            return

        self._last_similarity_log_at = now
        score = "none" if similarity is None else f"{similarity:.4f}"
        print(
            "[AUTH] Face similarity: "
            f"{score} | threshold={self.FACE_MATCH_THRESHOLD:.2f} | "
            f"match={is_match} | consecutive={consecutive_matches}/{self.REQUIRED_CONSECUTIVE_MATCHES}"
        )

    def _compare_landmarks(self, landmarks1, landmarks2, threshold=FACE_MATCH_THRESHOLD):
        """Legacy wrapper around identity embedding comparison."""
        return self._compare_embeddings(landmarks1, landmarks2, threshold=threshold)

    @staticmethod
    def _read_image_bgr(path):
        """Read an image using a Unicode-safe path on Windows."""
        try:
            image_bytes = np.fromfile(Path(path), dtype=np.uint8)
            if image_bytes.size == 0:
                return None
            return cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
        except Exception as e:
            print(f"[AUTH] [ERR] Failed to read image bytes: {e}")
            return None

    def _load_reference(self):
        if not os.path.exists(self.reference_image_path):
            print(f"[AUTH] [WARN] Reference file not found at {self.reference_image_path}. Authentication will fail.")
            return

        try:
            print("[AUTH] Loading reference image...")
            img_bgr = self._read_image_bgr(self.reference_image_path)
            if img_bgr is None:
                print(f"[AUTH] [ERR] Failed to read image file: {self.reference_image_path}")
                return
            
            self.reference_embedding = self._extract_face_embedding(img_bgr)
            self.reference_landmarks = self.reference_embedding

            if self.reference_embedding is not None:
                print("[AUTH] [OK] Reference face embedding extracted successfully.")
            else:
                print("[AUTH] [ERR] No face found in reference image.")
        except Exception as e:
            print(f"[AUTH] [ERR] Error loading reference: {e}")

    async def start_authentication_loop(self):
        if self.authenticated:
            print("[AUTH] Already authenticated.")
            if self.on_status_change:
                await self.on_status_change(True)
            return

        if self.reference_embedding is None:
             print("[AUTH] [ERR] Cannot start auth loop: No reference face embedding.")
             return

        self.running = True
        print("[AUTH] Starting camera for authentication...")
        
        # Capture the current (main) event loop
        loop = asyncio.get_running_loop()
        
        # Use a separate thread for blocking camera/CV operations
        await asyncio.to_thread(self._run_cv_loop, loop)

        print("[AUTH] Authentication loop finished.")
    
    def stop(self):
        print("[AUTH] Stopping authentication loop...")
        self.running = False

    def reset_authentication(self, reload_reference=False):
        """Require a fresh face match before the next protected action."""
        print("[AUTH] Resetting authentication state.")
        self.running = False
        self.authenticated = False
        if reload_reference:
            self.reference_embedding = None
            self.reference_landmarks = None
            self._load_reference()

    @staticmethod
    def _camera_backend_candidates():
        candidates = []

        def add_backend(name):
            backend = getattr(cv2, name, None)
            if backend is not None:
                candidates.append((name, backend))

        if os.name == "nt":
            add_backend("CAP_DSHOW")
            add_backend("CAP_MSMF")
        elif sys.platform == "darwin":
            add_backend("CAP_AVFOUNDATION")
        else:
            add_backend("CAP_V4L2")

        candidates.append(("default", None))
        return candidates

    def _try_open_camera(self, index):
        for backend_name, backend in self._camera_backend_candidates():
            print(f"[AUTH] Trying camera index {index} with backend {backend_name}...")
            cap = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                print(f"[AUTH] [ERR] Could not open video device {index} with backend {backend_name}.")
                cap.release()
                continue

            ret, frame = cap.read()
            if not ret:
                print(f"[AUTH] [ERR] Opened device {index} with backend {backend_name} but failed to read first frame.")
                cap.release()
                continue

            print(f"[AUTH] [OK] Successfully opened camera {index} with backend {backend_name}.")
            return cap

        return None

    def _run_cv_loop(self, loop):
        video_capture = self._try_open_camera(0)
        
        if video_capture is None:
            print("[AUTH] Device 0 failed. Trying device 1...")
            video_capture = self._try_open_camera(1)

        if video_capture is None:
            print("[AUTH] [ERR] All camera attempts failed. Authentication cannot proceed.")
            self.running = False
            return

        process_this_frame = True
        consecutive_matches = 0
        
        while self.running and not self.authenticated:
            ret, frame = video_capture.read()
            if not ret:
                print("[AUTH] [ERR] Failed to read frame from camera loop.")
                break
            
            # Process every other frame for performance
            if process_this_frame:
                current_embedding = self._extract_face_embedding(frame)
                is_match, similarity = self._embedding_match_details(self.reference_embedding, current_embedding)

                if is_match:
                    consecutive_matches += 1
                else:
                    consecutive_matches = 0

                self._log_auth_attempt(similarity, is_match, consecutive_matches)

                if consecutive_matches >= self.REQUIRED_CONSECUTIVE_MATCHES:
                    self.authenticated = True
                    print("[AUTH] [OPEN] FACE RECOGNIZED! Access Granted.")
                    if self.on_status_change:
                        asyncio.run_coroutine_threadsafe(self.on_status_change(True), loop)
                    self.running = False
                    break

            process_this_frame = not process_this_frame

            # Send frame to frontend if callback exists
            if self.on_frame:
                small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
                _, buffer = cv2.imencode('.jpg', small_frame)
                b64_str = base64.b64encode(buffer).decode('utf-8')
                
                asyncio.run_coroutine_threadsafe(self.on_frame(b64_str), loop)

        video_capture.release()
