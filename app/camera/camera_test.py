import cv2

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print(" Could not open camera")
    raise SystemExit

print(" Camera opened successfully")
print("Press Q to close the camera.")

while True:
    success, frame = camera.read()

    if not success:
        print(" Could not read camera frame")
        break

    cv2.imshow("KOLAPSE Camera Test", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()

print("Camera closed")