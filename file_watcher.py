import os
import logging
import time
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from app import app, db
from models import MediaFolder, MediaFile
from media_scanner import MediaScanner

logger = logging.getLogger(__name__)

class MediaFileHandler(FileSystemEventHandler):
    def __init__(self, media_scanner):
        self.media_scanner = media_scanner
        self.supported_extensions = {
            '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m4v', '.webm', 
            '.ts', '.mts', '.m2ts', '.vob', '.mpg', '.mpeg', '.3gp', '.asf'
        }
        # Debounce mechanism to avoid multiple events for the same file
        self.pending_files = {}
        self.debounce_delay = 2  # seconds
    
    def on_created(self, event):
        if not event.is_directory:
            self._handle_file_event(event.src_path, 'created')
    
    def on_modified(self, event):
        if not event.is_directory:
            self._handle_file_event(event.src_path, 'modified')
    
    def on_deleted(self, event):
        if not event.is_directory:
            self._handle_file_event(event.src_path, 'deleted')
    
    def on_moved(self, event):
        if not event.is_directory:
            self._handle_file_event(event.dest_path, 'moved')
            self._handle_file_event(event.src_path, 'deleted')
    
    def _handle_file_event(self, file_path, event_type):
        """Handle file system events with debouncing"""
        # Check if file has supported extension
        if os.path.splitext(file_path)[1].lower() not in self.supported_extensions:
            return
        
        # Debounce: delay processing to avoid multiple events for the same file
        if file_path in self.pending_files:
            # Cancel previous timer
            self.pending_files[file_path].cancel()
        
        # Create new timer
        timer = threading.Timer(
            self.debounce_delay, 
            self._process_file_event, 
            args=(file_path, event_type)
        )
        timer.start()
        self.pending_files[file_path] = timer
    
    def _process_file_event(self, file_path, event_type):
        """Process the file event after debounce delay"""
        try:
            # Remove from pending files
            if file_path in self.pending_files:
                del self.pending_files[file_path]
            
            logger.info(f"Processing file event: {event_type} - {file_path}")
            
            with app.app_context():
                if event_type == 'deleted':
                    # Remove file from database
                    media_file = MediaFile.query.filter_by(file_path=file_path).first()
                    if media_file:
                        db.session.delete(media_file)
                        db.session.commit()
                        logger.info(f"Removed deleted file from database: {file_path}")
                
                elif event_type in ['created', 'modified', 'moved']:
                    # Check if file exists and is accessible
                    if os.path.exists(file_path):
                        try:
                            # Wait a bit to ensure file is fully written
                            time.sleep(1)
                            
                            # Find the folder this file belongs to
                            folder = self._find_folder_for_file(file_path)
                            if folder:
                                # Rescan the file
                                self.media_scanner.rescan_file(file_path)
                            else:
                                logger.warning(f"File {file_path} is not in any configured folder")
                        
                        except Exception as e:
                            logger.error(f"Error processing file {file_path}: {e}")
        
        except Exception as e:
            logger.error(f"Error in file event processing: {e}")
    
    def _find_folder_for_file(self, file_path):
        """Find which configured folder contains this file"""
        folders = MediaFolder.query.filter_by(is_active=True).all()
        
        for folder in folders:
            if file_path.startswith(folder.path):
                return folder
        
        return None

class FileWatcher:
    def __init__(self):
        self.observer = Observer()
        self.media_scanner = MediaScanner()
        self.watching = False
    
    def start_watching(self):
        """Start watching all configured media folders"""
        logger.info("Starting file watcher...")
        
        try:
            with app.app_context():
                # Get all active folders
                folders = MediaFolder.query.filter_by(is_active=True).all()
                
                if not folders:
                    logger.info("No folders configured for watching")
                    return
                
                # Create event handler
                event_handler = MediaFileHandler(self.media_scanner)
                
                # Watch each folder
                for folder in folders:
                    if os.path.exists(folder.path):
                        self.observer.schedule(
                            event_handler, 
                            folder.path, 
                            recursive=True
                        )
                        logger.info(f"Watching folder: {folder.path}")
                    else:
                        logger.warning(f"Folder does not exist: {folder.path}")
                
                # Start observer
                self.observer.start()
                self.watching = True
                
                try:
                    while self.watching:
                        time.sleep(1)
                except KeyboardInterrupt:
                    logger.info("File watcher interrupted")
                
        except Exception as e:
            logger.error(f"Error in file watcher: {e}")
        
        finally:
            self.stop_watching()
    
    def stop_watching(self):
        """Stop the file watcher"""
        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
        self.watching = False
        logger.info("File watcher stopped")
    
    def restart_watching(self):
        """Restart the file watcher (useful when folders are added/removed)"""
        logger.info("Restarting file watcher...")
        self.stop_watching()
        time.sleep(1)
        
        # Start in a new thread
        watch_thread = threading.Thread(target=self.start_watching, daemon=True)
        watch_thread.start()
