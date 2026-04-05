from flask import Flask, request, jsonify
from flask_cors import CORS
import os, re, tempfile, requests
from collections import Counter
from groq import Groq

app = Flask(__name__)
CORS(app)

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
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
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
            chunk_file = os.path.join(tempfile.gettempdir(), f"chunk_{chunk_index}.wav")
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
# YOUTUBE DOWNLOAD — pytubefix + Invidious fallback
# ═══════════════════════════════════════════════════════════════
def extract_video_id(url):
    patterns = [
        r'v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
        r'shorts/([a-zA-Z0-9_-]{11})',
        r'live/([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def download_via_pytubefix(url):
    """Try pytubefix — fast and free."""
    try:
        from pytubefix import YouTube
        print("   Trying pytubefix...")

        yt      = YouTube(url)
        title   = yt.title
        dur     = yt.length
        channel = yt.author

        stream = yt.streams.filter(only_audio=True).order_by("abr").last()
        if not stream:
            return None, None, 0, None

        tmp_dir    = tempfile.gettempdir()
        audio_file = stream.download(output_path=tmp_dir, filename="audio_raw_pt")
        wav        = os.path.join(tmp_dir, "audio_pt.wav")

        os.system(
            f"ffmpeg -i '{audio_file}' -ar 16000 -ac 1 -b:a 32k "
            f"'{wav}' -y 2>/dev/null"
        )
        if os.path.exists(audio_file):
            os.remove(audio_file)

        if os.path.exists(wav):
            print("   ✅ pytubefix success")
            return wav, title, dur, channel

    except Exception as e:
        print(f"   pytubefix failed: {e}")

    return None, None, 0, None


def download_via_invidious(video_id):
    """Fallback — Invidious public API, no bot detection."""
    instances = [
        "https://invidious.snopyta.org",
        "https://yewtu.be",
        "https://invidious.kavin.rocks",
        "https://inv.riverside.rocks",
        "https://invidious.nerdvpn.de",
        "https://invidious.tiekoetter.com",
        "https://yt.artemislena.eu",
        "https://invidious.flokinet.to",
        "https://vid.puffyan.us",
        "https://invidious.namazso.eu",
    ]

    for instance in instances:
        try:
            print(f"   Trying Invidious: {instance}")
            r = requests.get(
                f"{instance}/api/v1/videos/{video_id}",
                timeout = 10,
                headers = {"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code != 200:
                continue

            data    = r.json()
            title   = data.get("title",          "Unknown")
            dur     = data.get("lengthSeconds",   0)
            channel = data.get("author",          "Unknown")
            fmts    = data.get("adaptiveFormats", [])

            audio_fmts = [
                f for f in fmts
                if f.get("type", "").startswith("audio/")
            ]
            if not audio_fmts:
                continue

            audio_fmts.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
            audio_url = audio_fmts[0].get("url", "")
            if not audio_url:
                continue

            tmp_webm = os.path.join(tempfile.gettempdir(), "audio_inv.webm")
            tmp_wav  = os.path.join(tempfile.gettempdir(), "audio_inv.wav")

            resp = requests.get(
                audio_url, stream=True, timeout=60,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with open(tmp_webm, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)

            os.system(
                f"ffmpeg -i '{tmp_webm}' -ar 16000 -ac 1 -b:a 32k "
                f"'{tmp_wav}' -y 2>/dev/null"
            )
            if os.path.exists(tmp_webm):
                os.remove(tmp_webm)

            if os.path.exists(tmp_wav):
                print(f"   ✅ Invidious success: {instance}")
                return tmp_wav, title, int(dur), channel

        except Exception as e:
            print(f"   Invidious {instance} failed: {e}")
            continue

    return None, None, 0, None


def download_audio(url, video_id):
    """Try pytubefix first, then Invidious — both 100% free."""
    wav, title, dur, channel = download_via_pytubefix(url)
    if wav:
        return wav, title, dur, channel

    wav, title, dur, channel = download_via_invidious(video_id)
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
            text = re.sub(rf'\b{re.escape(w)}\b', '', text, flags=re.IGNORECASE)

    return re.sub(r'\s+', ' ', text).strip()


def get_summary_config(wc):
    if   wc < 500:  return {"bullets": "3-4",  "words": "100-150", "detail": "brief"}
    elif wc < 1500: return {"bullets": "4-5",  "words": "200-250", "detail": "moderate"}
    elif wc < 3000: return {"bullets": "6-8",  "words": "300-400", "detail": "detailed"}
    elif wc < 6000: return {"bullets": "8-10", "words": "450-550", "detail": "very detailed"}
    else:           return {"bullets": "10-15","words": "600-800", "detail": "comprehensive"}


def detect_video_type(transcript, title):
    client = Groq(api_key=GROQ_API_KEY)
    r = client.chat.completions.create(
        model    = "llama-3.3-70b-versatile",
        messages = [{"role": "user", "content":
            f"Classify this video into ONE word: song, movie, or educational.\n"
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
        "version": "3.0",
        "routes" : [
            "POST /api/process-url",
            "POST /api/process-file",
            "POST /api/summarize",
            "POST /api/ask",
            "POST /api/translate",
            "GET  /api/health",
        ]
    })


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "mode": "groq-whisper-api"})


@app.route("/api/process-url", methods=["POST"])
def process_url():
    try:
        url = request.json.get("url", "").strip()
        if not url:
            return jsonify({"error": "No URL provided"}), 400

        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({"error": "Invalid YouTube URL"}), 400

        print(f"Processing video ID: {video_id}")

        wav, title, duration, channel = download_audio(url, video_id)

        if not wav:
            return jsonify({"error":
                "Could not download this video. "
                "Please try a different video or try again in a few minutes."}), 500

        transcript, lang = do_transcribe(wav)
        if os.path.exists(wav):
            os.remove(wav)

        vtype = detect_video_type(transcript, title)

        return jsonify({
            "success"          : True,
            "transcript"       : transcript,
            "video_title"      : title,
            "channel"          : channel,
            "duration"         : f"{duration // 60}m {duration % 60}s",
            "detected_language": lang,
            "word_count"       : len(transcript.split()),
            "video_type"       : vtype,
        })

    except Exception as e:
        print(f"process_url error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/process-file", methods=["POST"])
def process_file():
    try:
        if "video" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        f     = request.files["video"]
        tmp_v = os.path.join(tempfile.gettempdir(), "upload_video.mp4")
        tmp_a = os.path.join(tempfile.gettempdir(), "upload_audio.wav")
        f.save(tmp_v)

        os.system(
            f"ffmpeg -i '{tmp_v}' -ar 16000 -ac 1 -b:a 32k "
            f"'{tmp_a}' -y 2>/dev/null"
        )

        if not os.path.exists(tmp_a):
            return jsonify({"error": "Audio extraction failed"}), 500

        transcript, lang = do_transcribe(tmp_a)

        for p in [tmp_v, tmp_a]:
            if os.path.exists(p):
                os.remove(p)

        vtype = detect_video_type(transcript, f.filename)

        return jsonify({
            "success"          : True,
            "transcript"       : transcript,
            "video_title"      : f.filename,
            "detected_language": lang,
            "word_count"       : len(transcript.split()),
            "video_type"       : vtype,
        })

    except Exception as e:
        print(f"process_file error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/summarize", methods=["POST"])
def summarize():
    try:
        data       = request.json
        transcript = data.get("transcript", "")
        title      = data.get("video_title", "")
        vtype      = data.get("video_type",  "educational")

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
                f'Include main plot, key characters, important events and ending.\n'
                f'Write at least 300 words.'
            )
        else:
            prompt = (
                f'Summarize this video "{title}" ({wc} words).\n'
                f'Write a {cfg["detail"]} summary:\n'
                f'- 1 opening sentence about the overall topic\n'
                f'- {cfg["bullets"]} detailed bullet points '
                f'(2-3 sentences each with specific details and examples)\n'
                f'- 1 strong closing sentence\n'
                f'Total: {cfg["words"]} words. Cover ALL topics.\n\n'
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


@app.route("/api/ask", methods=["POST"])
def ask():
    try:
        data       = request.json
        question   = data.get("question",   "")
        transcript = data.get("transcript", "")

        if not question:
            return jsonify({"error": "No question provided"}), 400

        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model    = "llama-3.3-70b-versatile",
            messages = [{"role": "user", "content":
                f"You are a smart AI assistant.\n"
                f"1. If question relates to the video transcript, answer from it.\n"
                f"2. If question is general or asks for code, use your own knowledge.\n"
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


@app.route("/api/translate", methods=["POST"])
def translate():
    try:
        data     = request.json
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
                f"Only translate the text, nothing else.\n\n"
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
