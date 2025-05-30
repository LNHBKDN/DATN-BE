# models/notification.py
from extensions import db
from datetime import datetime

class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    # type_id = db.Column(db.Integer, db.ForeignKey('notificationtype.id', ondelete='SET NULL'), nullable=True)  # Đã sửa nullable=True
    target_type = db.Column(db.Enum('ALL', 'ROOM', 'USER', 'SYSTEM'), nullable=False)
    target_id = db.Column(db.BigInteger, nullable=True)
    related_entity_type = db.Column(db.String(50), nullable=True)
    related_entity_id = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    media = db.relationship('NotificationMedia', backref='notification_ref', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'message': self.message,
            # 'type_id': self.type_id,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'related_entity_type': self.related_entity_type,
            'related_entity_id': self.related_entity_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'media': [m.to_dict() for m in self.media if not m.is_deleted] if self.media else []
        }