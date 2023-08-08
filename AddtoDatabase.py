import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

cred = credentials.Certificate("Key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': ""
})

ref = db.reference('Master')

data = {
    "001":
        {
            "name": "TSUNG HSIN",
            "major": "CS",
            "start_year": 0000,
            "Last_appear": "2023-03-21 00:00:00"
        },
    "002":
        {
            "name": "Elon Musk",
            "major": "Physics",
            "start_year": 0000,
            "Last_appear": "2023-03-21 00:00:00"
        }
}

for key, value in data.items():
    ref.child(key).set(value)