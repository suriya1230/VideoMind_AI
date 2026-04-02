# VideoMind AI — Deploy Guide

## 🚀 Deploy in 15 Minutes

### Step 1: Push to GitHub
```bash
git init
git add .
git commit -m "VideoMind AI website"
git remote add origin https://github.com/YOUR_USERNAME/video-ai-website.git
git push -u origin main
```

### Step 2: Deploy Backend on Render
1. Go to render.com → Sign up free
2. New → Web Service → Connect GitHub repo
3. Settings:
   - Root Directory : `backend`
   - Build Command  : `pip install -r requirements.txt`
   - Start Command  : `gunicorn app:app --bind 0.0.0.0:5000 --workers 1 --timeout 300`
4. Environment Variables:
   - `GROQ_API_KEY` = your_groq_api_key
5. Click Deploy → Wait 3-5 minutes
6. Copy your backend URL: `https://videoai-backend.onrender.com`

### Step 3: Update Frontend API URL
Open `frontend/index.html` → line 1:
```js
const API = 'https://videoai-backend.onrender.com'; // ← paste your URL here
```

### Step 4: Deploy Frontend on Render
1. Render → New → Static Site → Connect same repo
2. Settings:
   - Root Directory  : `frontend`
   - Publish Directory: `.`  (just a dot — it's a single HTML file)
3. Click Deploy
4. Your website: `https://videoai-frontend.onrender.com`

---

## ✅ Features
- YouTube URL input with playlist protection
- Video file upload with drag & drop
- Auto video type detection (Song / Movie / Educational)
- Smart summary scaling by video length
- Chat-style Q&A (video + general + code generation)
- Language chips + custom language translation
- Animated premium dark UI
- Mobile responsive

## 🔐 Security
- Never commit GROQ_API_KEY to GitHub
- Set it as environment variable in Render dashboard
- Regenerate if exposed: console.groq.com
