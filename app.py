from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import edge_tts
import asyncio
import io
import json
import os
import sys
import logging
from functools import wraps

# Production configuration
PRODUCTION = os.environ.get('FLASK_ENV', 'production') == 'production'
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', 5000))
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',')

# Configure logging
logging.basicConfig(
    level=logging.INFO if PRODUCTION else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configure CORS for production
if ALLOWED_ORIGINS == ['*']:
    CORS(app, resources={r"/*": {"origins": "*"}})
else:
    CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})

# Cache for voices list
voices_cache = None

# Fix for Windows asyncio event loop issues
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def async_route(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(f(*args, **kwargs))
        finally:
            loop.close()
    return wrapper

@app.route('/api/voices', methods=['GET'])
@async_route
async def get_voices():
    """Get all available voices from edge-tts"""
    global voices_cache
    
    if voices_cache is None:
        voices = await edge_tts.list_voices()
        voices_cache = voices
    
    # Group voices by language
    grouped_voices = {}
    for voice in voices_cache:
        locale = voice['Locale']
        lang_name = voice['LocaleName']
        
        if locale not in grouped_voices:
            grouped_voices[locale] = {
                'locale': locale,
                'language': lang_name,
                'voices': []
            }
        
        grouped_voices[locale]['voices'].append({
            'name': voice['ShortName'],
            'displayName': voice['ShortName'].split('-')[-1].replace('Neural', ''),
            'gender': voice['Gender'],
            'locale': locale,
            'language': lang_name,
            'styles': voice.get('StyleList', []),
            'roles': voice.get('RolePlayList', [])
        })
    
    return jsonify({
        'success': True,
        'data': list(grouped_voices.values())
    })

@app.route('/api/tts', methods=['POST'])
@async_route
async def text_to_speech():
    """Convert text to speech"""
    try:
        data = request.get_json()
        text = data.get('text', '')
        voice = data.get('voice', 'en-US-AriaNeural')
        rate = data.get('rate', '+0%')
        pitch = data.get('pitch', '+0Hz')
        volume = data.get('volume', '+0%')
        style = data.get('style', None)
        style_degree = data.get('styleDegree', 1.0)
        
        if not text:
            return jsonify({'success': False, 'error': 'Text is required'}), 400
        
        if len(text) > 10000:
            return jsonify({'success': False, 'error': 'Text too long. Maximum 10000 characters.'}), 400
        
        # Create communicate object with SSML for styling
        if style:
            ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" 
                xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">
                <voice name="{voice}">
                    <mstts:express-as style="{style}" styledegree="{style_degree}">
                        <prosody rate="{rate}" pitch="{pitch}" volume="{volume}">
                            {text}
                        </prosody>
                    </mstts:express-as>
                </voice>
            </speak>'''
            communicate = edge_tts.Communicate(ssml, voice)
        else:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
        
        # Collect audio data
        audio_data = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.write(chunk["data"])
        
        audio_data.seek(0)
        
        return send_file(
            audio_data,
            mimetype='audio/mpeg',
            as_attachment=True,
            download_name='speech.mp3'
        )
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tts/stream', methods=['POST'])
@async_route
async def text_to_speech_stream():
    """Stream text to speech audio"""
    try:
        data = request.get_json()
        text = data.get('text', '')
        voice = data.get('voice', 'en-US-AriaNeural')
        rate = data.get('rate', '+0%')
        pitch = data.get('pitch', '+0Hz')
        volume = data.get('volume', '+0%')
        
        if not text:
            return jsonify({'success': False, 'error': 'Text is required'}), 400
        
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
        
        async def generate():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        
        # Collect all audio first (streaming async generator requires special handling)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        
        audio_data = b''.join(audio_chunks)
        
        return Response(
            audio_data,
            mimetype='audio/mpeg',
            headers={
                'Content-Disposition': 'inline',
                'Cache-Control': 'no-cache'
            }
        )
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/preview', methods=['POST'])
@async_route
async def preview_voice():
    """Quick preview of a voice with sample text"""
    try:
        data = request.get_json()
        voice = data.get('voice', 'en-US-AriaNeural')
        sample_text = data.get('text', 'Hello! This is a sample of my voice. I hope you like how I sound.')
        
        communicate = edge_tts.Communicate(sample_text, voice)
        
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        
        audio_data = b''.join(audio_chunks)
        
        return Response(
            audio_data,
            mimetype='audio/mpeg',
            headers={
                'Content-Disposition': 'inline',
                'Cache-Control': 'no-cache'
            }
        )
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy', 
        'service': 'Shayra AI TTS',
        'environment': 'production' if PRODUCTION else 'development'
    })

@app.route('/')
def index():
    """Root endpoint"""
    return jsonify({
        'service': 'Shayra AI TTS API',
        'version': '1.0.0',
        'endpoints': {
            '/api/voices': 'GET - List all available voices',
            '/api/tts': 'POST - Convert text to speech',
            '/api/tts/stream': 'POST - Stream text to speech',
            '/api/preview': 'POST - Preview a voice',
            '/api/health': 'GET - Health check'
        }
    })

def run_production_server():
    """Run the production server using Waitress"""
    from waitress import serve
    logger.info(f"Starting production server on {HOST}:{PORT}")
    logger.info(f"Allowed origins: {ALLOWED_ORIGINS}")
    serve(app, host=HOST, port=PORT, threads=8)

def run_development_server():
    """Run the development server"""
    logger.info(f"Starting development server on {HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=True)

if __name__ == '__main__':
    if PRODUCTION:
        run_production_server()
    else:
        run_development_server()
