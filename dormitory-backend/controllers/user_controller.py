from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db, mail, limiter
from models.user import User
from models.token_blacklist import TokenBlacklist
from controllers.auth_controller import admin_required, user_required
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Message
from pydantic import BaseModel, EmailStr, validator
from typing import Optional
import os
from werkzeug.utils import secure_filename
import logging
from datetime import datetime, timedelta, date
import secrets
from PIL import Image
from sqlalchemy.exc import SQLAlchemyError
import shutil
import re
from flask import render_template


# Thiết lập logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Khởi tạo Blueprint
user_bp = Blueprint('user', __name__)

# Validation schemas
class UserCreateSchema(BaseModel):
    email: EmailStr
    fullname: str
    phone: Optional[str] = None

    @validator('fullname')
    def validate_fullname(cls, v):
        if len(v) < 2 or len(v) > 255:
            raise ValueError('Fullname phải từ 2 đến 255 ký tự')
        return v.strip()

    @validator('phone')
    def validate_phone(cls, v):
        if v and (len(v) < 10 or not v.isdigit()):
            raise ValueError('Số điện thoại không hợp lệ')
        return v

class UserUpdateSchema(BaseModel):
    email: Optional[EmailStr] = None
    fullname: Optional[str] = None
    phone: Optional[str] = None
    CCCD: Optional[str] = None
    date_of_birth: Optional[date] = None
    class_name: Optional[str] = None

    @validator('fullname')
    def validate_fullname(cls, v):
        if v and (len(v) < 2 or len(v) > 255):
            raise ValueError('Fullname phải từ 2 đến 255 ký tự')
        return v.strip() if v else v

    @validator('phone')
    def validate_phone(cls, v):
        if v and (len(v) < 10 or not v.isdigit()):
            raise ValueError('Số điện thoại không hợp lệ')
        return v

    @validator('CCCD')
    def validate_CCCD(cls, v):
        if v and (not v.isdigit() or len(v) != 12):
            raise ValueError('CCCD phải là chuỗi 12 chữ số')
        return v

    @validator('date_of_birth')
    def validate_date_of_birth(cls, v):
        if v and v > date.today():
            raise ValueError('Ngày sinh không được là tương lai')
        return v

    @validator('class_name')
    def validate_class_name(cls, v):
        if v and len(v) > 50:
            raise ValueError('Tên lớp không được vượt quá 50 ký tự')
        return v.strip() if v else v

class PasswordChangeSchema(BaseModel):
    old_password: str
    new_password: str

    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 12:
            raise ValueError('Mật khẩu mới phải dài ít nhất 12 ký tự')
        return v

# Hàm tiện ích
def allowed_file(filename, file):
    """Kiểm tra file có hợp lệ dựa trên MIME type."""
    return '.' in filename and file.mimetype in {'image/png', 'image/jpeg', 'image/gif'}

def create_user_directory(email, fullname):
    """Tạo thư mục cho user dựa trên email và fullname."""
    safe_email = secure_filename(email.split('@')[0])
    safe_fullname = ''.join(word.capitalize() for word in fullname.split())
    user_dir = os.path.join(current_app.config['AVATAR_UPLOAD_FOLDER'], f"{safe_email}_{safe_fullname}")
    try:
        os.makedirs(user_dir, exist_ok=True)
        return user_dir
    except OSError as e:
        logger.error(f"Error creating directory {user_dir}: {str(e)}")
        raise

def move_to_trash(file_path):
    """Di chuyển file vào thư mục trash."""
    if not os.path.exists(file_path):
        return
    filename = os.path.basename(file_path)
    trash_path = os.path.join(current_app.config['TRASH_BASE'], f"{datetime.utcnow().timestamp()}_{filename}")
    try:
        shutil.move(file_path, trash_path)
        logger.info(f"Moved file {file_path} to trash: {trash_path}")
    except Exception as e:
        logger.error(f"Error moving file to trash: {str(e)}")

# API Endpoints
@user_bp.route('/users', methods=['GET'])
@admin_required()
def get_all_users():
    """Lấy danh sách tất cả người dùng với bộ lọc và phân trang."""
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        email = request.args.get('email', type=str)
        fullname = request.args.get('fullname', type=str)
        phone = request.args.get('phone', type=str)
        class_name = request.args.get('class_name', type=str)

        query = User.query.filter_by(is_deleted=False)
        if email:
            query = query.filter(User.email.ilike(f'%{email}%'))
        if fullname:
            query = query.filter(User.fullname.ilike(f'%{fullname}%'))
        if phone:
            query = query.filter(User.phone.ilike(f'%{phone}%'))
        if class_name:
            query = query.filter(User.class_name.ilike(f'%{class_name}%'))

        users = query.paginate(page=page, per_page=limit)
        return jsonify({
            'users': [user.to_dict() for user in users.items if user.to_dict()],
            'total': users.total,
            'pages': users.pages,
            'current_page': users.page
        }), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching users: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@user_bp.route('/users/<int:user_id>', methods=['GET'])
@admin_required()
def get_user_by_id(user_id):
    """Lấy chi tiết người dùng theo ID."""
    try:
        user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
        if not user:
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404
        return jsonify(user.to_dict()), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching user {user_id}: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@user_bp.route('/admin/users', methods=['POST'])
@admin_required()
def create_user():
    """Tạo người dùng mới và gửi email chào mừng chứa thông tin đăng nhập."""
    try:
        logger.debug("Starting create_user with request: %s", request.get_json())
        data = UserCreateSchema(**request.get_json())
        logger.debug("Validated data: %s", data)

        # Kiểm tra trùng lặp email
        if User.query.filter_by(email=data.email).first():
            logger.debug("Email %s already in use", data.email)
            return jsonify({'message': 'Email đã được sử dụng'}), 400

        # Kiểm tra trùng lặp phone (nếu có)
        if data.phone and User.query.filter_by(phone=data.phone).first():
            logger.debug("Phone %s already in use", data.phone)
            return jsonify({'message': 'Số điện thoại đã được sử dụng'}), 400

        # Tạo mật khẩu ngẫu nhiên
        raw_password = secrets.token_urlsafe(12)  # Mật khẩu 16 ký tự ngẫu nhiên
        password_hash = generate_password_hash(raw_password)

        user_dir = create_user_directory(data.email, data.fullname)
        logger.debug("Created directory: %s", user_dir)
        user = User(
            email=data.email,
            password_hash=password_hash,
            fullname=data.fullname,
            phone=data.phone,
            is_deleted=False,
            version=1
        )
        db.session.add(user)
        db.session.commit()
        logger.debug("User created with ID: %s", user.user_id)

        # Gửi email chào mừng
        msg = Message(
            subject='Chào mừng đến với Hệ thống Ký túc xá',
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'no-reply@dormitory.com'),
            recipients=[data.email]
        )
        msg.html = render_template(
            'emails/welcome_email.html',
            fullname=data.fullname,
            email=data.email,
            password=raw_password
        )
        try:
            mail.send(msg)
            logger.debug("Email sent to %s", data.email)
        except Exception as e:
            logger.error(f"Email sending failed: {str(e)}")
            return jsonify({
                'message': 'Tạo tài khoản thành công nhưng không thể gửi email. Vui lòng cung cấp thông tin đăng nhập cho người dùng.',
                'user': user.to_dict(),
                'email': data.email,
                'password': raw_password
            }), 201

        return jsonify({
            'message': 'Tạo tài khoản thành công! Thông tin đăng nhập đã được gửi qua email.',
            'user': user.to_dict()
        }), 201
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error creating user: {str(e)}")
        if "Duplicate entry" in str(e):
            if "phone" in str(e):
                return jsonify({'message': 'Số điện thoại đã được sử dụng'}), 400
            return jsonify({'message': 'Email đã được sử dụng'}), 400
        return jsonify({'message': 'Lỗi database'}), 500

@user_bp.route('/admin/users/<int:user_id>', methods=['PUT'])
@admin_required()
def update_user(user_id):
    """Cập nhật thông tin người dùng."""
    try:
        logger.debug(f"Admin updating user_id={user_id}")
        user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404

        data = UserUpdateSchema(**request.get_json())
        old_email = user.email
        old_fullname = user.fullname

        user.email = data.email or user.email
        user.fullname = data.fullname or user.fullname
        user.phone = data.phone or user.phone
        user.CCCD = data.CCCD or user.CCCD
        user.date_of_birth = data.date_of_birth or user.date_of_birth
        user.class_name = data.class_name or user.class_name
        user.version += 1

        if data.email and User.query.filter(User.email == user.email, User.user_id != user_id).first():
            logger.warning(f"Email already in use: {user.email}")
            return jsonify({'message': 'Email đã được sử dụng bởi người dùng khác'}), 400
        if data.phone and User.query.filter(User.phone == user.phone, User.user_id != user_id).first():
            logger.warning(f"Phone already in use: {user.phone}")
            return jsonify({'message': 'Số điện thoại đã được sử dụng bởi người dùng khác'}), 400
        if data.CCCD and User.query.filter(User.CCCD == user.CCCD, User.user_id != user_id).first():
            logger.warning(f"CCCD already in use: {user.CCCD}")
            return jsonify({'message': 'CCCD đã được sử dụng bởi người dùng khác'}), 400

        if data.email or data.fullname:
            old_dir = create_user_directory(old_email, old_fullname)
            new_dir = create_user_directory(user.email, user.fullname)
            if os.path.exists(old_dir) and old_dir != new_dir:
                try:
                    logger.debug(f"Moving avatar directory from {old_dir} to {new_dir}")
                    shutil.move(old_dir, new_dir)
                    if user.avatar_url:
                        old_safe_fullname = secure_filename(old_fullname.replace(' ', '_').lower())
                        new_safe_fullname = secure_filename(user.fullname.replace(' ', '_').lower())
                        user.avatar_url = user.avatar_url.replace(
                            f"/Uploads/avatars/{secure_filename(old_email.split('@')[0])}_{old_safe_fullname}/",
                            f"/Uploads/avatars/{secure_filename(user.email.split('@')[0])}_{new_safe_fullname}/"
                        )
                        logger.debug(f"Updated avatar_url: {user.avatar_url}")
                except Exception as e:
                    logger.error(f"Error moving directory {old_dir} to {new_dir}: {str(e)}")
                    logger.warning("Continuing despite directory move error")

        db.session.commit()
        logger.info(f"User updated successfully: user_id={user_id}")
        return jsonify(user.to_dict()), 200
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error updating user {user_id}: {str(e)}")
        if "Duplicate entry" in str(e):
            if "phone" in str(e):
                return jsonify({'message': 'Số điện thoại đã được sử dụng bởi người dùng khác'}), 400
            if "CCCD" in str(e):
                return jsonify({'message': 'CCCD đã được sử dụng bởi người dùng khác'}), 400
            return jsonify({'message': 'Email đã được sử dụng bởi người dùng khác'}), 400
        return jsonify({'message': 'Lỗi database'}), 500
    except Exception as e:
        logger.error(f"Unexpected error updating user {user_id}: {str(e)}")
        return jsonify({'message': 'Lỗi không xác định'}), 500

@user_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required()
def delete_user(user_id):
    """Soft delete người dùng."""
    try:
        logger.debug(f"Admin deleting user_id={user_id}")
        user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404

        user.is_deleted = True
        user.deleted_at = datetime.utcnow()
        user.version += 1
        db.session.commit()
        logger.info(f"User deleted successfully: user_id={user_id}")
        return '', 204
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error deleting user {user_id}: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@user_bp.route('/me', methods=['GET'])
@user_required()
def get_user_profile():
    """Lấy thông tin cá nhân của user."""
    try:
        user_id = get_jwt_identity()
        logger.debug(f"User ID from JWT: {user_id}")
        user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404
        return jsonify(user.to_dict()), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching user profile: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@user_bp.route('/me', methods=['PUT'])
@user_required()
def update_user_profile():
    """Cập nhật thông tin cá nhân của user."""
    try:
        user_id = get_jwt_identity()
        logger.debug(f"User ID from JWT: {user_id}")
        user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404

        logger.debug(f"User found: email={user.email}, fullname={user.fullname}")
        data = UserUpdateSchema(**request.get_json())
        old_fullname = user.fullname

        # Cập nhật các trường
        user.fullname = data.fullname or user.fullname
        user.phone = data.phone or user.phone
        user.CCCD = data.CCCD or user.CCCD
        user.date_of_birth = data.date_of_birth or user.date_of_birth
        user.class_name = data.class_name or user.class_name
        user.version += 1

        # Kiểm tra trùng lặp phone
        if data.phone and User.query.filter(User.phone == user.phone, User.user_id != user_id).first():
            logger.warning(f"Phone already in use: {user.phone}")
            return jsonify({'message': 'Số điện thoại đã được sử dụng bởi người dùng khác'}), 400

        # Kiểm tra trùng lặp CCCD
        if data.CCCD and User.query.filter(User.CCCD == user.CCCD, User.user_id != user_id).first():
            logger.warning(f"CCCD already in use: {user.CCCD}")
            return jsonify({'message': 'CCCD đã được sử dụng bởi người dùng khác'}), 400

        # Đổi tên thư mục avatar nếu fullname thay đổi
        if data.fullname and data.fullname != old_fullname:
            logger.debug(f"Fullname changed from '{old_fullname}' to '{data.fullname}'")
            old_dir = create_user_directory(user.email, old_fullname)
            new_dir = create_user_directory(user.email, user.fullname)
            if os.path.exists(old_dir) and old_dir != new_dir:
                try:
                    logger.debug(f"Moving avatar directory from {old_dir} to {new_dir}")
                    shutil.move(old_dir, new_dir)
                    if user.avatar_url:
                        old_safe_fullname = secure_filename(old_fullname.replace(' ', '_').lower())
                        new_safe_fullname = secure_filename(user.fullname.replace(' ', '_').lower())
                        user.avatar_url = user.avatar_url.replace(
                            f"/Uploads/avatars/{secure_filename(user.email.split('@')[0])}_{old_safe_fullname}/",
                            f"/Uploads/avatars/{secure_filename(user.email.split('@')[0])}_{new_safe_fullname}/"
                        )
                        logger.debug(f"Updated avatar_url: {user.avatar_url}")
                except Exception as e:
                    logger.error(f"Error moving directory from {old_dir} to {new_dir}: {str(e)}")
                    logger.warning("Continuing despite directory move error")

        db.session.commit()
        logger.info(f"Profile updated successfully for user_id={user_id}")
        return jsonify(user.to_dict()), 200

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error updating profile for user {user_id}: {str(e)}")
        if "Duplicate entry" in str(e):
            if "phone" in str(e):
                return jsonify({'message': 'Số điện thoại đã được sử dụng bởi người dùng khác'}), 400
            if "CCCD" in str(e):
                return jsonify({'message': 'CCCD đã được sử dụng bởi người dùng khác'}), 400
        return jsonify({'message': 'Lỗi database'}), 500
    except Exception as e:
        logger.error(f"Unexpected error updating profile for user {user_id}: {str(e)}")
        return jsonify({'message': 'Lỗi không xác định'}), 500

@user_bp.route('/me/password', methods=['PUT'])
@limiter.limit("5 per minute")
@user_required()
def change_password():
    """Đổi mật khẩu với kiểm tra bảo mật và thu hồi token cũ."""
    try:
        user_id = get_jwt_identity()
        logger.debug(f"User ID from JWT: {user_id}")
        user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404

        # Kiểm tra số lần thử sai
        if user.reset_attempts >= 5:
            if user.reset_token_expiry and user.reset_token_expiry > datetime.utcnow():
                logger.warning(f"Account locked for user {user.email}: too many attempts")
                return jsonify({'message': 'Tài khoản tạm khóa do quá số lần thử. Vui lòng thử lại sau.'}), 429
            else:
                user.reset_attempts = 0  # Reset sau khi khóa hết hạn

        data = PasswordChangeSchema(**request.get_json())

        # Kiểm tra mật khẩu cũ
        if not check_password_hash(user.password_hash, data.old_password):
            user.reset_attempts += 1
            user.reset_token_expiry = datetime.utcnow() + timedelta(minutes=15)  # Khóa 15 phút
            db.session.commit()
            logger.warning(f"Failed password attempt for user {user.email}, attempts: {user.reset_attempts}, IP: {request.remote_addr}")
            return jsonify({'message': 'Mật khẩu cũ không đúng'}), 401

        # Reset attempts sau khi xác thực đúng
        user.reset_attempts = 0
        user.reset_token_expiry = None

        # Kiểm tra độ mạnh mật khẩu mới
        password_pattern = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{12,}$'
        if not re.match(password_pattern, data.new_password):
            logger.warning(f"Invalid new password format for user {user.email}")
            return jsonify({
                'message': 'Mật khẩu mới phải dài ít nhất 12 ký tự, chứa chữ hoa, chữ thường, số và ký tự đặc biệt (@$!%*?&)'
            }), 400

        # Thu hồi token hiện tại
        claims = get_jwt()
        jti = claims['jti']
        expires_at = datetime.utcfromtimestamp(claims['exp'])
        blacklisted_token = TokenBlacklist(
            jti=jti,
            revoked_at=datetime.utcnow(),
            expires_at=expires_at
        )
        db.session.add(blacklisted_token)

        # Hash mật khẩu mới
        user.password_hash = generate_password_hash(data.new_password)
        user.version += 1

        db.session.commit()
        logger.info(f"Password changed successfully for user {user.email}, token blacklisted, IP: {request.remote_addr}")

        # Gửi email thông báo
        change_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        msg = Message(
            subject='Thông báo thay đổi mật khẩu',
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'no-reply@dormitory.com'),
            recipients=[user.email]
        )
        msg.html = render_template(
            'emails/password_changed.html',
            fullname=user.fullname,
            change_time=change_time
        )
        try:
            mail.send(msg)
            logger.debug(f"Notification email sent to {user.email}")
        except Exception as e:
            logger.error(f"Failed to send notification email to {user.email}: {str(e)}")

        return jsonify({'message': 'Đổi mật khẩu thành công, vui lòng đăng nhập lại'}), 200
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error changing password: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@user_bp.route('/me/avatar', methods=['PUT'])
@user_required()
def update_user_avatar():
    """Cập nhật ảnh đại diện của user."""
    try:
        user_id = get_jwt_identity()
        logger.debug(f"User ID from JWT: {user_id}")
        user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404

        logger.debug(f"User found: email={user.email}, fullname={user.fullname}")
        if 'avatar' not in request.files:
            logger.warning("No avatar file in request")
            return jsonify({'message': 'Yêu cầu file ảnh (key: avatar)'}), 400

        file = request.files['avatar']
        if not file or file.filename == '':
            logger.warning("Empty or no file selected")
            return jsonify({'message': 'Không có file được chọn'}), 400

        logger.debug(f"File received: filename={file.filename}, mimetype={file.mimetype}")
        if not allowed_file(file.filename, file):
            logger.warning(f"Invalid file type: filename={file.filename}, mimetype={file.mimetype}")
            return jsonify({'message': 'File không phải ảnh hợp lệ (chỉ hỗ trợ PNG, JPG, GIF)'}), 400

        # Xử lý ảnh cũ nếu có
        if user.avatar_url:
            old_file_path = os.path.join(current_app.config['UPLOAD_BASE'], user.avatar_url.lstrip('/'))
            try:
                if os.path.exists(old_file_path):
                    move_to_trash(old_file_path)
                    logger.debug(f"Moved old avatar to trash: {old_file_path}")
                else:
                    logger.warning(f"Old avatar file not found: {old_file_path}")
            except Exception as e:
                logger.error(f"Error moving old avatar to trash: {str(e)}")

        # Tạo thư mục con theo email và tên user
        logger.debug("Creating user directory")
        user_dir = create_user_directory(user.email, user.fullname)
        logger.debug(f"User directory created: {user_dir}")

        # Tạo tên file duy nhất
        filename = secure_filename(f"avatar_{user_id}_{datetime.utcnow().timestamp()}.jpg")
        file_path = os.path.join(user_dir, filename)
        logger.debug(f"File path: {file_path}")

        # Resize và lưu ảnh
        logger.debug("Opening image with PIL")
        img = Image.open(file)
        logger.debug(f"Image mode: {img.mode}")

        # Chuyển đổi chế độ màu nếu cần
        if img.mode == 'RGBA':
            logger.debug("Converting RGBA to RGB")
            img = img.convert('RGB')

        logger.debug("Resizing image")
        img.thumbnail((200, 200))
        logger.debug(f"Saving image to {file_path}")
        img.save(file_path, 'JPEG', quality=85)

        # Tạo URL công khai
        base_url = request.host_url.rstrip('/')
        safe_email = secure_filename(user.email.split('@')[0])
        safe_fullname = secure_filename(user.fullname.replace(' ', '_').lower())
        image_url = f"{base_url}/Uploads/avatars/{safe_email}_{safe_fullname}/{filename}"
        logger.debug(f"Generated image URL: {image_url}")

        user.avatar_url = image_url
        user.version += 1
        db.session.commit()
        logger.info(f"Avatar updated successfully for user_id={user_id}")
        return jsonify(user.to_dict()), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error uploading avatar: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500
    except OSError as e:
        logger.error(f"File system error uploading avatar: {str(e)}")
        return jsonify({'message': 'Lỗi lưu file ảnh'}), 500
    except Exception as e:
        logger.error(f"Error uploading avatar: {str(e)}")
        return jsonify({'message': 'Lỗi upload ảnh'}), 500

@user_bp.route('/users/<int:user_id>/avatar', methods=['PUT'])
@admin_required()
def update_user_avatar_admin(user_id):
    """Admin cập nhật ảnh đại diện cho người dùng."""
    try:
        logger.debug(f"Admin updating avatar for user_id={user_id}")
        user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404

        logger.debug(f"User found: email={user.email}, fullname={user.fullname}")
        if 'avatar' not in request.files:
            logger.warning("No avatar file in request")
            return jsonify({'message': 'Yêu cầu file ảnh (key: avatar)'}), 400

        file = request.files['avatar']
        if not file or file.filename == '':
            logger.warning("Empty or no file selected")
            return jsonify({'message': 'Không có file được chọn'}), 400

        logger.debug(f"File received: filename={file.filename}, mimetype={file.mimetype}")
        if not allowed_file(file.filename, file):
            logger.warning(f"Invalid file type: filename={file.filename}, mimetype={file.mimetype}")
            return jsonify({'message': 'File không phải ảnh hợp lệ (chỉ hỗ trợ PNG, JPG, GIF)'}), 400

        # Xử lý ảnh cũ nếu có
        if user.avatar_url:
            old_file_path = os.path.join(current_app.config['UPLOAD_BASE'], user.avatar_url.lstrip('/'))
            try:
                if os.path.exists(old_file_path):
                    move_to_trash(old_file_path)
                    logger.debug(f"Moved old avatar to trash: {old_file_path}")
                else:
                    logger.warning(f"Old avatar file not found: {old_file_path}")
            except Exception as e:
                logger.error(f"Error moving old avatar to trash: {str(e)}")

        # Tạo thư mục con theo email và tên user
        logger.debug("Creating user directory")
        user_dir = create_user_directory(user.email, user.fullname)
        logger.debug(f"User directory created: {user_dir}")

        # Tạo tên file duy nhất
        filename = secure_filename(f"avatar_{user_id}_{datetime.utcnow().timestamp()}.jpg")
        file_path = os.path.join(user_dir, filename)
        logger.debug(f"File path: {file_path}")

        # Resize và lưu ảnh
        logger.debug("Opening image with PIL")
        img = Image.open(file)
        logger.debug(f"Image mode: {img.mode}")

        # Chuyển đổi chế độ màu nếu cần
        if img.mode == 'RGBA':
            logger.debug("Converting RGBA to RGB")
            img = img.convert('RGB')

        logger.debug("Resizing image")
        img.thumbnail((200, 200))
        logger.debug(f"Saving image to {file_path}")
        img.save(file_path, 'JPEG', quality=85)

        # Tạo URL công khai
        base_url = request.host_url.rstrip('/')
        safe_email = secure_filename(user.email.split('@')[0])
        safe_fullname = secure_filename(user.fullname.replace(' ', '_').lower())
        image_url = f"{base_url}/Uploads/avatars/{safe_email}_{safe_fullname}/{filename}"
        logger.debug(f"Generated image URL: {image_url}")

        user.avatar_url = image_url
        user.version += 1
        db.session.commit()
        logger.info(f"Avatar updated successfully for user_id={user_id}")
        return jsonify(user.to_dict()), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error uploading avatar for user {user_id}: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500
    except OSError as e:
        logger.error(f"File system error uploading avatar for user {user_id}: {str(e)}")
        return jsonify({'message': 'Lỗi lưu file ảnh'}), 500
    except Exception as e:
        logger.error(f"Error uploading avatar for user {user_id}: {str(e)}")
        return jsonify({'message': 'Lỗi upload ảnh'}), 500