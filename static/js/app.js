// Media Manager Application JavaScript

class MediaManager {
    constructor() {
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.startProgressUpdates();
        this.setupAutoSave();
    }

    setupEventListeners() {
        // Global error handler for fetch requests
        window.addEventListener('unhandledrejection', this.handleFetchError.bind(this));
        
        // Setup tooltips
        this.initializeTooltips();
        
        // Setup confirmation dialogs
        this.setupConfirmationDialogs();
    }

    initializeTooltips() {
        // Initialize Bootstrap tooltips
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    setupConfirmationDialogs() {
        // Add confirmation to dangerous actions
        document.querySelectorAll('[data-confirm]').forEach(element => {
            element.addEventListener('click', function(e) {
                const message = this.dataset.confirm || 'Are you sure?';
                if (!confirm(message)) {
                    e.preventDefault();
                    return false;
                }
            });
        });
    }

    startProgressUpdates() {
        // Update progress indicators every 5 seconds
        setInterval(() => {
            this.updateScanProgress();
            this.updateProcessingStatus();
        }, 5000);

        // Initial update
        this.updateScanProgress();
        this.updateProcessingStatus();
    }

    updateScanProgress() {
        fetch('/api/scan_progress')
            .then(response => response.json())
            .then(data => {
                const progressElement = document.getElementById('scan-progress');
                if (progressElement) {
                    if (data.progress < 100) {
                        progressElement.innerHTML = `Scanning... ${data.progress.toFixed(1)}%`;
                        progressElement.parentElement.classList.add('processing-indicator');
                    } else {
                        progressElement.innerHTML = 'Scan Complete';
                        progressElement.parentElement.classList.remove('processing-indicator');
                    }
                }

                // Update page progress bars if they exist
                const pageProgressBars = document.querySelectorAll('.scan-progress-bar');
                pageProgressBars.forEach(bar => {
                    bar.style.width = `${data.progress}%`;
                    bar.setAttribute('aria-valuenow', data.progress);
                    bar.textContent = `${data.progress.toFixed(1)}%`;
                });
            })
            .catch(error => {
                console.error('Error fetching scan progress:', error);
            });
    }

    updateProcessingStatus() {
        fetch('/api/processing_status')
            .then(response => response.json())
            .then(data => {
                const statusElement = document.getElementById('processing-progress');
                if (statusElement) {
                    if (data.length > 0) {
                        statusElement.innerHTML = `Processing ${data.length} file(s)`;
                        statusElement.parentElement.classList.add('processing-indicator');
                    } else {
                        statusElement.innerHTML = 'Ready';
                        statusElement.parentElement.classList.remove('processing-indicator');
                    }
                }

                // Update individual job progress if on detail page
                this.updateJobProgress(data);
            })
            .catch(error => {
                console.error('Error fetching processing status:', error);
            });
    }

    updateJobProgress(jobs) {
        const progressContainer = document.getElementById('processing-progress');
        if (!progressContainer) return;

        const currentMediaId = this.getCurrentMediaId();
        if (!currentMediaId) return;

        const relevantJob = jobs.find(job => 
            job.media_file.toLowerCase().includes(currentMediaId.toString())
        );

        if (relevantJob && relevantJob.status === 'processing') {
            progressContainer.style.display = 'block';
            const progressBar = progressContainer.querySelector('.progress-bar');
            if (progressBar) {
                progressBar.style.width = `${relevantJob.progress}%`;
                progressBar.setAttribute('aria-valuenow', relevantJob.progress);
            }
        } else {
            progressContainer.style.display = 'none';
        }
    }

    getCurrentMediaId() {
        // Extract media ID from URL if on detail page
        const path = window.location.pathname;
        const match = path.match(/\/media\/(\d+)/);
        return match ? parseInt(match[1]) : null;
    }

    setupAutoSave() {
        // Auto-save track modifications after typing stops
        let saveTimeout;
        
        document.querySelectorAll('.track-title, .track-language').forEach(input => {
            input.addEventListener('input', function() {
                clearTimeout(saveTimeout);
                
                // Add visual indicator that changes are pending
                this.classList.add('pending-save');
                
                saveTimeout = setTimeout(() => {
                    const row = this.closest('tr');
                    const saveButton = row.querySelector('.save-track');
                    if (saveButton) {
                        saveButton.click();
                    }
                }, 2000); // Auto-save after 2 seconds of inactivity
            });
        });
    }

    handleFetchError(event) {
        console.error('Fetch error:', event.reason);
        this.showNotification('Network error occurred. Please check your connection.', 'error');
    }

    showNotification(message, type = 'info', duration = 5000) {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 1060; min-width: 300px;';
        
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        document.body.appendChild(notification);

        // Auto-dismiss after duration
        setTimeout(() => {
            if (notification.parentNode) {
                const alert = bootstrap.Alert.getOrCreateInstance(notification);
                alert.close();
            }
        }, duration);
    }

    // Utility method for making API calls
    async apiCall(url, options = {}) {
        try {
            const response = await fetch(url, {
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }

            return data;
        } catch (error) {
            this.showNotification(`API Error: ${error.message}`, 'error');
            throw error;
        }
    }

    // Method to refresh media data
    refreshMediaData() {
        // Add loading state
        document.body.classList.add('loading');
        
        // Reload page after short delay to show loading state
        setTimeout(() => {
            window.location.reload();
        }, 500);
    }

    // Method to format file sizes
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // Method to format duration
    formatDuration(seconds) {
        if (!seconds) return 'Unknown';
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        
        if (hours > 0) {
            return `${hours}h ${minutes}m`;
        } else {
            return `${minutes}m`;
        }
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    window.mediaManager = new MediaManager();
});

// Export for use in other scripts
window.MediaManager = MediaManager;
