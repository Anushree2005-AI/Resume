# TalentPool — Resume Search App

A full-stack web app that lets recruiters upload resumes, automatically extract candidate information using AI, and search/filter their talent pool.

## Features

- Upload multiple PDF or DOCX resumes at once
- PII scrubbing before any AI processing (emails, phones, LinkedIn, GitHub replaced with placeholders)
- AI-powered extraction of skills, experience, job title, and location (via Groq + LLaMA 3 70B)
- Supabase database storage
- Search and filter by skill, years of experience, and location
- Click any candidate to view full profile including contact details

## Tech Stack

- **Backend:** FastAPI (Python)
- **Database:** Supabase (PostgreSQL)
- **AI Model:** Groq — LLaMA 3 70B (fast, free tier, generous limits)
- **Frontend:** Vanilla HTML + CSS + JS (no framework needed)
- **Deployment:** Render (backend) + Vercel (frontend)

## Why Groq + LLaMA 3 70B?

Groq's inference is extremely fast (typically under 2 seconds per resume) and has a generous free tier — perfect for batch processing resumes. LLaMA 3 70B gives excellent structured JSON extraction accuracy compared to smaller models.

## Local Setup

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Create a `.env` file in `/backend`:

```
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
GROQ_API_KEY=your_groq_api_key
```

Run the server:

```bash
uvicorn main:app --reload
```

Backend runs at: http://localhost:8000

### Frontend

Open `frontend/index.html` in your browser — or serve it:

```bash
cd frontend
python -m http.server 3000
```

Make sure the `API` variable in `index.html` points to `http://localhost:8000` for local dev.

### Supabase Table Setup

Run this in your Supabase SQL Editor:

```sql
CREATE TABLE candidates (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name TEXT,
  email TEXT,
  phone TEXT,
  linkedin TEXT,
  github TEXT,
  skills TEXT[],
  years_experience INTEGER,
  recent_job_title TEXT,
  location TEXT,
  raw_text TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

## What I'd Add Next

**Smart duplicate detection** — before inserting, check if a candidate with the same email already exists and offer to update their profile instead. Recruiters often get updated resumes from the same person months apart.

## Deployment

- Backend: Deploy to [Render](https://render.com) as a Python web service
- Frontend: Deploy to [Vercel](https://vercel.com) by importing the frontend folder
- Set environment variables in Render dashboard (same as .env)
- Update the `API` constant in `index.html` to your Render backend URL before deploying frontend