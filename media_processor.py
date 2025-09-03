import os
import logging
import threading
import time
import tempfile
import shutil
from datetime import datetime
from app import app, db
from models import ProcessingJob, MediaFile, AudioTrack, SubtitleTrack, AppSettings
from config_manager import ConfigManager
import ffmpeg, string

logger = logging.getLogger(__name__)

class MediaProcessor:
    def __init__(self):
        self.processing = False
        self.config_manager = ConfigManager()
        self.active_jobs = {}
    
    def start_processing(self):
        """Start the background processing loop"""
        logger.info("Starting media processor...")
        
        while True:
            try:
                with app.app_context():
                    # Get maximum concurrent jobs
                    max_jobs_setting = self.config_manager.get_setting('max_concurrent_jobs', '1')
                    max_jobs = int(max_jobs_setting) if max_jobs_setting else 1
                    
                    # Check how many jobs are currently processing
                    active_count = len(self.active_jobs)

                    # If nothing is active, requeue any "stuck" jobs
                    if active_count == 0:
                        stuck_jobs = ProcessingJob.query.filter_by(status='processing').all()
                        requeued = 0
                        for job in stuck_jobs:
                            if job.id not in self.active_jobs:
                                job.status = 'queued'
                                job.temp_file_path = None
                                job.started_at = None
                                requeued += 1
                        if requeued:
                            db.session.commit()
                            logger.warning(f"Requeued {requeued} stuck jobs")
                    
                    if active_count < max_jobs:
                        # Get next queued job
                        job = ProcessingJob.query.filter_by(status='queued').order_by(ProcessingJob.created_at).first()
                        
                        if job:
                            # Start processing in a separate thread
                            job_thread = threading.Thread(
                                target=self._process_job, 
                                args=(job.id,), 
                                daemon=True
                            )
                            job_thread.start()
                            self.active_jobs[job.id] = job_thread
                    
                    # Clean up completed threads
                    completed_jobs = [job_id for job_id, thread in self.active_jobs.items() if not thread.is_alive()]
                    for job_id in completed_jobs:
                        del self.active_jobs[job_id]
                
                # Wait before checking for new jobs
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                time.sleep(10)
    
    def _process_job(self, job_id):
        """Process a single job"""
        with app.app_context():
            job = ProcessingJob.query.get(job_id)
            if not job:
                return
            
            try:
                logger.info(f"Starting processing job {job_id} for file: {job.media_file.filename}")
                
                # Update job status
                job.status = 'processing'
                job.started_at = datetime.utcnow()
                job.progress = 0.0
                db.session.commit()
                
                # Process the media file
                self._process_media_file(job)
                
                # Mark job as completed
                job.status = 'completed'
                job.progress = 100.0
                job.completed_at = datetime.utcnow()
                job.media_file.process_status = 'completed'
                
                logger.info(f"Completed processing job {job_id}")
                
            except Exception as e:
                logger.error(f"Error processing job {job_id}: {e}")
                job.status = 'failed'
                job.error_message = str(e)
                job.media_file.process_status = 'error'
            
            finally:
                # Clean up temp file if it exists
                if job.temp_file_path and os.path.exists(job.temp_file_path):
                    try:
                        os.remove(job.temp_file_path)
                    except Exception as e:
                        logger.error(f"Error removing temp file: {e}")
                
                db.session.commit()
    
    def _process_media_file(self, job):
        """Process a media file with modified tracks"""
        media_file = job.media_file
        original_path = media_file.file_path
        
        # Check if there are any modifications to process
        audio_modifications = AudioTrack.query.filter_by(
            media_file_id=media_file.id, 
            is_modified=True
        ).all()
        
        subtitle_modifications = SubtitleTrack.query.filter_by(
            media_file_id=media_file.id, 
            is_modified=True
        ).all()
        
        if not audio_modifications and not subtitle_modifications:
            logger.info(f"No modifications found for {media_file.filename}")
            return
        
        # Create temporary file
        temp_dir = tempfile.mkdtemp()
        temp_filename = f"processed_{sanitize_filename(media_file.filename)}"
        temp_path = os.path.join(temp_dir, temp_filename)

        job.temp_file_path = temp_path
        db.session.commit()
        
        try:
            command = ["ffmpeg", "-i", original_path]

            # Add stream mapping and codecs for all tracks
            command.extend(["-c:v", "copy", "-map", "0:v:0"])

            # Add metadata for modified audio tracks
            for audio_track in media_file.audio_tracks:
                track_index = audio_track.track_index
                command.extend(["-map", f"0:a:{track_index}"])
                if audio_track.is_modified:
                    if audio_track.new_title:
                        command.extend([f'-metadata:s:a:{track_index}', f'title={audio_track.new_title}'])
                    if audio_track.new_language:
                        iso_lang = to_iso639_2(audio_track.new_language)
                        command.extend([f'-metadata:s:a:{track_index}', f'language={iso_lang}'])

            # Add metadata for modified subtitle tracks
            for subtitle_track in media_file.subtitle_tracks:
                track_index = subtitle_track.track_index
                command.extend(["-map", f"0:s:{track_index}"])
                if subtitle_track.is_modified:
                    if subtitle_track.new_title:
                        command.extend([f'-metadata:s:s:{track_index}', f'title={subtitle_track.new_title}'])
                    if subtitle_track.new_language:
                        iso_lang = to_iso639_2(subtitle_track.new_language)
                        command.extend([f'-metadata:s:s:{track_index}', f'language={iso_lang}'])
            
            command.extend([temp_path, "-y"])

            # Run ffmpeg with progress tracking
            self._run_ffmpeg_with_progress(command, job)
            
            # Verify the output file was created successfully
            if not os.path.exists(temp_path):
                raise Exception("Output file was not created")
            
            # Create backup of original file
            backup_path = f"{original_path}.backup"
            shutil.copy2(original_path, backup_path)
            
            # Replace original file with processed file
            shutil.move(temp_path, original_path)
            
            # Remove backup if successful
            if os.path.exists(backup_path):
                os.remove(backup_path)
            
            # Update track modification flags
            for audio_track in audio_modifications:
                audio_track.is_modified = False
            
            for subtitle_track in subtitle_modifications:
                subtitle_track.is_modified = False
            
            db.session.commit()
            
        finally:
            # Clean up temp directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def _run_ffmpeg_with_progress(self, cmd, job):
        """Run ffmpeg command with progress tracking"""
        import subprocess
        import re
        from collections import deque
        
        # Get total duration for progress calculation
        duration = job.media_file.duration or 0
        
        # Run process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )

        last_lines = deque(maxlen=20)
        
        # Track progress
        stdout = process.stdout
        if stdout:
            for raw_line in iter(stdout.readline, b''):
                # decode manually
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("latin-1", errors="replace")

                logger.debug(f"FFmpeg: {line.strip()}")
                last_lines.append(line.strip())

                time_match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                if time_match and duration > 0:
                    hours = int(time_match.group(1))
                    minutes = int(time_match.group(2))
                    seconds = int(time_match.group(3))

                    current_time = hours * 3600 + minutes * 60 + seconds
                    progress = min(95.0, (current_time / duration) * 100)

                    job.progress = progress
                    db.session.commit()
        
        # Wait for process to complete
        return_code = process.wait()
        
        if return_code != 0:
            error_output = "\n".join(last_lines)
            raise Exception(
                f"FFmpeg failed with return code {return_code}\n"
                f"Last lines of output:\n{error_output}"
            )


def sanitize_filename(name):
    valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
    return "".join(c if c in valid_chars else "_" for c in name)

import pycountry
def to_iso639_2(lang_key: str) -> str:
    """
    Convert a language identifier (name or any ISO code) to ISO 639-2/T alpha-3 code.
    Returns 'und' if the language cannot be determined.
    """
    if not lang_key:
        return "und"

    lang_key = lang_key.strip().lower()

    # Try to lookup by name or any code
    try:
        lang = pycountry.languages.lookup(lang_key)
        if hasattr(lang, "alpha_3"):
            return lang.alpha_3
        elif hasattr(lang, "bibliographic"):
            return lang.bibliographic
    except LookupError:
        return "und"

    return "und"