from flask import Flask, request, jsonify
from flask_cors import CORS
import os, re, tempfile
from collections import Counter
from groq import Groq
import shutil

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "your_key_here")

# ✅ No Whisper model loaded — uses Groq API instead (zero RAM)
print("✅ Backend ready — using Groq Whisper API")

# ─── Transcribe using Groq Whisper API ──────────────────────────────────────
def do_transcribe(audio_path):
    """
    Uses Groq's free Whisper API — no local model needed.
    Groq supports files up to 25MB.
    For larger files we split into chunks.
    """
    client    = Groq(api_key=GROQ_API_KEY)
    file_size = os.path.getsize(audio_path) / (1024*1024)  # MB

    print(f"   Audio size: {file_size:.1f} MB")

    if file_size <= 24:
        # ✅ Small file — send directly
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file            = (os.path.basename(audio_path), f),
                model           = "whisper-large-v3",
                response_format = "verbose_json",
            )
        return result.text.strip(), result.language

    else:
        # ✅ Large file — split into 20MB chunks using ffmpeg
        print("   Large file — splitting into chunks...")
        chunks      = []
        chunk_dur   = 600  # 10 minutes per chunk in seconds
        chunk_index = 0
        transcripts = []

        # Get total duration
        import subprocess
        probe = subprocess.run([
            "ffprobe","-v","quiet","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1", audio_path
        ], capture_output=True, text=True)
        total_dur = float(probe.stdout.strip())

        start = 0
        while start < total_dur:
            chunk_file = os.path.join(tempfile.gettempdir(), f"chunk_{chunk_index}.wav")
            os.system(f"ffmpeg -i '{audio_path}' -ss {start} -t {chunk_dur} "
                      f"-ar 16000 -ac 1 '{chunk_file}' -y -q:a 0 2>/dev/null")

            if os.path.exists(chunk_file):
                chunks.append(chunk_file)
                with open(chunk_file, "rb") as f:
                    r = client.audio.transcriptions.create(
                        file            = (f"chunk_{chunk_index}.wav", f),
                        model           = "whisper-large-v3",
                        response_format = "verbose_json",
                    )
                transcripts.append(r.text)
                lang = r.language
                os.remove(chunk_file)
                print(f"   Chunk {chunk_index+1} done")

            start        += chunk_dur
            chunk_index  += 1

        return " ".join(transcripts).strip(), lang

# ─── Helpers ────────────────────────────────────────────────────────────────
def clean_transcript(text):
    fillers = [
        r"\bum+\b",r"\buh+\b",r"\bumm+\b",r"\bokay+\b",r"\bright\b",
        r"\byou know\b",r"\bi mean\b",r"\bbasically\b",r"\bactually\b",
        r"\bliterally\b",r"\blet's say\b",r"\bgo ahead\b",r"\bi think\b",
    ]
    for f in fillers:
        text = re.sub(f, "", text, flags=re.IGNORECASE)
    text = re.sub(r'\b(\w+)(\s+\1){1,}\b', r'\1', text, flags=re.IGNORECASE)
    words     = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    counts    = Counter(words)
    threshold = max(20, int(len(words)*0.015))
    whitelist = {
        "the","and","that","this","with","from","have","will","are",
        "for","not","can","you","your","they","about","what","when",
        "how","all","also","use","data","model","video","language"
    }
    for w,c in counts.items():
        if c > threshold and w not in whitelist:
            text = re.sub(rf'\b{re.escape(w)}\b', '', text, flags=re.IGNORECASE)
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
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":
            f"Classify this video: song, movie, or educational. ONE word only.\n"
            f"Title: {title}\nTranscript: {' '.join(transcript.split()[:300])}\nCategory:"}],
        max_tokens=10, temperature=0.1)
    cat = r.choices[0].message.content.strip().lower()
    if "song"  in cat: return "song"
    if "movie" in cat: return "movie"
    return "educational"

# ─── Routes ─────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({
        "status" : "✅ VideoMind AI Backend is running",
        "version": "2.0",
        "routes" : [
            "POST /api/process-url",
            "POST /api/process-file",
            "POST /api/summarize",
            "POST /api/ask",
            "POST /api/translate",
            "GET  /api/health"
        ]
    })

@app.route("/api/health")
def health():
    return jsonify({"status":"ok","mode":"groq-whisper-api"})


def get_cookies_path():
    """
    Copy cookies from read-only secret location to writable temp folder.
    """
    secret_path = "/etc/secrets/cookies.txt"
    temp_path   = os.path.join(tempfile.gettempdir(), "cookies.txt")

    if os.path.exists(secret_path):
        # ✅ Copy to writable temp location
        shutil.copy2(secret_path, temp_path)
        print("✅ Cookies copied to temp")
        return temp_path

    elif os.path.exists(temp_path):
        return temp_path

    print("⚠ No cookies found")
    return None

@app.route("/api/process-url", methods=["POST"])
def process_url():
    try:
        url = request.json.get("url","").strip()
        if not url: return jsonify({"error":"No URL"}), 400

        import yt_dlp
        out          = os.path.join(tempfile.gettempdir(), "audio_raw")
        cookies_path = get_cookies_path()   # ✅ use temp writable path

        opts = {
            "format"    : "bestaudio/best/worstaudio/worst",
            "outtmpl"   : out,
            "noplaylist": True,
            "postprocessors":[{
                "key"            : "FFmpegExtractAudio",
                "preferredcodec" : "wav",
                "preferredquality": "192"
            }],

            # ✅ Only add cookiefile if it exists
            **( {"cookiefile": cookies_path} if cookies_path else {} ),

            "extractor_args": {
                "youtube": {
                    "player_client": [
                        "web_creator",
                        "android_vr",
                        "android_embedded",
                        "web_embedded",
                        "android",
                        "web"
                    ]
                }
            },
            "http_headers": {
                "User-Agent"     : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            "sleep_interval"         : 3,
            "max_sleep_interval"     : 8,
            "sleep_interval_requests": 2,
            "quiet"      : True,
            "no_warnings": False,
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            info     = ydl.extract_info(url, download=True)
            title    = info.get("title",   "Unknown")
            duration = info.get("duration", 0)
            channel  = info.get("uploader","Unknown")

        wav = out + ".wav"
        if not os.path.exists(wav):
            for ext in [".webm",".m4a",".opus",".mp3"]:
                candidate = out + ext
                if os.path.exists(candidate):
                    os.system(f"ffmpeg -i '{candidate}' '{wav}' -y -q:a 0")
                    os.remove(candidate)
                    break

        if not os.path.exists(wav):
            return jsonify({"error":"Audio download failed — try again in a few minutes"}), 500

        transcript, lang = do_transcribe(wav)
        if os.path.exists(wav): os.remove(wav)

        vtype = detect_video_type(transcript, title)

        return jsonify({
            "success"          : True,
            "transcript"       : transcript,
            "video_title"      : title,
            "channel"          : channel,
            "duration"         : f"{duration//60}m {duration%60}s",
            "detected_language": lang,
            "word_count"       : len(transcript.split()),
            "video_type"       : vtype
        })

    except Exception as e:
        error_msg = str(e)
        if "Sign in" in error_msg or "bot" in error_msg:
            return jsonify({"error":"YouTube blocked this. Please try again in 2-3 minutes."}), 500
        elif "429" in error_msg:
            return jsonify({"error":"Too many requests. Wait 5 minutes and try again."}), 500
        elif "Errno 30" in error_msg or "Read-only" in error_msg:
            return jsonify({"error":"Server file system error. Cookies path issue — contact admin."}), 500
        else:
            return jsonify({"error": error_msg}), 500

@app.route("/api/process-file", methods=["POST"])
def process_file():
    try:
        if "video" not in request.files:
            return jsonify({"error":"No file uploaded"}), 400

        f     = request.files["video"]
        tmp_v = os.path.join(tempfile.gettempdir(),"upload.mp4")
        tmp_a = os.path.join(tempfile.gettempdir(),"upload.wav")
        f.save(tmp_v)

        # Convert to compressed wav — keep under 25MB
        os.system(f"ffmpeg -i '{tmp_v}' -ar 16000 -ac 1 -b:a 32k '{tmp_a}' -y 2>/dev/null")

        if not os.path.exists(tmp_a):
            return jsonify({"error":"Audio extraction failed"}), 500

        transcript, lang = do_transcribe(tmp_a)

        for p in [tmp_v, tmp_a]:
            if os.path.exists(p): os.remove(p)

        vtype = detect_video_type(transcript, f.filename)

        return jsonify({
            "success":True, "transcript":transcript,
            "video_title":f.filename, "detected_language":lang,
            "word_count":len(transcript.split()), "video_type":vtype
        })

    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/summarize", methods=["POST"])
def summarize():
    try:
        data       = request.json
        transcript = data.get("transcript","")
        title      = data.get("video_title","")
        vtype      = data.get("video_type","educational")

        if vtype == "song":
            return jsonify({"success":True,"summary":None,
                "message":"🎵 Song detected — summarization not available.",
                "video_type":"song"})

        client = Groq(api_key=GROQ_API_KEY)
        text   = clean_transcript(transcript)
        wc     = len(transcript.split())
        cfg    = get_summary_config(wc)

        if vtype == "movie":
            prompt = f'Tell the complete story of the movie: "{title}". 300+ words.'
        else:
            prompt = (
                f'Summarize this video "{title}" ({wc} words) — {cfg["detail"]} summary.\n'
                f'- 1 opening sentence\n'
                f'- {cfg["bullets"]} bullet points (2-3 sentences each, include specific details)\n'
                f'- 1 closing sentence\n'
                f'Total: {cfg["words"]} words. Cover ALL topics.\n\n'
                f'Transcript:\n{text}\n\nSummary:'
            )

        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            max_tokens=1500, temperature=0.3)

        return jsonify({
            "success":True,
            "summary":r.choices[0].message.content.strip(),
            "video_type":vtype, "word_count":wc
        })

    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/ask", methods=["POST"])
def ask():
    try:
        data   = request.json
        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":
                f"Smart AI assistant. Answer from transcript if related, else general knowledge. "
                f"For code requests write complete working code.\n\n"
                f"Transcript:\n{data.get('transcript','')}\n\n"
                f"Q: {data.get('question','')}\nA:"}],
            max_tokens=1500, temperature=0.5)
        return jsonify({"success":True,
            "answer":r.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/translate", methods=["POST"])
def translate():
    try:
        data   = request.json
        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":
                f"Translate to {data.get('language')}. Keep bullet structure.\n\n"
                f"{data.get('summary','')}"}],
            max_tokens=800, temperature=0.2)
        return jsonify({"success":True,
            "translated":r.choices[0].message.content.strip(),
            "language":data.get("language")})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
