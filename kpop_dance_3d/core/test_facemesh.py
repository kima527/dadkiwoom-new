import cv2
import numpy as np
import mediapipe as mp

mp_face_mesh = mp.solutions.face_mesh
with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True) as face_mesh:
    # Test on a small dummy image
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    res = face_mesh.process(img)
    print("FaceMesh initialized successfully!")

