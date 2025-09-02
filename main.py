import threading
import time
from app import app
from media_scanner import MediaScanner
from file_watcher import FileWatcher
from media_processor import MediaProcessor
from config_manager import ConfigManager

def start_background_services():
    """Start background services for media scanning and processing"""
    config_manager = ConfigManager()
    media_scanner = MediaScanner()
    file_watcher = FileWatcher()
    media_processor = MediaProcessor()
    
    # Start media processor
    processor_thread = threading.Thread(target=media_processor.start_processing, daemon=True)
    processor_thread.start()
    
    # Start file watcher
    watcher_thread = threading.Thread(target=file_watcher.start_watching, daemon=True)
    watcher_thread.start()
    
    # Start initial scan after a short delay
    def delayed_scan():
        time.sleep(2)  # Give the app time to start
        media_scanner.start_initial_scan()
    
    scan_thread = threading.Thread(target=delayed_scan, daemon=True)
    scan_thread.start()

import os
if __name__ == "__main__" or os.environ.get("RUN_THREADS", "").lower() in ["true", "1", "yes"]:
    start_background_services()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
