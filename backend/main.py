from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
import pdfplumber
import docx
import re
import os
import json
from pathlib import Path
from groq import Groq
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import List, Optional
import io

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path, override=True)

FRONTEND_PATH = Path(__file__).resolve().parent.parent / "frontend"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

missing_vars = [name for name, value in (
    ("SUPABASE_URL", SUPABASE_URL),
    ("SUPABASE_KEY", SUPABASE_KEY),
    ("GROQ_API_KEY", GROQ_API_KEY),
) if not value]
if missing_vars:
    raise RuntimeError(
        f"Missing environment variables in {env_path}: {', '.join(missing_vars)}"
    )

if SUPABASE_KEY.startswith("sb_publishable_"):
    raise RuntimeError(
        "SUPABASE_KEY appears to be a publishable key. Use a Supabase anon or service key instead."
    )

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as exc:
    raise RuntimeError(
        "Failed to create Supabase client. Check SUPABASE_URL and SUPABASE_KEY."
    ) from exc

groq_client = Groq(api_key=GROQ_API_KEY)

app = FastAPI(title="Talent Pool Search")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_ngrok_header(request, call_next):
    response = await call_next(request)
    return response

@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/", response_class=FileResponse)
def root():
    return FileResponse(FRONTEND_PATH / "index.html", media_type="text/html")


# ── Text extraction ──────────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = docx.Document(io.BytesIO(file_bytes))
    return "\n".join([para.text for para in doc.paragraphs])


# ── PII extraction (before scrubbing) ───────────────────────────────────────

def extract_pii(text: str) -> dict:
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    phone_pattern = r'(\+?\d[\d\s\-().]{7,}\d)'
    linkedin_pattern = r'(https?://)?(www\.)?linkedin\.com/in/[A-Za-z0-9_-]+'
    github_pattern = r'(https?://)?(www\.)?github\.com/[A-Za-z0-9_-]+'

    emails = re.findall(email_pattern, text)
    phones = re.findall(phone_pattern, text)
    linkedins = re.findall(linkedin_pattern, text)
    githubs = re.findall(github_pattern, text)

    # Try to extract name — first non-empty line heuristic
    name = ""
    for line in text.strip().split('\n'):
        line = line.strip()
        if line and len(line.split()) <= 5 and not any(c in line for c in ['@', ':', '/']):
            name = line
            break

    return {
        "name": name,
        "email": emails[0] if emails else "",
        "phone": phones[0].strip() if phones else "",
        "linkedin": linkedins[0] if linkedins else "",
        "github": githubs[0] if githubs else "",
    }


# ── PII scrubbing ────────────────────────────────────────────────────────────

def scrub_pii(text: str) -> str:
    # Emails
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
    # Phone numbers
    text = re.sub(r'(\+?\d[\d\s\-().]{7,}\d)', '[PHONE]', text)
    # LinkedIn URLs
    text = re.sub(r'(https?://)?(www\.)?linkedin\.com/in/[A-Za-z0-9_-]+', '[LINKEDIN]', text)
    # GitHub URLs
    text = re.sub(r'(https?://)?(www\.)?github\.com/[A-Za-z0-9_-]+', '[GITHUB]', text)
    return text


# ── AI extraction via Groq ───────────────────────────────────────────────────

def extract_with_ai(scrubbed_text: str) -> dict:
    prompt = f"""You are a resume parser. Extract information from the resume below.
Return ONLY a valid JSON object with these exact keys:
- skills: array of strings (technical and soft skills)
- years_experience: integer (total years of work experience, 0 if fresher)
- recent_job_title: string (most recent job title or "Fresher" if none)
- location: string (city and country if available, else "Not specified")

Resume:
{scrubbed_text[:3000]}

Return only JSON, no explanation, no markdown."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=800,
    )

    content = response.choices[0].message.content.strip()

    # Clean any markdown fences
    content = re.sub(r'```json|```', '', content).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "skills": [],
            "years_experience": 0,
            "recent_job_title": "Unknown",
            "location": "Not specified",
        }


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <html>
        <head>
            <title>Talent Pool API</title>
        </head>
        <body>
            <h1>Talent Pool API is running</h1>
            <p>Use the API endpoints or visit <a href='/docs'>/docs</a> for interactive API docs.</p>
            <h2>Upload resumes</h2>
            <form id="upload-form">
                <input type="file" id="file-input" name="files" multiple accept=".pdf,.docx" />
                <button type="submit">Upload</button>
            </form>
            <pre id="output" style="white-space: pre-wrap; border: 1px solid #ccc; padding: 10px; margin-top: 1rem;"></pre>
            <script>
                document.getElementById('upload-form').addEventListener('submit', async event => {
                    event.preventDefault();
                    const files = document.getElementById('file-input').files;
                    if (!files.length) {
                        alert('Please select one or more PDF or DOCX files.');
                        return;
                    }
                    const formData = new FormData();
                    for (const file of files) {
                        formData.append('files', file);
                    }
                    const response = await fetch('/upload', {
                        method: 'POST',
                        body: formData,
                    });
                    const data = await response.json();
                    document.getElementById('output').textContent = JSON.stringify(data, null, 2);
                });
            </script>
        </body>
    </html>
    """


@app.post("/upload")
async def upload_resumes(
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
):
    # Accept either multiple files under 'files' or a single file under 'file'
    uploads: List[UploadFile] = []
    if files:
        uploads.extend(files)
    if file:
        uploads.append(file)

    if not uploads:
        raise HTTPException(
            status_code=400,
            detail="No files uploaded. Use field name 'files' or 'file'.",
        )

    results = []

    for file in uploads:
        try:
            file_bytes = await file.read()
            filename = file.filename.lower()

            # Extract raw text
            if filename.endswith(".pdf"):
                raw_text = extract_text_from_pdf(file_bytes)
            elif filename.endswith(".docx"):
                raw_text = extract_text_from_docx(file_bytes)
            else:
                results.append({"file": file.filename, "status": "error", "message": "Unsupported file type"})
                continue

            if not raw_text.strip():
                results.append({"file": file.filename, "status": "error", "message": "Could not extract text"})
                continue

            # Extract PII before scrubbing
            pii = extract_pii(raw_text)

            # Scrub PII from text
            scrubbed_text = scrub_pii(raw_text)

            # AI extraction on scrubbed text
            ai_data = extract_with_ai(scrubbed_text)

            # Store in Supabase
            record = {
                "name": pii["name"],
                "email": pii["email"],
                "phone": pii["phone"],
                "linkedin": pii["linkedin"],
                "github": pii["github"],
                "skills": ai_data.get("skills", []),
                "years_experience": ai_data.get("years_experience", 0),
                "recent_job_title": ai_data.get("recent_job_title", "Unknown"),
                "location": ai_data.get("location", "Not specified"),
                "raw_text": scrubbed_text[:5000],
            }

            response = supabase.table("candidates").insert(record).execute()
            results.append({"file": file.filename, "status": "success", "name": pii["name"]})

        except Exception as e:
            results.append({"file": file.filename, "status": "error", "message": str(e)})

    return {"results": results}


@app.get("/candidates")
def get_candidates(
    skill: Optional[str] = None,
    min_experience: Optional[int] = None,
    location: Optional[str] = None,
):
    query = supabase.table("candidates").select("*").order("created_at", desc=True)
    response = query.execute()
    candidates = response.data

    # Filter in Python (Supabase free tier has limited array query support)
    if skill:
        skill_lower = skill.lower()
        candidates = [
            c for c in candidates
            if any(skill_lower in s.lower() for s in (c.get("skills") or []))
        ]

    if min_experience is not None:
        candidates = [
            c for c in candidates
            if (c.get("years_experience") or 0) >= min_experience
        ]

    if location:
        location_lower = location.lower()
        candidates = [
            c for c in candidates
            if location_lower in (c.get("location") or "").lower()
        ]

    return {"candidates": candidates, "total": len(candidates)}


@app.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: str):
    response = supabase.table("candidates").select("*").eq("id", candidate_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return response.data[0]


@app.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: str):
    supabase.table("candidates").delete().eq("id", candidate_id).execute()
    return {"message": "Candidate deleted"}
