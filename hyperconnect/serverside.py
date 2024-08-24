from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import uuid
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit, join_room
import shutil 
import time
import zipfile

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/Volumes/YZDE/uploads' 
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
socketio = SocketIO(app)

file_transfers = {}

def cleanup_transfers():
    current_time = time.time()
    for pin, transfer in list(file_transfers.items()):
        if current_time - transfer['start_time'] > 24 * 60 * 60:  
            shutil.rmtree(transfer['directory'], ignore_errors=True)
            del file_transfers[pin]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)
    pin = request.headers.get('X-Pin')
    chunk_index = int(request.headers.get('X-Chunk-Index'))
    total_chunks = int(request.headers.get('X-Total-Chunks'))
    is_folder = request.headers.get('X-Is-Folder') == 'true'
    relative_path = request.headers.get('X-Relative-Path') or ''

    if pin not in file_transfers:
        return jsonify({'error': 'PIN not connected'}), 400  # Reject upload if not connected

    directory = file_transfers[pin]['directory']

    if relative_path not in file_transfers[pin]['transfers']:
        file_transfers[pin]['transfers'][relative_path] = {
            'filename': filename,
            'is_folder': is_folder,
            'chunks': [None] * total_chunks if not is_folder else []
        }

    transfer = file_transfers[pin]['transfers'][relative_path]

    if not is_folder:
        transfer['chunks'][chunk_index] = file.read()

        progress = (chunk_index + 1) / total_chunks * 100
        socketio.emit('progress', {'progress': progress, 'relative_path': relative_path}, room=pin)

        if all(transfer['chunks']):
            filepath = os.path.join(directory, relative_path)
            with open(filepath, 'wb') as f:
                for chunk in transfer['chunks']:
                    f.write(chunk)
            del file_transfers[pin]['transfers'][relative_path]

    else:
        folder_path = os.path.join(directory, relative_path)
        os.makedirs(folder_path, exist_ok=True)

    if not any(file_transfers[pin]['transfers'].values()):
        socketio.emit('all_complete', {}, room=pin)
        zip_filename = f"{pin}.zip"
        zip_filepath = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)
        with zipfile.ZipFile(zip_filepath, 'w') as zipf:
            for root, _, files in os.walk(directory):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, directory)
                    zipf.write(filepath, arcname)

        shutil.rmtree(directory, ignore_errors=True)
        file_transfers[pin]['zip_filename'] = zip_filename

    return jsonify({'success': True})

@app.route('/download/<pin>')
def download(pin):
    if pin in file_transfers:
        zip_filename = file_transfers[pin]['zip_filename']
        return send_from_directory(app.config['UPLOAD_FOLDER'], zip_filename, as_attachment=True)
    else:
        return jsonify({'error': 'Invalid PIN or transfer expired'}), 400

@socketio.on('connect', namespace='/connect/<pin>')
def handle_connect(pin):
    """Handle WebSocket connections on the /connect/<pin> namespace."""
    join_room(pin)  # Join the room for this PIN

    if pin not in file_transfers:
        directory = os.path.join(app.config['UPLOAD_FOLDER'], pin)
        os.makedirs(directory, exist_ok=True)
        file_transfers[pin] = {
            'directory': directory,
            'start_time': time.time(),
            'transfers': {}
        }

    emit('connected', {'is_sender': len(file_transfers[pin]['transfers']) == 0}, room=pin) 

@socketio.on('start_upload', namespace='/connect/<pin>')
def start_upload(pin, data):
    emit('start_upload', data, room=pin, include_self=False)  # Notify the receiver

if __name__ == '__main__':
    socketio.run(app, debug=True, host="0.0.0.0", port=4333)