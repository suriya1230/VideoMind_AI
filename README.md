# 🚀 VideoMind AI — Smart YouTube Video Analyzer

VideoMind AI is an advanced AI-powered system that extracts, transcribes, and summarizes YouTube videos - even without captions - using multiple fallback strategies and AI models.

---

# 🔥 Features

## 🎥 Video Processing

* Extract transcript from YouTube videos
* Supports:

  * English videos only ✅
  
## 🧠 AI Transcription (Multi-Engine System)

* Method 1: YouTube Transcript API
* Method 2: Supadata API
* Method 3: RapidAPI
* Method 4: Invidious Captions
* Method 5: Invidious Audio + Whisper
* Method 6: yt-dlp + Whisper (🔥 final fallback)

👉 Ensures **almost 100% success rate**

---

## ✨ AI Features

* 📄 Smart transcript cleaning
* 🧠 AI-based summarization (Groq LLaMA)
* 🎯 Chunked summarization for long videos
* 🌍 Multi-language detection (Tamil, Hindi, Telugu, etc.)
* 🔁 Translation support
* 💬 Ask questions from video (AI Q&A)

---

## 📊 Smart Analysis

* Detects:

  * Video type (Educational / Movie / Song)
  * Language
  * Word count
* Generates structured summaries:

  * Bullet points
  * Key insights
  * Clean readable output

---

## 📁 File Upload Support

* Upload video directly
* Extract audio
* Transcribe using Whisper AI

---

# ⚙️ Tech Stack

* Backend: Flask (Python)
* AI: Groq (Whisper + LLaMA)
* APIs: RapidAPI, Supadata
* Tools: yt-dlp, ffmpeg
* Frontend: HTML, CSS, JS
* Deployment: Render

---

# 🚀 Deploy in 15 Minutes

## Step 1: Push to GitHub

```bash
git init
git add .
git commit -m "VideoMind AI website"
git remote add origin https://github.com/YOUR_USERNAME/video-ai-website.git
git push -u origin main
```

---

## Step 2: Deploy Backend on Render

1. Go to https://render.com → Sign up (Free)
2. Click **New → Web Service**
3. Connect your GitHub repo

### Settings:

```
Root Directory : backend
Build Command  : pip install -r requirements.txt
Start Command  : gunicorn app:app --bind 0.0.0.0:5000 --workers 1 --timeout 300
```

### Environment Variables:

```
GROQ_API_KEY = your_groq_api_key
SUPADATA_KEY = (optional)
RAPIDAPI_KEY = (optional)
```

👉 Click **Deploy** → Wait 3–5 minutes

✅ Copy backend URL:

```
https://videoai-backend.onrender.com
```

---

## Step 3: Update Frontend API URL

Open:

```
frontend/index.html
```

Update:

```js
const API = 'https://videoai-backend.onrender.com';
```

---

## Step 4: Deploy Frontend on Render

1. Render → New → Static Site
2. Connect same repo

### Settings:

```
Root Directory    : frontend
Publish Directory : .
```

👉 Click **Deploy**

---

## 🌐 Final Output

Frontend:

```
https://videoai-frontend.onrender.com
```

Backend:

```
https://videoai-backend.onrender.com
```

---

# ⚠️ Important Notes

* Install dependencies:

```bash
pip install yt-dlp
```

* Install ffmpeg (required for audio processing)

* Always restart server after code changes

---

# 💡 Future Improvements

* Admin Dashboard 📊
* User analytics 📈
* History tracking 🕒
* Export summary (PDF/Docx)
* Real-time progress UI ⚡

---

# 👨‍💻 Author

Developed by **Suriya** 🚀

---

# ⭐ Support

If you like this project:

* ⭐ Star the repo
* 🔁 Share with others

---

# 🔥 Final Note

VideoMind AI is designed to **never fail on video processing** by using multiple fallback systems — making it production-ready and scalable.

---
Check My Web Site - link : https://videomind-ai-front-end.onrender.com
