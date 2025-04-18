import logging
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from models.report import Report
from models.user import User
from models.room import Room
from models.report_type import ReportType
from models.reportimage import ReportImage
from models.contract import Contract
from controllers.auth_controller import admin_required, user_required
from datetime import datetime
from sqlalchemy.exc import IntegrityError, DataError
import os
from werkzeug.utils import secure_filename
import uuid
import re
from unidecode import unidecode
from werkzeug.exceptions import RequestEntityTooLarge

# Thiết lập logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

report_bp = Blueprint('report', __name__)

# Danh sách trạng thái hợp lệ
VALID_STATUSES = ['PENDING', 'RECEIVED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED']

# Danh sách định dạng được phép
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi'}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB mỗi file
MAX_FILES_PER_REQUEST = 10  # Tối đa 10 file mỗi yêu cầu
MAX_TOTAL_SIZE = 1000 * 1024 * 1024  # 1000MB tổng kích thước

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return 'video' if ext in VIDEO_EXTENSIONS else 'image'

def generate_filename(fullname, extension, folder):
    base_name = re.sub(r'[^\w]', '', unidecode(fullname)).title()
    name_parts = base_name.split()
    if len(name_parts) > 1:
        base_name = ''.join(name_parts[:-1]) + name_parts[-1][0]
    else:
        base_name = name_parts[0]
    
    filename = f"{base_name}.{extension.lower()}"
    counter = 1
    while os.path.exists(os.path.join(folder, filename)):
        filename = f"{base_name}_{counter}.{extension.lower()}"
        counter += 1
    return filename

# Lấy chi tiết báo cáo theo ID (Admin hoặc User sở hữu)
@report_bp.route('/reports/<int:report_id>', methods=['GET'])
@jwt_required()
def get_report_by_id(report_id):
    try:
        identity = get_jwt_identity()
        claims = get_jwt()
        if not identity:
            logger.warning("Không thể xác định người dùng: %s", identity)
            return jsonify({'message': 'Không thể xác định người dùng'}), 401

        user_id = int(identity)
        type_user = claims.get('type')

        logger.info("Lấy chi tiết báo cáo: report_id=%s, user_id=%s, type=%s", report_id, user_id, type_user)

        report = Report.query.get(report_id)
        if not report:
            logger.warning("Báo cáo không tồn tại: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy báo cáo'}), 404

        if type_user == 'USER' and report.user_id != user_id:
            logger.warning("Người dùng không có quyền truy cập báo cáo: user_id=%s, report_id=%s", user_id, report_id)
            return jsonify({'message': 'Bạn không có quyền xem báo cáo này'}), 403

        if type_user == 'ADMIN' and report.status == 'PENDING':
            report.status = 'RECEIVED'
            try:
                db.session.commit()
                logger.info("Báo cáo chuyển sang RECEIVED bởi admin: report_id=%s, user_id=%s", report_id, user_id)
            except SQLAlchemyError as e:
                db.session.rollback()
                logger.error("Lỗi cơ sở dữ liệu khi cập nhật trạng thái báo cáo: report_id=%s, error=%s", report_id, str(e))
                return jsonify({'message': 'Lỗi cơ sở dữ liệu khi cập nhật trạng thái báo cáo'}), 500

        logger.info("Lấy chi tiết báo cáo thành công: report_id=%s", report_id)
        return jsonify(report.to_dict()), 200

    except ValueError as e:
        logger.error("Lỗi giá trị khi lấy chi tiết báo cáo: report_id=%s, error=%s", report_id, str(e))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(e)}), 400
    except SQLAlchemyError as e:
        logger.error("Lỗi cơ sở dữ liệu khi lấy chi tiết báo cáo: report_id=%s, error=%s", report_id, str(e))
        return jsonify({'message': 'Lỗi cơ sở dữ liệu'}), 500
    except Exception as e:
        logger.error("Lỗi server khi lấy chi tiết báo cáo: report_id=%s, error=%s", report_id, str(e))
        return jsonify({'message': 'Lỗi server không xác định', 'error': str(e)}), 500

# Lấy danh sách tất cả báo cáo (Admin)
@report_bp.route('/admin/reports', methods=['GET'])
@admin_required()
def get_all_reports():
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        user_id = request.args.get('user_id', type=int)
        room_id = request.args.get('room_id', type=int)
        status = request.args.get('status', type=str)

        logger.info("Lấy danh sách báo cáo với page=%s, limit=%s, user_id=%s, room_id=%s, status=%s", 
                    page, limit, user_id, room_id, status)

        if page < 1 or limit < 1:
            logger.warning("Tham số page=%s hoặc limit=%s không hợp lệ", page, limit)
            return jsonify({'message': 'Page và limit phải lớn hơn 0'}), 400

        if user_id and not User.query.get(user_id):
            logger.warning("Người dùng không tồn tại: user_id=%s", user_id)
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404

        if room_id and not Room.query.get(room_id):
            logger.warning("Phòng không tồn tại: room_id=%s", room_id)
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        if status:
            status = status.upper()
            if status not in VALID_STATUSES:
                logger.warning("Trạng thái không hợp lệ: status=%s", status)
                return jsonify({
                    'message': f'Trạng thái không hợp lệ, chỉ chấp nhận: {", ".join(VALID_STATUSES)}'
                }), 400

        query = Report.query
        if user_id:
            query = query.filter_by(user_id=user_id)
        if room_id:
            query = query.filter_by(room_id=room_id)
        if status:
            query = query.filter_by(status=status)

        reports = query.paginate(page=page, per_page=limit, error_out=False)
        if not reports.items and page > 1:
            logger.warning("Trang không tồn tại: page=%s", page)
            return jsonify({'message': 'Trang không tồn tại'}), 404

        logger.info("Lấy danh sách báo cáo thành công: total=%s", reports.total)
        return jsonify({
            'reports': [report.to_dict() for report in reports.items],
            'total': reports.total,
            'pages': reports.pages,
            'current_page': reports.page
        }), 200

    except Exception as e:
        logger.error("Lỗi server khi lấy danh sách báo cáo: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Lấy danh sách báo cáo của User hiện tại
@report_bp.route('/me/reports', methods=['GET'])
@user_required()
def get_my_reports():
    try:
        identity = get_jwt_identity()
        claims = get_jwt()
        if not identity:
            logger.warning("Không thể xác định người dùng: %s", identity)
            return jsonify({'message': 'Không thể xác định người dùng'}), 401

        user_id = int(identity)
        type_user = claims.get('type')
        if type_user != 'USER':
            logger.warning("Loại người dùng không hợp lệ: type=%s, user_id=%s", type_user, user_id)
            return jsonify({'message': 'Yêu cầu quyền người dùng'}), 403

        logger.info("Lấy danh sách báo cáo cho user_id=%s", user_id)

        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        status = request.args.get('status', type=str)

        if page < 1 or limit < 1:
            logger.warning("Tham số page=%s hoặc limit=%s không hợp lệ", page, limit)
            return jsonify({'message': 'Page và limit phải lớn hơn 0'}), 400

        if status:
            status = status.upper()
            if status not in VALID_STATUSES:
                logger.warning("Trạng thái không hợp lệ: status=%s", status)
                return jsonify({
                    'message': f'Trạng thái không hợp lệ, chỉ chấp nhận: {", ".join(VALID_STATUSES)}'
                }), 400

        query = Report.query.filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)

        reports = query.paginate(page=page, per_page=limit, error_out=False)
        if not reports.items and page > 1:
            logger.warning("Trang không tồn tại: page=%s", page)
            return jsonify({'message': 'Trang không tồn tại'}), 404

        logger.info("Lấy danh sách báo cáo của user_id=%s thành công: total=%s", user_id, reports.total)
        return jsonify({
            'reports': [report.to_dict() for report in reports.items],
            'total': reports.total,
            'pages': reports.pages,
            'current_page': reports.page
        }), 200

    except Exception as e:
        logger.error("Lỗi server khi lấy báo cáo của người dùng: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Tạo báo cáo mới với ảnh/video (User)
@report_bp.route('/reports', methods=['POST'])
@jwt_required()
@user_required()
def create_report():
    try:
        identity = get_jwt_identity()
        claims = get_jwt()
        if not identity:
            logger.warning("Yêu cầu không xác định được người dùng: %s", identity)
            return jsonify({'message': 'Token không hợp lệ hoặc thiếu thông tin người dùng'}), 401

        user_id = int(identity)
        type_user = claims.get('type')
        if type_user != 'USER':
            logger.warning("Loại người dùng không hợp lệ: type=%s, user_id=%s", type_user, user_id)
            return jsonify({'message': 'Yêu cầu quyền người dùng'}), 403

        logger.info("Bắt đầu tạo báo cáo cho user_id=%s", user_id)

        if not request.content_type.startswith('multipart/form-data'):
            logger.warning("Yêu cầu không phải multipart/form-data")
            return jsonify({'message': 'Yêu cầu multipart/form-data'}), 400

        data = request.form
        room_id = data.get('room_id', type=int)
        report_type_id = data.get('report_type_id', type=int)
        content = data.get('content')
        title = data.get('title')

        if not all([room_id, content, title]):
            missing_fields = [field for field, value in [('room_id', room_id), ('content', content), ('title', title)] if not value]
            logger.warning("Thiếu các trường bắt buộc: %s", missing_fields)
            return jsonify({'message': f'Yêu cầu các trường bắt buộc: {", ".join(missing_fields)}'}), 400

        try:
            if not isinstance(title, str) or not isinstance(content, str):
                raise ValueError("title và content phải là chuỗi")
            if len(title) > 255:
                raise ValueError("title không được vượt quá 255 ký tự")
            if len(content) > 65535:
                raise ValueError("content quá dài")
        except ValueError as e:
            logger.warning("Dữ liệu đầu vào không hợp lệ: %s", str(e))
            return jsonify({'message': f'Dữ liệu không hợp lệ: {str(e)}'}), 400

        room = Room.query.get(room_id)
        if not room:
            logger.warning("Phòng không tồn tại: room_id=%s", room_id)
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        if report_type_id is not None:
            report_type = ReportType.query.get(report_type_id)
            if not report_type:
                logger.warning("Loại báo cáo không tồn tại: report_type_id=%s", report_type_id)
                return jsonify({'message': 'Không tìm thấy loại báo cáo'}), 404

        user = User.query.get(user_id)
        if not user:
            logger.warning("Người dùng không tồn tại: user_id=%s", user_id)
            return jsonify({'message': 'Không tìm thấy người dùng'}), 404

        valid_contract = Contract.query.filter(
            Contract.user_id == user_id,
            Contract.room_id == room_id,
            Contract.status.in_(['ACTIVE', 'PENDING'])
        ).first()
        if not valid_contract:
            logger.warning("Không tìm thấy hợp đồng hợp lệ cho user_id=%s, room_id=%s", user_id, room_id)
            return jsonify({'message': 'Bạn không có hợp đồng hợp lệ trong phòng này'}), 403

        report = Report(
            room_id=room_id,
            user_id=user_id,
            report_type_id=report_type_id,
            title=title.strip(),
            description=content.strip(),
            status='PENDING'
        )
        db.session.add(report)
        db.session.flush()  # Lấy report_id trước khi commit

        files = request.files.getlist('images')
        if not files or all(file.filename == '' for file in files):
            logger.warning("Không có file media hợp lệ: report_id=%s", report.report_id)

        uploaded_images = []
        saved_files = []
        base_url = request.host_url.rstrip('/')

        if files:
            if len(files) > MAX_FILES_PER_REQUEST:
                logger.warning("Số lượng file vượt quá giới hạn: count=%s, max=%s, report_id=%s", len(files), MAX_FILES_PER_REQUEST, report.report_id)
                return jsonify({'message': f'Tối đa {MAX_FILES_PER_REQUEST} file mỗi yêu cầu'}), 400

            total_size = 0
            for file in files:
                file.seek(0, os.SEEK_END)
                total_size += file.tell()
                file.seek(0)
            if total_size > MAX_TOTAL_SIZE:
                logger.warning("Tổng kích thước file quá lớn: total=%s, max=%s, report_id=%s", total_size, MAX_TOTAL_SIZE, report.report_id)
                return jsonify({'message': f'Tổng kích thước file vượt quá {MAX_TOTAL_SIZE // (1024 * 1024)}MB'}), 400

            room_name = re.sub(r'[^\w\-]', '_', room.name)
            user_name = re.sub(r'[^\w\-]', '_', user.fullname if user.fullname else 'unknown')
            folder_name = f"{report.report_id}_{room_name}_{user_name}"
            report_folder = os.path.join(current_app.config['REPORT_IMAGES_FOLDER'], folder_name)
            try:
                os.makedirs(report_folder, exist_ok=True)
                logger.debug("Tạo thư mục media: %s", report_folder)
            except OSError as e:
                logger.error("Lỗi khi tạo thư mục: folder=%s, error=%s", report_folder, str(e))
                return jsonify({'message': 'Lỗi khi tạo thư mục lưu trữ'}), 500

            for index, file in enumerate(files):
                if file.filename == '':
                    logger.warning("File không có tên: index=%s, report_id=%s", index, report.report_id)
                    continue

                if not allowed_file(file.filename):
                    logger.warning("Định dạng file không hỗ trợ: filename=%s, report_id=%s", file.filename, report.report_id)
                    return jsonify({'message': f'File {file.filename} có định dạng không hỗ trợ. Chỉ chấp nhận: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                if file_size > MAX_FILE_SIZE:
                    file_type = get_file_type(file.filename)
                    logger.warning("File %s quá lớn: filename=%s, size=%s, max=%s, report_id=%s", file_type, file.filename, file_size, MAX_FILE_SIZE, report.report_id)
                    return jsonify({'message': f'File {file.filename} ({file_type}) quá lớn. Tối đa {MAX_FILE_SIZE // (1024 * 1024)}MB'}), 400

                extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                filename = generate_filename(user.fullname, extension, report_folder)
                file_path = os.path.join(report_folder, filename)

                try:
                    file.save(file_path)
                    logger.debug("Lưu file media tại: %s", file_path)
                except OSError as e:
                    logger.error("Lỗi khi lưu file media: filename=%s, error=%s", filename, str(e))
                    return jsonify({'message': f'Lỗi khi lưu file {filename}'}), 500

                saved_files.append(file_path)
                image_url = f"{base_url}/Uploads/report_images/{folder_name}/{filename}"
                file_type = get_file_type(filename)

                report_image = ReportImage(
                    report_id=report.report_id,
                    image_url=image_url,
                    file_type=file_type,
                    alt_text=data.get(f'alt_text_{index}', ''),
                    uploaded_at=datetime.utcnow()
                )
                db.session.add(report_image)
                uploaded_images.append(report_image)

        try:
            db.session.commit()
            logger.info("Tạo báo cáo thành công: report_id=%s, media_count=%s", report.report_id, len(uploaded_images))
            return jsonify(report.to_dict()), 201
        except IntegrityError as e:
            db.session.rollback()
            for file_path in saved_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Cleaned up file: {file_path}")
            logger.error("Lỗi toàn vẹn cơ sở dữ liệu khi tạo báo cáo: %s", str(e))
            return jsonify({'message': 'Lỗi cơ sở dữ liệu: Dữ liệu không hợp lệ hoặc xung đột'}), 409
        except DataError as e:
            db.session.rollback()
            for file_path in saved_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
            logger.error("Lỗi dữ liệu khi tạo báo cáo: %s", str(e))
            return jsonify({'message': 'Dữ liệu đầu vào vượt quá giới hạn cho phép'}), 400
        except Exception as e:
            db.session.rollback()
            for file_path in saved_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
            logger.error("Lỗi không xác định khi tạo báo cáo: %s", str(e))
            return jsonify({'message': 'Lỗi khi tạo báo cáo, vui lòng thử lại'}), 500

    except RequestEntityTooLarge:
        logger.warning("Yêu cầu vượt quá giới hạn kích thước")
        return jsonify({'message': f'Kích thước yêu cầu vượt quá giới hạn {current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)}MB'}), 413
    except Exception as e:
        logger.error("Lỗi server khi xử lý yêu cầu tạo báo cáo: %s", str(e))
        return jsonify({'message': 'Lỗi server nội bộ, vui lòng thử lại sau'}), 500

# Cập nhật thông tin báo cáo (Admin)
@report_bp.route('/admin/reports/<int:report_id>', methods=['PUT'])
@admin_required()
def update_report(report_id):
    try:
        logger.info("Cập nhật báo cáo: report_id=%s", report_id)

        report = Report.query.get(report_id)
        if not report:
            logger.warning("Báo cáo không tồn tại: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy báo cáo'}), 404

        data = request.get_json()
        if not data:
            logger.warning("Thiếu dữ liệu JSON cho báo cáo: report_id=%s", report_id)
            return jsonify({'message': 'Thiếu dữ liệu'}), 400

        new_room_id = data.get('room_id', report.room_id)
        new_report_type_id = data.get('report_type_id', report.report_type_id)
        new_description = data.get('content', report.description)
        new_status = data.get('status', report.status).upper() if data.get('status') else report.status

        if not Room.query.get(new_room_id):
            logger.warning("Phòng không tồn tại: room_id=%s", new_room_id)
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        if new_report_type_id and not ReportType.query.get(new_report_type_id):
            logger.warning("Loại báo cáo không tồn tại: report_type_id=%s", new_report_type_id)
            return jsonify({'message': 'Không tìm thấy loại báo cáo'}), 404

        if new_status not in VALID_STATUSES:
            logger.warning("Trạng thái không hợp lệ: status=%s", new_status)
            return jsonify({
                'message': f'Trạng thái không hợp lệ, chỉ chấp nhận: {", ".join(VALID_STATUSES)}'
            }), 400

        report.room_id = new_room_id
        report.report_type_id = new_report_type_id
        report.description = new_description
        report.status = new_status

        if new_status == 'RESOLVED' and report.status != 'RESOLVED':
            report.resolved_at = datetime.utcnow()
        elif new_status == 'CLOSED' and report.status != 'CLOSED':
            report.closed_at = datetime.utcnow()

        try:
            db.session.commit()
            logger.info("Cập nhật báo cáo thành công: report_id=%s", report_id)
            return jsonify(report.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi cập nhật báo cáo: %s", str(e))
            return jsonify({'message': 'Lỗi khi cập nhật báo cáo', 'error': str(e)}), 500

    except Exception as e:
        logger.error("Lỗi server khi cập nhật báo cáo: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Cập nhật trạng thái báo cáo (Admin)
@report_bp.route('/admin/reports/<int:report_id>/status', methods=['PUT'])
@admin_required()
def update_report_status(report_id):
    try:
        logger.info("Cập nhật trạng thái báo cáo: report_id=%s", report_id)

        report = Report.query.get(report_id)
        if not report:
            logger.warning("Báo cáo không tồn tại: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy báo cáo'}), 404

        data = request.get_json()
        if not data:
            logger.warning("Thiếu dữ liệu JSON cho báo cáo: report_id=%s", report_id)
            return jsonify({'message': 'Thiếu dữ liệu'}), 400

        status = data.get('status')
        if not status:
            logger.warning("Thiếu trường status cho báo cáo: report_id=%s", report_id)
            return jsonify({'message': 'Yêu cầu status'}), 400

        status = status.upper()
        if status not in VALID_STATUSES:
            logger.warning("Trạng thái không hợp lệ: status=%s, report_id=%s", status, report_id)
            return jsonify({
                'message': f'Trạng thái không hợp lệ, chỉ chấp nhận: {", ".join(VALID_STATUSES)}'
            }), 400

        old_status = report.status
        report.status = status

        if status == 'RESOLVED' and old_status != 'RESOLVED':
            report.resolved_at = datetime.utcnow()
        elif status == 'CLOSED' and old_status != 'CLOSED':
            report.closed_at = datetime.utcnow()

        try:
            db.session.commit()
            logger.info("Cập nhật trạng thái báo cáo thành công: report_id=%s, status=%s", report_id, status)
            return jsonify(report.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi cập nhật trạng thái báo cáo: %s", str(e))
            return jsonify({'message': 'Lỗi khi cập nhật trạng thái báo cáo', 'error': str(e)}), 500

    except Exception as e:
        logger.error("Lỗi server khi cập nhật trạng thái báo cáo: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Xóa báo cáo (Admin)
@report_bp.route('/admin/reports/<int:report_id>', methods=['DELETE'])
@admin_required()
def delete_report(report_id):
    try:
        logger.info("Attempting to delete report: report_id=%s", report_id)

        report = Report.query.get(report_id)
        if not report:
            logger.warning("Report not found: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy báo cáo'}), 404

        report_images = ReportImage.query.filter_by(report_id=report_id).all()
        for image in report_images:
            image.is_deleted = True
            image.deleted_at = datetime.utcnow()
            image.report_id = None
            logger.debug("Marked ReportImage as deleted: image_id=%s, report_id=None", image.image_id)

        db.session.delete(report)

        try:
            db.session.commit()
            logger.info("Report deleted and associated images marked as deleted: report_id=%s", report_id)
            return '', 204
        except IntegrityError as e:
            db.session.rollback()
            logger.error("Integrity error deleting report: report_id=%s, error=%s", report_id, str(e))
            return jsonify({'message': 'Lỗi cơ sở dữ liệu: Không thể xóa báo cáo do ràng buộc dữ liệu'}), 409
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error("Database error deleting report: report_id=%s, error=%s", report_id, str(e))
            return jsonify({'message': 'Lỗi cơ sở dữ liệu khi xóa báo cáo'}), 500

    except Exception as e:
        db.session.rollback()
        logger.error("Unexpected error deleting report: report_id=%s, error=%s", report_id, str(e))
        return jsonify({'message': 'Lỗi server không xác định', 'error': str(e)}), 500