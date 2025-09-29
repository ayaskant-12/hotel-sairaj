import os
import pytz
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import jwt
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import base64
from export_utils import export_to_excel, export_to_pdf
from flask import send_file

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URI', 'postgresql://postgres:your-id@localhost/hotel_sairaj')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'your_secret_key_here')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['TIMEZONE'] = pytz.timezone('Asia/Kolkata')
app.config['SMTP_SERVER'] = 'smtp.gmail.com'
app.config['SMTP_PORT'] = 587  # Use 587 for TLS
app.config['SMTP_USERNAME'] = 'your-email@gmail.com' #Your email
app.config['SMTP_PASSWORD'] = 'your-app-password'  # Your app password
app.config['ADMIN_EMAIL'] = os.environ.get('ADMIN_EMAIL', 'admin@hotelsairaj.com')
app.config['HOTEL_NAME'] = os.environ.get('HOTEL_NAME', 'Hotel SairaJ')

# Create upload directory
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.cli.command("init-db")
def init_db_command():
    db.create_all()
    create_admin_user()
    print("Database initialized")
    

db = SQLAlchemy(app)
@app.context_processor
def inject_current_time():
    def current_time(format='%Y-%m-%d'):
        return kolkata_now().strftime(format)
    return dict(current_time=current_time)

# Helper function to get current time in Kolkata
def kolkata_now():
    return datetime.now(app.config['TIMEZONE'])

# Database Models
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(20), default='Available')  # Available, Booked, Occupied, Maintenance
    room_type = db.Column(db.String(50))
    rate = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)

    @property
    def formatted_rate(self):
        return f" ₹{self.rate:.2f}"

class Guest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guest_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    id_proof_type = db.Column(db.String(50), nullable=False)
    age = db.Column(db.Integer)  # Add this line for guest age
    id_proof_number = db.Column(db.String(50), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    room = db.relationship('Room', backref='guests')
    purpose = db.Column(db.String(100))
    check_in = db.Column(db.DateTime(timezone=True), nullable=False)
    check_out = db.Column(db.DateTime(timezone=True))  # Add timezone=True
    status = db.Column(db.String(20), default='Checked-In')
    created_at = db.Column(db.DateTime(timezone=True), default=kolkata_now)
    guest_photo = db.Column(db.String(100))
    id_photo = db.Column(db.String(100))
    rate = db.Column(db.Float)
    adults = db.Column(db.Integer, default=1)  # Including the guest
    children = db.Column(db.Integer, default=0)
    accompanying_persons = db.Column(db.JSON, nullable=True)
    
    @property
    def formatted_rate(self):
        rate = self.rate if self.rate else self.room.rate
        return f" ₹{rate:.2f}"

    @property
    def formatted_check_in(self):
        return self.check_in.strftime('%d %b %Y, %I:%M %p')
    
    @property
    def formatted_check_out(self):
        return self.check_out.strftime('%d %b %Y, %I:%M %p') if self.check_out else '-'

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    activity = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=kolkata_now)

class Booking(db.Model):
    __tablename__ = 'booking'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    arrival_date = db.Column(db.DateTime, nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'))
    status = db.Column(db.String(20), default='Pending')  # Pending, Confirmed, Cancelled
    created_at = db.Column(db.DateTime, default=kolkata_now)
    notes = db.Column(db.Text)
    
    room = db.relationship('Room', backref='bookings')
    
    @property
    def formatted_arrival(self):
        return self.arrival_date.strftime('%d %b %Y, %I:%M %p')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(100), nullable=False)  # Email or 'admin'
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=kolkata_now)
    notification_type = db.Column(db.String(20))  # email, in_app, both

    @property
    def formatted_time(self):
        return self.created_at.strftime('%d %b %Y, %I:%M %p')

# Helper Functions
def generate_guest_id():
    timestamp = kolkata_now().strftime("%Y%m%d%H%M%S")
    return f"HSAI-{timestamp}"

def create_jwt_token(username):
    payload = {
        'username': username,
        'exp': datetime.utcnow() + timedelta(hours=8)
    }
    return jwt.encode(payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')

def verify_jwt_token(token):
    try:
        payload = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def format_datetime(dt, format='%d %b %Y, %I:%M %p'):
    if not dt:
        return '-'
    return dt.strftime(format)

def send_email_notification(recipient, subject, message):
    try:
        msg = MIMEMultipart()
        msg['From'] = app.config['SMTP_USERNAME']
        msg['To'] = recipient
        msg['Subject'] = subject
        
        # HTML template with hotel contact info
        html = f"""<html>
            <body>
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background-color: #1a73e8; padding: 20px; text-align: center;">
                        <h2 style="color: white; margin: 0;">{app.config['HOTEL_NAME']}</h2>
                    </div>
                    <div style="padding: 30px; background-color: #f9f9f9;">
                        {message}
                        
                        <!-- Hotel Contact Information -->
                        <div style="margin-top: 30px; padding: 15px; background: #fff; border-radius: 8px; border: 1px solid #e0e0e0;">
                            <p style="margin-bottom: 10px; font-weight: 600;">Hotel Contact Information:</p>
                            <p style="margin: 5px 0;">B1- Chandaka Industrial Estate, Patia, Bhubaneswar Pin-751024</p>
                            <p style="margin: 5px 0;">Phone: 7735388115, 9078030107</p>
                        </div>
                        
                        <p style="margin-top: 30px; color: #777;">
                            This is an automated message. Please do not reply directly to this email.
                        </p>
                    </div>
                    <div style="text-align: center; padding: 20px; color: #777; font-size: 12px;">
                        © {datetime.now().year} {app.config['HOTEL_NAME']}. All rights reserved.
                    </div>
                </div>
            </body>
        </html>"""
        
        msg.attach(MIMEText(html, 'html'))
        
        server = smtplib.SMTP(app.config['SMTP_SERVER'], app.config['SMTP_PORT'])
        server.starttls()  # Enable TLS
        server.login(app.config['SMTP_USERNAME'], app.config['SMTP_PASSWORD'])
        server.sendmail(msg['From'], recipient, msg.as_string())
        server.quit()
        
        return True
    except Exception as e:
        app.logger.error(f"Email sending failed: {str(e)}")
        return False

def create_notification(recipient, subject, message, notification_type='both'):
    try:
        notification = Notification(
            recipient=recipient,
            subject=subject,
            message=message,
            notification_type=notification_type
        )
        db.session.add(notification)
        db.session.commit()
        
        if notification_type in ('email', 'both') and '@' in recipient:
            send_email_notification(recipient, subject, message)
            
        return True
    except Exception as e:
        app.logger.error(f"Failed to create notification: {str(e)}")
        return False

# Routes
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def home():
    if 'jwt_token' in session:
        token = session['jwt_token']
        if verify_jwt_token(token):
            return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and admin.check_password(password):
            token = create_jwt_token(username)
            session['jwt_token'] = token
            
            new_log = ActivityLog(activity=f"Admin logged in at {kolkata_now().strftime('%I:%M %p')}")
            db.session.add(new_log)
            db.session.commit()
            
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'jwt_token' in session:
        new_log = ActivityLog(activity=f"Admin logged out at {kolkata_now().strftime('%I:%M %p')}")
        db.session.add(new_log)
        db.session.commit()
        
        session.pop('jwt_token', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return redirect(url_for('login'))
    
    active_guests = Guest.query.filter_by(status='Checked-In').count()
    available_rooms = Room.query.filter_by(status='Available').count()
    
    # Calculate today's revenue
    today = kolkata_now().date()
    revenue_today = db.session.query(db.func.sum(Revenue.amount)).filter(
        db.func.date(Revenue.date) == today
    ).scalar() or 0
    
    # Calculate today's expenses
    expenses_today = db.session.query(db.func.sum(Expense.amount)).filter(
        db.func.date(Expense.date) == today
    ).scalar() or 0
    
    activities = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
    
    return render_template('dashboard.html', 
                           active_guests=active_guests,
                           available_rooms=available_rooms,
                           revenue_today=revenue_today,
                           expenses_today=expenses_today,
                           activities=activities)

@app.route('/guests')
def guests():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return redirect(url_for('login'))
    
    # Get search query
    search_query = request.args.get('search', '')
    
    # Base query
    query = Guest.query
    
    # Apply search filter
    if search_query:
        query = query.filter(
            (Guest.name.ilike(f'%{search_query}%')) |
            (Guest.guest_id.ilike(f'%{search_query}%')) |
            (Guest.phone.ilike(f'%{search_query}%')) |
            (Room.room_number.ilike(f'%{search_query}%'))  # Search by room number
        ).join(Room)
    
    # Sort by check-in date descending
    guests = Guest.query.all()
    guests_list = query.order_by(Guest.check_in.desc()).all()
    available_rooms = Room.query.filter_by(status='Available').all()
    
    return render_template('guests.html', 
                           guests=guests_list,
                           available_rooms=available_rooms,
                           search_query=search_query)

@app.route('/add_guest', methods=['POST'])
def add_guest():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        guest_photo = request.files.get('guest_photo')
        id_photo = request.files.get('id_photo')
        
        guest_photo_filename = None
        id_photo_filename = None
        
        if guest_photo and allowed_file(guest_photo.filename):
            filename = secure_filename(guest_photo.filename)
            unique_name = f"guest_{kolkata_now().strftime('%Y%m%d%H%M%S')}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            guest_photo.save(filepath)
            guest_photo_filename = unique_name
        
        if id_photo and allowed_file(id_photo.filename):
            filename = secure_filename(id_photo.filename)
            unique_name = f"id_{kolkata_now().strftime('%Y%m%d%H%M%S')}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            id_photo.save(filepath)
            id_photo_filename = unique_name
        
        check_in_str = request.form.get('check_in')
        naive_check_in = datetime.strptime(check_in_str, '%Y-%m-%dT%H:%M')
        check_in_dt = app.config['TIMEZONE'].localize(naive_check_in)
        
        room_id = request.form.get('room_id')
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'success': False, 'error': 'Room not found'}), 400
        
        custom_rate = request.form.get('custom_rate')
        rate = float(custom_rate) if custom_rate else room.rate
        
        if room.status != 'Available':
            return jsonify({'success': False, 'error': 'Room is not available'}), 400
        
        # Get accompanying persons data
        accompanying_persons = []
        names = request.form.getlist('accompanying_name[]')
        relationships = request.form.getlist('accompanying_relationship[]')
        ages = request.form.getlist('accompanying_age[]')
        genders = request.form.getlist('accompanying_gender[]')
        id_types = request.form.getlist('accompanying_id_type[]')
        id_numbers = request.form.getlist('accompanying_id_number[]')
        
        for i in range(len(names)):
            person = {
                'name': names[i],
                'relationship': relationships[i] if i < len(relationships) else '',
                'age': ages[i],
                'gender': genders[i],
                'id_type': id_types[i] if i < len(id_types) else '',
                'id_number': id_numbers[i] if i < len(id_numbers) else ''
            }
            accompanying_persons.append(person)
        age = int(request.form.get('age', 0)) if request.form.get('age') else None
        # Get adults and children
        adults = int(request.form.get('adults', 1))
        children = int(request.form.get('children', 0))
        
        new_guest = Guest(
            guest_id=generate_guest_id(),
            name=request.form.get('name'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            id_proof_type=request.form.get('id_proof_type'),
            id_proof_number=request.form.get('id_proof_number'),
            age=age,
            room=room,
            rate=rate,
            purpose=request.form.get('purpose'),
            check_in=check_in_dt,
            status='Checked-In',
            guest_photo=guest_photo_filename,
            id_photo=id_photo_filename,
            adults=adults,
            children=children,
            accompanying_persons=accompanying_persons
        )
        
        room.status = 'Occupied'
        
        db.session.add(new_guest)
        db.session.commit()
        
        new_log = ActivityLog(activity=f"Added new guest: {new_guest.name} (Room {room.room_number}) at {kolkata_now().strftime('%I:%M %p')}")
        db.session.add(new_log)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Guest added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/guest_details/<int:guest_id>')
def guest_details(guest_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return redirect(url_for('login'))
    
    guest = Guest.query.get_or_404(guest_id)
    return render_template('guest_details.html', guest=guest)

@app.route('/update_guest_status/<int:guest_id>', methods=['POST'])
def update_guest_status(guest_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        guest = Guest.query.get(guest_id)
        if not guest:
            return jsonify({'success': False, 'error': 'Guest not found'}), 404
        
        new_status = request.form.get('status')
        guest.status = new_status
        
        if new_status == 'Checked-Out':
            guest.check_out = kolkata_now()
            if guest.room:
                guest.room.status = 'Available'
            
            # Calculate room revenue
            rate = guest.rate if guest.rate else guest.room.rate
            check_in_aware = guest.check_in
            if guest.check_in.tzinfo is None:
                check_in_aware = app.config['TIMEZONE'].localize(guest.check_in)
            else:
                check_in_aware = guest.check_in
            # Calculate stay duration (minimum 1 day)
            stay_duration = (guest.check_out - guest.check_in).days
            if stay_duration == 0:
                stay_duration = 1
            total_amount = rate * stay_duration
            
            # Add to revenue
            new_revenue = Revenue(
                date=kolkata_now(),
                source=f"Room {guest.room.room_number}",
                amount=total_amount,
                notes=f"Guest: {guest.name} ({stay_duration} days)"
            )
            db.session.add(new_revenue)
        
        db.session.commit()
        
        action = "checked out" if new_status == 'Checked-Out' else "updated"
        new_log = ActivityLog(activity=f"Guest {guest.name} {action} at {kolkata_now().strftime('%I:%M %p')}")
        db.session.add(new_log)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'Guest status updated to {new_status}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/update_guest_rate/<int:guest_id>', methods=['POST'])
def update_guest_rate(guest_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        guest = Guest.query.get(guest_id)
        if not guest:
            return jsonify({'success': False, 'error': 'Guest not found'}), 404
        
        new_rate = request.form.get('new_rate')
        if new_rate:
            guest.rate = float(new_rate)
        else:
            guest.rate = None
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Rate updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/delete_guest/<int:guest_id>', methods=['DELETE'])
def delete_guest(guest_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        guest = Guest.query.get(guest_id)
        if not guest:
            return jsonify({'success': False, 'error': 'Guest not found'}), 404
        
        if guest.status == 'Checked-In' and guest.room:
            guest.room.status = 'Available'
        
        photo_errors = []
        if guest.guest_photo:
            try:
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], guest.guest_photo)
                if os.path.exists(photo_path):
                    os.remove(photo_path)
            except Exception as e:
                photo_errors.append(f"Guest photo: {str(e)}")
        
        if guest.id_photo:
            try:
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], guest.id_photo)
                if os.path.exists(photo_path):
                    os.remove(photo_path)
            except Exception as e:
                photo_errors.append(f"ID photo: {str(e)}")
        
        db.session.delete(guest)
        db.session.commit()
        
        new_log = ActivityLog(activity=f"Deleted guest: {guest.name} (Room {guest.room.room_number}) at {kolkata_now().strftime('%I:%M %p')}")
        db.session.add(new_log)
        db.session.commit()
        
        response = {'success': True, 'message': 'Guest deleted successfully'}
        if photo_errors:
            response['warning'] = "Guest deleted but some files couldn't be removed: " + ", ".join(photo_errors)
        
        return jsonify(response)
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/rooms')
def rooms():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return redirect(url_for('login'))
    
    rooms = Room.query.all()
    return render_template('rooms.html', rooms=rooms)

@app.route('/add_room', methods=['POST'])
def add_room():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        room_number = request.form.get('room_number')
        room_type = request.form.get('room_type')
        rate = float(request.form.get('rate'))
        description = request.form.get('description')
        status = request.form.get('status', 'Available')
        
        if Room.query.filter_by(room_number=room_number).first():
            return jsonify({'success': False, 'error': 'Room number already exists'}), 400
        
        new_room = Room(
            room_number=room_number,
            room_type=room_type,
            rate=rate,
            description=description,
            status=status
        )
        db.session.add(new_room)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Room added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/update_room/<int:room_id>', methods=['POST'])
def update_room(room_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'success': False, 'error': 'Room not found'}), 404
        
        room.room_number = request.form.get('room_number', room.room_number)
        room.room_type = request.form.get('room_type', room.room_type)
        room.rate = float(request.form.get('rate', room.rate))
        room.description = request.form.get('description', room.description)
        room.status = request.form.get('status', room.status)
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Room updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/delete_room/<int:room_id>', methods=['DELETE'])
def delete_room(room_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'success': False, 'error': 'Room not found'}), 404
        
        if room.status == 'Occupied' or room.status == 'Booked':
            return jsonify({'success': False, 'error': 'Cannot delete occupied or booked room'}), 400
        
        db.session.delete(room)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Room deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/room_details/<int:room_id>')
def room_details(room_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'error': 'Unauthorized'}), 401
    
    room = Room.query.get(room_id)
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    
    return jsonify({
        'id': room.id,
        'room_number': room.room_number,
        'room_type': room.room_type,
        'rate': room.rate,
        'status': room.status,
        'description': room.description
    })

@app.route('/bookings')
def bookings():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return redirect(url_for('login'))
    
    # Get search query
    search_query = request.args.get('search', '')
    
    # Base query
    query = Booking.query
    
    # Apply search filter
    if search_query:
        query = query.filter(
            (Booking.name.ilike(f'%{search_query}%')) |
            (Booking.phone.ilike(f'%{search_query}%')) |
            (Booking.email.ilike(f'%{search_query}%'))
        )
    
    # Sort by arrival date descending (newest first)
    query = query.order_by(Booking.arrival_date.asc())
    
    # Get bookings by status
    pending_bookings = query.filter_by(status='Pending').all()
    confirmed_bookings = query.filter_by(status='Confirmed').all()
    cancelled_bookings = query.filter_by(status='Cancelled').all()
    
    available_rooms = Room.query.filter_by(status='Available').all()
    
    return render_template(
        'bookings.html',
        pending_bookings=pending_bookings,
        confirmed_bookings=confirmed_bookings,
        cancelled_bookings=cancelled_bookings,
        available_rooms=available_rooms,
        search_query=search_query  # Pass search query to template
    )

@app.route('/export_guests/excel')
def export_guests_excel():
    guests = Guest.query.all()
    headers = [
        "Guest ID", "Name", "Phone", "Email", "Address", "Age",
        "ID Proof Type", "ID Proof Number", "Room Number", "Room Type",
        "Room Rate (₹)", "Purpose of Stay", "Check-In Date", "Check-Out Date",
        "Status", "Total Adults", "Total Children", "Accompanying Persons"
    ]
    
    data = []
    
    for guest in guests:
        # Format accompanying persons
        accompanying = []
        if guest.accompanying_persons:
            for i, person in enumerate(guest.accompanying_persons, 1):
                accompanying.append(
                    f"Person {i}: {person['name']} ({person['relationship']}), "
                    f"Age: {person['age']}, Gender: {person['gender']}, "
                    f"ID: {person['id_type']} - {person['id_number']}"
                )
        
        data.append([
            guest.guest_id,
            guest.name,
            guest.phone,
            guest.email or "N/A",
            guest.address or "N/A",
            guest.age or "N/A",
            guest.id_proof_type,
            guest.id_proof_number,
            guest.room.room_number if guest.room else "N/A",
            guest.room.room_type if guest.room else "N/A",
            guest.rate if guest.rate else (guest.room.rate if guest.room else "N/A"),
            guest.purpose or "N/A",
            guest.check_in.strftime('%Y-%m-%d %H:%M'),
            guest.check_out.strftime('%Y-%m-%d %H:%M') if guest.check_out else "N/A",
            guest.status,
            guest.adults,
            guest.children,
            "\n".join(accompanying) or "None"
        ])
    
    output, filename = export_to_excel(data, headers, "guests_full_details.xlsx")
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/export_guests/pdf')
def export_guests_pdf():
    guests = Guest.query.all()
    headers = [
        "Guest ID", "Name", "Phone", "Email", "Address", "Age",
        "ID Proof Type", "ID Proof Number", "Room Number", "Room Type",
        "Room Rate (₹)", "Purpose", "Check-In", "Check-Out",
        "Status", "Adults", "Children", "Accompanying Persons"
    ]
    
    data = []
    
    for guest in guests:
        # Format accompanying persons
        accompanying = []
        if guest.accompanying_persons:
            for i, person in enumerate(guest.accompanying_persons, 1):
                accompanying.append(
                    f"Person {i}: {person['name']} ({person['relationship']}), "
                    f"Age: {person['age']}, Gender: {person['gender']}, "
                    f"ID: {person['id_type']} - {person['id_number']}"
                )
        
        data.append([
            guest.guest_id,
            guest.name,
            guest.phone,
            guest.email or "N/A",
            guest.address or "N/A",
            guest.age or "N/A",
            guest.id_proof_type,
            guest.id_proof_number,
            guest.room.room_number if guest.room else "N/A",
            guest.room.room_type if guest.room else "N/A",
            str(guest.rate) if guest.rate else str(guest.room.rate) if guest.room else "N/A",
            guest.purpose or "N/A",
            guest.check_in.strftime('%Y-%m-%d %H:%M'),
            guest.check_out.strftime('%Y-%m-%d %H:%M') if guest.check_out else "N/A",
            guest.status,
            str(guest.adults),
            str(guest.children),
            "\n".join(accompanying) or "None"
        ])
    
    output, filename = export_to_pdf(data, headers, "Guests Full Details Report", "guests_full_details.pdf")
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype='application/pdf'
    )


# Booking Export Routes
@app.route('/export_bookings/excel')
def export_bookings_excel():
    bookings = Booking.query.all()
    headers = ["ID", "Name", "Phone", "Email", "Arrival Date", "Room", "Status"]
    data = []
    
    for booking in bookings:
        data.append([
            booking.id,
            booking.name,
            booking.phone,
            booking.email or "N/A",
            booking.arrival_date.strftime('%Y-%m-%d %H:%M'),
            booking.room.room_number if booking.room else "N/A",
            booking.status
        ])
    
    output, filename = export_to_excel(data, headers, "bookings.xlsx")
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/export_bookings/pdf')
def export_bookings_pdf():
    bookings = Booking.query.all()
    headers = ["ID", "Name", "Phone", "Email", "Arrival Date", "Room", "Status"]
    data = []
    
    for booking in bookings:
        data.append([
            booking.id,
            booking.name,
            booking.phone,
            booking.email or "N/A",
            booking.arrival_date.strftime('%Y-%m-%d %H:%M'),
            booking.room.room_number if booking.room else "N/A",
            booking.status
        ])
    
    output, filename = export_to_pdf(data, headers, "Bookings Report", "bookings.pdf")
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype='application/pdf'
    )

@app.route('/add_booking', methods=['POST'])
def add_booking():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        arrival_str = request.form.get('arrival_date')
        arrival_dt = datetime.strptime(arrival_str, '%Y-%m-%dT%H:%M')
        
        new_booking = Booking(
            name=request.form.get('name'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            arrival_date=arrival_dt,
            room_id=request.form.get('room_id'),
            notes=request.form.get('notes'),
            status='Pending'
        )
        
        db.session.add(new_booking)
        db.session.commit()
        
        new_log = ActivityLog(activity=f"Added new booking for {new_booking.name} at {kolkata_now().strftime('%I:%M %p')}")
        db.session.add(new_log)
        db.session.commit()
        
        # Send notifications
        guest_message = f"""
            <p>Dear {new_booking.name},</p>
            <p>Thank you for your booking at {app.config['HOTEL_NAME']}!</p>
            <p>Your booking details:</p>
            <ul>
                <li>Booking ID: {new_booking.id}</li>
                <li>Arrival: {new_booking.formatted_arrival}</li>
                <li>Room: {new_booking.room.room_number if new_booking.room else 'TBD'}</li>
                <li>Status: {new_booking.status}</li>
            </ul>
            <p>Should you need to contact us before your arrival, please find our contact information below.</p>
            <p>We look forward to welcoming you!</p>
        """
        
        admin_message = f"""
            <p>New booking received:</p>
            <ul>
                <li>Guest: {new_booking.name}</li>
                <li>Phone: {new_booking.phone}</li>
                <li>Arrival: {new_booking.formatted_arrival}</li>
                <li>Room: {new_booking.room.room_number if new_booking.room else 'TBD'}</li>
            </ul>
        """
        
        if new_booking.email:
            create_notification(
                recipient=new_booking.email,
                subject=f"Booking Confirmation - {app.config['HOTEL_NAME']}",
                message=guest_message,
                notification_type='both'
            )
        
        create_notification(
            recipient='admin',
            subject="New Booking Received",
            message=admin_message,
            notification_type='in_app'
        )
        
        return jsonify({'success': True, 'message': 'Booking added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/get_booking_details/<int:booking_id>')
def get_booking_details(booking_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'error': 'Unauthorized'}), 401
    
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404
    
    return jsonify({
        'id': booking.id,
        'name': booking.name,
        'phone': booking.phone,
        'email': booking.email,
        'arrival_date': booking.arrival_date.strftime('%Y-%m-%dT%H:%M'),
        'room_id': booking.room_id,
        'notes': booking.notes
    })

@app.route('/update_booking/<int:booking_id>', methods=['POST'])
def update_booking(booking_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({'success': False, 'error': 'Booking not found'}), 404
        
        original_room = Room.query.get(booking.room_id)
        new_room_id = int(request.form.get('room_id'))
        
        booking.name = request.form.get('name')
        booking.phone = request.form.get('phone')
        booking.email = request.form.get('email')
        booking.notes = request.form.get('notes')
        
        arrival_str = request.form.get('arrival_date')
        booking.arrival_date = datetime.strptime(arrival_str, '%Y-%m-%dT%H:%M')
        
        if booking.room_id != new_room_id:
            if booking.status == 'Confirmed' and original_room:
                original_room.status = 'Available'
            
            new_room = Room.query.get(new_room_id)
            if not new_room:
                return jsonify({'success': False, 'error': 'New room not found'}), 400
                
            if booking.status == 'Confirmed':
                if new_room.status != 'Available':
                    return jsonify({'success': False, 'error': 'New room is not available'}), 400
                new_room.status = 'Booked'
            
            booking.room_id = new_room_id
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Booking updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/update_booking_status/<int:booking_id>', methods=['POST'])
def update_booking_status(booking_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({'success': False, 'error': 'Booking not found'}), 404
        
        new_status = request.form.get('status')
        booking.status = new_status
        
        if new_status == 'Confirmed':
            room = Room.query.get(booking.room_id)
            if not room:
                return jsonify({'success': False, 'error': 'Room not found'}), 400
            if room.status != 'Available':
                return jsonify({'success': False, 'error': 'Room is not available'}), 400
            room.status = 'Booked'
        
        elif new_status == 'Cancelled' and booking.room:
            if booking.room.status == 'Booked':
                booking.room.status = 'Available'
        
        db.session.commit()
        
        action = "confirmed" if new_status == 'Confirmed' else "cancelled"
        new_log = ActivityLog(activity=f"Booking {action} for {booking.name} at {kolkata_now().strftime('%I:%M %p')}")
        db.session.add(new_log)
        db.session.commit()
        
        # Send cancellation notifications
        if new_status == 'Cancelled':
            if booking.email:
                guest_message = f"""
                    <p>Dear {booking.name},</p>
                    <p>Your booking at {app.config['HOTEL_NAME']} has been cancelled.</p>
                    <p>Booking details:</p>
                    <ul>
                        <li>Booking ID: {booking.id}</li>
                        <li>Arrival: {booking.formatted_arrival}</li>
                        <li>Room: {booking.room.room_number if booking.room else 'TBD'}</li>
                    </ul>
                    <p>If this cancellation was made in error, please contact us using the information below.</p>
                    <p>We hope to serve you in the future.</p>
                """
                
                create_notification(
                    recipient=booking.email,
                    subject=f"Booking Cancelled - {app.config['HOTEL_NAME']}",
                    message=guest_message,
                    notification_type='both'
                )
            
            admin_message = f"""
                <p>Booking cancelled:</p>
                <ul>
                    <li>Guest: {booking.name}</li>
                    <li>Phone: {booking.phone}</li>
                    <li>Arrival: {booking.formatted_arrival}</li>
                    <li>Room: {booking.room.room_number if booking.room else 'TBD'}</li>
                </ul>
            """
            
            create_notification(
                recipient='admin',
                subject="Booking Cancelled",
                message=admin_message,
                notification_type='in_app'
            )
        elif new_status == 'Confirmed':
            if booking.email:
                guest_message = f"""
                    <p>Dear {booking.name},</p>
                    <p>Your booking at {app.config['HOTEL_NAME']} has been confirmed!</p>
                    <p>Booking details:</p>
                    <ul>
                        <li>Booking ID: {booking.id}</li>
                        <li>Arrival: {booking.formatted_arrival}</li>
                        <li>Room: {booking.room.room_number}</li>
                    </ul>
                    <p>We look forward to welcoming you!</p>
                """
                
                create_notification(
                    recipient=booking.email,
                    subject=f"Booking Confirmed - {app.config['HOTEL_NAME']}",
                    message=guest_message,
                    notification_type='both'
                )
        
        return jsonify({'success': True, 'message': f'Booking status updated to {new_status}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/delete_booking/<int:booking_id>', methods=['DELETE'])
def delete_booking(booking_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({'success': False, 'error': 'Booking not found'}), 404
        
        if booking.status == 'Confirmed' and booking.room:
            booking.room.status = 'Available'
        
        db.session.delete(booking)
        db.session.commit()
        
        new_log = ActivityLog(activity=f"Deleted booking for {booking.name} at {kolkata_now().strftime('%I:%M %p')}")
        db.session.add(new_log)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Booking deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/notifications')
def notifications():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return redirect(url_for('login'))
    
    notifications = Notification.query.filter_by(recipient='admin', is_read=False).order_by(Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=notifications)

@app.route('/mark_notification_read/<int:notification_id>', methods=['POST'])
def mark_notification_read(notification_id):
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        notification = Notification.query.get(notification_id)
        if notification:
            notification.is_read = True
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Notification not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/notifications_count')
def notifications_count():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'count': 0})
    
    count = Notification.query.filter_by(recipient='admin', is_read=False).count()
    return jsonify({'count': count})

@app.route('/invoice_generator')
def invoice_generator():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return redirect(url_for('login'))
    return render_template('invoice_generator.html')

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=kolkata_now, nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # e.g., Staff, Supplies, Maintenance
    notes = db.Column(db.Text)
    
    @property
    def formatted_date(self):
        return self.date.strftime('%d %b %Y')
    
    @property
    def formatted_amount(self):
        return f"₹{self.amount:.2f}"

class Revenue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=kolkata_now, nullable=False)
    source = db.Column(db.String(100), nullable=False)  # e.g., Room Booking, Restaurant
    amount = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)
    
    @property
    def formatted_date(self):
        return self.date.strftime('%d %b %Y')
    
    @property
    def formatted_amount(self):
        return f"₹{self.amount:.2f}"
    @app.route('/accounts')
    def accounts():
        token = session.get('jwt_token')
        if not token or not verify_jwt_token(token):
            return redirect(url_for('login'))

        # Calculate totals
        total_revenue = db.session.query(db.func.sum    (Revenue.amount)).scalar() or 0
        total_expense = db.session.query(db.func.sum    (Expense.amount)).scalar() or 0
        balance = total_revenue - total_expense

        # Get recent transactions
        expenses = Expense.query.order_by(Expense.date.desc ()).limit(10).all()
        revenues = Revenue.query.order_by(Revenue.date.desc ()).limit(10).all()

        # Generate chart data for last 7 days
        chart_labels = []
        revenue_data = []
        expense_data = []

        today = kolkata_now().date()
        for i in range(6, -1, -1):
            date = today - timedelta(days=i)
            chart_labels.append(date.strftime('%a'))

            # Revenue for the day
            rev = db.session.query(db.func.sum(Revenue. amount)).filter(
                db.func.date(Revenue.date) == date
            ).scalar() or 0
            revenue_data.append(rev)

            # Expenses for the day
            exp = db.session.query(db.func.sum(Expense. amount)).filter(
                db.func.date(Expense.date) == date
            ).scalar() or 0
            expense_data.append(exp)

        return render_template('accounts.html', 
                               total_revenue=total_revenue,
                               total_expense=total_expense,
                               balance=balance,
                               expenses=expenses,
                               revenues=revenues,
                               revenue_data=revenue_data,
                               expense_data=expense_data,
                               chart_labels=chart_labels)

@app.route('/add_expense', methods=['POST'])
def add_expense():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        date_str = request.form.get('date')
        date_dt = datetime.strptime(date_str, '%Y-%m-%d') if date_str else kolkata_now()
        
        new_expense = Expense(
            date=date_dt,
            description=request.form.get('description'),
            amount=float(request.form.get('amount')),
            category=request.form.get('category'),
            notes=request.form.get('notes')
        )
        
        db.session.add(new_expense)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Expense added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/add_revenue', methods=['POST'])
def add_revenue():
    token = session.get('jwt_token')
    if not token or not verify_jwt_token(token):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        date_str = request.form.get('date')
        date_dt = datetime.strptime(date_str, '%Y-%m-%d') if date_str else kolkata_now()
        
        new_revenue = Revenue(
            date=date_dt,
            source=request.form.get('source'),
            amount=float(request.form.get('amount')),
            notes=request.form.get('notes')
        )
        
        db.session.add(new_revenue)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Revenue added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


def create_admin_user():
    try:
        admin = Admin.query.filter_by(username='admin').first()
        
        if not admin:
            new_admin = Admin(username='admin')
            new_admin.set_password('admin123')
            db.session.add(new_admin)
            db.session.commit()
            print("Admin user created!")
        elif not admin.check_password('admin123'):
            print("Updating admin password...")
            admin.set_password('admin123')
            db.session.commit()
            print("Admin password updated!")
        else:
            print("Admin user already exists with correct password")
            
        db.session.commit()
        
    except Exception as e:
        print(f"Error in create_admin_user: {str(e)}")
        # Handle error as before...

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

