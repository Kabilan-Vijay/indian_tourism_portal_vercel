from flask import Flask, render_template, request, redirect, session, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
import time
import os

import config

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = "tourism_secret"

# Upload settings for admin image uploads
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER")
if not UPLOAD_FOLDER:
    if os.environ.get("VERCEL") or os.path.abspath(__file__).startswith("/var/task"):
        UPLOAD_FOLDER = "/tmp/uploads"
    else:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if UPLOAD_FOLDER.startswith("/tmp"):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    """Return True if the filename has an allowed image extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def get_db():
    """Get a per-request database connection (avoids stale connections on serverless)."""
    if "db" not in g:
        g.db = psycopg2.connect(
            os.environ["DATABASE_URL"],
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return g.db


@app.teardown_appcontext
def close_db(exc):
    """Close the database connection at the end of each request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Context processor to pass states and places to all templates
@app.context_processor
def inject_states():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM states")
    states = cursor.fetchall()

    states_with_places = []
    for state in states:
        cursor.execute("SELECT * FROM places WHERE state_id=%s", (state['id'],))
        places = cursor.fetchall()
        state['places'] = places
        states_with_places.append(state)

    return {'all_states': states_with_places}


# HOME PAGE
@app.route('/')
def home():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM states")
    states = cursor.fetchall()
    return render_template("index.html", states=states)


# STATES PAGE
@app.route('/states')
def states():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM states")
    states = cursor.fetchall()
    return render_template("states.html", states=states)


# PLACES PAGE
@app.route('/places/<int:state_id>')
def places(state_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM states WHERE id=%s", (state_id,))
    state = cursor.fetchone()
    cursor.execute("SELECT * FROM places WHERE state_id=%s", (state_id,))
    places = cursor.fetchall()
    return render_template("places.html", places=places, state=state)


# GALLERY PAGE
@app.route('/place/<int:place_id>')
def gallery(place_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM places WHERE id=%s", (place_id,))
    place = cursor.fetchone()
    cursor.execute("SELECT * FROM place_images WHERE place_id=%s", (place_id,))
    images = cursor.fetchall()
    return render_template("gallery.html", place=place, images=images)


# CONTACT PAGE
@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == "POST":
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO contact_messages(name,email,message) VALUES(%s,%s,%s)",
            (name, email, message),
        )
        db.commit()
    return render_template("contact.html")


# LOGIN PAGE
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email=%s AND password=%s",
            (email, password),
        )
        user = cursor.fetchone()
        if user:
            session['role'] = user['role']
            if user['role'] == "admin":
                return redirect('/admin/dashboard')
            return redirect('/')
    return render_template("login.html")


# ADMIN DASHBOARD
@app.route('/admin/dashboard')
def dashboard():
    if session.get("role") != "admin":
        return redirect('/login')
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM states")
    states = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM places")
    places = cursor.fetchone()
    return render_template("admin/dashboard.html", states=states, places=places)


# ADD PLACE
@app.route('/admin/add_place', methods=['GET', 'POST'])
def add_place():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM states")
    states = cursor.fetchall()

    if request.method == "POST":
        place = request.form['place']
        state = request.form['state']
        desc = request.form['description']
        custom_filename = request.form.get('image_filename', '').strip()
        image_name = ""

        file = request.files.get('image_file')
        if file and file.filename and custom_filename:
            if allowed_file(file.filename):
                safe_filename = secure_filename(custom_filename)
                if not safe_filename:
                    return render_template("admin/add_place.html", states=states,
                        error="Invalid filename. Please use only letters, numbers, underscores, hyphens, and dots.")
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_filename)
                if os.path.exists(file_path):
                    return render_template("admin/add_place.html", states=states,
                        error=f"File '{safe_filename}' already exists. Please choose a different filename.")
                file.save(file_path)
                image_name = safe_filename
        elif custom_filename and not file:
            safe_filename = secure_filename(custom_filename)
            if not safe_filename:
                return render_template("admin/add_place.html", states=states,
                    error="Invalid filename. Please use only letters, numbers, underscores, hyphens, and dots.")
            image_name = safe_filename
        else:
            return render_template("admin/add_place.html", states=states,
                error="Please select a file to upload and provide a filename, or enter an existing filename.")

        if image_name:
            cursor2 = db.cursor()
            cursor2.execute(
                "INSERT INTO places(place_name,state_id,description,image) VALUES(%s,%s,%s,%s)",
                (place, state, desc, image_name),
            )
            db.commit()
            return redirect('/admin/dashboard')

    return render_template("admin/add_place.html", states=states)


# ADD GALLERY IMAGE
@app.route('/admin/add_gallery', methods=['GET', 'POST'])
def add_gallery():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM places")
    places = cursor.fetchall()

    if request.method == "POST":
        place = request.form.get('place')
        custom_filename = request.form.get('image_filename', '').strip()
        image_name = ""

        file = request.files.get('image_file')
        if file and file.filename and custom_filename:
            if allowed_file(file.filename):
                safe_filename = secure_filename(custom_filename)
                if not safe_filename:
                    return render_template("admin/add_gallery.html", places=places,
                        error="Invalid filename. Please use only letters, numbers, underscores, hyphens, and dots.")
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_filename)
                if os.path.exists(file_path):
                    return render_template("admin/add_gallery.html", places=places,
                        error=f"File '{safe_filename}' already exists. Please choose a different filename.")
                file.save(file_path)
                image_name = safe_filename
        elif custom_filename and not file:
            safe_filename = secure_filename(custom_filename)
            if not safe_filename:
                return render_template("admin/add_gallery.html", places=places,
                    error="Invalid filename. Please use only letters, numbers, underscores, hyphens, and dots.")
            image_name = safe_filename
        else:
            return render_template("admin/add_gallery.html", places=places,
                error="Please select a file to upload and provide a filename, or enter an existing filename.")

        if image_name:
            cursor2 = db.cursor()
            cursor2.execute(
                "INSERT INTO place_images(place_id,image) VALUES(%s,%s)",
                (place, image_name),
            )
            db.commit()
            return redirect('/admin/dashboard')

    return render_template("admin/add_gallery.html", places=places)


app = app