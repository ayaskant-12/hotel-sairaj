from app import db, create_admin_user
from app import app as application

with application.app_context():
    db.create_all()
    create_admin_user()
