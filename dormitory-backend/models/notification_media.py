from extensions import db

class NotificationMedia(db.Model):
    __tablename__ = 'notification_media'
    media_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    notification_id = db.Column(db.BigInteger, db.ForeignKey('notification.id', ondelete='CASCADE'), nullable=False)
    media_url = db.Column(db.String(512), nullable=False)
    alt_text = db.Column(db.String(255), nullable=True)
    uploaded_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.SmallInteger, default=0, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.TIMESTAMP, nullable=True)
    file_type = db.Column(db.String(10), default='image', nullable=False)
    file_size = db.Column(db.BigInteger, nullable=True, comment='Kích thước file (bytes)')



    def to_dict(self):
        return {
            'media_id': self.media_id,
            'notification_id': self.notification_id,
            'media_url': self.media_url,
            'alt_text': self.alt_text,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'is_primary': self.is_primary,
            'sort_order': self.sort_order,
            'is_deleted': self.is_deleted,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'file_type': self.file_type,
            'file_size': self.file_size
        }