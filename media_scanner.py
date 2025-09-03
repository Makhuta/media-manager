import os
import logging
import time
import threading
from datetime import datetime
from app import app, db
from models import MediaFolder, MediaFile, AudioTrack, SubtitleTrack, ProcessingJob
import ffmpeg
from pathlib import Path

logger = logging.getLogger(__name__)

class MediaScanner:
    def __init__(self):
        self.scanning = False
        self.scan_thread = None
        self.supported_extensions = {
            '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m4v', '.webm', 
            '.ts', '.mts', '.m2ts', '.vob', '.mpg', '.mpeg', '.3gp', '.asf'
        }
    
    def start_initial_scan(self):
        """Start the initial media scan"""
        if self.scanning:
            logger.info("Scan already in progress")
            return
        
        self.scan_thread = threading.Thread(target=self._scan_all_folders, daemon=True)
        self.scan_thread.start()
    
    def _scan_all_folders(self):
        """Scan all configured media folders"""
        self.scanning = True
        logger.info("Starting media scan...")
        
        try:
            with app.app_context():
                folders = MediaFolder.query.filter_by(is_active=True).all()
                
                for folder in folders:
                    logger.info(f"Scanning folder: {folder.path}")
                    self._scan_folder(folder)
                    folder.last_scanned = datetime.utcnow()
                    db.session.commit()
                
                logger.info("Media scan completed")
        
        except Exception as e:
            logger.error(f"Error during media scan: {e}")
        
        finally:
            self.scanning = False
    
    def _scan_folder(self, folder):
        """Scan a specific folder for media files"""
        try:
            folder_path = Path(folder.path)
            if not folder_path.exists():
                logger.warning(f"Folder does not exist: {folder.path}")
                return
            
            existing_files_in_folder = set()

            # Walk through files on disk
            for root, dirs, files in os.walk(folder.path):
                for file in files:
                    file_path = os.path.join(root, file)

                    # Check extension
                    if Path(file).suffix.lower() not in self.supported_extensions:
                        continue

                    existing_files_in_folder.add(file_path)

                    # See if it exists in DB
                    existing_file = MediaFile.query.filter_by(file_path=file_path).first()
                    if existing_file:
                        # Check if file was modified
                        file_stat = os.stat(file_path)
                        file_modified = datetime.fromtimestamp(file_stat.st_mtime)

                        if existing_file.file_modified and existing_file.file_modified >= file_modified:
                            continue  # File hasn't changed

                    # (Re)scan the media file
                    self._scan_media_file(folder, file_path)

                    # Small delay to prevent system overload
                    time.sleep(0.1)

            # Cleanup DB entries for missing files
            media_files_in_db = MediaFile.query.filter_by(folder_id=folder.id).all()
            for media_file in media_files_in_db:
                if media_file.file_path not in existing_files_in_folder:
                    # Skip deletion if there’s an active processing job
                    active_job = ProcessingJob.query.filter_by(
                        media_file_id=media_file.id, status="processing"
                    ).first()
                    if active_job:
                        logger.info(
                            f"Skipping deletion of {media_file.file_path} "
                            f"because job {active_job.id} is still processing"
                        )
                        continue

                    logger.info(f"Deleting missing file from DB: {media_file.file_path}")

                    # Delete related tracks first
                    AudioTrack.query.filter_by(media_file_id=media_file.id).delete()
                    SubtitleTrack.query.filter_by(media_file_id=media_file.id).delete()
                    ProcessingJob.query.filter_by(media_file_id=media_file.id).delete()

                    # Delete the MediaFile itself
                    db.session.delete(media_file)

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error scanning folder {folder.path}: {e}", exc_info=True)

    
    def _scan_media_file(self, folder, file_path):
        """Scan a specific media file and extract metadata"""
        try:
            logger.debug(f"Scanning file: {file_path}")
            
            # Get file statistics
            file_stat = os.stat(file_path)
            file_size = file_stat.st_size
            file_modified = datetime.fromtimestamp(file_stat.st_mtime)
            filename = os.path.basename(file_path)
            
            # Check if file already exists
            media_file = MediaFile.query.filter_by(file_path=file_path).first()
            if not media_file:
                media_file = MediaFile()
                media_file.folder_id = folder.id
                media_file.file_path = file_path
                media_file.filename = filename
                db.session.add(media_file)
            
            # Update file information
            media_file.file_size = file_size
            media_file.file_modified = file_modified
            media_file.scan_status = 'scanning'
            db.session.commit()
            
            # Extract media information using ffmpeg
            try:
                probe = ffmpeg.probe(file_path)
                
                # Get video stream info
                video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
                if video_stream:
                    media_file.duration = float(probe['format'].get('duration', 0))
                    media_file.video_codec = video_stream.get('codec_name', '')
                    width = video_stream.get('width', 0)
                    height = video_stream.get('height', 0)
                    if width and height:
                        media_file.resolution = f"{width}x{height}"
                
                # Determine media type and extract title information
                media_file.media_type, media_file.title, media_file.series_name, media_file.season_number, media_file.episode_number = self._classify_media(filename, file_path)
                
                # Clear existing tracks
                AudioTrack.query.filter_by(media_file_id=media_file.id).delete()
                SubtitleTrack.query.filter_by(media_file_id=media_file.id).delete()
                
                # Extract audio tracks
                audio_tracks = [stream for stream in probe['streams'] if stream['codec_type'] == 'audio']
                for i, audio_stream in enumerate(audio_tracks):
                    audio_track = AudioTrack()
                    audio_track.media_file_id = media_file.id
                    audio_track.track_index = i
                    audio_track.original_title = audio_stream.get('tags', {}).get('title', '')
                    audio_track.original_language = audio_stream.get('tags', {}).get('language', '')
                    audio_track.codec = audio_stream.get('codec_name', '')
                    audio_track.channels = audio_stream.get('channels', 0)
                    audio_track.sample_rate = audio_stream.get('sample_rate', 0)
                    db.session.add(audio_track)
                
                # Extract subtitle tracks
                subtitle_tracks = [stream for stream in probe['streams'] if stream['codec_type'] == 'subtitle']
                for i, subtitle_stream in enumerate(subtitle_tracks):
                    subtitle_track = SubtitleTrack()
                    subtitle_track.media_file_id = media_file.id
                    subtitle_track.track_index = i
                    subtitle_track.original_title = subtitle_stream.get('tags', {}).get('title', '')
                    subtitle_track.original_language = subtitle_stream.get('tags', {}).get('language', '')
                    subtitle_track.codec = subtitle_stream.get('codec_name', '')
                    subtitle_track.is_forced = subtitle_stream.get('disposition', {}).get('forced', 0) == 1
                    subtitle_track.is_default = subtitle_stream.get('disposition', {}).get('default', 0) == 1
                    db.session.add(subtitle_track)
                
                media_file.scan_status = 'completed'
                media_file.error_message = None
                
            except Exception as e:
                logger.error(f"Error probing file {file_path}: {e}")
                media_file.scan_status = 'error'
                media_file.error_message = str(e)
            
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Error scanning media file {file_path}: {e}")
    
    def _classify_media(self, filename, file_path):
        """Classify media as movie or TV show and extract metadata"""
        import re
        
        # Remove file extension
        name = os.path.splitext(filename)[0]
        
        # Common TV show patterns
        tv_patterns = [
            r'(.+?)\s?-\s?S(\d+)E(\d+)',  # Series - S01E01
            r'(.+?)\s?-\s?(\d+)x(\d+)',   # Series - 1x01
            r'(.+?)\s?-\s?Season[\s\.](\d+)[\s\.]Episode[\s\.](\d+)',  # Series Season 1 Episode 01
        ]
        
        for pattern in tv_patterns:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                series_name = match.group(1).replace('.', ' ').replace('_', ' ').strip()
                season_number = int(match.group(2))
                episode_number = int(match.group(3))
                title = f"{series_name} S{season_number:02d}E{episode_number:02d}"
                return 'tv', title, series_name, season_number, episode_number
        
        # If no TV pattern matches, classify as movie
        title = name.replace('.', ' ').replace('_', ' ').strip()
        # Clean up common movie patterns
        title = re.sub(r'\b(19|20)\d{2}\b', '', title)  # Remove years
        title = re.sub(r'\b(720p|1080p|4K|BluRay|DVDRip|WEBRip|x264|x265|HEVC)\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s+', ' ', title).strip()
        
        return 'movie', title, None, None, None

    def rescan_file(self, file_path):
        """Rescan a specific file"""
        try:
            with app.app_context():
                media_file = MediaFile.query.filter_by(file_path=file_path).first()
                if media_file:
                    folder = media_file.folder
                    self._scan_media_file(folder, file_path)
                    logger.info(f"Rescanned file: {file_path}")
        except Exception as e:
            logger.error(f"Error rescanning file {file_path}: {e}")
