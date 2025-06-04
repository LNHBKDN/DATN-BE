import datetime
import os
import logging
from flask import Flask, jsonify, send_from_directory, request
from extensions import db, migrate, jwt, mail, limiter
from config import Config
from dotenv import load_dotenv
from pathlib import Path
from flask_swagger_ui import get_swaggerui_blueprint
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from flask_cors import CORS
from celery import Celery
from models.refresh_tokens import RefreshToken
import firebase_admin
from firebase_admin import credentials, messaging

# Load biến môi trường
dotenv_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path)

# Khởi tạo Firebase Admin SDK
cred = credentials.Certificate('firebase-adminsdk.json')
firebase_admin.initialize_app(cred)

# Khởi tạo Flask app
app = Flask(__name__)

# Cấu hình logging
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    encoding='utf-8'
)

# Cấu hình CORS
CORS(app, resources={r"/api/*": {
    "origins": "*",
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "Range"],
    "expose_headers": ["Content-Range", "Accept-Ranges"],
    "supports_credentials": False
}})

# Cấu hình Celery
def make_celery(app):
    celery = Celery(
        app.import_name,
        broker=app.config['CELERY_BROKER_URL'],
        backend=app.config['CELERY_RESULT_BACKEND']
    )
    celery.conf.update(app.config)
    
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    
    celery.Task = ContextTask
    return celery

app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
celery = make_celery(app)

# Cấu hình Swagger UI
SWAGGER_URL = '/docs'
API_URL = '/static/swagger.json'
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={'app_name': "Dormitory API"}
)

# Cấu hình Flask-Caching
cache = Cache(config={'CACHE_TYPE': 'redis', 'CACHE_REDIS_URL': 'redis://localhost:6379/1'})
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

# Cấu hình thư mục upload
UPLOAD_BASE = os.path.join(app.root_path, 'Uploads')
os.makedirs(UPLOAD_BASE, exist_ok=True)
app.config['UPLOAD_BASE'] = UPLOAD_BASE
REPORT_IMAGES_FOLDER = os.path.join(UPLOAD_BASE, 'report_images')
os.makedirs(REPORT_IMAGES_FOLDER, exist_ok=True)
app.config['REPORT_IMAGES_FOLDER'] = REPORT_IMAGES_FOLDER
NOTIFICATION_MEDIA_BASE = os.path.join(UPLOAD_BASE, 'notification_media')
os.makedirs(NOTIFICATION_MEDIA_BASE, exist_ok=True)
app.config['NOTIFICATION_MEDIA_BASE'] = NOTIFICATION_MEDIA_BASE
ROOM_IMAGES_BASE = os.path.join(UPLOAD_BASE, 'roomimage')
os.makedirs(ROOM_IMAGES_BASE, exist_ok=True)
app.config['ROOM_IMAGES_BASE'] = ROOM_IMAGES_BASE
AVATAR_UPLOAD_FOLDER = os.path.join(UPLOAD_BASE, 'avatars')
os.makedirs(AVATAR_UPLOAD_FOLDER, exist_ok=True)
app.config['AVATAR_UPLOAD_FOLDER'] = AVATAR_UPLOAD_FOLDER
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
from models.room_status_history import RoomStatusHistory
from models.user_room_history import UserRoomHistory

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
from controllers.statistics_controller import statistics_bp

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
app.register_blueprint(monthly_bill_bp, url_prefix='/api')
app.register_blueprint(payment_transaction_bp, url_prefix='/api')
app.register_blueprint(report_type_bp, url_prefix='/api')
app.register_blueprint(notification_type_bp, url_prefix='/api')
app.register_blueprint(statistics_bp, url_prefix='/api')

# Debug routes, file serving, error handlers, JWT blocklist loader
@app.route('/debug/routes')
def debug_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'rule': rule.rule
        })
    logger.info("Registered routes: %s", routes)
    return jsonify(routes)

@app.route('/api/roomimage/<path:filename>')
def serve_room_image(filename):
    logger.info(f"Serving room image: {filename}")
    full_path = os.path.join(app.config['ROOM_IMAGES_BASE'], filename)
    logger.info(f"Full path: {full_path}")
    try:
        if not os.path.exists(full_path):
            logger.error(f"File does not exist: {full_path}")
            return jsonify({'message': f'Không tìm thấy hình ảnh: {filename}'}), 404
        logger.info(f"Serving file: {full_path}")
        return send_from_directory(app.config['ROOM_IMAGES_BASE'], filename)
    except Exception as e:
        logger.error(f"Error serving room image {filename}: {str(e)}")
        return jsonify({'message': f'Không tìm thấy hình ảnh: {filename}'}), 404

@app.route('/api/reportimage/<path:filename>')
def serve_report_image(filename):
    logger.info(f"Serving report image: {filename}")
    full_path = os.path.join(app.config['REPORT_IMAGES_FOLDER'], filename)
    logger.info(f"Full path: {full_path}")
    try:
        if not os.path.exists(full_path):
            logger.error(f"File does not exist: {full_path}")
            return jsonify({'message': f'Không tìm thấy tệp: {filename}'}), 404
        logger.info(f"Serving file: {full_path}")
        response = send_from_directory(app.config['REPORT_IMAGES_FOLDER'], filename)
        if filename.lower().endswith(('.mp4', '.avi')):
            response.headers['Content-Disposition'] = 'inline'
            response.headers['Accept-Ranges'] = 'bytes'
        return response
    except Exception as e:
        logger.error(f"Error serving report image {filename}: {str(e)}")
        return jsonify({'message': f'Không tìm thấy tệp: {filename}'}), 404

@app.route('/api/notification_media/<path:filename>')
def serve_noti_image(filename):
    logger.info(f"Serving notification media: {filename}")
    full_path = os.path.join(app.config['NOTIFICATION_MEDIA_BASE'], filename)
    logger.info(f"Full path: {full_path}")
    try:
        if not os.path.exists(full_path):
            logger.error(f"File does not exist: {full_path}")
            return jsonify({'message': f'Không tìm thấy tệp: {filename}'}), 404
        logger.info(f"Serving file: {full_path}")
        response = send_from_directory(app.config['NOTIFICATION_MEDIA_BASE'], filename)
        if filename.lower().endswith(('.mp4', '.avi')):
            response.headers['Content-Disposition'] = 'inline'
            response.headers['Accept-Ranges'] = 'bytes'
        return response
    except Exception as e:
        logger.error(f"Error serving notification media {filename}: {str(e)}")
        return jsonify({'message': f'Không tìm thấy tệp: {filename}'}), 404

@app.route('/api/avatars/<path:filename>')
def serve_avatar(filename):
    logger.info(f"Serving avatar: {filename}")
    full_path = os.path.join(app.config['AVATAR_UPLOAD_FOLDER'], filename)
    logger.info(f"Full path: {full_path}")
    try:
        if not os.path.exists(full_path):
            logger.error(f"File does not exist: {full_path}")
            return jsonify({'message': f'Không tìm thấy ảnh: {filename}'}), 404
        logger.info(f"Serving file: {full_path}")
        return send_from_directory(app.config['AVATAR_UPLOAD_FOLDER'], filename)
    except Exception as e:
        logger.error(f"Error serving avatar {filename}: {str(e)}")
        return jsonify({'message': f'Không tìm thấy ảnh: {filename}'}), 404

@app.route('/Uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_BASE'], filename)

@app.before_request
def log_request():
    logger.info(f"Before request: method={request.method}, url={request.url}, headers={request.headers}")
    if request.method == 'OPTIONS':
        logger.info("Handling OPTIONS preflight request")
        return '', 200

@app.errorhandler(404)
def not_found(error):
    logger.error("404 Error: %s", str(error))
    return jsonify({'message': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error("500 Error: %s", str(error))
    return jsonify({'message': 'Internal server error'}), 500

@app.errorhandler(401)
def unauthorized(error):
    logger.error("401 Error: %s", str(error))
    return jsonify({'message': 'Unauthorized'}), 401

@app.errorhandler(403)
def forbidden(error):
    logger.error("403 Error: %s", str(error))
    return jsonify({'message': 'Forbidden'}), 403

from scheduler import init_scheduler
init_scheduler(db)

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    try:
        jti = jwt_payload['jti']
        token_type = jwt_payload.get('type')
        if token_type == 'access':
            from models.token_blacklist import TokenBlacklist
            token = TokenBlacklist.query.filter_by(jti=jti).first()
            if token:
                logger.debug("Access token %s đã bị vô hiệu hóa", jti)
                return True
            logger.debug("Access token %s không có trong danh sách đen", jti)
        if token_type == 'refresh':
            refresh_token = RefreshToken.query.filter_by(jti=jti).first()
            if refresh_token:
                if refresh_token.revoked_at or refresh_token.expires_at < datetime.utcnow():
                    logger.debug("Refresh token %s đã bị thu hồi hoặc hết hạn", jti)
                    return True
                logger.debug("Refresh token %s hợp lệ", jti)
            else:
                logger.debug("Refresh token %s không tồn tại", jti)
                return True
        return False
    except Exception as e:
        logger.error("Lỗi khi kiểm tra blacklist token: %s", str(e))
        return True

if __name__ == '__main__':
    if os.getenv('FLASK_ENV') == 'development':
        app.run(debug=True, host='127.0.0.1', port=5000)
    else:
        app.run(host='0.0.0.0', port=5000)