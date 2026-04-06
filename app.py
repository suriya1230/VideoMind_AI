from flask import Flask, request, jsonify
from flask_cors import CORS
import os, re, tempfile, requests
from collections import Counter
from groq import Groq

app = Flask(__name__)

# ✅ Fix CORS — allow all origins
CORS(app, resources={
    r"/api/*": {
        "origins"     : "*",
        "methods"     : ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# ✅ Fix file upload limit — 100MB
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "your_key_here")
print("✅ Backend ready — using Groq Whisper API")


# ═══════════════════════════════════════════════════════════════
# TRANSCRIPTION — Groq Whisper API (zero RAM)
# ═══════════════════════════════════════════════════════════════
def do_transcribe(audio_path):
    client    = Groq(api_key=GROQ_API_KEY)
    file_size = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"   Audio size: {file_size:.1f} MB")

    if file_size <= 24:
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file            = (os.path.basename(audio_path), f),
                model           = "whisper-large-v3",
                response_format = "verbose_json",
            )
        return result.text.strip(), result.language

    else:
        print("   Large file — splitting into chunks...")
        import subprocess
        probe = subprocess.run([
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ], capture_output=True, text=True)

        try:
            total_dur = float(probe.stdout.strip())
        except:
            total_dur = 3600

        chunk_dur   = 600
        chunk_index = 0
        transcripts = []
        lang        = "en"
        start       = 0

        while start < total_dur:
            chunk_file = os.path.join(
                tempfile.gettempdir(), f"chunk_{chunk_index}.wav"
            )
            os.system(
                f"ffmpeg -i '{audio_path}' -ss {start} -t {chunk_dur} "
                f"-ar 16000 -ac 1 '{chunk_file}' -y 2>/dev/null"
            )
            if os.path.exists(chunk_file):
                with open(chunk_file, "rb") as f:
                    r = client.audio.transcriptions.create(
                        file            = (f"chunk_{chunk_index}.wav", f),
                        model           = "whisper-large-v3",
                        response_format = "verbose_json",
                    )
                transcripts.append(r.text)
                lang = r.language
                os.remove(chunk_file)
                print(f"   Chunk {chunk_index + 1} done")

            start       += chunk_dur
            chunk_index += 1

        return " ".join(transcripts).strip(), lang


# ═══════════════════════════════════════════════════════════════
# YOUTUBE — Extract Video ID
# ═══════════════════════════════════════════════════════════════
def extract_video_id(url):
    patterns = [
        r'v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
        r'shorts/([a-zA-Z0-9_-]{11})',
        r'live/([a-zA-Z0-9_-]{11})',
        r'embed/([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


# ═══════════════════════════════════════════════════════════════
# METHOD 1 — pytubefix
# ═══════════════════════════════════════════════════════════════
def download_via_pytubefix(url):
    try:
        from pytubefix import YouTube
        print("   [Method 1] Trying pytubefix...")

        yt      = YouTube(url)
        title   = yt.title
        dur     = yt.length
        channel = yt.author

        stream = (
            yt.streams
              .filter(only_audio=True)
              .order_by("abr")
              .last()
        )
        if not stream:
            print("   No audio stream found")
            return None, None, 0, None

        tmp_dir    = tempfile.gettempdir()
        audio_file = stream.download(
            output_path = tmp_dir,
            filename    = "audio_pytubefix"
        )
        wav = os.path.join(tmp_dir, "audio_pytubefix.wav")

        os.system(
            f"ffmpeg -i '{audio_file}' -ar 16000 -ac 1 -b:a 32k "
            f"'{wav}' -y 2>/dev/null"
        )
        if os.path.exists(audio_file):
            os.remove(audio_file)

        if os.path.exists(wav) and os.path.getsize(wav) > 1000:
            print("   ✅ pytubefix success")
            return wav, title, dur, channel

    except Exception as e:
        print(f"   pytubefix failed: {e}")

    return None, None, 0, None


# ═══════════════════════════════════════════════════════════════
# METHOD 2 — Invidious API
# ═══════════════════════════════════════════════════════════════
def download_via_invidious(video_id):
    instances = [
        "https://invidious.io.lol",
        "https://invidious.privacydev.net",
        "https://iv.ggtyler.dev",
        "https://invidious.perennialte.ch",
        "https://invidious.lunar.icu",
        "https://invidious.reallyaweso.me",
        "https://invidious.incogniweb.net",
        "https://invidious.slipfox.xyz",
        "https://yewtu.be",
        "https://invidious.kavin.rocks",
        "https://inv.riverside.rocks",
        "https://invidious.nerdvpn.de",
        "https://yt.artemislena.eu",
        "https://invidious.flokinet.to",
        "https://vid.puffyan.us",
        "https://invidious.namazso.eu",
    ]

    for instance in instances:
        try:
            print(f"   [Method 2] Trying: {instance}")
            r = requests.get(
                f"{instance}/api/v1/videos/{video_id}",
                timeout = 8,
                headers = {"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code != 200:
                continue

            data    = r.json()
            title   = data.get("title",         "Unknown")
            dur     = data.get("lengthSeconds",  0)
            channel = data.get("author",         "Unknown")

            # Try adaptiveFormats
            fmts = data.get("adaptiveFormats", [])
            audio_fmts = [
                f for f in fmts
                if "audio" in f.get("type", "")
            ]

            # Fallback to formatStreams
            if not audio_fmts:
                fmts = data.get("formatStreams", [])
                audio_fmts = [
                    f for f in fmts
                    if "audio" in f.get("type", "")
                ]

            if not audio_fmts:
                continue

            audio_fmts.sort(
                key     = lambda x: x.get("bitrate", 0),
                reverse = True
            )
            audio_url = audio_fmts[0].get("url", "")
            if not audio_url:
                continue

            tmp_webm = os.path.join(
                tempfile.gettempdir(), f"audio_{video_id}.webm"
            )
            tmp_wav = os.path.join(
                tempfile.gettempdir(), f"audio_{video_id}.wav"
            )

            for p in [tmp_webm, tmp_wav]:
                if os.path.exists(p):
                    os.remove(p)

            resp = requests.get(
                audio_url, stream=True, timeout=120,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code != 200:
                continue

            size = 0
            with open(tmp_webm, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
                    size += len(chunk)

            print(f"   Downloaded: {size/1024/1024:.1f} MB")
            if size < 1000:
                continue

            os.system(
                f"ffmpeg -i '{tmp_webm}' -ar 16000 -ac 1 -b:a 32k "
                f"'{tmp_wav}' -y 2>/dev/null"
            )
            if os.path.exists(tmp_webm):
                os.remove(tmp_webm)

            if os.path.exists(tmp_wav) and os.path.getsize(tmp_wav) > 1000:
                print(f"   ✅ Invidious success: {instance}")
                return tmp_wav, title, int(dur), channel

        except requests.Timeout:
            print(f"   Timeout: {instance}")
            continue
        except Exception as e:
            print(f"   Error {instance}: {e}")
            continue

    return None, None, 0, None


# ═══════════════════════════════════════════════════════════════
# METHOD 3 — yt-dlp iOS client (last resort)
# ═══════════════════════════════════════════════════════════════
def download_via_ytdlp(url):
    try:
        import yt_dlp
        print("   [Method 3] Trying yt-dlp iOS client...")

        out = os.path.join(tempfile.gettempdir(), "audio_ytdlp")

        opts = {
            "format"    : "bestaudio/best",
            "outtmpl"   : out,
            "noplaylist": True,
            "postprocessors": [{
                "key"            : "FFmpegExtractAudio",
                "preferredcodec" : "wav",
                "preferredquality": "96",
            }],
            # iOS client bypasses bot detection better
            "extractor_args": {
                "youtube": {
                    "player_client": [
                        "ios",
                        "android_music",
                        "android_creator",
                        "web_creator",
                    ]
                }
            },
            "quiet"         : True,
            "no_warnings"   : True,
            "sleep_interval": 2,
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            info    = ydl.extract_info(url, download=True)
            title   = info.get("title",   "Unknown")
            dur     = info.get("duration", 0)
            channel = info.get("uploader","Unknown")

        wav = out + ".wav"
        if os.path.exists(wav) and os.path.getsize(wav) > 1000:
            print("   ✅ yt-dlp success")
            return wav, title, dur, channel

    except Exception as e:
        print(f"   yt-dlp failed: {e}")

    return None, None, 0, None


# ═══════════════════════════════════════════════════════════════
# MASTER DOWNLOAD — tries all 3 methods
# ═══════════════════════════════════════════════════════════════
def download_audio(url, video_id):
    # Method 1: pytubefix
    wav, title, dur, channel = download_via_pytubefix(url)
    if wav:
        return wav, title, dur, channel

    # Method 2: Invidious
    wav, title, dur, channel = download_via_invidious(video_id)
    if wav:
        return wav, title, dur, channel

    # Method 3: yt-dlp iOS
    wav, title, dur, channel = download_via_ytdlp(url)
    if wav:
        return wav, title, dur, channel

    return None, None, 0, None


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def clean_transcript(text):
    fillers = [
        r"\bum+\b", r"\buh+\b", r"\bumm+\b", r"\bokay+\b", r"\bright\b",
        r"\byou know\b", r"\bi mean\b", r"\bbasically\b", r"\bactually\b",
        r"\bliterally\b", r"\blet's say\b", r"\bgo ahead\b", r"\bi think\b",
    ]
    for f in fillers:
        text = re.sub(f, "", text, flags=re.IGNORECASE)

    text  = re.sub(r'\b(\w+)(\s+\1){1,}\b', r'\1', text, flags=re.IGNORECASE)
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    counts    = Counter(words)
    threshold = max(20, int(len(words) * 0.015))
    whitelist = {
        "the","and","that","this","with","from","have","will","are",
        "for","not","can","you","your","they","about","what","when",
        "how","all","also","use","data","model","video","language",
    }
    for w, c in counts.items():
        if c > threshold and w not in whitelist:
            text = re.sub(
                rf'\b{re.escape(w)}\b', '', text, flags=re.IGNORECASE
            )
    return re.sub(r'\s+', ' ', text).strip()


def get_summary_config(wc):
    if   wc < 500:  return {"bullets":"3-4",  "words":"100-150","detail":"brief"}
    elif wc < 1500: return {"bullets":"4-5",  "words":"200-250","detail":"moderate"}
    elif wc < 3000: return {"bullets":"6-8",  "words":"300-400","detail":"detailed"}
    elif wc < 6000: return {"bullets":"8-10", "words":"450-550","detail":"very detailed"}
    else:           return {"bullets":"10-15","words":"600-800","detail":"comprehensive"}


def detect_video_type(transcript, title):
    client = Groq(api_key=GROQ_API_KEY)
    r = client.chat.completions.create(
        model    = "llama-3.3-70b-versatile",
        messages = [{"role": "user", "content":
            f"Classify this video into ONE word only: song, movie, or educational.\n"
            f"Title: {title}\n"
            f"Transcript: {' '.join(transcript.split()[:300])}\n"
            f"Category:"}],
        max_tokens  = 10,
        temperature = 0.1,
    )
    cat = r.choices[0].message.content.strip().lower()
    if "song"  in cat: return "song"
    if "movie" in cat: return "movie"
    return "educational"


# ═══════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════
@app.route("/")
def home():
    return jsonify({
        "status" : "✅ VideoMind AI Backend is running",
        "version": "4.0",
        "routes" : [
            "GET  /api/health",
            "POST /api/process-url",
            "POST /api/process-file",
            "POST /api/summarize",
            "POST /api/ask",
            "POST /api/translate",
        ]
    })


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "mode": "groq-whisper-api"})


# ── Process YouTube URL ──────────────────────────────────────────────────────
@app.route("/api/process-url", methods=["POST", "OPTIONS"])
def process_url():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid request body"}), 400

        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "No URL provided"}), 400

        # Clean URL — remove extra spaces or characters
        url = url.strip().strip('"').strip("'")

        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({
                "error": "Invalid YouTube URL. Please use format: "
                         "https://www.youtube.com/watch?v=XXXXXXXXXXX"
            }), 400

        print(f"\n{'='*50}")
        print(f"Processing video ID: {video_id}")
        print(f"URL: {url}")
        print(f"{'='*50}")

        wav, title, duration, channel = download_audio(url, video_id)

        if not wav:
            return jsonify({
                "error": (
                    "All download methods failed for this video. "
                    "Please try a different video or try again in 5 minutes."
                )
            }), 500

        print(f"Transcribing: {title}")
        transcript, lang = do_transcribe(wav)

        if os.path.exists(wav):
            os.remove(wav)

        if not transcript or len(transcript.strip()) < 10:
            return jsonify({"error": "Transcription failed — audio may be empty"}), 500

        vtype = detect_video_type(transcript, title)

        print(f"✅ Done: {title} | {lang} | {vtype}")

        return jsonify({
            "success"          : True,
            "transcript"       : transcript,
            "video_title"      : title,
            "channel"          : channel or "Unknown",
            "duration"         : f"{duration // 60}m {duration % 60}s",
            "detected_language": lang,
            "word_count"       : len(transcript.split()),
            "video_type"       : vtype,
        })

    except Exception as e:
        print(f"process_url error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Process Uploaded File ────────────────────────────────────────────────────
@app.route("/api/process-file", methods=["POST", "OPTIONS"])
def process_file():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        if "video" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        f         = request.files["video"]
        filename  = f.filename or "video.mp4"
        tmp_v     = os.path.join(tempfile.gettempdir(), "upload_video.mp4")
        tmp_a     = os.path.join(tempfile.gettempdir(), "upload_audio.wav")

        # Clean old files
        for p in [tmp_v, tmp_a]:
            if os.path.exists(p):
                os.remove(p)

        f.save(tmp_v)
        size_mb = os.path.getsize(tmp_v) / 1024 / 1024
        print(f"Uploaded: {filename} ({size_mb:.1f} MB)")

        # Extract audio
        ret = os.system(
            f"ffmpeg -i '{tmp_v}' -ar 16000 -ac 1 -b:a 32k "
            f"'{tmp_a}' -y 2>/dev/null"
        )

        if os.path.exists(tmp_v):
            os.remove(tmp_v)

        if not os.path.exists(tmp_a):
            return jsonify({"error": "Audio extraction failed"}), 500

        transcript, lang = do_transcribe(tmp_a)

        if os.path.exists(tmp_a):
            os.remove(tmp_a)

        if not transcript or len(transcript.strip()) < 10:
            return jsonify({"error": "Transcription failed — video may have no audio"}), 500

        vtype = detect_video_type(transcript, filename)

        return jsonify({
            "success"          : True,
            "transcript"       : transcript,
            "video_title"      : filename,
            "channel"          : "Uploaded File",
            "duration"         : "—",
            "detected_language": lang,
            "word_count"       : len(transcript.split()),
            "video_type"       : vtype,
        })

    except Exception as e:
        print(f"process_file error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Summarize ────────────────────────────────────────────────────────────────
@app.route("/api/summarize", methods=["POST", "OPTIONS"])
def summarize():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data       = request.get_json(silent=True) or {}
        transcript = data.get("transcript", "")
        title      = data.get("video_title", "")
        vtype      = data.get("video_type",  "educational")

        if not transcript:
            return jsonify({"error": "No transcript provided"}), 400

        if vtype == "song":
            return jsonify({
                "success"   : True,
                "summary"   : None,
                "message"   : "🎵 Song detected — summarization not available.",
                "video_type": "song",
            })

        client = Groq(api_key=GROQ_API_KEY)
        text   = clean_transcript(transcript)
        wc     = len(transcript.split())
        cfg    = get_summary_config(wc)

        if vtype == "movie":
            prompt = (
                f'Tell the complete story of the movie: "{title}".\n'
                f'Include: main plot, key characters, important events, ending.\n'
                f'Write at least 300 words.'
            )
        else:
            prompt = (
                f'Summarize this video "{title}" ({wc} words).\n'
                f'Write a {cfg["detail"]} summary:\n'
                f'- 1 opening sentence about the overall topic\n'
                f'- {cfg["bullets"]} detailed bullet points '
                f'(2-3 sentences each, include specific details, '
                f'examples and numbers from the video)\n'
                f'- 1 strong closing sentence\n'
                f'Total: {cfg["words"]} words. '
                f'Cover ALL topics without missing anything.\n\n'
                f'Transcript:\n{text}\n\nSummary:'
            )

        r = client.chat.completions.create(
            model       = "llama-3.3-70b-versatile",
            messages    = [{"role": "user", "content": prompt}],
            max_tokens  = 1500,
            temperature = 0.3,
        )

        return jsonify({
            "success"   : True,
            "summary"   : r.choices[0].message.content.strip(),
            "video_type": vtype,
            "word_count": wc,
        })

    except Exception as e:
        print(f"summarize error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Q&A ──────────────────────────────────────────────────────────────────────
@app.route("/api/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data       = request.get_json(silent=True) or {}
        question   = data.get("question",   "")
        transcript = data.get("transcript", "")

        if not question:
            return jsonify({"error": "No question provided"}), 400

        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model    = "llama-3.3-70b-versatile",
            messages = [{"role": "user", "content":
                f"You are a smart AI assistant.\n"
                f"1. If the question relates to the video transcript, answer from it.\n"
                f"2. If the question is general or asks for code, use your knowledge.\n"
                f"3. For code requests always write complete working code with comments.\n\n"
                f"Video Transcript:\n{transcript}\n\n"
                f"Question: {question}\n\nAnswer:"}],
            max_tokens  = 1500,
            temperature = 0.5,
        )

        return jsonify({
            "success": True,
            "answer" : r.choices[0].message.content.strip(),
        })

    except Exception as e:
        print(f"ask error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Translate ────────────────────────────────────────────────────────────────
@app.route("/api/translate", methods=["POST", "OPTIONS"])
def translate():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data     = request.get_json(silent=True) or {}
        language = data.get("language", "")
        summary  = data.get("summary",  "")

        if not language:
            return jsonify({"error": "No language provided"}), 400
        if not summary:
            return jsonify({"error": "No summary to translate"}), 400

        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model    = "llama-3.3-70b-versatile",
            messages = [{"role": "user", "content":
                f"Translate this video summary to {language}.\n"
                f"Keep the bullet point structure exactly as it is.\n"
                f"Only translate — do not add any extra text.\n\n"
                f"Summary:\n{summary}\n\n"
                f"{language} Translation:"}],
            max_tokens  = 800,
            temperature = 0.2,
        )

        return jsonify({
            "success"   : True,
            "translated": r.choices[0].message.content.strip(),
            "language"  : language,
        })

    except Exception as e:
        print(f"translate error: {e}")
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=False, host="0.0.0.0", port=port)
