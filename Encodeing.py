import cv2
import face_recognition
import pickle
import os
import firebase_admin
from firebase_admin import credentials
from firebase_admin import  storage

cred = credentials.Certificate("Key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': "",
    'storageBucket': ""
})


folderPath = 'images'
pathList = os.listdir(folderPath)
imgList = []
MasterIds = []
encodeList = []
bucket = storage.bucket()
for path in pathList:
    imgList.append(cv2.imread(os.path.join(folderPath, path)))
    MasterIds.append(os.path.splitext(path)[0])
    fileName = f'{folderPath}/{path}'
    blob = bucket.blob(fileName)
    blob.upload_from_filename(fileName)

def Encodings(imagesList):
    for img in imagesList:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        encode = face_recognition.face_encodings(img)[0]
        encodeList.append(encode)

    return encodeList

encodeList = Encodings(imgList)
encodeListIds = [encodeList, MasterIds]
file = open("EncodeFile.p", 'wb')
pickle.dump(encodeListIds, file)
file.close()
print("File Saved")