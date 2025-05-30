from flask import Blueprint, request, jsonify, send_from_directory
from extensions import db
from models.roomimage import RoomImage
from models.room import Room
from models.area import Area
from controllers.auth_controller import admin_required
from sqlalchemy.exc import SQLAlchemyError
import os
import logging
from werkzeug.utils import secure_filename
from flask import current_app
from datetime import datetime
import uuid
from unidecode import unidecode
import re

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

roomimage_bp = Blueprint('roomimage', __name__)

# Normalize name (remove Vietnamese accents and special characters)
def normalize_name(name):
    normalized = unidecode(name)
    normalized = re.sub(r'[^a-zA-Z0-9]', '_', normalized)
    return normalized

# Upload multiple room media at once (Admin)
@roomimage_bp.route('/admin/rooms/<int:room_id>/images', methods=['POST'])
@admin_required()
def upload_room_images(room_id):
    try:
        # Check if room exists
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Room not found'}), 404

        # Check area
        area = Area.query.get(room.area_id)
        if not area:
            logger.warning(f"Area {room.area_id} not found for room {room_id}")
            return jsonify({'message': 'Area not found for room'}), 404

        # Create media storage directory
        upload_folder = os.path.join(current_app.config['ROOM_IMAGES_BASE'])
        os.makedirs(upload_folder, exist_ok=True)

        # Check for media files
        if 'images' not in request.files:
            logger.warning("No media in request")
            return jsonify({'message': 'No media files provided (key: images)'}), 400

        files = request.files.getlist('images')
        if not files or all(file.filename == '' for file in files):
            logger.warning("Empty or invalid media files")
            return jsonify({'message': 'No valid media files provided'}), 400

        # Log received data
        logger.info(f"Received {len(files)} files for room {room_id}")
        logger.info(f"Form data: {request.form.to_dict()}")

        # Limit number of media
        max_media = 20
        if len(files) > max_media:
            logger.warning(f"Too many media files uploaded: {len(files)} > {max_media}")
            return jsonify({'message': f'Maximum {max_media} files allowed at once'}), 400

        media_list = []
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'avi'}
        max_file_size = 100 * 1024 * 1024  # 100MB
        saved_files = []  # Track saved files for cleanup on error

        # Validate and process all files
        for i, file in enumerate(files):
            if not file or not file.filename:
                logger.warning(f"Empty file at index {i}")
                return jsonify({'message': 'List contains empty file'}), 400

            # Check file extension
            if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
                logger.warning(f"Invalid file extension: {file.filename}")
                return jsonify({'message': f'File {file.filename}: Only png, jpg, jpeg, gif, mp4, avi supported'}), 400

            # Check file size
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            if file_size > max_file_size:
                logger.warning(f"File too large: {file.filename}, size: {file_size}")
                return jsonify({'message': f'File {file.filename}: Exceeds 100MB limit'}), 400
            file.seek(0)

            # Generate unique filename
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(upload_folder, filename)

            # Save file
            file.save(file_path)
            saved_files.append(file_path)
            logger.info(f"Saved file: {file_path}")

            # Get is_primary from form data
            is_primary = request.form.get(f'is_primary[{i}]', 'False', type=str).lower() == 'true'
            alt_text = request.form.get(f'alt_text[{i}]', '')
            sort_order = request.form.get(f'sort_order[{i}]', 0, type=int)

            # Log received values
            logger.info(f"Media {i}: is_primary={is_primary}, alt_text={alt_text}, sort_order={sort_order}")

            # Set other files to non-primary if this is primary
            primary_set = False
            if is_primary and not primary_set:
                RoomImage.query.filter_by(room_id=room_id, is_primary=True).update({'is_primary': False})
                primary_set = True
            elif is_primary:
                logger.warning(f"Multiple primary media attempted for room {room_id}")
                is_primary = False

            file_type = 'video' if ext in {'mp4', 'avi'} else 'image'
            media = RoomImage(
                room_id=room_id,
                image_url=filename,
                alt_text=alt_text,
                is_primary=is_primary,
                sort_order=sort_order,
                file_type=file_type,
                file_size=file_size
            )
            db.session.add(media)
            media_list.append(media)
            logger.info(f"Added media to session: {media.to_dict()}")

        # Commit all changes
        db.session.commit()
        logger.info(f"Committed {len(media_list)} media files for room {room_id} to database")
        return jsonify([media.to_dict() for media in media_list]), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        for file_path in saved_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up file: {file_path}")
                except OSError:
                    logger.warning(f"Failed to clean up file: {file_path}")
        logger.error(f"Database error uploading media for room {room_id}: {str(e)}")
        return jsonify({'message': 'Database error saving media'}), 500
    except OSError as e:
        db.session.rollback()
        for file_path in saved_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        logger.error(f"File system error uploading media for room {room_id}: {str(e)}")
        return jsonify({'message': 'System error saving files'}), 500
    except ValueError as e:
        logger.error(f"Value error uploading media for room {room_id}: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        for file_path in saved_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        logger.error(f"Unexpected error uploading media for room {room_id}: {str(e)}")
        return jsonify({'message': 'Unknown server error'}), 500

# Get room media list (Public)
@roomimage_bp.route('/rooms/<int:room_id>/images', methods=['GET'])
def get_room_images(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Room not found'}), 404

        media = RoomImage.query.filter_by(room_id=room_id, is_deleted=False).order_by(RoomImage.sort_order).all()
        # Return empty list with 200 if no media found
        media_list = [{'imageId': m.image_id, 'imageUrl': m.image_url, 'fileType': m.file_type} for m in media]
        logger.info(f"Retrieved {len(media_list)} media items for room {room_id}")
        return jsonify(media_list), 200
    except Exception as e:
        logger.error(f"Error retrieving media for room {room_id}: {str(e)}")
        return jsonify({'message': 'Unknown server error'}), 500

# Serve media file
@roomimage_bp.route('/roomimage/<filename>', methods=['GET'])
def serve_image(filename):
    try:
        full_path = os.path.join(current_app.config['ROOM_IMAGES_BASE'], filename)
        logger.info(f"Serving media: {filename}, full path: {full_path}")

        media = RoomImage.query.filter_by(image_url=filename, is_deleted=False).first()
        if not media:
            logger.warning(f"Media not found or deleted: {filename}")
            return jsonify({'message': 'Media file not found or deleted'}), 404

        if not os.path.exists(full_path):
            logger.error(f"Media file not found: {full_path}")
            return jsonify({'message': f'Media file does not exist at: {full_path}'}), 404

        response = send_from_directory(current_app.config['ROOM_IMAGES_BASE'], filename)
        if media.file_type == 'video':
            response.headers['Content-Disposition'] = 'inline'
            response.headers['Accept-Ranges'] = 'bytes'
        return response
    except Exception as e:
        logger.error(f"Error serving media {filename}: {str(e)}")
        return jsonify({'message': f'Error serving media: {str(e)}'}), 404

# Update media info (Admin)
@roomimage_bp.route('/admin/rooms/<int:room_id>/images/<int:image_id>', methods=['PUT'])
@admin_required()
def update_room_image_info(room_id, image_id):
    try:
        media = RoomImage.query.get(image_id)
        if not media or media.room_id != room_id or media.is_deleted:
            logger.warning(f"Media {image_id} not found or deleted for room {room_id}")
            return jsonify({'message': 'Media not found or deleted'}), 404

        data = request.get_json()
        if not data:
            logger.warning("No data provided for updating media")
            return jsonify({'message': 'No update data provided'}), 400

        # Update info
        media.alt_text = data.get('alt_text', media.alt_text)
        is_primary = data.get('is_primary', media.is_primary)
        if is_primary and not media.is_primary:
            RoomImage.query.filter_by(room_id=room_id, is_primary=True).update({'is_primary': False})
        media.is_primary = is_primary
        media.sort_order = data.get('sort_order', media.sort_order)

        db.session.commit()
        logger.info(f"Updated media {image_id} for room {room_id}")
        return jsonify(media.to_dict()), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error updating media {image_id}: {str(e)}")
        return jsonify({'message': 'Database error updating media'}), 500
    except ValueError as e:
        logger.error(f"Value error updating media {image_id}: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error updating media {image_id}: {str(e)}")
        return jsonify({'message': 'Unknown server error'}), 500

# Delete room media (Admin) - Soft delete and move to trash
@roomimage_bp.route('/admin/rooms/<int:room_id>/images/<int:image_id>', methods=['DELETE'])
@admin_required()
def delete_room_image(room_id, image_id):
    try:
        logger.info(f"Attempting to delete media {image_id} for room {room_id}")
        
        # Check media
        media = RoomImage.query.filter_by(image_id=image_id, room_id=room_id, is_deleted=False).first()
        if not media:
            logger.warning(f"Media {image_id} not found or already deleted for room {room_id}")
            return jsonify({'message': 'Media not found or already deleted'}), 404

        # Check room
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Room not found'}), 404

        # Check area
        area = Area.query.get(room.area_id)
        if not area:
            logger.warning(f"Area {room.area_id} not found")
            return jsonify({'message': 'Area not found for room'}), 404

        # Mark as soft deleted
        media.is_deleted = True
        media.deleted_at = datetime.utcnow()
        logger.info(f"Marked media {image_id} as soft deleted for room {room_id}")

        # Move file to trash
        roomname = f"{room.name} - {area.name}"
        logger.info(f"Room name: {room.name}, Area name: {area.name}, Combined: {roomname}")
        roomname = normalize_name(roomname)
        logger.info(f"Normalized roomname: {roomname}")

        # Log configuration
        upload_base = current_app.config.get('UPLOAD_BASE', 'Not configured')
        room_images_base = current_app.config.get('ROOM_IMAGES_BASE', 'Not configured')
        logger.info(f"UPLOAD_BASE: {upload_base}")
        logger.info(f"ROOM_IMAGES_BASE: {room_images_base}")

        trash_folder = os.path.join(current_app.config['UPLOAD_BASE'], 'trash', 'roomimage', roomname)
        logger.info(f"Creating trash folder: {trash_folder}")
        os.makedirs(trash_folder, exist_ok=True)

        absolute_path = os.path.join(current_app.config['ROOM_IMAGES_BASE'], media.image_url)
        logger.info(f"Absolute path of media: {absolute_path}")
        if os.path.exists(absolute_path):
            trash_filename = f"{uuid.uuid4().hex}_{media.image_url}"
            trash_path = os.path.join(trash_folder, trash_filename)
            logger.info(f"Renaming {absolute_path} to {trash_path}")
            os.rename(absolute_path, trash_path)
            logger.info(f"Moved media {media.image_url} to trash: {trash_path}")
        else:
            logger.warning(f"Media file not found: {absolute_path}")

        # Commit changes to database
        db.session.commit()
        logger.info(f"Soft deleted media {image_id} for room {room_id}")
        return '', 204

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error deleting media {image_id}: {str(e)}")
        return jsonify({'message': 'Database error deleting media'}), 500
    except OSError as e:
        logger.error(f"File system error deleting media {image_id}: {str(e)}")
        try:
            db.session.commit()
            logger.info(f"Soft deleted media {image_id} despite file system error")
            return '', 204
        except SQLAlchemyError as db_e:
            db.session.rollback()
            logger.error(f"Database error after file system error: {str(db_e)}")
            return jsonify({'message': 'Database error after file system error'}), 500
    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error deleting media {image_id}: {str(e)}")
        return jsonify({'message': 'Unknown server error: ' + str(e)}), 500

# Delete multiple room media at once (Admin)
@roomimage_bp.route('/admin/rooms/<int:room_id>/images/batch', methods=['DELETE'])
@admin_required()
def delete_room_images_batch(room_id):
    try:
        logger.info(f"Attempting to delete multiple media for room {room_id}")
        
        # Get image_ids from request body
        data = request.get_json()
        if not data or 'imageIds' not in data:
            logger.warning("No imageIds provided for batch deletion")
            return jsonify({'message': 'No imageIds provided'}), 400

        image_ids = data.get('imageIds', [])
        if not isinstance(image_ids, list) or not image_ids:
            logger.warning("Invalid or empty imageIds list")
            return jsonify({'message': 'Invalid or empty imageIds list'}), 400

        # Check room
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Room not found'}), 404

        # Check area
        area = Area.query.get(room.area_id)
        if not area:
            logger.warning(f"Area {room.area_id} not found")
            return jsonify({'message': 'Area not found for room'}), 404

        # Query all media to delete
        media_items = RoomImage.query.filter(
            RoomImage.image_id.in_(image_ids),
            RoomImage.room_id == room_id,
            RoomImage.is_deleted == False
        ).all()

        if not media_items:
            logger.warning(f"No valid media found for deletion in room {room_id}")
            return jsonify({'message': 'No valid media found to delete'}), 404

        if len(media_items) != len(image_ids):
            logger.warning(f"Some image IDs are invalid or already deleted: {image_ids}")

        # Mark as soft deleted and move files
        roomname = f"{room.name} - {area.name}"
        logger.info(f"Room name: {room.name}, Area name: {area.name}, Combined: {roomname}")
        roomname = normalize_name(roomname)
        logger.info(f"Normalized roomname: {roomname}")

        trash_folder = os.path.join(current_app.config['UPLOAD_BASE'], 'trash', 'roomimage', roomname)
        logger.info(f"Creating trash folder: {trash_folder}")
        os.makedirs(trash_folder, exist_ok=True)

        for media in media_items:
            media.is_deleted = True
            media.deleted_at = datetime.utcnow()
            logger.info(f"Marked media {media.image_id} as soft deleted for room {room_id}")

            absolute_path = os.path.join(current_app.config['ROOM_IMAGES_BASE'], media.image_url)
            logger.info(f"Absolute path of media: {absolute_path}")
            if os.path.exists(absolute_path):
                trash_filename = f"{uuid.uuid4().hex}_{media.image_url}"
                trash_path = os.path.join(trash_folder, trash_filename)
                logger.info(f"Renaming {absolute_path} to {trash_path}")
                os.rename(absolute_path, trash_path)
                logger.info(f"Moved media {media.image_url} to trash: {trash_path}")
            else:
                logger.warning(f"Media file not found: {absolute_path}")

        db.session.commit()
        logger.info(f"Soft deleted {len(media_items)} media for room {room_id}")
        return '', 204

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error deleting media for room {room_id}: {str(e)}")
        return jsonify({'message': 'Database error deleting media'}), 500
    except OSError as e:
        logger.error(f"File system error deleting media for room {room_id}: {str(e)}")
        try:
            db.session.commit()
            logger.info(f"Soft deleted media for room {room_id} despite file system error")
            return '', 204
        except SQLAlchemyError as db_e:
            db.session.rollback()
            logger.error(f"Database error after file system error: {str(db_e)}")
            return jsonify({'message': 'Database error after file system error'}), 500
    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error deleting media for room {room_id}: {str(e)}")
        return jsonify({'message': 'Unknown server error: ' + str(e)}), 500

# Reorder room media (Admin)
@roomimage_bp.route('/admin/rooms/<int:room_id>/images/reorder', methods=['POST'])
@admin_required()
def reorder_room_images(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Room not found'}), 404

        data = request.get_json()
        if not data or 'imageIds' not in data:
            logger.warning("No imageIds provided for reordering")
            return jsonify({'message': 'No imageIds provided'}), 400

        image_ids = data.get('imageIds', [])
        if not isinstance(image_ids, list):
            logger.warning("Invalid imageIds format")
            return jsonify({'message': 'imageIds must be a list'}), 400

        if not image_ids:
            logger.warning("Empty imageIds list")
            return jsonify({'message': 'Empty imageIds list'}), 400

        media = RoomImage.query.filter(
            RoomImage.image_id.in_(image_ids),
            RoomImage.room_id == room_id,
            RoomImage.is_deleted == False
        ).all()
        if len(media) != len(image_ids):
            logger.warning(f"Invalid or deleted media IDs provided: {image_ids}")
            return jsonify({'message': 'One or more image_id invalid, deleted, or not in room'}), 400

        media_map = {img.image_id: img for img in media}
        for sort_order, image_id in enumerate(image_ids):
            media_item = media_map.get(image_id)
            if media_item:
                media_item.sort_order = sort_order

        db.session.commit()
        logger.info(f"Reordered media for room {room_id}")
        return jsonify({'message': 'Media reordered successfully'}), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error reordering media for room {room_id}: {str(e)}")
        return jsonify({'message': 'Database error reordering media'}), 500
    except ValueError as e:
        logger.error(f"Value error reordering media for room {room_id}: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error reordering media for room {room_id}: {str(e)}")
        return jsonify({'message': 'Unknown server error'}), 500