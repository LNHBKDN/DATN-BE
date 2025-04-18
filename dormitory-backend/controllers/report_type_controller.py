from flask import Blueprint, request, jsonify
from extensions  import db
from models.report_type import ReportType
from controllers.auth_controller import admin_required
import os
from flask import current_app
from werkzeug.utils import secure_filename
report_type_bp = Blueprint('report_type', __name__)

# Lấy danh sách tất cả loại báo cáo (Public)
@report_type_bp.route('/report-types', methods=['GET'])
def get_all_report_types():
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)

        types = ReportType.query.paginate(page=page, per_page=limit)
        return jsonify({
            'report_types': [type.to_dict() for type in types.items],
            'total': types.total,
            'pages': types.pages,
            'current_page': types.page
        }), 200
    except Exception as e:
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Tạo loại báo cáo mới (Admin)
@report_type_bp.route('/admin/report-types', methods=['POST'])
@admin_required()
def create_report_type():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'message': 'Thiếu dữ liệu'}), 400

        name = data.get('name')

        if not name:
            return jsonify({'message': 'Yêu cầu name'}), 400

        # Kiểm tra trùng tên
        existing_report_type = ReportType.query.filter_by(name=name).first()
        if existing_report_type:
            return jsonify({'message': 'Tên đã tồn tại'}), 400

        report_type = ReportType(name=name)
        db.session.add(report_type)

        # Commit để lưu ReportType
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'message': 'Lỗi khi tạo loại báo cáo', 'error': str(e)}), 500

        # Tạo thư mục với tên report_<name>
        folder_name = f"report_{name}"
        # Thay thế các ký tự không hợp lệ trong tên thư mục
        folder_name = "".join(c if c.isalnum() or c == '_' else '_' for c in folder_name)
        report_type_folder = os.path.join(
            current_app.config['REPORT_IMAGES_FOLDER'],
            'report_types',
            folder_name
        )
        if not os.path.exists(report_type_folder):
            try:
                os.makedirs(report_type_folder)
            except Exception as e:
                return jsonify({'message': 'Không thể tạo thư mục cho loại báo cáo', 'error': str(e)}), 500

        return jsonify(report_type.to_dict()), 201

    except Exception as e:
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Cập nhật loại báo cáo (Admin)
@report_type_bp.route('/admin/report-types/<int:report_type_id>', methods=['PUT'])
@admin_required()
def update_report_type(report_type_id):
    try:
        report_type = ReportType.query.get(report_type_id)
        if not report_type:
            return jsonify({'message': 'Không tìm thấy loại báo cáo'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'message': 'Thiếu dữ liệu'}), 400

        old_name = report_type.name
        new_name = data.get('name', old_name)

        # Kiểm tra trùng tên (ngoại trừ bản ghi hiện tại)
        if new_name != old_name:
            existing_report_type = ReportType.query.filter(
                ReportType.name == new_name,
                ReportType.report_type_id != report_type_id
            ).first()
            if existing_report_type:
                return jsonify({'message': 'Tên đã tồn tại'}), 400

        report_type.name = new_name


        # Nếu tên thay đổi, đổi tên thư mục
        if old_name != new_name:
            old_folder_name = f"report_{old_name}"
            old_folder_name = "".join(c if c.isalnum() or c == '_' else '_' for c in old_folder_name)
            old_folder = os.path.join(
                current_app.config['REPORT_IMAGES_FOLDER'],
                'report_types',
                old_folder_name
            )

            new_folder_name = f"report_{new_name}"
            new_folder_name = "".join(c if c.isalnum() or c == '_' else '_' for c in new_folder_name)
            new_folder = os.path.join(
                current_app.config['REPORT_IMAGES_FOLDER'],
                'report_types',
                new_folder_name
            )

            # Đổi tên thư mục nếu thư mục cũ tồn tại
            if os.path.exists(old_folder):
                try:
                    os.rename(old_folder, new_folder)
                except Exception as e:
                    return jsonify({'message': 'Không thể đổi tên thư mục cho loại báo cáo', 'error': str(e)}), 500

        try:
            db.session.commit()
            return jsonify(report_type.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'message': 'Lỗi khi cập nhật loại báo cáo', 'error': str(e)}), 500

    except Exception as e:
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500
# Xóa loại báo cáo (Admin)
@report_type_bp.route('/admin/report-types/<int:report_type_id>', methods=['DELETE'])
@admin_required()
def delete_report_type(report_type_id):
    try:
        report_type = ReportType.query.get(report_type_id)
        if not report_type:
            return jsonify({'message': 'Không tìm thấy loại báo cáo'}), 404

        # Xóa bản ghi ReportType
        db.session.delete(report_type)

        # Thư mục uploads/report_images/report_types/report_<name> sẽ không bị xóa
        try:
            db.session.commit()
            return '', 204
        except Exception as e:
            db.session.rollback()
            return jsonify({'message': 'Lỗi khi xóa loại báo cáo', 'error': str(e)}), 500

    except Exception as e:
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500