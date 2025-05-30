# models/notification_type.py
from extensions import db
from datetime import datetime

class NotificationType(db.Model):
    __tablename__ = 'notificationtype'  # Sửa để khớp với tên bảng trong cơ sở dữ liệu

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='ROOM')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # # Thêm mối quan hệ ngược với Notification
    # notifications = db.relationship('Notification', back_populates='notification_type', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }