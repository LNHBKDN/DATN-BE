from extensions import db

class RoomImage(db.Model):
    __tablename__ = 'roomimage'
    image_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id'), nullable=True)
    image_url = db.Column(db.String(512), nullable=False)
    alt_text = db.Column(db.String(255), nullable=True)
    is_primary = db.Column(db.Boolean, default=False, nullable=True)
    sort_order = db.Column(db.SmallInteger, default=0, nullable=True)
    uploaded_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    file_type = db.Column(db.String(10), nullable=False, default='image')  # 'image' hoặc 'video'
    file_size = db.Column(db.BigInteger, nullable=True)  # Kích thước file (bytes)
    room = db.relationship('Room', backref='images', lazy=True)

    def to_dict(self):
        return {
            'image_id': self.image_id,
            'room_id': self.room_id,
            'image_url': self.image_url,
            'alt_text': self.alt_text,
            'is_primary': self.is_primary,
            'sort_order': self.sort_order,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'is_deleted': self.is_deleted,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'file_type': self.file_type,
            'file_size': self.file_size,
            'room_details': self.room.to_dict() if self.room else None
        }