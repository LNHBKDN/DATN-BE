from extensions import db
from datetime import datetime

class ReportImage(db.Model):
    __tablename__ = 'reportImage'
    image_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    report_id = db.Column(db.BigInteger, db.ForeignKey('reports.report_id'), nullable=True)  # Xóa ondelete='CASCADE', đặt nullable=True
    image_url = db.Column(db.String(512), nullable=False)
    alt_text = db.Column(db.String(255), nullable=True)
    uploaded_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=True)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.SmallInteger, default=0, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.TIMESTAMP, nullable=True)
    file_type = db.Column(db.String(10), nullable=False, default='image')

    report = db.relationship('Report', backref='images', lazy=True)

    def to_dict(self):
        return {
            'image_id': self.image_id,
            'report_id': self.report_id,
            'image_url': self.image_url,
            'alt_text': self.alt_text,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'is_primary': self.is_primary,
            'sort_order': self.sort_order,
            'is_deleted': self.is_deleted,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'file_type': self.file_type,
            'report_details': self.report.to_dict() if self.report else None
        }