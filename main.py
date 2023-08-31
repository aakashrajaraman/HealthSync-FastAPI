from fastapi import FastAPI, Request, Depends, HTTPException, Form, File, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import uvicorn
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
from dotenv import load_dotenv
import os
from google.cloud import storage
from itertools import chain
import re
import pickle
import json
import numpy as np
import torch
os.environ['USE_TORCH'] = '1'
from pathlib import Path
import io 
#from doctr.io import DocumentFile
#import tensorflow as tf

predictor = torch.load(r"text_extraction_model.pth")
clinic_data = {}
global userType
apps = []


templates = Jinja2Templates(directory="templates")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

load_dotenv()
path = os.environ.get("FIREBASE_KEY_PATH")
bucket_path = "healthsync-c9b49.appspot.com"
current_date = datetime.date.today()

cred = credentials.Certificate(path)
firebase_admin.initialize_app(cred)
client = storage.Client.from_service_account_json(path)

app.secret_key = "HealthSync"
firestoreDB = firestore.client()


session = {}


# Load the rf model using pickle
with open(r"final_rf_model.pkl", "rb") as file:
    loaded_rf_model = pickle.load(file)

# Load the specialized_dict from JSON
with open(r"disease_specialist_dict.json", "r") as file:
    loaded_specialized_dict = json.load(file)

# Load the prediction_encoder classes from JSON
with open(r"encoder_data.json", "r") as file:
    encoder_data = json.load(file)

with open(r"X.pkl", "rb") as file:
    X = pickle.load(file)

symptoms = X.columns.values

symptom_index = {}
for index, value in enumerate(symptoms):
    symptom = " ".join([i.capitalize() for i in value.split("_")])
    symptom_index[symptom] = index

data_dict = {
    "symptom_index": symptom_index,
    "prediction_classes": encoder_data,
}


def check_existing_data(field_name, value):
    clinicRef = firestoreDB.collection('clinics')
    query = clinicRef.where(field_name, '==', value).limit(1).stream()
    if len(list(query)) > 0:
        raise HTTPException(
            status_code=400, detail=f'{field_name.capitalize()} already exists')


# Function to convert string to camel case format
def to_camel_case(string):
    return re.sub(r"(?:^|_)(\w)", lambda x: x.group(1).capitalize(), string)


# Load Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Your Firestore initialization and other imports


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/chatbot")
async def chatbot(request: Request):
    return templates.TemplateResponse("chatbot.html", {"request": request})


@app.post('/clinicSignUp')
async def clinicSignUp(
    request: Request,
    name: str = Form(...),
    license: str = Form(...),
    address: str = Form(...),
    doctors: str = Form(...),
    prim_doc: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    specialties: list = Form(...)
):
    clinic_data = {
        'name': name,
        'license': license,
        'address': address,
        'username': username,
        'password': password,
        'email': email,
        'phone': phone,
        'doctors': doctors.split(','),
        'prim_doc': prim_doc,
        'specialties': specialties
    }

    check_existing_data('username', username)
    check_existing_data('email', email)
    check_existing_data('phone', phone)

    firestoreDB.collection('clinics').add(clinic_data)
    return templates.TemplateResponse(
        "login.html", {"request": request}
    )


@app.post("/userSignUp")
async def userSignUp(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    user_email: str = Form(...),
    password: str = Form(...),
    address: str = Form(...),
    phone: int = Form(...),
    date: str = Form(...),
    aadhaar: str = Form(...),
    user_bio: str = Form(...),
    user_job: str = Form(...),
    gender: str = Form(...),
    checkbox: List[str] = Form(...),

):
    # Check Firestore for existing data and perform validation
    # Note: This part might need to be adapted to use Firestore operations

    # Placeholder for Firestore data storage
    patientRef = firestoreDB.collection('patients')
    date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")

    query = patientRef.where('username', '==', username).limit(1).stream()

    # Example validation checks (replace with Firestore queries)
    if username in query:
        raise HTTPException(status_code=400, detail="Username already exists")
    if user_email in query:
        raise HTTPException(
            status_code=400, detail="User email already exists")
    if phone in query:
        raise HTTPException(
            status_code=400, detail="Phone number already exists")
    if aadhaar in query:
        raise HTTPException(status_code=400, detail="Aadhaar already exists")

    # Placeholder for Firestore write operation (replace with actual write)
    foldername = username
    bucket = client.get_bucket(bucket_path)
    blob = bucket.blob(foldername+'/')
    blob.upload_from_string('')
    patient_data = {
        'name': name,
        'username': username,
        'user_email': user_email,
        'password': password,
        'address': address,
        'phone': phone,
        'date': date,
        'aadhaar': aadhaar,
        'user_bio': user_bio,
        'user_job': user_job,
        'checkbox_values': checkbox,
        'gender': gender
    }
    firestoreDB.collection('patients').add(patient_data)

    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(
    request: Request,
    id: str = Form(...),
    password: str = Form(...),
    userType: str = Form(...),
    response_class=HTMLResponse,

):
    if userType == "patient":
        collection = "patients"
    elif userType == "clinic":
        collection = "clinics"

    user_ref = firestoreDB.collection(collection)
    query = user_ref.where("username", "==", id).limit(1).stream()
    if query:
        for doc in query:
            user_data = doc.to_dict()
            if user_data["password"] == password:
                session["name"] = user_data["name"]
                if userType == "patient":
                    session["date"] = user_data["date"]
                session["user_id"] = doc.id

                if userType == "patient":
                    # Get info of patient to render on page
                    name = user_data["name"]
                    age = datetime.datetime.now().date(
                    ) - datetime.datetime.strptime(user_data["date"], "%m%d%Y").date()
                    years = age.days // 365
                    gender = user_data["gender"]
                    session["userType"] = "patient"
                    session["username"] = user_data["username"]
                    session["phone"] = user_data["phone"]
                    session["address"] = user_data["address"]
                    session["user_bio"] = user_data["user_bio"]
                    session["gender"] = user_data["gender"]
                    session["user_email"] = user_data["user_email"]
                    session["name"] = user_data["name"]
                    user_bio = user_data["user_bio"]

                    return templates.TemplateResponse(
                        "patient_dashboard.html",
                        {"request": request, "name": name, "age": years,
                            "gender": gender, "user_bio": user_data["user_bio"]},
                    )
                elif userType == "clinic":
                    # Get info of clinic to render on page
                    name = user_data["name"]
                    username = user_data["username"]
                    doctors = user_data["doctors"]
                    session["userType"] = "clinic"
                    total_patients = 0
                    upcoming_patients = 0

                    appointmentsDB = firestoreDB.collection("appointments")
                    appointments = appointmentsDB.where(
                        "clinic", "==", username).stream()

                    apps = []  # Initialize the apps list

                    for doc in appointments:
                        app_data = doc.to_dict()
                        app_date = app_data.get("time")
                        findate = datetime.datetime.strptime(
                            app_date, "%d-%m-%Y %I:%M %p").date()
                        current_date = datetime.datetime.now().date()
                        if findate > current_date:
                            upcoming_patients += 1
                            patient_username = app_data.get("patient")
                            if patient_username:
                                total_patients += 1
                                patient_doc = firestoreDB.collection("patients").where(
                                    "username", "==", patient_username).limit(1).stream()
                                patient_doc = list(patient_doc)
                                if patient_doc:
                                    app_data["patient_name"] = patient_doc[0].to_dict().get(
                                        "name")
                                    days = current_date - \
                                        datetime.datetime.strptime(
                                            patient_doc[0].to_dict().get("date"), "%m%d%Y").date()
                                    years = days.days // 365
                                    app_data["p_username"] = patient_doc[0].to_dict().get(
                                        "username")
                                    app_data["patient_age"] = years
                            apps.append(app_data)

                    session["apps"] = apps
                    clinic_data = {
                        "name": name,
                        "doctors": doctors,
                        "total_patients": int(total_patients),
                        "upcoming_patients": int(upcoming_patients),
                        "current_date": current_date.strftime("%d-%m-%Y"),
                    }
                    session["clinic_data"] = clinic_data

                    return templates.TemplateResponse(
                        "clinic_dashboard.html",
                        {"request": request, "clinic_data": clinic_data,
                            "appointments": apps},
                    )
        else:  # wrong password
            return templates.TemplateResponse("login.html")
    else:  # wrong username
        return templates.TemplateResponse("login.html")


# Protected route for logout
@app.get('/logout')
async def logout(request: Request):
    session.clear()
    return templates.TemplateResponse("login.html", {"request": request})

# Route for user redirection


@app.get('/userRedir', response_class=HTMLResponse)
def userRedir(request: Request):
    return templates.TemplateResponse("userSignUp.html", {"request": request})

# Route for patient redirection


@app.get('/patientRedir', response_class=HTMLResponse)
def patientRedir(request: Request):
    name = session['name']
    user_bio = session['user_bio']
    age = datetime.datetime.now().date(
    ) - datetime.datetime.strptime(session['date'], '%m%d%Y').date()
    years = age.days // 365
    gender = session['gender']
    return templates.TemplateResponse(
        "patient_dashboard.html",
        {"request": request, "name": name, "age": years,
            "user_bio": user_bio, "gender": gender},
    )

# Route for clinic redirection


@app.get('/clinicRedir',  response_class=HTMLResponse)
async def clinicRedir(request: Request):
    specialties = ['Dermatology', 'Allergology', 'Gastroenterology',
                   'Hepatology', 'Infectious Diseases', 'Endocrinology',
                   'Pulmonology', 'Cardiology', 'Neurology', 'Orthopedics',
                   'Internal Medicine', 'Proctology', 'Vascular Surgery',
                   'Rheumatology', 'Otolaryngology', 'Urology']

    return templates.TemplateResponse(
        "clinicSignUp.html",
        {"request": request, "specialties": specialties},
    )


@app.get("/dashRedir")
async def dashRedir(request: Request):
    clinic_data = session.get('clinic_data', {})
    apps = session.get('apps', [])
    return templates.TemplateResponse(
        "clinic_dashboard.html",
        {"request": request, "clinic_data": clinic_data, "appointments": apps}
    )


@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    metadata: str = Form(...),
    name: str = Form(...),
):
    bucket = client.get_bucket(bucket_path)
    path = f"{session['username']}/{name}.pdf"
    blob = bucket.blob(path)
    blob.content_disposition = "inline"
    blob.metadata = {"metadata": metadata}

    with file.file as pdf:
        blob.upload_from_file(pdf)

    return templates.TemplateResponse("patient_dashboard.html", {"request": request})


@app.get("/uploadRedir")
async def uploadRedir(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@app.get("/recRedir")
async def recRedir(request: Request):
    response = {}
    return templates.TemplateResponse(
        "recommender_html.html", {"request": request, "response": response}
    )


@app.get("/profile")
async def profile(request: Request):
    if session["userType"] == 'patient':
        name = session['name']
        email = session['user_email']
        phone = session['phone']
        age = current_date - \
            datetime.datetime.strptime(session['date'], '%m%d%Y').date()
        age = age.days//365
        address = session['address']
        bio = session['user_bio']
        gender = session['gender']

        patient_data = {
            'name': name,
            'email': email,
            'phone': phone,
            'age': age,
            'address': address,
            'bio': bio,
            'gender': gender
        }
        username = session['username']
        bucket = client.get_bucket(bucket_path)
        blobs = bucket.list_blobs(prefix=username+'/')
        prefixes = set()
        toBeRendered = []

        for blob in chain(*blobs.pages):
            prefixes.add(blob.name.split('/')[0])
            if blob.name.endswith('.pdf'):
                pdf_name = blob.name
                pdf_name = pdf_name.split('/')[1]
                pdf_link = f"https://storage.googleapis.com/{bucket_path}/{blob.name}"
                metadata = blob.metadata
                # remove brackets and the word metadata from metadata
                metadata = str(metadata)
                metadata = metadata.replace('metadata', '')
                metadata = metadata.replace('{', '')
                metadata = metadata.replace('}', '')
                metadata = metadata.replace("'", '')
                metadata = metadata.replace(':', '')
                tbu = {'pdf_name': pdf_name,
                       'pdf_link': pdf_link, 'metadata': metadata}
                toBeRendered.append(tbu)
        return templates.TemplateResponse('profile.html', {'request': request, 'patient_data': patient_data, 'toBeRendered': toBeRendered})
    elif session["userType"] == 'clinic':
        username = request.query_params.get('p_username')

        patient_doc_query = firestoreDB.collection('patients').where(
            'username', '==', username).limit(1).stream()
        patient_doc = list(patient_doc_query)

        if patient_doc:
            patient_dict = patient_doc[0].to_dict()
            name = patient_dict.get('name')
            email = patient_dict.get('user_email')
            phone = patient_dict.get('phone')
            age = (current_date - datetime.datetime.strptime(
                patient_dict.get('date'), '%m%d%Y').date()).days // 365
            address = patient_dict.get('address')
            bio = patient_dict.get('user_bio')
            gender = patient_dict.get('gender')
        else:
            raise HTTPException(status_code=404, detail="Patient not found")

        patient_data = {
            'name': name,
            'email': email,
            'phone': phone,
            'age': age,
            'address': address,
            'bio': bio,
            'gender': gender
        }

        bucket = client.get_bucket(bucket_path)
        blobs = bucket.list_blobs(prefix=f"{username}/")
        prefixes = set()
        toBeRendered = []

        for blob in chain(*blobs.pages):
            prefixes.add(blob.name.split('/')[0])
            if blob.name.endswith('.pdf'):
                pdf_name = blob.name.split('/')[1]
                pdf_link = f"https://storage.googleapis.com/{bucket_path}/{blob.name}"
                metadata = blob.metadata
                metadata_str = str(metadata).replace(
                    "'", '').replace('{', '').replace('}', '')
                tbu = {'pdf_name': pdf_name, 'pdf_link': pdf_link,
                       'metadata': metadata_str}
                toBeRendered.append(tbu)

        return templates.TemplateResponse('viewProfileClinic.html', {'request': request, 'patient_data': patient_data, 'toBeRendered': toBeRendered})


@app.get('/showDocs')
async def showDocs(request: Request):
    username = session['username']
    bucket = client.get_bucket(bucket_path)
    blobs = bucket.list_blobs(prefix=username+'/')
    prefixes = set()
    toBeRendered = []

    for blob in chain(*blobs.pages):
        prefixes.add(blob.name.split('/')[0])
        if blob.name.endswith('.pdf'):
            pdf_name = blob.name
            pdf_link = f"https://storage.googleapis.com/{bucket_path}/{blob.name}"
            metadata = blob.metadata
            # only get pdfname from '/' onwards
            pdf_name = pdf_name.split('/')[1]
            metadata = str(metadata)
            metadata = metadata.replace('metadata', '')
            metadata = metadata.replace('{', '')
            metadata = metadata.replace('}', '')
            metadata = metadata.replace("'", '')
            metadata = metadata.replace(':', '')

            tbu = {'pdf_name': pdf_name,
                   'pdf_link': pdf_link, 'metadata': metadata}
            toBeRendered.append(tbu)
    return templates.TemplateResponse('yourDocs.html', {'request': request, 'toBeRendered': toBeRendered})


@app.post("/recommender", response_class=HTMLResponse)
async def recommender(request: Request, symptom1: str = Form(...), symptom2: str = Form(...), symptom3: str = Form(...)):
    symptoms = [to_camel_case(symptom1), to_camel_case(
        symptom2), to_camel_case(symptom3)]
    input_data = [0] * len(data_dict["symptom_index"])
    for symptom in symptoms:
        index = data_dict["symptom_index"].get(symptom)
        if index is not None:
            input_data[index] = 1
    input_data = np.array(input_data).reshape(1, -1)
    final_prediction = data_dict["prediction_classes"][loaded_rf_model.predict(input_data)[
        0]]
    specialist_info = loaded_specialized_dict.get(final_prediction)
    if specialist_info is None:
        specialist_department = "Unknown"
        severity = "Unknown"
        observed_symptoms = []
    else:
        specialist_department = specialist_info.get("department", "Unknown")
        severity = specialist_info.get("severity", "Unknown")
        observed_symptoms = specialist_info.get("observed_symptoms", [])

    clinics = firestoreDB.collection('clinics').where(
        'specialties', 'array_contains', specialist_department).stream()
    clinic_list = []
    for clinic in clinics:
        clinic_list.append(clinic.to_dict())
    response = {
        "suspected_disease": final_prediction,
        "specialist_department": specialist_department,
        "severity": severity,
        "observed_symptoms": observed_symptoms,
        "clinic_data": clinic_list  # Add the clinic data to the response dictionary
    }
    return templates.TemplateResponse("recommender_html.html", {"request": request, "response": response})


@app.post("/book_appointment")
async def book_appointment(
    request: Request,
    clinic_username: str = Form(...),
    time: str = Form(...),
    reason: str = Form(...),
    symptoms: str = Form(...),
    department: str = Form(...),
):
    patient_username = session.get("username")
    appointment_time = datetime.datetime.strptime(time, "%Y-%m-%dT%H:%M")

    formatted_time = appointment_time.strftime("%d-%m-%Y %I:%M %p")

    appointment_data = {
        "clinic": clinic_username,
        "patient": patient_username,
        "time": formatted_time,
        "reason": reason,
        "symptoms": symptoms,
        "department": department,
    }
    firestoreDB.collection("appointments").add(appointment_data)

    return templates.TemplateResponse("patient_dashboard.html", {"request": request})
