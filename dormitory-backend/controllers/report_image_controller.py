from flask import Blueprint, request, jsonify, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from flask import current_app
from models.reportimage import ReportImage
from models.report import Report
from controllers.auth_controller import admin_required, user_required
import os
import uuid
import logging
from datetime import datetime
from werkzeug.exceptions import RequestEntityTooLarge

# Thiết lập logging
logger = logging.getLogger(__name__)

report_image_bp = Blueprint('report_image', __name__)

# Danh sách định dạng được phép
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi'}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB mỗi file
MAX_FILES_PER_REQUEST = 20  # Tăng giới hạn lên 20 file mỗi yêu cầu
MAX_TOTAL_SIZE = 1000 * 1024 * 1024  # 1000MB tổng kích thước

# Hàm kiểm tra file hợp lệ
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Hàm xác định loại file
def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return 'video' if ext in VIDEO_EXTENSIONS else 'image'

# Thêm nhiều ảnh/video vào báo cáo (Chỉ User sở hữu)
@report_image_bp.route('/reports/<int:report_id>/images', methods=['POST'])
@jwt_required()
@user_required()
def create_report_image(report_id):
    try:
        identity = get_jwt_identity()
        if not identity:
            logger.warning("Yêu cầu không xác định được người dùng: %s", identity)
            return jsonify({'message': 'Token không hợp lệ hoặc thiếu thông tin người dùng'}), 401

        user_id = int(identity)
        logger.info("Bắt đầu thêm media vào báo cáo: report_id=%s, user_id=%s", report_id, user_id)

        report = Report.query.get(report_id)
        if not report:
            logger.warning("Báo cáo không tồn tại: report_id=%s", report_id)
            return jsonify({'message': 'Không tìm thấy báo cáo'}), 404

        # Kiểm tra quyền: Chỉ user sở hữu báo cáo được thêm media
        if report.user_id != user_id:
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
        saved_files = []

        # Tạo thư mục lưu trữ ảnh
        upload_folder = os.path.join(current_app.config['REPORT_IMAGES_FOLDER'])
        os.makedirs(upload_folder, exist_ok=True)
        logger.debug("Tạo thư mục media: %s", upload_folder)

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

            # Tạo tên file duy nhất bằng uuid
            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            filename = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(upload_folder, filename)

            # Lưu file
            file.save(file_path)
            saved_files.append(file_path)
            logger.debug("Lưu file media tại: %s", file_path)

            # Xác định loại file
            file_type = get_file_type(filename)

            # Tạo bản ghi ReportImage
            report_image = ReportImage(
                report_id=report_id,
                image_url=filename,  # Chỉ lưu tên file, không bao gồm đường dẫn con
                file_type=file_type,
                alt_text=request.form.get('alt_text', None),
                file_size=file_size,
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
            for file_path in saved_files:
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
        if not images:
            logger.info("Không có media cho báo cáo: report_id=%s", report_id)
            return jsonify({'message': 'Không có ảnh'}), 200

        # Trả về danh sách ảnh với imageId, imageUrl và fileType
        image_list = [{'imageId': image.image_id, 'imageUrl': image.image_url, 'fileType': image.file_type} for image in images]
        logger.info("Lấy danh sách media thành công: report_id=%s, total=%s", report_id, len(images))
        return jsonify(image_list), 200

    except Exception as e:
        logger.error("Lỗi server khi lấy danh sách media: %s", str(e))
        return jsonify({'message': 'Lỗi server, vui lòng thử lại sau'}), 500

# Thêm route để phục vụ tệp hình ảnh
@report_image_bp.route('/reportimage/<path:filename>')
def serve_image(filename):
    try:
        full_path = os.path.join(current_app.config['REPORT_IMAGES_FOLDER'], filename)
        logger.info(f"Serving image: {filename}, full path: {full_path}")

        # Kiểm tra file tồn tại trong database
        media = ReportImage.query.filter_by(image_url=filename, is_deleted=False).first()
        if not media:
            logger.warning(f"Media not found or deleted: {filename}")
            return jsonify({'message': 'Không tìm thấy file media hoặc file đã bị xóa'}), 404

        if not os.path.exists(full_path):
            logger.error(f"Image file not found at: {full_path}")
            return jsonify({'message': f'Tệp hình ảnh không tồn tại tại: {full_path}'}), 404

        response = send_from_directory(current_app.config['REPORT_IMAGES_FOLDER'], filename)
        # Thêm header CORS
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        # Thêm xử lý cho video
        if media.file_type == 'video':
            response.headers['Content-Disposition'] = 'inline'
            response.headers['Accept-Ranges'] = 'bytes'
        return response
    except Exception as e:
        logger.error(f"Error serving image {filename}: {str(e)}")
        return jsonify({'message': f'Lỗi khi phục vụ hình ảnh: {str(e)}'}), 404

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