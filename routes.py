from flask import render_template, request, jsonify, redirect, url_for, flash
from app import app, db
from models import MediaFolder, MediaFile, AudioTrack, SubtitleTrack, ProcessingJob, AppSettings
from config_manager import ConfigManager
from media_processor import MediaProcessor
import os
import logging, pycountry, langcodes

logger = logging.getLogger(__name__)
config_manager = ConfigManager()
media_processor = MediaProcessor()

# Language mappings for common languages
def build_language_dict_native():
    lang_dict = {}
    
    for lang in pycountry.languages:
        # Try to get any code
        codes = [getattr(lang, attr, None) for attr in ("alpha_2", "alpha_3", "bibliographic", "terminology")]
        codes = [c for c in codes if c]
        if not codes:
            continue
        
        # Get native name using langcodes
        try:
            native_name = langcodes.Language.get(codes[0]).display_name(codes[0])
        except Exception:
            native_name = getattr(lang, "name", codes[0])
        
        for code in codes:
            lang_dict[code] = str(native_name).title()
    
    return lang_dict

@app.route('/')
def index():
    """Main dashboard showing media library"""
    # Get filter parameters
    media_type = request.args.get('type', 'all')
    search_query = request.args.get('search', '')
    selected_language = request.args.get('language', '').strip()
    lang_mode = request.args.get('lang_mode', 'has')
    
    # Build query
    query = MediaFile.query.filter(MediaFile.scan_status == 'completed')
    
    if media_type != 'all':
        query = query.filter(MediaFile.media_type == media_type)
    
    if search_query:
        search_filter = f"%{search_query}%"
        query = query.filter(
            db.or_(
                MediaFile.title.like(search_filter),
                MediaFile.series_name.like(search_filter),
                MediaFile.filename.like(search_filter)
            )
        )
    
    # Language filter
    if selected_language:
        # Build subquery for files with the language
        audio_match = db.session.query(AudioTrack.media_file_id.label('media_file_id')).filter(
            db.or_(
                AudioTrack.original_language == selected_language,
                AudioTrack.new_language == selected_language
            )
        )
        subtitle_match = db.session.query(SubtitleTrack.media_file_id.label('media_file_id')).filter(
            db.or_(
                SubtitleTrack.original_language == selected_language,
                SubtitleTrack.new_language == selected_language
            )
        )
        match_ids = audio_match.union(subtitle_match).subquery()

        if lang_mode == 'has':
            query = query.filter(MediaFile.id.in_(db.select(match_ids.c.media_file_id)))
        else:  # 'not'
            query = query.filter(~MediaFile.id.in_(db.select(match_ids.c.media_file_id)))

    # Get movies
    movies = []
    if media_type in ['all', 'movie']:
        movies = query.filter(MediaFile.media_type == 'movie').order_by(MediaFile.title).all()
    
    # Get TV shows grouped by series
    tv_shows = {}
    if media_type in ['all', 'tv']:
        tv_files = query.filter(MediaFile.media_type == 'tv').order_by(
            MediaFile.series_name, MediaFile.season_number, MediaFile.episode_number
        ).all()
        
        for file in tv_files:
            if file.series_name not in tv_shows:
                tv_shows[file.series_name] = {}
            if file.season_number not in tv_shows[file.series_name]:
                tv_shows[file.series_name][file.season_number] = []
            tv_shows[file.series_name][file.season_number].append(file)
    
    # Get scanning progress
    total_files = MediaFile.query.count()
    scanned_files = MediaFile.query.filter(MediaFile.scan_status == 'completed').count()
    scanning_progress = (scanned_files / total_files * 100) if total_files > 0 else 100
    
    return render_template('index.html', 
                         movies=movies, 
                         tv_shows=tv_shows,
                         media_type=media_type,
                         search_query=search_query,
                         scanning_progress=scanning_progress,
                         language_options=build_language_dict_native(),
                         selected_language=selected_language,
                         lang_mode=lang_mode)

@app.route('/media/<int:media_id>')
def media_detail(media_id):
    """Show detailed view of a media file with track editing"""
    media_file = MediaFile.query.get_or_404(media_id)
    
    return render_template('media_detail.html', 
                         media_file=media_file, 
                         language_mappings=build_language_dict_native())

@app.route('/api/update_track', methods=['POST'])
def update_track():
    """Update audio or subtitle track information"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        track_type = data.get('track_type')  # 'audio' or 'subtitle'
        track_id = data.get('track_id')
        new_title = data.get('title', '').strip()
        new_language = data.get('language', '').strip()
        
        if track_type == 'audio':
            track = AudioTrack.query.get_or_404(track_id)
        elif track_type == 'subtitle':
            track = SubtitleTrack.query.get_or_404(track_id)
        else:
            return jsonify({'error': 'Invalid track type'}), 400
        
        # Update track information
        track.new_title = new_title if new_title else None
        track.new_language = new_language if new_language else None
        track.is_modified = True
        
        # Mark media file as needing processing
        media_file = track.media_file
        media_file.process_status = 'pending'
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Track updated successfully'})
    
    except Exception as e:
        logger.error(f"Error updating track: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue_processing/<int:media_id>', methods=['POST'])
def queue_processing(media_id):
    """Queue a media file for processing"""
    try:
        media_file = MediaFile.query.get_or_404(media_id)
        
        # Check if already queued or processing
        existing_job = ProcessingJob.query.filter(
            ProcessingJob.media_file_id == media_id,
            ProcessingJob.status.in_(['queued', 'processing'])
        ).first()
        
        if existing_job:
            return jsonify({'error': 'File is already queued or processing'}), 400
        
        # Create new processing job
        job = ProcessingJob()
        job.media_file_id = media_id
        db.session.add(job)
        
        # Update media file status
        media_file.process_status = 'queued'
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'File queued for processing'})
    
    except Exception as e:
        logger.error(f"Error queuing processing: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/settings')
def settings():
    """Settings page for managing folders and configuration"""
    folders = MediaFolder.query.all()
    settings = {
        setting.key: setting.value 
        for setting in AppSettings.query.all()
    }
    return render_template('settings.html', folders=folders, settings=settings)

@app.route('/api/add_folder', methods=['POST'])
def add_folder():
    """Add a new media folder"""
    try:
        path = request.form.get('path', '').strip()
        name = request.form.get('name', '').strip()
        
        if not path or not name:
            flash('Path and name are required', 'error')
            return redirect(url_for('settings'))
        
        if not os.path.exists(path):
            flash('Path does not exist', 'error')
            return redirect(url_for('settings'))
        
        # Check if folder already exists
        existing = MediaFolder.query.filter_by(path=path).first()
        if existing:
            flash('Folder already exists', 'error')
            return redirect(url_for('settings'))
        
        folder = MediaFolder()
        folder.path = path
        folder.name = name
        db.session.add(folder)
        db.session.commit()
        
        flash('Folder added successfully', 'success')
        return redirect(url_for('settings'))
    
    except Exception as e:
        logger.error(f"Error adding folder: {e}")
        flash(f'Error adding folder: {e}', 'error')
        return redirect(url_for('settings'))

@app.route('/api/remove_folder/<int:folder_id>', methods=['POST'])
def remove_folder(folder_id):
    """Remove a media folder"""
    try:
        folder = MediaFolder.query.get_or_404(folder_id)
        db.session.delete(folder)
        db.session.commit()
        
        flash('Folder removed successfully', 'success')
        return redirect(url_for('settings'))
    
    except Exception as e:
        logger.error(f"Error removing folder: {e}")
        flash(f'Error removing folder: {e}', 'error')
        return redirect(url_for('settings'))

@app.route('/api/update_settings', methods=['POST'])
def update_settings():
    """Update application settings"""
    try:
        for key, value in request.form.items():
            if key.startswith('setting_'):
                setting_key = key.replace('setting_', '')
                setting = AppSettings.query.filter_by(key=setting_key).first()
                if setting:
                    setting.value = value
                else:
                    setting = AppSettings()
                    setting.key = setting_key
                    setting.value = value
                    db.session.add(setting)
        
        db.session.commit()
        flash('Settings updated successfully', 'success')
        return redirect(url_for('settings'))
    
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        flash(f'Error updating settings: {e}', 'error')
        return redirect(url_for('settings'))

@app.route('/api/scan_progress')
def scan_progress():
    """Get current scanning progress"""
    total_files = MediaFile.query.count()
    scanned_files = MediaFile.query.filter(MediaFile.scan_status == 'completed').count()
    scanning_files = MediaFile.query.filter(MediaFile.scan_status == 'scanning').count()
    
    progress = (scanned_files / total_files * 100) if total_files > 0 else 100
    
    return jsonify({
        'total': total_files,
        'scanned': scanned_files,
        'scanning': scanning_files,
        'progress': progress
    })

@app.route('/api/processing_status')
def processing_status():
    """Get current processing status"""
    jobs = ProcessingJob.query.filter(
        ProcessingJob.status.in_(['queued', 'processing'])
    ).all()
    
    return jsonify([{
        'id': job.id,
        'media_file': job.media_file.filename,
        'status': job.status,
        'progress': job.progress
    } for job in jobs])

@app.route('/api/preview_audio/<int:media_id>/<int:track_index>')
def preview_audio(media_id, track_index):
    """Generate and serve a short audio preview for a specific track"""
    try:
        media_file = MediaFile.query.get_or_404(media_id)

        import tempfile
        import ffmpeg
        from flask import send_file, request

        # Read optional start time (in seconds) from query params
        start_time = request.args.get("start", default=30, type=int)
        if start_time < 0:
            start_time = 0

        # Create temporary file for audio snippet
        temp_audio = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        temp_audio.close()

        # Extract 10-second audio snippet from the specific track
        (
            ffmpeg
            .input(media_file.file_path, ss=start_time)  # Start time is now dynamic
            .output(
                temp_audio.name,
                map=f"0:a:{track_index}",  # Select specific audio track
                t=10,  # Duration: 10 seconds
                acodec="mp3",
                ab="128k",
            )
            .overwrite_output()
            .run(quiet=True)
        )

        return send_file(temp_audio.name, as_attachment=False, mimetype="audio/mpeg")

    except Exception as e:
        logger.error(f"Error generating audio preview: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/preview_subtitle/<int:media_id>/<int:track_index>')
def preview_subtitle(media_id, track_index):
    """Extract and return subtitle content sample for preview"""
    try:
        media_file = MediaFile.query.get_or_404(media_id)
        
        import tempfile
        import ffmpeg
        
        # Create temporary file for subtitle extraction
        temp_srt = tempfile.NamedTemporaryFile(suffix='.srt', delete=False, mode='w+', encoding='utf-8')
        temp_srt.close()
        
        # Extract subtitle track
        (
            ffmpeg
            .input(media_file.file_path, ss=60)  # Start at 60 seconds
            .output(
                temp_srt.name,
                map=f'0:s:{track_index}',  # Select specific subtitle track
                t=600,  # Duration: 10 minutes
                f='srt'  # SRT format
            )
            .overwrite_output()
            .run(quiet=True)
        )
        
        # Read and return subtitle content
        try:
            with open(temp_srt.name, 'r', encoding='utf-8') as f:
                subtitle_content = f.read()
        except UnicodeDecodeError:
            # Try with different encoding
            with open(temp_srt.name, 'r', encoding='latin-1') as f:
                subtitle_content = f.read()
        
        # Clean up
        os.unlink(temp_srt.name)
        
        # Return first few subtitle entries for preview
        lines = subtitle_content.split('\n')
        preview_lines = lines
        
        return jsonify({
            'content': '\n'.join(preview_lines),
            'sample_text': subtitle_content
        })
        
    except Exception as e:
        logger.error(f"Error extracting subtitle preview: {e}")
        return jsonify({'error': str(e)}), 500
