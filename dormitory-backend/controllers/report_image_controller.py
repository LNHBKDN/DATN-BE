from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from flask import current_app
from models.reportimage import ReportImage
from models.report import Report
from controllers.auth_controller import admin_required, user_required
from werkzeug.utils import secure_filename
import os
import uuid
import logging
from datetime import datetime
import re
from werkzeug.exceptions import RequestEntityTooLarge
from unidecode import unidecode

# Thiết lập logging
logger = logging.getLogger(__name__)

report_image_bp = Blueprint('report_image', __name__)

# Danh sách định dạng được phép
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi'}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB mỗi file
MAX_FILES_PER_REQUEST = 10  # Tối đa 10 file mỗi yêu cầu
MAX_TOTAL_SIZE = 1000 * 1024 * 1024  # 1000MB tổng kích thước

# Hàm kiểm tra file hợp lệ
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Hàm xác định loại file
def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return 'video' if ext in VIDEO_EXTENSIONS else 'image'

# Hàm tạo tên file từ fullname
def generate_filename(fullname, extension, folder):
    # Chuẩn hóa fullname thành không dấu, loại bỏ ký tự đặc biệt
    base_name = re.sub(r'[^\w]', '', unidecode(fullname)).title()
    # Lấy chữ cái đầu của tên cuối (nếu có)
    name_parts = base_name.split()
    if len(name_parts) > 1:
        base_name = ''.join(name_parts[:-1]) + name_parts[-1][0]
    else:
        base_name = name_parts[0]
    
    # Tạo tên file cơ bản
    filename = f"{base_name}.{extension.lower()}"
    
    # Xử lý trùng tên bằng cách thêm hậu tố _1, _2, ...
    counter = 1
    while os.path.exists(os.path.join(folder, filename)):
        filename = f"{base_name}_{counter}.{extension.lower()}"
        counter += 1
    
    return filename

# Thêm nhiều ảnh/video vào báo cáo (User sở hữu hoặc Admin)
@report_image_bp.route('/reports/<int:report_id>/images', methods=['POST'])
@jwt_required()
def create_report_image(report_id):
    try:
        identity = get_jwt_identity()
        claims = get_jwt()
        if not identity:
            logger.warning("Yêu cầu không xác định được người dùng: %s", identity)
            return jsonify({'message': 'Token không hợp lệ hoặc thiếu thông tin người dùng'}), 401

        user_id = int(identity)  # identity là sub (user_id)
        type_user = claims.get('type')
        logger.info("Bắt đầu thêm media vào báo cáo: report_id=%s, user_id=%s, type=%s", report_id, user_id, type_user)

        report = Report.query.get(report_id)
        if not report:
            logger.warning("Báo cáo không tồn tại: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy báo cáo'}), 404

        # Kiểm tra quyền
        if type_user == 'USER' and report.user_id != user_id:
            logger.warning("Người dùng không có quyền thêm media: user_id=%s, report_id=%s", user_id, report_id)
            return jsonify({'message': 'Bạn không có quyền thêm media vào báo cáo này'}), 403

        # Kiểm tra trạng thái báo cáo
        if report.status == 'CLOSED':
            logger.warning("Báo cáo đã đóng, không thể thêm media: report_id=%s", report_id)
            return jsonify({'message': 'Báo cáo đã đóng, không thể thêm media'}), 403

        if 'images[]' not in request.files:
            logger.warning("Yêu cầu thiếu danh sách file media: report_id=%s", report_id)
            return jsonify({'message': 'Yêu cầu danh sách file media (key: images[])'}), 400

        files = request.files.getlist('images[]')
        if not files or len(files) == 0:
            logger.warning("Không có file nào được chọn: report_id=%s", report_id)
            return jsonify({'message': 'Không có file nào được chọn'}), 400

        if len(files) > MAX_FILES_PER_REQUEST:
            logger.warning("Số lượng file vượt quá giới hạn: count=%s, max=%s, report_id=%s", len(files), MAX_FILES_PER_REQUEST, report_id)
            return jsonify({'message': f'Tối đa {MAX_FILES_PER_REQUEST} file mỗi yêu cầu'}), 400

        # Kiểm tra tổng kích thước các file
        total_size = 0
        for file in files:
            file.seek(0, os.SEEK_END)
            total_size += file.tell()
            file.seek(0)
        if total_size > MAX_TOTAL_SIZE:
            logger.warning("Tổng kích thước file quá lớn: total=%s, max=%s, report_id=%s", total_size, MAX_TOTAL_SIZE, report_id)
            return jsonify({'message': f'Tổng kích thước file vượt quá {MAX_TOTAL_SIZE // (1024 * 1024)}MB'}), 400

        uploaded_images = []
        base_url = request.host_url.rstrip('/')

        # Lấy thông tin room và user
        room = report.room
        user = report.user
        if not room or not user:
            logger.warning("Không tìm thấy room hoặc user: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy thông tin phòng hoặc người dùng'}), 404

        # Tạo tên thư mục: [report_id]_[room_name]_[user_name]
        room_name = re.sub(r'[^\w\-]', '_', room.name)
        user_name = re.sub(r'[^\w\-]', '_', user.fullname if user.fullname else 'unknown')
        folder_name = f"{report_id}_{room_name}_{user_name}"
        report_folder = os.path.join(current_app.config['REPORT_IMAGES_FOLDER'], folder_name)
        try:
            os.makedirs(report_folder, exist_ok=True)
            logger.debug("Tạo thư mục media: %s", report_folder)
        except OSError as e:
            logger.error("Lỗi khi tạo thư mục: folder=%s, error=%s", report_folder, str(e))
            return jsonify({'message': 'Lỗi khi tạo thư mục lưu trữ'}), 500

        for file in files:
            if file.filename == '':
                logger.warning("File không có tên: report_id=%s", report_id)
                continue

            if not allowed_file(file.filename):
                logger.warning("Định dạng file không hỗ trợ: filename=%s, report_id=%s", file.filename, report_id)
                return jsonify({'message': f'File {file.filename} có định dạng không hỗ trợ. Chỉ chấp nhận: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

            # Kiểm tra kích thước file
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            if file_size > MAX_FILE_SIZE:
                file_type = get_file_type(file.filename)
                logger.warning("File %s quá lớn: filename=%s, size=%s, max=%s, report_id=%s", file_type, file.filename, file_size, MAX_FILE_SIZE, report_id)
                return jsonify({'message': f'File {file.filename} ({file_type}) quá lớn. Tối đa {MAX_FILE_SIZE // (1024 * 1024)}MB'}), 400

            # Lấy phần mở rộng của file
            extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''

            # Tạo tên file theo định dạng NguyenVanC
            filename = generate_filename(user.fullname, extension, report_folder)
            
            file_path = os.path.join(report_folder, filename)
            try:
                file.save(file_path)
                logger.debug("Lưu file media tại: %s", file_path)
            except OSError as e:
                logger.error("Lỗi khi lưu file media: filename=%s, error=%s", filename, str(e))
                return jsonify({'message': f'Lỗi khi lưu file {filename}'}), 500

            # Tạo URL công khai
            image_url = f"{base_url}/Uploads/report_images/{folder_name}/{filename}"

            # Xác định loại file
            file_type = get_file_type(filename)

            # Tạo bản ghi ReportImage
            report_image = ReportImage(
                report_id=report_id,
                image_url=image_url,
                file_type=file_type,
                alt_text=request.form.get('alt_text', None)
            )
            db.session.add(report_image)
            uploaded_images.append(report_image)

        if not uploaded_images:
            logger.warning("Không có file hợp lệ nào được tải lên: report_id=%s", report_id)
            return jsonify({'message': 'Không có file hợp lệ nào được tải lên'}), 400

        try:
            db.session.commit()
            logger.info("Thêm %s file media thành công: report_id=%s", len(uploaded_images), report_id)
            return jsonify([image.to_dict() for image in uploaded_images]), 201
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi lưu media vào cơ sở dữ liệu: %s", str(e))
            # Xóa các file đã lưu nếu commit thất bại
            for image in uploaded_images:
                file_path = os.path.join(report_folder, os.path.basename(image.image_url))
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info("Xóa file media do rollback: %s", file_path)
            return jsonify({'message': 'Lỗi khi lưu media, vui lòng thử lại'}), 500

    except RequestEntityTooLarge:
        logger.warning("Yêu cầu vượt quá giới hạn kích thước: report_id=%s", report_id)
        return jsonify({'message': f'Kích thước yêu cầu vượt quá giới hạn {current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)}MB'}), 413
    except Exception as e:
        logger.error("Lỗi server khi xử lý yêu cầu thêm media: %s", str(e))
        return jsonify({'message': 'Lỗi server nội bộ, vui lòng thử lại sau'}), 500

# Lấy danh sách ảnh/video của báo cáo (Admin hoặc User sở hữu)
@report_image_bp.route('/reports/<int:report_id>/images', methods=['GET'])
@jwt_required()
def get_report_images(report_id):
    try:
        identity = get_jwt_identity()
        claims = get_jwt()
        if not identity:
            logger.warning("Yêu cầu không xác định được người dùng: %s", identity)
            return jsonify({'message': 'Token không hợp lệ hoặc thiếu thông tin người dùng'}), 401

        user_id = int(identity)
        type_user = claims.get('type')
        logger.info("Lấy danh sách media của báo cáo: report_id=%s, user_id=%s, type=%s", report_id, user_id, type_user)

        report = Report.query.get(report_id)
        if not report:
            logger.warning("Báo cáo không tồn tại: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy báo cáo'}), 404

        if type_user == 'USER' and report.user_id != user_id:
            logger.warning("Người dùng không có quyền xem media: user_id=%s, report_id=%s", user_id, report_id)
            return jsonify({'message': 'Bạn không có quyền xem media của báo cáo này'}), 403

        images = ReportImage.query.filter_by(report_id=report_id, is_deleted=False).all()
        logger.info("Lấy danh sách media thành công: report_id=%s, total=%s", report_id, len(images))
        return jsonify([image.to_dict() for image in images]), 200

    except Exception as e:
        logger.error("Lỗi server khi lấy danh sách media: %s", str(e))
        return jsonify({'message': 'Lỗi server, vui lòng thử lại sau'}), 500

# Xóa ảnh/video của báo cáo (Admin)
@report_image_bp.route('/admin/reports/<int:report_id>/images/<int:report_image_id>', methods=['DELETE'])
@admin_required()
def delete_report_image(report_id, report_image_id):
    try:
        logger.info("Xóa media của báo cáo: report_id=%s, image_id=%s", report_id, report_image_id)

        report = Report.query.get(report_id)
        if not report:
            logger.warning("Báo cáo không tồn tại: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy báo cáo'}), 404

        image = ReportImage.query.get(report_image_id)
        if not image or image.report_id != report_id or image.is_deleted:
            logger.warning("Media không tồn tại hoặc đã bị xóa: image_id=%s, report_id=%s", report_image_id, report_id)
            return jsonify({'message': 'Không tìm thấy media'}), 404

        # Cập nhật soft delete
        image.is_deleted = True
        image.deleted_at = datetime.utcnow()
        logger.info("Đánh dấu soft delete media: image_id=%s, report_id=%s", report_image_id, report_id)

        try:
            db.session.commit()
            logger.info("Xóa media thành công: image_id=%s, report_id=%s", report_image_id, report_id)
            return '', 204
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi xóa media: %s", str(e))
            return jsonify({'message': 'Lỗi khi xóa media, vui lòng thử lại'}), 500

    except Exception as e:
        logger.error("Lỗi server khi xóa media: %s", str(e))
        return jsonify({'message': 'Lỗi server, vui lòng thử lại sau'}), 500