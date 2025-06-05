from extensions import db
from datetime import datetime

class NotificationRecipient(db.Model):
    __tablename__ = 'notification_recipients'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    notification_id = db.Column(db.BigInteger, db.ForeignKey('notification.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    read_at = db.Column(db.TIMESTAMP, nullable=True, comment="NULL when is_read=False; set to timestamp when is_read=True")
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.TIMESTAMP, nullable=True)
    # relationships
    notification = db.relationship('Notification', backref='recipients', lazy=True)
    user = db.relationship('User', backref='notifications', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'notification_id': self.notification_id,
            'user_id': self.user_id,
            'is_read': self.is_read,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'is_deleted': self.is_deleted,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            # relationships
            'notification_details': self.notification.to_dict() if self.notification else None,
            'user_details': self.user.to_dict() if self.user else None
        }