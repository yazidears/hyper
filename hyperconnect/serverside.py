from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import uuid
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit, join_room
import shutil
import time

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
        return jsonify({'error': 'PIN not connected'}), 400 

    # If this is the first chunk, notify the receiver to start the download
    if chunk_index == 0:
        socketio.emit('start_download', 
                      {'filename': filename, 'totalChunks': total_chunks, 'relative_path': relative_path}, 
                      room=pin, 
                      include_self=False)  

    # Emit the chunk data to the receiver in real-time
    socketio.emit('chunk', {'data': file.read(), 'chunk_index': chunk_index, 'relative_path': relative_path}, room=pin, include_self=False)

    # If this is the last chunk, signal completion to the receiver
    if chunk_index == total_chunks - 1:
        socketio.emit('transfer_complete', {'relative_path': relative_path}, room=pin, include_self=False)

    return jsonify({'success': True})

@socketio.on('connect')
def handle_connect():
    pin = request.args.get('pin')
    if not pin:
        return False 

    join_room(pin)

    if pin not in file_transfers:
        directory = os.path.join(app.config['UPLOAD_FOLDER'], pin)
        os.makedirs(directory, exist_ok=True)
        file_transfers[pin] = {
            'directory': directory,
            'start_time': time.time(),
            'transfers': {}
        }

    emit('connected', {'is_sender': len(file_transfers[pin]['transfers']) == 0}, room=pin) 

@socketio.on('start_upload')
def start_upload(data):
    pin = data.get('pin') 
    if not pin:
        return False 

    emit('start_upload', data, room=pin, include_self=False) 

if __name__ == '__main__':
    socketio.run(app, host='192.168.0.15', port=4333, debug=True)