import cv2
import face_recognition
import os
import numpy as np

# 1. Загрузка известных лиц из папки known_faces
KNOWN_FACES_DIR = 'known_faces'
known_face_encodings = []
known_face_names = []

print("Загрузка известных лиц...")
if os.path.exists(KNOWN_FACES_DIR):
    for filename in os.listdir(KNOWN_FACES_DIR):
        if filename.endswith(('.jpg', '.jpeg', '.png')):
            # Загружаем картинку
            filepath = os.path.join(KNOWN_FACES_DIR, filename)
            image = face_recognition.load_image_file(filepath)
            
            # Извлекаем кодировку лица (если лицо найдено)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                known_face_encodings.append(encodings[0])
                # Имя берем из названия файла (например, "Lawliet.jpg" -> "Lawliet")
                known_face_names.append(os.path.splitext(filename)[0])
                print(f"Загружено лицо: {os.path.splitext(filename)[0]}")
            else:
                print(f"ПРЕДУПРЕЖДЕНИЕ: Лицо не найдено на фото {filename}")

if not known_face_names:
    print("В папке known_faces нет фотографий с лицами. Алгоритм будет просто выделять лица как 'Unknown'.")

# 2. Запуск камеры
print("Включаем веб-камеру...")
video_capture = cv2.VideoCapture(0) # 0 - встроенная камера

while True:
    ret, frame = video_capture.read()
    if not ret:
        print("Не удалось получить кадр с камеры")
        break

    # Уменьшаем кадр для более быстрого распознавания (оптимизация)
    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    
    # Конвертируем цвета из BGR (OpenCV) в RGB (face_recognition)
    rgb_small_frame = np.ascontiguousarray(small_frame[:, :, ::-1])
    
    # Находим все лица и их кодировки на текущем кадре
    face_locations = face_recognition.face_locations(rgb_small_frame)
    face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

    face_names = []
    for face_encoding in face_encodings:
        # Сравниваем найденное лицо с нашими известными лицами
        matches = face_recognition.compare_faces(known_face_encodings, face_encoding, tolerance=0.6)
        name = "Unknown"

        # Находим наилучшее совпадение
        if known_face_encodings:
            face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
            best_match_index = np.argmin(face_distances)
            if matches[best_match_index]:
                name = known_face_names[best_match_index]

        face_names.append(name)

    # Рисуем рамки и подписи вокруг распознанных лиц
    for (top, right, bottom, left), name in zip(face_locations, face_names):
        # Масштабируем координаты обратно, так как мы уменьшали кадр в 4 раза (fx=0.25)
        top *= 4
        right *= 4
        bottom *= 4
        left *= 4

        # Рисуем рамку вокруг лица
        color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

        # Рисуем подпись с именем
        cv2.rectangle(frame, (left, bottom - 35), (right, bottom), color, cv2.FILLED)
        font = cv2.FONT_HERSHEY_DUPLEX
        cv2.putText(frame, name, (left + 6, bottom - 6), font, 1.0, (255, 255, 255), 1)

    # Показываем результат
    cv2.imshow('Face Recognition System', frame)

    # Выход по нажатию клавиши 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

video_capture.release()
cv2.destroyAllWindows()
