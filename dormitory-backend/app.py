import os
import logging
from flask import Flask, jsonify, send_from_directory
from extensions import db, migrate, jwt, mail, limiter
from config import Config
from dotenv import load_dotenv
from pathlib import Path
from flask_swagger_ui import get_swaggerui_blueprint
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from celery import Celery

# Load biến môi trường từ file .env
dotenv_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path)

# Khởi tạo ứng dụng Flask
app = Flask(__name__)

# Cấu hình logging với mã hóa UTF-8
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    encoding='utf-8'  # Thêm encoding UTF-8
)

# Khởi tạo Celery
celery = Celery(app.name, broker='redis://localhost:6379/0')

# Cấu hình Swagger UI
SWAGGER_URL = '/docs'
API_URL = '/static/swagger.json'
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={'app_name': "Dormitory API"}
)

# Thêm cấu hình upload
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['AVATAR_UPLOAD_FOLDER'] = 'C:/Users/ACER/Desktop/NET/DATN/dormitory-backend/Uploads/avatars'
app.config['TRASH_BASE'] = 'C:/Users/ACER/Desktop/NET/DATN/dormitory-backend/Uploads/trash'
app.config['MAX_FILE_SIZE'] = 5 * 1024 * 1024  # 5MB

# Cấu hình Flask-Caching
cache = Cache(config={'CACHE_TYPE': 'redis', 'CACHE_REDIS_URL': 'redis://localhost:6379/0'})
cache.init_app(app)

app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)
app.config.from_object(Config())
logger = logging.getLogger(__name__)

# Kiểm tra JWT_SECRET_KEY
if app.config.get('JWT_SECRET_KEY') == 'your_jwt_secret_key_here':
    logger.warning("JWT_SECRET_KEY đang sử dụng giá trị mặc định, điều này không an toàn trong môi trường production!")

print("DB URI:", app.config.get('SQLALCHEMY_DATABASE_URI'))
db.init_app(app)
migrate.init_app(app, db)
jwt.init_app(app)
mail.init_app(app)
limiter.init_app(app)

# Cấu hình thư mục upload gốc
UPLOAD_BASE = os.path.join(app.root_path, 'Uploads')
os.makedirs(UPLOAD_BASE, exist_ok=True)

# Thư mục cho report_images
REPORT_IMAGES_FOLDER = os.path.join(UPLOAD_BASE, 'report_images')
os.makedirs(REPORT_IMAGES_FOLDER, exist_ok=True)
app.config['REPORT_IMAGES_FOLDER'] = REPORT_IMAGES_FOLDER

# Thư mục gốc cho roomimage
ROOM_IMAGES_BASE = os.path.join(UPLOAD_BASE, 'roomimage')
os.makedirs(ROOM_IMAGES_BASE, exist_ok=True)
app.config['ROOM_IMAGES_BASE'] = ROOM_IMAGES_BASE

# Thư mục cho avatars
AVATAR_UPLOAD_FOLDER = os.path.join(UPLOAD_BASE, 'avatars')
os.makedirs(AVATAR_UPLOAD_FOLDER, exist_ok=True)
app.config['AVATAR_UPLOAD_FOLDER'] = AVATAR_UPLOAD_FOLDER

# Thư mục rác
TRASH_BASE = os.path.join(UPLOAD_BASE, 'trash')
os.makedirs(TRASH_BASE, exist_ok=True)
app.config['TRASH_BASE'] = TRASH_BASE

# Import models
from models.area import Area
from models.room import Room
from models.user import User
from models.register import Register
from models.roomimage import RoomImage
from models.contract import Contract
from models.report_type import ReportType
from models.report import Report
from models.reportimage import ReportImage
from models.notification_type import NotificationType
from models.notification import Notification
from models.notification_recipient import NotificationRecipient
from models.service import Service
from models.service_rate import ServiceRate
from models.monthly_bill import MonthlyBill
from models.bill_detail import BillDetail
from models.payment_transaction import PaymentTransaction
from models.admin import Admin
from models.token_blacklist import TokenBlacklist
from models.notification_media import NotificationMedia

# Import controllers
from controllers.auth_controller import auth_bp
from controllers.user_controller import user_bp
from controllers.admin_controller import admin_bp
from controllers.area_controller import area_bp
from controllers.room_controller import room_bp
from controllers.room_image_controller import roomimage_bp
from controllers.contract_controller import contract_bp
from controllers.registration_controller import registration_bp
from controllers.report_controller import report_bp
from controllers.report_image_controller import report_image_bp
from controllers.notification_controller import notification_bp
from controllers.notification_recipient_controller import notification_recipient_bp
from controllers.service_rate_controller import service_rate_bp
from controllers.service_controller import service_bp
from controllers.monthly_bill_controller import monthly_bill_bp
from controllers.payment_transaction_controller import payment_transaction_bp
from controllers.report_type_controller import report_type_bp
from controllers.notification_type_controller import notification_type_bp
from controllers.notification_media_controller import notification_media_bp
# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/api')
app.register_blueprint(area_bp, url_prefix='/api')
app.register_blueprint(room_bp, url_prefix='/api')
app.register_blueprint(roomimage_bp, url_prefix='/api')
app.register_blueprint(contract_bp, url_prefix='/api')
app.register_blueprint(registration_bp, url_prefix='/api')
app.register_blueprint(report_bp, url_prefix='/api')
app.register_blueprint(report_image_bp, url_prefix='/api')
app.register_blueprint(notification_bp, url_prefix='/api')
app.register_blueprint(service_rate_bp, url_prefix='/api')
app.register_blueprint(service_bp, url_prefix='/api')
app.register_blueprint(notification_media_bp, url_prefix='/api')

app.register_blueprint(notification_recipient_bp, url_prefix='/api')

# Đăng ký blueprint cho các controller
app.register_blueprint(monthly_bill_bp, url_prefix='/api')
app.register_blueprint(payment_transaction_bp, url_prefix='/api')
app.register_blueprint(report_type_bp, url_prefix='/api')
app.register_blueprint(notification_type_bp, url_prefix='/api')

# Route phục vụ file tĩnh
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_BASE, filename)

# Error handlers
@app.errorhandler(404)
def not_found(error):
    logger.error("404 Error: %s", str(error))
    return jsonify({'message': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error("500 Error: %s", str(error))
    return jsonify({'message': 'Internal server error'}), 500

from scheduler import init_scheduler
init_scheduler(db)

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    try:
        from models.token_blacklist import TokenBlacklist
        jti = jwt_payload['jti']
        token = TokenBlacklist.query.filter_by(jti=jti).first()
        if token:
            logger.debug("Token %s đã bị vô hiệu hóa", jti)
            return True
        logger.debug("Token %s không có trong danh sách đen", jti)
        return False
    except Exception as e:
        logger.error("Lỗi khi kiểm tra blacklist token: %s", str(e))
        return False

if __name__ == '__main__':
    if os.getenv('FLASK_ENV') == 'development':
        app.run(debug=True)
    else:
        app.run()