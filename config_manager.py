import logging
from app import app, db
from models import AppSettings

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self):
        self._initialize_default_settings()
    
    def _initialize_default_settings(self):
        """Initialize default application settings"""
        default_settings = {
            'max_concurrent_jobs': {
                'value': '1',
                'description': 'Maximum number of concurrent media processing jobs'
            },
            'scan_interval': {
                'value': '3600',
                'description': 'Interval in seconds for periodic media scanning'
            },
            'temp_directory': {
                'value': '/tmp',
                'description': 'Directory for temporary files during processing'
            },
            'backup_original_files': {
                'value': 'true',
                'description': 'Create backup copies of original files before processing'
            },
            'auto_detect_language': {
                'value': 'true',
                'description': 'Automatically detect track languages when possible'
            },
            'default_audio_language': {
                'value': 'und',
                'description': 'Default language code for audio tracks'
            },
            'default_subtitle_language': {
                'value': 'und',
                'description': 'Default language code for subtitle tracks'
            }
        }
        
        try:
            with app.app_context():
                for key, config in default_settings.items():
                    existing = AppSettings.query.filter_by(key=key).first()
                    if not existing:
                        setting = AppSettings()
                        setting.key = key
                        setting.value = config['value']
                        setting.description = config['description']
                        db.session.add(setting)
                
                db.session.commit()
        
        except Exception as e:
            logger.error(f"Error initializing default settings: {e}")
    
    def get_setting(self, key, default_value=None):
        """Get a setting value"""
        try:
            with app.app_context():
                setting = AppSettings.query.filter_by(key=key).first()
                if setting:
                    return setting.value
                return default_value
        
        except Exception as e:
            logger.error(f"Error getting setting {key}: {e}")
            return default_value
    
    def set_setting(self, key, value, description=None):
        """Set a setting value"""
        try:
            with app.app_context():
                setting = AppSettings.query.filter_by(key=key).first()
                if setting:
                    setting.value = value
                    if description:
                        setting.description = description
                else:
                    setting = AppSettings()
                    setting.key = key
                    setting.value = value
                    setting.description = description or ''
                    db.session.add(setting)
                
                db.session.commit()
                return True
        
        except Exception as e:
            logger.error(f"Error setting {key}: {e}")
            return False
    
    def get_all_settings(self):
        """Get all settings as a dictionary"""
        try:
            with app.app_context():
                settings = AppSettings.query.all()
                return {
                    setting.key: {
                        'value': setting.value,
                        'description': setting.description
                    }
                    for setting in settings
                }
        
        except Exception as e:
            logger.error(f"Error getting all settings: {e}")
            return {}