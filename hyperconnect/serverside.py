from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import uuid
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO
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
        directory = os.path.join(app.config['UPLOAD_FOLDER'], pin)
        os.makedirs(directory, exist_ok=True)
        file_transfers[pin] = {
            'directory': directory,
            'start_time': time.time(),
            'transfers': {}
        }

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
            filepath = os.path.join(file_transfers[pin]['directory'], relative_path)
            with open(filepath, 'wb') as f:
                for chunk in transfer['chunks']:
                    f.write(chunk)
            del file_transfers[pin]['transfers'][relative_path]

    else:
        folder_path = os.path.join(file_transfers[pin]['directory'], relative_path)
        os.makedirs(folder_path, exist_ok=True)

    if not any(file_transfers[pin]['transfers'].values()):
        socketio.emit('all_complete', {}, room=pin)
        # Create a zip file of the entire directory
        zip_filename = f"{pin}.zip"
        zip_filepath = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)
        with zipfile.ZipFile(zip_filepath, 'w') as zipf:
            for root, _, files in os.walk(file_transfers[pin]['directory']):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, file_transfers[pin]['directory'])
                    zipf.write(filepath, arcname)

        # Clean up the original directory
        shutil.rmtree(file_transfers[pin]['directory'], ignore_errors=True)

        # Update file_transfers to point to the zip file
        file_transfers[pin]['zip_filename'] = zip_filename

    return jsonify({'success': True})

@app.route('/download/<pin>')
def download(pin):
    if pin in file_transfers:
        zip_filename = file_transfers[pin]['zip_filename']
        return send_from_directory(app.config['UPLOAD_FOLDER'], zip_filename, as_attachment=True)
    else:
        return jsonify({'error': 'Invalid PIN or transfer expired'}), 400

@socketio.on('connect', namespace='/download/<pin>')
def connect(pin):
    join_room(pin)

if __name__ == '__main__':
    socketio.run(app, debug=True, host="0.0.0.0",port=4333)