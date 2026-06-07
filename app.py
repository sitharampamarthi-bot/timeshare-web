from flask import Flask, render_template, request, redirect, jsonify
import sqlite3
import firebase_admin
from firebase_admin import credentials, firestore, storage
from datetime import datetime
from flask import send_file
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
import tempfile
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for
)
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import json

app = Flask(__name__)

firebase_key = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if firebase_key:
    cred_dict = json.loads(firebase_key)
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate(
        os.path.join(BASE_DIR, "serviceAccountKey.json")
    )

firebase_admin.initialize_app(cred, {
    "storageBucket": "timeshare-app-f35b3.firebasestorage.app"
})

db = firestore.client()


def parse_bill_date(date_text):
    if not date_text:
        return None

    date_text = str(date_text).strip()

    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_text, fmt).date()
        except:
            pass

    return None


print("BASE_DIR =", BASE_DIR)

file_path = os.path.join(BASE_DIR, "serviceAccountKey.json")
print("FILE =", file_path)

print("EXISTS =", os.path.exists(file_path))

def upload_files(files):
    urls = []
    bucket = storage.bucket()

    for file in files:
        if file and file.filename:
            filename = f"bill_files/{datetime.now().timestamp()}_{file.filename}"
            blob = bucket.blob(filename)
            blob.upload_from_file(file, content_type=file.content_type)
            blob.make_public()
            urls.append({
                "name": file.filename,
                "url": blob.public_url,
                "type": file.content_type
            })

    return urls

@app.route("/remove-file/<doc_id>/<int:file_index>")
def remove_file(doc_id, file_index):
    bill_ref = db.collection("bills").document(doc_id)
    bill = bill_ref.get().to_dict() or {}

    files = bill.get("files", [])

    if 0 <= file_index < len(files):
        files.pop(file_index)

    bill_ref.update({"files": files})
    return redirect(f"/edit-bill/{doc_id}")

@app.route("/get-member/<id_no>")
def get_member(id_no):
    search_id = id_no.strip().lower()

    docs = db.collection("bills").stream()

    for doc in docs:
        data = doc.to_dict()
        existing_id = str(data.get("idNo", "")).strip().lower()

        if existing_id == search_id:
            return jsonify({
                "found": True,
                "memberName": data.get("memberName", ""),
                "mobileNo": data.get("mobileNo", "")
            })

    return jsonify({"found": False})

@app.route("/test-firebase")
def test_firebase():
    docs = db.collection("bills").stream()

    count = 0
    for doc in docs:
        count += 1

    return {"bills_count": count}

def create_db():
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            mobile TEXT UNIQUE,
            email TEXT,
            password TEXT,
            role TEXT DEFAULT 'user'
        )
    """)

    conn.commit()
    conn.close()

@app.route("/", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip().lower()
        password = request.form.get("password", "").strip()

        docs = db.collection("users").stream()

        for doc in docs:
            data = doc.to_dict()

            db_mobile = str(data.get("mobile", "")).strip().lower()
            db_phone = str(data.get("phone", "")).strip().lower()
            db_email = str(data.get("email", "")).strip().lower()
            db_password = str(data.get("password", "")).strip()

            if (login_id == db_mobile or login_id == db_phone or login_id == db_email) and password == db_password:
                return redirect("/admin-dashboard")

        error = "Invalid mobile/email or password"

    return render_template("login.html", error=error)


@app.route("/signup", methods=["GET", "POST"])
def signup():

    error = ""

    if request.method == "POST":

        name = request.form["name"]
        mobile = request.form["mobile"]
        email = request.form["email"]
        password = request.form["password"]

        user = db.collection("users") \
                 .where("mobile", "==", mobile) \
                 .limit(1) \
                 .get()

        if len(user) > 0:
            error = "Mobile number already registered"

        else:
            db.collection("users").add({
                "name": name,
                "mobile": mobile,
                "email": email,
                "password": password
            })

            return redirect("/")

    return render_template(
        "signup.html",
        error=error
    )
    
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = ""

    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        email = request.form.get("email", "").strip().lower()

        found_id = None

        docs = db.collection("users").stream()

        for doc in docs:
            data = doc.to_dict()

            db_mobile = str(data.get("mobile", "")).strip()
            db_phone = str(data.get("phone", "")).strip()
            db_email = str(data.get("email", "")).strip().lower()

            if mobile and (db_mobile == mobile or db_phone == mobile):
                found_id = doc.id
                break

            if email and db_email == email:
                found_id = doc.id
                break

        if found_id:
            return redirect(f"/reset-password/{found_id}")
        else:
            message = "Mobile number or email not found"

    return render_template("forgot_password.html", message=message)

@app.route("/reset-password/<user_id>", methods=["GET", "POST"])
def reset_password(user_id):
    message = ""

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if new_password != confirm_password:
            message = "Passwords do not match"
        elif len(new_password) < 4:
            message = "Password must be at least 4 characters"
        else:
            db.collection("users").document(user_id).update({
                "password": new_password
            })
            return redirect("/")

    return render_template("reset_password.html", message=message)    
    
@app.route("/admin-dashboard")
def admin_dashboard():
    bills_docs = list(db.collection("bills").stream())
    users_docs = list(db.collection("users").stream())

    total_bills = len(bills_docs)
    total_users = len(users_docs)

    total_payment = 0
    for doc in bills_docs:
        data = doc.to_dict()
        total_payment += float(data.get("paidAmount") or 0)

    return render_template(
        "admin_dashboard.html",
        total_bills=total_bills,
        total_users=total_users,
        total_payment=total_payment
    )

@app.route('/bills')
def bills():
    search = request.args.get("search", "").strip().lower()
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")

    page = int(request.args.get("page", 1))
    per_page = 50
    start = (page - 1) * per_page

    from_dt = parse_bill_date(from_date)
    to_dt = parse_bill_date(to_date)

    docs = db.collection('bills').stream()
    bills_list = []

    for doc in docs:
        data = doc.to_dict()

        bill = {
            "docId": doc.id,
            "date": data.get("date", ""),
            "idNo": data.get("idNo", ""),
            "receiptNo": data.get("receiptNo", ""),
            "memberName": data.get("memberName", ""),
            "mobileNo": data.get("mobileNo", ""),
            "paidAmount": data.get("paidAmount", 0),
            "paymentMode": data.get("paymentMode", ""),
            "executiveName": data.get("executiveName", ""),
            "remarks": data.get("remarks", ""),
            "files": data.get("files", []) or data.get("images", []),
        }

        search_text = f"{bill['idNo']} {bill['receiptNo']} {bill['memberName']} {bill['mobileNo']}".lower()

        if search and search not in search_text:
            continue

        bill_dt = parse_bill_date(bill["date"])

        if from_dt and bill_dt and bill_dt < from_dt:
            continue

        if to_dt and bill_dt and bill_dt > to_dt:
            continue

        bills_list.append(bill)

    bills_list.sort(
        key=lambda x: parse_bill_date(x.get("date", "")) or datetime.min.date(),
        reverse=True
    )

    total_payment = sum(float(b["paidAmount"] or 0) for b in bills_list)
    total_bills = len(bills_list)

    total_pages = (total_bills + per_page - 1) // per_page
    if total_pages == 0:
        total_pages = 1

    bills_page = bills_list[start:start + per_page]

    return render_template(
        "bills.html",
        bills=bills_page,
        total_bills=total_bills,
        total_payment=total_payment,
        search=search,
        from_date=from_date,
        to_date=to_date,
        page=page,
        total_pages=total_pages
    )
    
def is_duplicate_receipt(receipt_no, current_doc_id=None):
    receipt_no = str(receipt_no).strip().lower()

    docs = db.collection("bills").stream()

    for doc in docs:
        data = doc.to_dict()
        old_receipt = str(data.get("receiptNo", "")).strip().lower()

        if old_receipt == receipt_no:
            if current_doc_id and doc.id == current_doc_id:
                continue
            return True

    return False    
    
@app.route("/add-bill", methods=["GET", "POST"])
def add_bill():
    if request.method == "POST":
        receipt_no = request.form["receiptNo"]

        if is_duplicate_receipt(receipt_no):
            return render_template(
                "bill_form.html",
                bill=None,
                error="Receipt number already exists. Please use another receipt number."
            )

        uploaded_files = upload_files(request.files.getlist("files"))

        data = {
            "files": uploaded_files,
            "date": request.form["date"],
            "idNo": request.form["idNo"],
            "receiptNo": receipt_no,
            "memberName": request.form["memberName"],
            "mobileNo": request.form["mobileNo"],
            "paidAmount": float(request.form["paidAmount"] or 0),
            "paymentMode": request.form["paymentMode"],
            "executiveName": request.form["executiveName"],
            "remarks": request.form["remarks"],
        }

        db.collection("bills").add(data)
        return redirect("/bills")

    return render_template("bill_form.html", bill=None, error=None)


@app.route("/edit-bill/<doc_id>", methods=["GET", "POST"])
def edit_bill(doc_id):
    bill_ref = db.collection("bills").document(doc_id)

    if request.method == "POST":
        receipt_no = request.form["receiptNo"]

        if is_duplicate_receipt(receipt_no, doc_id):
            bill = bill_ref.get().to_dict() or {}
            bill["docId"] = doc_id

            return render_template(
                "bill_form.html",
                bill=bill,
                error="Receipt number already exists. Please use another receipt number."
            )

        old_bill = bill_ref.get().to_dict() or {}
        old_files = old_bill.get("files", []) or old_bill.get("images", [])

        new_files = upload_files(request.files.getlist("files"))
        all_files = old_files + new_files

        data = {
            "date": request.form["date"],
            "idNo": request.form["idNo"],
            "receiptNo": receipt_no,
            "memberName": request.form["memberName"],
            "mobileNo": request.form["mobileNo"],
            "paidAmount": float(request.form["paidAmount"] or 0),
            "paymentMode": request.form["paymentMode"],
            "executiveName": request.form["executiveName"],
            "remarks": request.form["remarks"],
            "files": all_files,
        }

        bill_ref.update(data)
        return redirect("/bills")

    bill = bill_ref.get().to_dict() or {}
    bill["docId"] = doc_id

    return render_template("bill_form.html", bill=bill, error=None)


@app.route("/delete-bill/<doc_id>")
def delete_bill(doc_id):
    db.collection("bills").document(doc_id).delete()
    return redirect("/bills")

@app.route("/download_pdf")
def download_pdf():
    
    search = request.args.get("search", "").strip().lower()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()

    from_dt = parse_bill_date(from_date) if from_date else None
    to_dt = parse_bill_date(to_date) if to_date else None

    docs = db.collection("bills").stream()
    bills_list = []

    for doc in docs:
        data = doc.to_dict()

        bill_date = data.get("date", "")
        bill_dt = parse_bill_date(bill_date)

        id_no = str(data.get("idNo", ""))
        receipt_no = str(data.get("receiptNo", ""))
        member_name = str(data.get("memberName", ""))
        mobile_no = str(data.get("mobileNo", ""))
        paid_amount = data.get("paidAmount", 0)

        search_text = f"{id_no} {receipt_no} {member_name} {mobile_no}".lower()

        if search and search not in search_text:
            continue

        if from_dt and bill_dt and bill_dt < from_dt:
            continue

        if to_dt and bill_dt and bill_dt > to_dt:
            continue

        bills_list.append({
            "date": bill_date,
            "idNo": id_no,
            "receiptNo": receipt_no,
            "memberName": member_name,
            "mobileNo": mobile_no,
            "paidAmount": paid_amount,
        })

    total_payment = sum(float(b["paidAmount"] or 0) for b in bills_list)

    pdf_path = tempfile.mktemp(".pdf")
    pdf = SimpleDocTemplate(pdf_path, pagesize=A4)

    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Timeshare Billing Report", styles["Title"]))
    elements.append(Spacer(1, 12))

    if search:
        elements.append(Paragraph(f"Search: {search}", styles["Normal"]))

    if from_date or to_date:
        elements.append(Paragraph(f"Date Filter: {from_date} to {to_date}", styles["Normal"]))

    elements.append(Paragraph(f"Total Bills: {len(bills_list)}", styles["Normal"]))
    elements.append(Paragraph(f"Total Payment: Rs.{total_payment}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    rows = [["Date", "ID No", "Receipt", "Member", "Mobile", "Amount"]]

    for b in bills_list:
        rows.append([
            str(b["date"]),
            str(b["idNo"]),
            str(b["receiptNo"]),
            str(b["memberName"]),
            str(b["mobileNo"]),
            str(b["paidAmount"]),
        ])

    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))

    elements.append(table)
    pdf.build(elements)
    
    print("SEARCH =", search)
    print("FROM =", from_date)
    print("TO =", to_date)

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name="bills_report.pdf"
    )

create_db()

if __name__ == "__main__":    
    app.run(debug=True, host="0.0.0.0", port=5000)