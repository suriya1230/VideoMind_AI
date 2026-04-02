from flask import Flask, request, jsonify
from flask_cors import CORS
import torch, re, os, tempfile
from collections import Counter
from groq import Groq

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "your_groq_api_key_here")

# Load Whisper once at startup
print("Loading Whisper model...")
try:
    from faster_whisper import WhisperModel
    device       = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    whisper_model = WhisperModel("small", device=device, compute_type=compute_type)
    print(f"✅ faster-whisper loaded on {device}")
    USE_FASTER = True
except:
    import whisper
    whisper_model = whisper.load_model("small")
    USE_FASTER = False
    print("✅ whisper loaded on CPU")

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
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    counts = Counter(words)
    threshold = max(20, int(len(words)*0.015))
    whitelist = {"the","and","that","this","with","from","have","will","are",
                 "for","not","can","you","your","they","about","what","when",
                 "how","all","also","use","data","model","video","language"}
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

def do_transcribe(audio_path):
    if USE_FASTER:
        segs, info = whisper_model.transcribe(audio_path, beam_size=5,
                         vad_filter=True, condition_on_previous_text=False)
        return " ".join(s.text for s in segs).strip(), info.language
    else:
        r = whisper_model.transcribe(audio_path, fp16=False)
        return r["text"].strip(), r.get("language","en")

# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status":"ok","device":device if USE_FASTER else "cpu"})

@app.route("/api/process-url", methods=["POST"])
def process_url():
    try:
        url = request.json.get("url","").strip()
        if not url: return jsonify({"error":"No URL"}), 400

        import yt_dlp
        out = os.path.join(tempfile.gettempdir(), "audio_raw")
        cookies = "/app/cookies.txt"
        opts = {
            "format":"bestaudio/best/worstaudio/worst","outtmpl":out,"noplaylist":True,
            "postprocessors":[{"key":"FFmpegExtractAudio","preferredcodec":"wav","preferredquality":"192"}],
            **( {"cookiefile":cookies} if os.path.exists(cookies) else {} ),
            "extractor_args":{"youtube":{"player_client":["android","web"]}},
            "quiet":True, "sleep_interval":2, "max_sleep_interval":4,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title    = info.get("title","Unknown")
            duration = info.get("duration",0)
            channel  = info.get("uploader","Unknown")

        wav = out+".wav"
        if not os.path.exists(wav):
            for ext in [".webm",".m4a",".opus",".mp3"]:
                if os.path.exists(out+ext):
                    os.system(f"ffmpeg -i '{out+ext}' '{wav}' -y -q:a 0"); break

        transcript, lang = do_transcribe(wav)
        if os.path.exists(wav): os.remove(wav)
        vtype = detect_video_type(transcript, title)

        return jsonify({"success":True,"transcript":transcript,"video_title":title,
            "channel":channel,"duration":f"{duration//60}m {duration%60}s",
            "detected_language":lang,"word_count":len(transcript.split()),"video_type":vtype})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/process-file", methods=["POST"])
def process_file():
    try:
        if "video" not in request.files: return jsonify({"error":"No file"}), 400
        f = request.files["video"]
        tmp_v = os.path.join(tempfile.gettempdir(),"upload.mp4")
        tmp_a = os.path.join(tempfile.gettempdir(),"upload.wav")
        f.save(tmp_v)
        os.system(f"ffmpeg -i '{tmp_v}' '{tmp_a}' -y -q:a 0")
        transcript, lang = do_transcribe(tmp_a)
        for p in [tmp_v,tmp_a]:
            if os.path.exists(p): os.remove(p)
        vtype = detect_video_type(transcript, f.filename)
        return jsonify({"success":True,"transcript":transcript,"video_title":f.filename,
            "detected_language":lang,"word_count":len(transcript.split()),"video_type":vtype})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/summarize", methods=["POST"])
def summarize():
    try:
        data = request.json
        transcript = data.get("transcript","")
        title      = data.get("video_title","")
        vtype      = data.get("video_type","educational")

        if vtype == "song":
            return jsonify({"success":True,"summary":None,
                "message":"🎵 Song detected — summarization not available.","video_type":"song"})

        client = Groq(api_key=GROQ_API_KEY)
        text   = clean_transcript(transcript)
        wc     = len(transcript.split())
        cfg    = get_summary_config(wc)

        if vtype == "movie":
            prompt = f'Tell me the complete story of the movie in title: "{title}". 300+ words.'
        else:
            prompt = (f'Summarize this video "{title}" ({wc} words) with {cfg["detail"]} detail.\n'
                      f'- 1 opening sentence\n- {cfg["bullets"]} bullet points (2-3 sentences each)\n'
                      f'- 1 closing sentence\nTotal: {cfg["words"]} words. Cover ALL topics.\n\n'
                      f'Transcript:\n{text}\n\nSummary:')

        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            max_tokens=1500, temperature=0.3)
        return jsonify({"success":True,"summary":r.choices[0].message.content.strip(),
            "video_type":vtype,"word_count":wc})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/ask", methods=["POST"])
def ask():
    try:
        data = request.json
        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":
                f"You are a smart AI. Answer from video transcript if related, else use general knowledge. "
                f"For code requests always write complete working code.\n\n"
                f"Transcript:\n{data.get('transcript','')}\n\nQ: {data.get('question','')}\nA:"}],
            max_tokens=1500, temperature=0.5)
        return jsonify({"success":True,"answer":r.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/translate", methods=["POST"])
def translate():
    try:
        data = request.json
        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":
                f"Translate keeping bullet structure. Language: {data.get('language')}\n\n"
                f"{data.get('summary','')}"}],
            max_tokens=800, temperature=0.2)
        return jsonify({"success":True,"translated":r.choices[0].message.content.strip(),
            "language":data.get("language")})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
