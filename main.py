import pickle
import time
import cv2
import face_recognition
import cvzone
import firebase_admin
import numpy as np
import smtplib
from firebase_admin import credentials
from firebase_admin import db
from firebase_admin import storage
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

cred = credentials.Certificate("Key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': "",
    'storageBucket': ""
})

cap = cv2.VideoCapture(0)
cap.set(3, 1280)
cap.set(4, 720)

bucket = storage.bucket()


file = open('EncodeFile.p', 'rb')
encodeListIds = pickle.load(file)
file.close()
encodeList, MasterIds = encodeListIds
id = -1
Master = []

def save_video(img):
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    current_time = datetime.now().strftime("%Y%m%d_%H%M")
    v_name = f"{current_time}.avi"
    out = cv2.VideoWriter('Videos\\' + v_name, fourcc, 30.0, (1280, 720))
    out.write(img)
    out.release()
def save_image(img):
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    i_name = f"{current_time}.jpg"
    cv2.imwrite('thief\\' +i_name, img, [cv2.IMWRITE_JPEG_QUALITY, 90])
while True:
    success, img = cap.read()
    # Compression to fast compute
    imgS = cv2.resize(img, (0, 0), None, 0.25, 0.25)
    imgS = cv2.cvtColor(imgS, cv2.COLOR_BGR2RGB)
    # Detect the current face and encode it
    faceCurFrame = face_recognition.face_locations(imgS)
    encodeCurFrame = face_recognition.face_encodings(imgS, faceCurFrame)

    if faceCurFrame:
        for encodeFace, faceLoc in zip(encodeCurFrame, faceCurFrame):
            matches = face_recognition.compare_faces(encodeList, encodeFace)
            faceDis = face_recognition.face_distance(encodeList, encodeFace)

            matchIndex = np.argmin(faceDis)


            if matches[matchIndex]:
                y1, x2, y2, x1 = faceLoc
                y1, x2, y2, x1 = y1 * 4, x2 * 4, y2 * 4, x1 * 4
                bbox = x1,  y1, x2 - x1, y2 - y1
                img = cvzone.cornerRect(img, bbox, rt=0)
                id = MasterIds[matchIndex]
                Masterinfo = db.reference(f'Master/{id}').get()
                cvzone.putTextRect(img, Masterinfo['name'], (25, 50))
                print(Masterinfo['Last_appear'], Masterinfo['name'])

                blob = bucket.get_blob(f'images/{id}.png')
                array = np.frombuffer(blob.download_as_string(), np.uint8)
                Master = cv2.imdecode(array, cv2.COLOR_BGRA2BGR)
                Master_re = cv2.resize(Master, (100, 100))
                img[0:0 + 100, 1180:1180+ 100] = Master_re
                datetimeObject = datetime.strptime(Masterinfo['Last_appear'], "%Y-%m-%d %H:%M:%S")
                secondsElapsed = (datetime.now() - datetimeObject).total_seconds()
                print(secondsElapsed)
                if secondsElapsed > 10:
                    ref = db.reference(f'Master/{id}')
                    ref.child('Last_appear').set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

                cv2.imshow("house", img)
                cv2.waitKey(1)
            else:
                save_image(img)
                content = MIMEMultipart()
                content["subject"] = "house"
                content["from"] = "0000@gmail.com"
                content["to"] = "0000@gmail.com"
                content.attach(MIMEText("thief in my house"))
                content.attach(MIMEImage(Path("thief\\").read_bytes()))
                with smtplib.SMTP(host="smtp.gmail.com") as smtp:
                    try:
                        smtp.ehlo()
                        smtp.starttls()
                        smtp.login("0000@gmail.com", "000000000")
                        smtp.send_message(content)
                        print("Complete!")
                    except Exception as e:
                        print("Error message: ", e)
                time.sleep(3000)

    else:
        save_video(img)
    cv2.imshow("house", img)
    k = cv2.waitKey(1)
    if k == 27:
        break

cap.release()
cv2.destroyAllWindows()