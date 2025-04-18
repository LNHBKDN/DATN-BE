from extensions import db

class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('notificationType.id', ondelete='RESTRICT'), nullable=False)
    target_type = db.Column(db.Enum('ALL', 'ROOM', 'USER'), nullable=False)
    target_id = db.Column(db.BigInteger, nullable=True)
    related_entity_type = db.Column(db.String(50), nullable=True)
    related_entity_id = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.TIMESTAMP, nullable=True)
    # relationships
    notification_type = db.relationship('NotificationType', backref='notifications', lazy=True)
    media = db.relationship('NotificationMedia', backref='notification_ref', lazy=True, cascade='all, delete-orphan')
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'message': self.message,
            'type_id': self.type_id,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'related_entity_type': self.related_entity_type,
            'related_entity_id': self.related_entity_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            # relationships
            'notification_type': self.notification_type.to_dict() if self.notification_type else None,
            'media': [m.to_dict() for m in self.media if not m.is_deleted] if self.media else []
        }