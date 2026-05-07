import cv2
import os
import argparse
from pathlib import Path


def write_image_unicode(path, image):
    """Write an image to disk using a Unicode-safe Windows path."""
    path = Path(path)
    success, buffer = cv2.imencode(path.suffix or ".jpg", image)
    if not success:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.tobytes())
    return True

def apply_orientation(frame, flip_horizontal=False, flip_vertical=False):
    """Apply the selected camera orientation before previewing/saving."""
    if flip_horizontal and flip_vertical:
        return cv2.flip(frame, -1)
    if flip_horizontal:
        return cv2.flip(frame, 1)
    if flip_vertical:
        return cv2.flip(frame, 0)
    return frame


def draw_status(frame, flip_horizontal=False, flip_vertical=False):
    status = f"H mirror: {'on' if flip_horizontal else 'off'} | V flip: {'on' if flip_vertical else 'off'}"
    help_text = "h=mirror  v=vertical  r=rotate180  s/space=save  q/esc=quit"
    cv2.putText(frame, status, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
    cv2.putText(frame, help_text, (12, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
    return frame


def capture_reference_face(output_path="reference.jpg", flip_horizontal=False, flip_vertical=False):
    """
    Opens the webcam and captures a frame when the user presses 's' or 'Space'.
    Saves the frame to the specified output path.
    """
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    print("Press 'h' to mirror horizontally, 'v' to flip vertically, or 'r' to rotate 180 degrees.")
    print("Press 's' or 'SPACE' to capture your face.")
    print("Press 'q' or 'ESC' to quit without saving.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Failed to capture frame.")
            break

        oriented_frame = apply_orientation(frame, flip_horizontal, flip_vertical)
        preview_frame = draw_status(oriented_frame.copy(), flip_horizontal, flip_vertical)
        cv2.imshow('Capture Reference Face', preview_frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('h'):
            flip_horizontal = not flip_horizontal
            print(f"Horizontal mirror: {'on' if flip_horizontal else 'off'}")
            continue

        if key == ord('v'):
            flip_vertical = not flip_vertical
            print(f"Vertical flip: {'on' if flip_vertical else 'off'}")
            continue

        if key == ord('r'):
            flip_horizontal = not flip_horizontal
            flip_vertical = not flip_vertical
            print("Rotated 180 degrees.")
            continue

        # 's' or SPACE to save
        if key == ord('s') or key == 32:
            if write_image_unicode(output_path, oriented_frame):
                print(f"Reference face saved to {output_path}")
                break

            print(f"Error: Failed to save reference face to {output_path}")
        
        # 'q' or ESC to quit
        if key == ord('q') or key == 27:
            print("Capture cancelled.")
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture a face reference image.")
    parser.add_argument("--flip-horizontal", action="store_true", help="Mirror the camera left/right before saving.")
    parser.add_argument("--flip-vertical", action="store_true", help="Flip the camera up/down before saving.")
    args = parser.parse_args()

    # Ensure backend directory context
    script_dir = os.path.dirname(os.path.abspath(__file__))
    save_path = os.path.join(script_dir, "reference.jpg")
    capture_reference_face(
        save_path,
        flip_horizontal=args.flip_horizontal,
        flip_vertical=args.flip_vertical,
    )
