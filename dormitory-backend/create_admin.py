from flask import Flask
from extensions import db
from models.admin import Admin
from werkzeug.security import generate_password_hash

# Khởi tạo ứng dụng Flask
app = Flask(__name__)

# Cấu hình database (thay đổi URI theo database của bạn)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root@localhost/dormitory'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Liên kết db với ứng dụng
db.init_app(app)

def create_admin(username, password, full_name, email, phone):
    hashed_password = generate_password_hash(password)
    new_admin = Admin(
        username=username,
        password_hash=hashed_password,
        full_name=full_name,
        email=email,
        phone=phone
    )
    db.session.add(new_admin)
    db.session.commit()
    print(f"Created admin: {username}")

# Chạy trong ngữ cảnh ứng dụng
with app.app_context():
    create_admin("admin0001", "admin123", "Le Van A", "admin0001@example.com", "0123456789")

if __name__ == "__main__":
    print("Script completed.")