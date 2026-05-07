"""
Legacy face-recognition smoke test updated for the current OpenCV SFace-based
FaceAuthenticator implementation.
"""
import sys
from pathlib import Path

import numpy as np
import pytest


BACKEND_DIR = Path(__file__).parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    from authenticator import FaceAuthenticator

    HAS_AUTH = True
    IMPORT_ERROR = ""
except ImportError as exc:
    FaceAuthenticator = None
    HAS_AUTH = False
    IMPORT_ERROR = str(exc)


pytestmark = pytest.mark.skipif(
    not HAS_AUTH,
    reason=f"Face authentication dependencies not installed: {IMPORT_ERROR}",
)


def test_face_authenticator_imports_current_stack():
    """The active face-auth stack uses OpenCV's face identity APIs and NumPy."""
    import cv2

    assert FaceAuthenticator is not None
    assert cv2.__version__
    assert hasattr(cv2, "FaceDetectorYN_create")
    assert hasattr(cv2, "FaceRecognizerSF_create")


def test_face_authenticator_handles_missing_reference():
    """A missing reference image should not crash initialization."""
    auth = FaceAuthenticator(reference_image_path="missing_reference.jpg")

    assert auth is not None
    assert auth.reference_embedding is None
    assert auth.reference_landmarks is None
    assert auth.authenticated is False


def test_blank_image_has_no_face_landmarks():
    """Blank images should be accepted and return no detected face."""
    auth = FaceAuthenticator(reference_image_path="missing_reference.jpg")
    blank_image = np.zeros((100, 100, 3), dtype=np.uint8)

    assert auth._extract_face_embedding(blank_image) is None


def test_embedding_comparison_for_identical_vectors():
    """Identical identity vectors should authenticate as a match."""
    auth = FaceAuthenticator(reference_image_path="missing_reference.jpg")
    embedding = np.random.default_rng(0).normal(size=128).astype(np.float32)

    assert bool(auth._compare_embeddings(embedding, embedding)) is True
