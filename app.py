from flask import Flask, request, jsonify
from flask_cors import CORS
import os, re, tempfile, requests
from collections import Counter
from groq import Groq

app = Flask(__name__)

CORS(app, resources={
    r"/api/*": {
        "origins"      : "*",
        "methods"      : ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

GROQ_API_KEY  = os.environ.get("GROQ_API_KEY",  "your_groq_key_here")
SUPADATA_KEY  = os.environ.get("SUPADATA_KEY",  "")
RAPIDAPI_KEY  = os.environ.get("RAPIDAPI_KEY",  "")

print("✅ Backend ready — VideoMind AI v7.0")


# ═══════════════════════════════════════════════════════════════
# TRANSCRIPTION — Groq Whisper API
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
# Get video title from oEmbed
# ═══════════════════════════════════════════════════════════════
def get_video_metadata(video_id):
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params  = {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout = 5
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("title", f"YouTube Video ({video_id})"), data.get("author_name", "YouTube")
    except Exception as e:
        print(f"   Metadata failed: {e}")
    return f"YouTube Video ({video_id})", "YouTube"


# ═══════════════════════════════════════════════════════════════
# METHOD 1 — youtube-transcript-api
# ═══════════════════════════════════════════════════════════════
def get_transcript_youtube_api(video_id):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        print("   [T1] Trying youtube-transcript-api...")

        languages = [
            'en','en-US','en-GB','en-IN',
            'ta','hi','te','ml','kn','bn',
            'fr','de','es','ar','ja','zh',
            'pt','ru','ko','it','nl',
        ]

        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id, languages=languages
        )
        transcript = " ".join([t.get("text","") for t in transcript_list]).strip()
        transcript = re.sub(r'<[^>]+>', ' ', transcript)
        transcript = re.sub(r'\s+', ' ', transcript).strip()

        if len(transcript) > 50:
            print(f"   ✅ T1 success ({len(transcript.split())} words)")
            return transcript

    except Exception as e:
        print(f"   T1 failed: {e}")

    return None


# ═══════════════════════════════════════════════════════════════
# METHOD 2 — Supadata API
# ═══════════════════════════════════════════════════════════════
def get_transcript_supadata(video_id):
    try:
        if not SUPADATA_KEY:
            print("   [T2] No SUPADATA_KEY — skipping")
            return None, None, 0, None

        print("   [T2] Trying Supadata...")
        r = requests.get(
            "https://api.supadata.ai/v1/youtube/transcript",
            params  = {"videoId": video_id, "lang": "en"},
            headers = {"x-api-key": SUPADATA_KEY},
            timeout = 30
        )
        if r.status_code != 200:
            print(f"   T2 error: {r.status_code}")
            return None, None, 0, None

        data       = r.json()
        transcript = " ".join([item.get("text","") for item in data.get("content",[])]).strip()

        if not transcript or len(transcript) < 50:
            return None, None, 0, None

        title = f"YouTube Video ({video_id})"
        dur   = 0
        ch    = "YouTube"

        try:
            meta = requests.get(
                "https://api.supadata.ai/v1/youtube/video",
                params={"videoId": video_id},
                headers={"x-api-key": SUPADATA_KEY},
                timeout=10
            )
            if meta.status_code == 200:
                m     = meta.json()
                title = m.get("title", title)
                dur   = m.get("duration", 0)
                ch    = m.get("channelName", "YouTube")
        except:
            pass

        print(f"   ✅ T2 success")
        return transcript, title, dur, ch

    except Exception as e:
        print(f"   T2 failed: {e}")

    return None, None, 0, None


# ═══════════════════════════════════════════════════════════════
# ✅ METHOD 3 — RapidAPI YouTube Transcript
# Works for Tamil/Telugu/Hindi even without captions
# ═══════════════════════════════════════════════════════════════
def get_transcript_rapidapi(video_id):
    try:
        if not RAPIDAPI_KEY:
            print("   [T3] No RAPIDAPI_KEY — skipping")
            return None

        print("   [T3] Trying RapidAPI...")

        # Try multiple RapidAPI YouTube transcript endpoints
        endpoints = [
            {
                "url"    : "https://youtube-transcript3.p.rapidapi.com/api/transcript-with-url",
                "params" : {"url": f"https://www.youtube.com/watch?v={video_id}", "lang": "ta"},
                "host"   : "youtube-transcript3.p.rapidapi.com",
            },
            {
                "url"    : "https://youtube-transcript3.p.rapidapi.com/api/transcript-with-url",
                "params" : {"url": f"https://www.youtube.com/watch?v={video_id}", "lang": "en"},
                "host"   : "youtube-transcript3.p.rapidapi.com",
            },
            {
                "url"    : "https://youtube-transcriptor.p.rapidapi.com/transcript",
                "params" : {"video_id": video_id, "lang": "ta"},
                "host"   : "youtube-transcriptor.p.rapidapi.com",
            },
            {
                "url"    : "https://youtube-transcriptor.p.rapidapi.com/transcript",
                "params" : {"video_id": video_id, "lang": "en"},
                "host"   : "youtube-transcriptor.p.rapidapi.com",
            },
        ]

        for ep in endpoints:
            try:
                r = requests.get(
                    ep["url"],
                    params  = ep["params"],
                    headers = {
                        "x-rapidapi-key" : RAPIDAPI_KEY,
                        "x-rapidapi-host": ep["host"],
                    },
                    timeout = 20
                )

                if r.status_code != 200:
                    continue

                data = r.json()

                # Handle different response formats
                transcript = ""

                if isinstance(data, list):
                    transcript = " ".join([
                        item.get("text","") if isinstance(item, dict) else str(item)
                        for item in data
                    ])
                elif isinstance(data, dict):
                    # Try common keys
                    for key in ["transcript","transcription","text","content","data"]:
                        val = data.get(key, [])
                        if isinstance(val, list):
                            transcript = " ".join([
                                item.get("text","") if isinstance(item, dict) else str(item)
                                for item in val
                            ])
                            break
                        elif isinstance(val, str) and len(val) > 50:
                            transcript = val
                            break
                elif isinstance(data, str):
                    transcript = data

                transcript = re.sub(r'<[^>]+>', ' ', transcript)
                transcript = re.sub(r'\s+', ' ', transcript).strip()

                if len(transcript) > 50:
                    print(f"   ✅ T3 RapidAPI success ({len(transcript.split())} words)")
                    return transcript

            except Exception as e:
                print(f"   T3 endpoint failed: {e}")
                continue

    except Exception as e:
        print(f"   T3 failed: {e}")

    return None


# ═══════════════════════════════════════════════════════════════
# METHOD 4 — Invidious Captions
# ═══════════════════════════════════════════════════════════════
def get_transcript_invidious(video_id):
    instances = [
        "https://invidious.io.lol",
        "https://yewtu.be",
        "https://invidious.kavin.rocks",
        "https://vid.puffyan.us",
        "https://inv.riverside.rocks",
        "https://invidious.nerdvpn.de",
    ]

    for instance in instances:
        try:
            print(f"   [T4] Invidious captions: {instance}")
            r = requests.get(
                f"{instance}/api/v1/videos/{video_id}",
                timeout=8, headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code != 200:
                continue

            data  = r.json()
            title = data.get("title",        f"YouTube Video ({video_id})")
            dur   = data.get("lengthSeconds", 0)
            ch    = data.get("author",        "YouTube")
            caps  = data.get("captions",      [])

            if not caps:
                continue

            en_caps    = [c for c in caps if "en" in c.get("languageCode","").lower()]
            target_cap = en_caps[0] if en_caps else caps[0]
            cap_url    = target_cap.get("url", "")
            if not cap_url:
                continue

            cap_r = requests.get(f"{instance}{cap_url}", timeout=10, headers={"User-Agent":"Mozilla/5.0"})
            if cap_r.status_code != 200:
                continue

            text = cap_r.text
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&amp;',  '&', text)
            text = re.sub(r'&lt;',   '<', text)
            text = re.sub(r'&gt;',   '>', text)
            text = re.sub(r'&quot;', '"', text)
            text = re.sub(r'\s+',    ' ', text).strip()

            if len(text) > 100:
                print(f"   ✅ T4 success: {instance}")
                return text, title, int(dur), ch

        except Exception as e:
            print(f"   T4 error {instance}: {e}")
            continue

    return None, None, 0, None


# ═══════════════════════════════════════════════════════════════
# ✅ METHOD 5 — Invidious Audio Download + Groq Whisper
# Works for Tamil/Telugu/Hindi without captions
# ═══════════════════════════════════════════════════════════════
def get_transcript_invidious_audio(video_id):
    instances = [
        "https://invidious.io.lol",
        "https://yewtu.be",
        "https://invidious.kavin.rocks",
        "https://vid.puffyan.us",
        "https://inv.riverside.rocks",
        "https://invidious.nerdvpn.de",
    ]

    for instance in instances:
        try:
            print(f"   [T5] Invidious audio: {instance}")
            r = requests.get(
                f"{instance}/api/v1/videos/{video_id}",
                timeout=10, headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code != 200:
                continue

            data  = r.json()
            title = data.get("title",          f"YouTube Video ({video_id})")
            dur   = data.get("lengthSeconds",   0)
            ch    = data.get("author",          "YouTube")

            # Get audio formats
            all_fmts   = data.get("adaptiveFormats", [])
            audio_fmts = [f for f in all_fmts if "audio" in f.get("type","") and f.get("url","")]

            if not audio_fmts:
                all_fmts   = data.get("formatStreams", [])
                audio_fmts = [f for f in all_fmts if f.get("url","")]

            if not audio_fmts:
                print(f"   No formats at {instance}")
                continue

            # Pick lowest bitrate to save bandwidth
            audio_fmts.sort(key=lambda x: x.get("bitrate", 999999))
            audio_url = audio_fmts[0].get("url","")
            if not audio_url:
                continue

            print(f"   Downloading audio from {instance}...")

            tmp_raw = os.path.join(tempfile.gettempdir(), f"yt_{video_id}.webm")
            tmp_wav = os.path.join(tempfile.gettempdir(), f"yt_{video_id}.wav")

            for p in [tmp_raw, tmp_wav]:
                if os.path.exists(p): os.remove(p)

            resp = requests.get(
                audio_url, stream=True, timeout=180,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer"   : f"https://www.youtube.com/watch?v={video_id}",
                }
            )

            if resp.status_code != 200:
                print(f"   Audio HTTP {resp.status_code}")
                continue

            size    = 0
            MAX_MB  = 20 * 1024 * 1024  # 20MB limit
            with open(tmp_raw, "wb") as f:
                for chunk in resp.iter_content(chunk_size=32768):
                    f.write(chunk)
                    size += len(chunk)
                    if size >= MAX_MB:
                        print(f"   Reached 20MB limit — stopping")
                        break

            print(f"   Downloaded: {size/1024/1024:.1f} MB")

            if size < 10000:
                print(f"   Too small — skip")
                if os.path.exists(tmp_raw): os.remove(tmp_raw)
                continue

            # Convert to compressed WAV
            ret = os.system(
                f"ffmpeg -i '{tmp_raw}' -ar 16000 -ac 1 -b:a 32k "
                f"'{tmp_wav}' -y 2>/dev/null"
            )
            if os.path.exists(tmp_raw): os.remove(tmp_raw)

            if not os.path.exists(tmp_wav):
                print("   FFmpeg failed")
                continue

            wav_mb = os.path.getsize(tmp_wav) / 1024 / 1024
            print(f"   WAV: {wav_mb:.1f}MB — sending to Groq Whisper...")

            transcript, lang = do_transcribe(tmp_wav)
            if os.path.exists(tmp_wav): os.remove(tmp_wav)

            if transcript and len(transcript.strip()) > 30:
                print(f"   ✅ T5 success! ({len(transcript.split())} words, lang={lang})")
                return transcript, title, int(dur), ch
            else:
                print(f"   Transcript too short — skip")

        except Exception as e:
            print(f"   T5 error {instance}: {e}")
            continue

    return None, None, 0, None


# ═══════════════════════════════════════════════════════════════
# MASTER YOUTUBE PROCESSOR
# ═══════════════════════════════════════════════════════════════
def get_youtube_transcript(url, video_id):
    title, channel = get_video_metadata(video_id)
    print(f"   Video: {title}")
    duration = 0
    lang     = "en"

    # Method 1: youtube-transcript-api (captions)
    print("\n[1/5] youtube-transcript-api")
    transcript = get_transcript_youtube_api(video_id)
    if transcript:
        return transcript, title, duration, channel, lang

    # Method 2: Supadata API
    print("\n[2/5] Supadata API")
    result = get_transcript_supadata(video_id)
    if result[0]:
        transcript, t, dur, ch = result
        if t:   title    = t
        if ch:  channel  = ch
        if dur: duration = dur
        return transcript, title, duration, channel, lang

    # Method 3: RapidAPI
    print("\n[3/5] RapidAPI")
    transcript = get_transcript_rapidapi(video_id)
    if transcript:
        return transcript, title, duration, channel, lang

    # Method 4: Invidious Captions
    print("\n[4/5] Invidious captions")
    result = get_transcript_invidious(video_id)
    if result[0]:
        transcript, t, dur, ch = result
        if t:   title    = t
        if ch:  channel  = ch
        if dur: duration = dur
        return transcript, title, duration, channel, lang

    # Method 5: Invidious Audio + Groq Whisper
    print("\n[5/5] Invidious audio + Groq Whisper")
    result = get_transcript_invidious_audio(video_id)
    if result[0]:
        transcript, t, dur, ch = result
        if t:   title    = t
        if ch:  channel  = ch
        if dur: duration = dur
        lang = detect_language(transcript)
        return transcript, title, duration, channel, lang

    return None, title, duration, channel, lang


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
    if   wc < 500:  return {"bullets":"3-4",  "words":"100-150","detail":"brief"}
    elif wc < 1500: return {"bullets":"4-5",  "words":"200-250","detail":"moderate"}
    elif wc < 3000: return {"bullets":"6-8",  "words":"300-400","detail":"detailed"}
    elif wc < 6000: return {"bullets":"8-10", "words":"450-550","detail":"very detailed"}
    else:           return {"bullets":"10-15","words":"600-800","detail":"comprehensive"}


def detect_video_type(transcript, title):
    client = Groq(api_key=GROQ_API_KEY)
    r = client.chat.completions.create(
        model    = "llama-3.3-70b-versatile",
        messages = [{"role":"user","content":
            f"Classify this video into ONE word: song, movie, or educational.\n"
            f"Title: {title}\n"
            f"Transcript: {' '.join(transcript.split()[:300])}\n"
            f"Category:"}],
        max_tokens=10, temperature=0.1,
    )
    cat = r.choices[0].message.content.strip().lower()
    if "song"  in cat: return "song"
    if "movie" in cat: return "movie"
    return "educational"


def detect_language(text):
    sample = text[:300]
    if any(c in sample for c in 'அஆஇஈஉஊஎஏஐஒஓஔ'): return 'ta'
    if any(c in sample for c in 'अआइईउऊएऐओऔ'):      return 'hi'
    if any(c in sample for c in 'అఆఇఈఉఊఎఏఐఒఓ'):     return 'te'
    if any(c in sample for c in 'അആഇഈഉഊഎഏഐഒ'):      return 'ml'
    if any(c in sample for c in 'ಅಆಇಈಉಊಎಏಐಒ'):      return 'kn'
    return 'en'


# ═══════════════════════════════════════════════════════════════
# ✅ SMART SUMMARIZE — handles long Tamil/regional transcripts
# ═══════════════════════════════════════════════════════════════
def smart_summarize(client, transcript, title, vtype, wc, cfg):
    """
    Chunked summarization for long transcripts.
    Tamil/Telugu text uses 3-4x more tokens than English.
    """
    text = clean_transcript(transcript)

    if vtype == "movie":
        prompt = (
            f'Tell the complete story of the movie: "{title}".\n'
            f'Include: main plot, key characters, important events, ending.\n'
            f'Write at least 300 words.'
        )
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            max_tokens=1500, temperature=0.3,
        )
        return r.choices[0].message.content.strip()

    words = text.split()

    # ✅ For long transcripts — use chunked summarization
    if wc > 2000:
        print(f"   Long transcript ({wc} words) — using chunked summarization")

        chunk_size = 1500
        chunks     = [
            " ".join(words[i:i+chunk_size])
            for i in range(0, min(len(words), 6000), chunk_size)
        ]

        print(f"   Processing {len(chunks)} chunks...")
        chunk_summaries = []

        for i, chunk in enumerate(chunks):
            try:
                r = client.chat.completions.create(
                    model    = "llama-3.3-70b-versatile",
                    messages = [{"role":"user","content":
                        f'Summarize this part of a video transcript in 3-4 clear bullet points.\n'
                        f'Be specific. Include all key concepts and details.\n'
                        f'The transcript may be in Tamil, Telugu, or another language — '
                        f'summarize in English.\n\n'
                        f'Transcript part {i+1}:\n{chunk}\n\n'
                        f'Bullet points (in English):'}],
                    max_tokens  = 500,
                    temperature = 0.3,
                )
                chunk_summaries.append(r.choices[0].message.content.strip())
                print(f"   Chunk {i+1}/{len(chunks)} done")
            except Exception as e:
                print(f"   Chunk {i+1} failed: {e}")
                continue

        if not chunk_summaries:
            raise Exception("All chunks failed")

        # Final merge
        combined = "\n\n".join(chunk_summaries)
        merge_prompt = (
            f'You have partial summaries of different parts of the video "{title}".\n'
            f'Combine them into ONE final well-structured summary.\n\n'
            f'Write:\n'
            f'- 1 opening sentence about the overall topic\n'
            f'- {cfg["bullets"]} detailed bullet points (2-3 sentences each)\n'
            f'- 1 strong closing sentence\n\n'
            f'Partial summaries:\n{combined}\n\n'
            f'Final Summary:'
        )

        r = client.chat.completions.create(
            model       = "llama-3.3-70b-versatile",
            messages    = [{"role":"user","content":merge_prompt}],
            max_tokens  = 2000,
            temperature = 0.3,
        )
        return r.choices[0].message.content.strip()

    else:
        # Short transcript — direct summarization
        text_limited = " ".join(words[:2000])
        prompt = (
            f'Summarize this video "{title}" ({wc} words).\n'
            f'The transcript may be in Tamil, Telugu, or another language.\n'
            f'Write the summary in English.\n\n'
            f'Write a {cfg["detail"]} summary:\n'
            f'- 1 opening sentence about the overall topic\n'
            f'- {cfg["bullets"]} detailed bullet points '
            f'(2-3 sentences each with specific details)\n'
            f'- 1 strong closing sentence\n'
            f'Total: {cfg["words"]} words.\n\n'
            f'Transcript:\n{text_limited}\n\nSummary:'
        )

        r = client.chat.completions.create(
            model       = "llama-3.3-70b-versatile",
            messages    = [{"role":"user","content":prompt}],
            max_tokens  = 2000,
            temperature = 0.3,
        )
        return r.choices[0].message.content.strip()


# ═══════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════
@app.route("/")
def home():
    return jsonify({
        "status" : "✅ VideoMind AI Backend is running",
        "version": "7.0",
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
    return jsonify({
        "status"      : "ok",
        "version"     : "7.0",
        "supadata_key": "set" if SUPADATA_KEY else "not set",
        "rapidapi_key": "set" if RAPIDAPI_KEY else "not set",
    })


@app.route("/api/process-url", methods=["POST","OPTIONS"])
def process_url():
    if request.method == "OPTIONS":
        return jsonify({"status":"ok"}), 200

    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error":"Invalid request body"}), 400

        url = data.get("url","").strip().strip('"').strip("'")
        if not url:
            return jsonify({"error":"No URL provided"}), 400

        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({"error":"Invalid YouTube URL. Use: https://www.youtube.com/watch?v=XXXXXXXXXXX"}), 400

        print(f"\n{'='*50}\nProcessing: {video_id}\n{'='*50}")

        transcript, title, duration, channel, lang = get_youtube_transcript(url, video_id)

        if not transcript or len(transcript.strip()) < 20:
            return jsonify({
                "error": (
                    "Could not get transcript for this video. "
                    "For Tamil/Telugu/Hindi videos without captions: "
                    "download the video using yt1s.com and use the "
                    "'Upload File' tab — Groq Whisper will transcribe it perfectly."
                )
            }), 500

        if lang == "en":
            lang = detect_language(transcript)

        vtype = detect_video_type(transcript, title)
        print(f"✅ Done: {title} | {lang} | {vtype} | {len(transcript.split())} words")

        return jsonify({
            "success"          : True,
            "transcript"       : transcript,
            "video_title"      : title,
            "channel"          : channel,
            "duration"         : f"{duration//60}m {duration%60}s" if duration else "—",
            "detected_language": lang,
            "word_count"       : len(transcript.split()),
            "video_type"       : vtype,
        })

    except Exception as e:
        print(f"process_url error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/process-file", methods=["POST","OPTIONS"])
def process_file():
    if request.method == "OPTIONS":
        return jsonify({"status":"ok"}), 200

    try:
        if "video" not in request.files:
            return jsonify({"error":"No file uploaded"}), 400

        f        = request.files["video"]
        filename = f.filename or "video.mp4"
        tmp_v    = os.path.join(tempfile.gettempdir(), "upload_video.mp4")
        tmp_a    = os.path.join(tempfile.gettempdir(), "upload_audio.wav")

        for p in [tmp_v, tmp_a]:
            if os.path.exists(p): os.remove(p)

        f.save(tmp_v)
        size_mb = os.path.getsize(tmp_v) / 1024 / 1024
        print(f"Uploaded: {filename} ({size_mb:.1f} MB)")

        os.system(f"ffmpeg -i '{tmp_v}' -ar 16000 -ac 1 -b:a 32k '{tmp_a}' -y 2>/dev/null")
        if os.path.exists(tmp_v): os.remove(tmp_v)

        if not os.path.exists(tmp_a):
            return jsonify({"error":"Audio extraction failed"}), 500

        transcript, lang = do_transcribe(tmp_a)
        if os.path.exists(tmp_a): os.remove(tmp_a)

        if not transcript or len(transcript.strip()) < 10:
            return jsonify({"error":"Transcription failed — video may have no audio"}), 500

        lang  = detect_language(transcript) if lang == "en" else lang
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


@app.route("/api/summarize", methods=["POST","OPTIONS"])
def summarize():
    if request.method == "OPTIONS":
        return jsonify({"status":"ok"}), 200

    try:
        data       = request.get_json(silent=True) or {}
        transcript = data.get("transcript", "")
        title      = data.get("video_title","")
        vtype      = data.get("video_type", "educational")

        if not transcript:
            return jsonify({"error":"No transcript provided"}), 400

        if vtype == "song":
            return jsonify({
                "success"   : True,
                "summary"   : None,
                "message"   : "🎵 Song detected — summarization not available.",
                "video_type": "song",
            })

        client = Groq(api_key=GROQ_API_KEY)
        wc     = len(transcript.split())
        cfg    = get_summary_config(wc)

        print(f"   Summarizing: {wc} words, type={vtype}")

        # ✅ Use smart chunked summarization
        summary = smart_summarize(client, transcript, title, vtype, wc, cfg)

        if not summary:
            return jsonify({"error":"Summary generation returned empty response"}), 500

        print(f"   ✅ Summary done: {len(summary.split())} words")

        return jsonify({
            "success"   : True,
            "summary"   : summary,
            "video_type": vtype,
            "word_count": wc,
        })

    except Exception as e:
        print(f"summarize error: {e}")
        return jsonify({"error": f"Summary failed: {str(e)}"}), 500


@app.route("/api/ask", methods=["POST","OPTIONS"])
def ask():
    if request.method == "OPTIONS":
        return jsonify({"status":"ok"}), 200

    try:
        data       = request.get_json(silent=True) or {}
        question   = data.get("question",   "")
        transcript = data.get("transcript", "")

        if not question:
            return jsonify({"error":"No question provided"}), 400

        transcript_limited = " ".join(transcript.split()[:6000])

        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model    = "llama-3.3-70b-versatile",
            messages = [{"role":"user","content":
                f"You are a smart AI assistant.\n"
                f"1. If the question relates to the video transcript, answer from it.\n"
                f"2. If the question is general or asks for code, use your knowledge.\n"
                f"3. For code requests always write complete working code with comments.\n\n"
                f"Video Transcript:\n{transcript_limited}\n\n"
                f"Question: {question}\n\nAnswer:"}],
            max_tokens=1500, temperature=0.5,
        )

        return jsonify({"success":True, "answer":r.choices[0].message.content.strip()})

    except Exception as e:
        print(f"ask error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/translate", methods=["POST","OPTIONS"])
def translate():
    if request.method == "OPTIONS":
        return jsonify({"status":"ok"}), 200

    try:
        data     = request.get_json(silent=True) or {}
        language = data.get("language","")
        summary  = data.get("summary", "")

        if not language:
            return jsonify({"error":"No language provided"}), 400
        if not summary:
            return jsonify({"error":"No summary to translate"}), 400

        client = Groq(api_key=GROQ_API_KEY)
        r = client.chat.completions.create(
            model    = "llama-3.3-70b-versatile",
            messages = [{"role":"user","content":
                f"Translate this video summary to {language}.\n"
                f"Keep the bullet point structure exactly as it is.\n"
                f"Only translate — do not add any extra text.\n\n"
                f"Summary:\n{summary}\n\n"
                f"{language} Translation:"}],
            max_tokens=1000, temperature=0.2,
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
