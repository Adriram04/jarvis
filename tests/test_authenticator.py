"""
Tests for Face Authentication.
"""
import pytest
import os
import numpy as np

# Try to import the authenticator, skip all tests if dependencies missing
try:
    import authenticator as authenticator_module
    from authenticator import FaceAuthenticator
    HAS_AUTH = True
except ImportError as e:
    HAS_AUTH = False
    IMPORT_ERROR = str(e)
    authenticator_module = None
    FaceAuthenticator = None

pytestmark = pytest.mark.skipif(not HAS_AUTH, reason=f"Auth dependencies not installed: {IMPORT_ERROR if not HAS_AUTH else ''}")



class TestAuthenticatorInit:
    """Test FaceAuthenticator initialization."""
    
    def test_authenticator_creation(self):
        """Test FaceAuthenticator can be created."""
        auth = FaceAuthenticator()
        assert auth is not None
        print("FaceAuthenticator initialized successfully")
    
    def test_authenticator_with_callbacks(self):
        """Test FaceAuthenticator with callbacks."""
        statuses = []
        frames = []
        
        async def on_status(is_auth):
            statuses.append(is_auth)
        
        async def on_frame(frame_b64):
            frames.append(frame_b64)
        
        auth = FaceAuthenticator(
            on_status_change=on_status,
            on_frame=on_frame
        )
        assert auth.on_status_change is not None
        assert auth.on_frame is not None


class TestFaceIdentityModels:
    """Test OpenCV face detector/recognizer models."""
    
    def test_model_paths_defined(self):
        """Test that model paths are defined."""
        assert hasattr(FaceAuthenticator, 'DETECTOR_MODEL_PATH')
        assert hasattr(FaceAuthenticator, 'RECOGNIZER_MODEL_PATH')
        print(f"Detector model path: {FaceAuthenticator.DETECTOR_MODEL_PATH}")
        print(f"Recognizer model path: {FaceAuthenticator.RECOGNIZER_MODEL_PATH}")
    
    def test_model_download_urls(self):
        """Test that model URLs are defined."""
        assert hasattr(FaceAuthenticator, 'DETECTOR_MODEL_URL')
        assert hasattr(FaceAuthenticator, 'RECOGNIZER_MODEL_URL')
        print(f"Detector model URL: {FaceAuthenticator.DETECTOR_MODEL_URL}")
        print(f"Recognizer model URL: {FaceAuthenticator.RECOGNIZER_MODEL_URL}")
    
    def test_ensure_model(self):
        """Test model download/verification."""
        auth = FaceAuthenticator()
        auth._ensure_model()
        
        for model_path in [
            FaceAuthenticator.DETECTOR_MODEL_PATH,
            FaceAuthenticator.RECOGNIZER_MODEL_PATH,
        ]:
            if os.path.exists(model_path):
                print(f"Model exists at: {model_path}")
                print(f"Model size: {os.path.getsize(model_path)} bytes")
            else:
                print(f"Model not downloaded: {model_path} (may require internet)")


class TestFaceEmbeddingExtraction:
    """Test face identity embedding extraction."""
    
    @pytest.fixture
    def auth(self):
        """Create a FaceAuthenticator."""
        a = FaceAuthenticator()
        try:
            a._init_face_recognition()
        except Exception as e:
            pytest.skip(f"Could not initialize face recognizer: {e}")
        return a
    
    def test_extract_from_blank_image(self, auth):
        """Test extraction from blank image (should return None)."""
        # Create a blank image
        blank_image = np.zeros((480, 640, 3), dtype=np.uint8)
        
        embedding = auth._extract_face_embedding(blank_image)
        
        # Blank image should have no face
        assert embedding is None
        print("No face detected in blank image (correct)")
    
    def test_extract_embedding_callable(self, auth):
        """Test that embedding extraction is callable."""
        # This would require a real face image
        # For now, just verify the method exists and is callable
        assert callable(auth._extract_face_embedding)


class TestEmbeddingComparison:
    """Test face identity embedding comparison."""
    
    def test_compare_identical_embeddings(self):
        """Test comparing identical embeddings."""
        auth = FaceAuthenticator()
        
        embedding = np.random.default_rng(0).normal(size=128).astype(np.float32)
        
        result = auth._compare_embeddings(embedding, embedding)
        assert result == True
        print("Identical embedding comparison: True (correct)")
    
    def test_compare_orthogonal_embeddings(self):
        """Test comparing clearly different embeddings."""
        auth = FaceAuthenticator()
        
        embedding1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        embedding2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        
        result = auth._compare_embeddings(embedding1, embedding2)
        assert result == False
        print("Orthogonal embedding comparison: False (correct)")
    
    def test_compare_with_threshold(self):
        """Test comparison with different thresholds."""
        auth = FaceAuthenticator()
        
        embedding1 = np.array([1.0, 0.0], dtype=np.float32)
        embedding2 = np.array([0.5, np.sqrt(0.75)], dtype=np.float32)
        
        result_low = auth._compare_embeddings(embedding1, embedding2, threshold=0.4)
        assert result_low == True
        print(f"Low threshold (0.4) result: {result_low}")
        
        result_high = auth._compare_embeddings(embedding1, embedding2, threshold=0.6)
        assert result_high == False
        print(f"High threshold (0.6) result: {result_high}")

    def test_reset_authentication_requires_fresh_match(self):
        """Test reset_authentication clears authenticated/running state."""
        auth = FaceAuthenticator()
        auth.authenticated = True
        auth.running = True
        auth.reference_embedding = np.ones(10, dtype=np.float32)
        auth.reference_landmarks = np.ones(10, dtype=np.float32)

        auth.reset_authentication()

        assert auth.authenticated is False
        assert auth.running is False
        assert auth.reference_embedding is not None
        assert auth.reference_landmarks is not None


class TestReferenceImage:
    """Test reference image handling."""
    
    def test_default_reference_path(self):
        """Test default reference image path."""
        auth = FaceAuthenticator()
        # Default is "reference.jpg" in backend directory
        print(f"Reference path: {auth.reference_image_path}")
    
    def test_load_reference(self):
        """Test loading reference image."""
        auth = FaceAuthenticator()
        
        ref_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "backend",
            "reference.jpg"
        )
        
        if os.path.exists(ref_path):
            auth._load_reference()
            print("Reference image loaded")
        else:
            print("No reference image found (expected in new setup)")


class TestCameraAccess:
    """Test camera access functions."""
    
    def test_camera_methods_exist(self):
        """Test that camera-related methods exist."""
        auth = FaceAuthenticator()
        
        assert hasattr(auth, 'start_authentication_loop')
        assert hasattr(auth, 'stop')
        assert hasattr(auth, '_camera_backend_candidates')
        assert hasattr(auth, '_try_open_camera')
        assert hasattr(auth, '_run_cv_loop')
        print("All camera methods exist")

    def test_windows_camera_backends_do_not_use_macos_backend(self, monkeypatch):
        """Test Windows prefers Windows/OpenCV camera backends."""
        monkeypatch.setattr(authenticator_module.os, 'name', 'nt', raising=False)
        monkeypatch.setattr(authenticator_module.sys, 'platform', 'win32', raising=False)

        backend_names = [name for name, _ in FaceAuthenticator._camera_backend_candidates()]
        non_default_backends = backend_names[:-1]

        assert backend_names[-1] == 'default'
        assert 'CAP_AVFOUNDATION' not in non_default_backends
        assert 'CAP_DSHOW' in non_default_backends or 'CAP_MSMF' in non_default_backends

    def test_macos_camera_backend_prefers_avfoundation(self, monkeypatch):
        """Test macOS still prefers AVFoundation when available."""
        monkeypatch.setattr(authenticator_module.os, 'name', 'posix', raising=False)
        monkeypatch.setattr(authenticator_module.sys, 'platform', 'darwin', raising=False)

        backend_names = [name for name, _ in FaceAuthenticator._camera_backend_candidates()]

        if getattr(authenticator_module.cv2, 'CAP_AVFOUNDATION', None) is not None:
            assert backend_names[0] == 'CAP_AVFOUNDATION'
        assert backend_names[-1] == 'default'


class TestDependencies:
    """Test required dependencies."""
    
    def test_opencv_import(self):
        """Test OpenCV is installed."""
        import cv2
        print(f"OpenCV version: {cv2.__version__}")

    def test_opencv_face_api(self):
        """Test OpenCV has the face detector/recognizer APIs used by auth."""
        import cv2

        assert hasattr(cv2, "FaceDetectorYN_create")
        assert hasattr(cv2, "FaceRecognizerSF_create")
    
    def test_numpy_import(self):
        """Test NumPy is installed."""
        import numpy
        print(f"NumPy version: {numpy.__version__}")
