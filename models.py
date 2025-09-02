from app import db
from datetime import datetime
from sqlalchemy import Index

class MediaFolder(db.Model):
    __tablename__ = 'media_folders'
    
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(500), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_scanned = db.Column(db.DateTime)
    
    # Relationship to media files
    media_files = db.relationship('MediaFile', backref='folder', lazy=True, cascade='all, delete-orphan')

class MediaFile(db.Model):
    __tablename__ = 'media_files'
    
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('media_folders.id'), nullable=False)
    file_path = db.Column(db.String(1000), nullable=False, unique=True)
    filename = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.BigInteger)
    file_modified = db.Column(db.DateTime)
    
    # Media type classification
    media_type = db.Column(db.String(20))  # 'movie' or 'tv'
    title = db.Column(db.String(500))
    series_name = db.Column(db.String(500))  # For TV shows
    season_number = db.Column(db.Integer)    # For TV shows
    episode_number = db.Column(db.Integer)   # For TV shows
    
    # Media information
    duration = db.Column(db.Float)
    video_codec = db.Column(db.String(50))
    resolution = db.Column(db.String(20))
    
    # Processing status
    scan_status = db.Column(db.String(20), default='pending')  # pending, scanning, completed, error
    process_status = db.Column(db.String(20), default='none')  # none, queued, processing, completed, error
    error_message = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    audio_tracks = db.relationship('AudioTrack', backref='media_file', lazy=True, cascade='all, delete-orphan')
    subtitle_tracks = db.relationship('SubtitleTrack', backref='media_file', lazy=True, cascade='all, delete-orphan')
    
    # Index for faster queries
    __table_args__ = (
        Index('idx_media_type_series', 'media_type', 'series_name'),
        Index('idx_scan_status', 'scan_status'),
        Index('idx_process_status', 'process_status'),
    )

class AudioTrack(db.Model):
    __tablename__ = 'audio_tracks'
    
    id = db.Column(db.Integer, primary_key=True)
    media_file_id = db.Column(db.Integer, db.ForeignKey('media_files.id'), nullable=False)
    track_index = db.Column(db.Integer, nullable=False)
    
    # Original track information
    original_title = db.Column(db.String(200))
    original_language = db.Column(db.String(10))
    codec = db.Column(db.String(50))
    channels = db.Column(db.Integer)
    sample_rate = db.Column(db.Integer)
    
    # User modifications
    new_title = db.Column(db.String(200))
    new_language = db.Column(db.String(10))
    is_modified = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SubtitleTrack(db.Model):
    __tablename__ = 'subtitle_tracks'
    
    id = db.Column(db.Integer, primary_key=True)
    media_file_id = db.Column(db.Integer, db.ForeignKey('media_files.id'), nullable=False)
    track_index = db.Column(db.Integer, nullable=False)
    
    # Original track information
    original_title = db.Column(db.String(200))
    original_language = db.Column(db.String(10))
    codec = db.Column(db.String(50))
    is_forced = db.Column(db.Boolean, default=False)
    is_default = db.Column(db.Boolean, default=False)
    
    # User modifications
    new_title = db.Column(db.String(200))
    new_language = db.Column(db.String(10))
    is_modified = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ProcessingJob(db.Model):
    __tablename__ = 'processing_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    media_file_id = db.Column(db.Integer, db.ForeignKey('media_files.id'), nullable=False)
    status = db.Column(db.String(20), default='queued')  # queued, processing, completed, failed
    progress = db.Column(db.Float, default=0.0)
    error_message = db.Column(db.Text)
    temp_file_path = db.Column(db.String(1000))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    
    # Relationship
    media_file = db.relationship('MediaFile', backref='processing_jobs')

class AppSettings(db.Model):
    __tablename__ = 'app_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)