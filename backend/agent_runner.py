# backend/agent_runner.py
import os
import re
import gdown
import pdfplumber
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv
from portia import Portia, Config, StorageClass, LLMProvider, DefaultToolRegistry
from portia.cli import CLIExecutionHooks
from portia.errors import PlanError

# --------- Resume helpers ----------
def download_resume(file_id: str, output_path="resume.pdf") -> str:
    url = f"https://drive.google.com/uc?id={file_id}"
    gdown.download(url, output_path, quiet=False)
    return output_path

def parse_resume(pdf_path="resume.pdf") -> str:
    text_content = ""
    if not os.path.exists(pdf_path):
        return ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text:
                text_content += page_text + "\n"
    return text_content.strip()

# --------- WebExecutionHooks (capture CLI auth URL) ----------
class WebExecutionHooks(CLIExecutionHooks):
    """
    Subclass CLIExecutionHooks to capture auth URL that would normally be printed to CLI.
    Portia calls on_auth_url when it needs the user to authenticate.
    We store the latest auth URL so the FastAPI endpoint can return it to the frontend.
    """
    def __init__(self):
        super().__init__()
        self.last_auth_url: Optional[str] = None

    def on_auth_url(self, url: str) -> None:
        # Save the URL where the frontend can pick it up.
        # Keep also printing so CLI users see it in terminal.
        try:
            print(f"[WebExecutionHooks] Auth URL captured: {url}")
        except Exception:
            pass
        self.last_auth_url = url
        
        try:
            super().on_auth_url(url)
        except Exception:
            
            pass


_PORTIA: Optional[Portia] = None
_HOOKS: Optional[WebExecutionHooks] = None
_AUTH_URL_PATTERN = re.compile(r"https?://accounts\.google\.com[^\s\"'>]+", re.I)

def init_portia_if_needed() -> Tuple[Portia, WebExecutionHooks]:
    global _PORTIA, _HOOKS
    if _PORTIA is not None and _HOOKS is not None:
        return _PORTIA, _HOOKS

    load_dotenv(override=True)
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

    config = Config.from_default(
        llm_provider=LLMProvider.MISTRALAI,
        default_model="mistralai/mistral-small-latest",
        mistralai_api_key=MISTRAL_API_KEY,
        storage_class=StorageClass.CLOUD,
    )

    hooks = WebExecutionHooks()
    portia = Portia(
        config=config,
        tools=DefaultToolRegistry(config),
        execution_hooks=hooks,
    )

    _PORTIA = portia
    _HOOKS = hooks
    return _PORTIA, _HOOKS


def ensure_gmail_auth() -> Dict:
    """
    Ask Portia Gmail tool if auth exists. If not, return the auth URL (captured by hooks).
    Returns a dict: {"authenticated": bool, "auth_url": Optional[str], "raw": Optional[str]}
    """
    portia, hooks = init_portia_if_needed()
    try:
        plan = portia.run(
            query=(
                "Check if Gmail is authenticated. "
                "If authenticated reply exactly AUTH_OK. Otherwise return the Google OAuth URL that the user must open."
            ),
            tools=["portia:google:gmail:send_email"],
        )
        out = str(getattr(getattr(plan.outputs, "final_output", None), "value", "") or "")
        if "AUTH_OK" in out:
            return {"authenticated": True, "auth_url": None, "raw": out}
        
        auth_url = None
       
        m = _AUTH_URL_PATTERN.search(out) if out else None
        if m:
            auth_url = m.group(0)
        
        if not auth_url:
            try:
                m2 = _AUTH_URL_PATTERN.search(plan.model_dump_json())
                if m2:
                    auth_url = m2.group(0)
            except Exception:
                pass
        
        if not auth_url and hooks.last_auth_url:
            auth_url = hooks.last_auth_url

        return {"authenticated": False, "auth_url": auth_url, "raw": out}
    except PlanError as pe:
        
        err_text = str(pe)
        m = _AUTH_URL_PATTERN.search(err_text)
        if m:
            return {"authenticated": False, "auth_url": m.group(0), "raw": err_text}
        return {"authenticated": False, "auth_url": hooks.last_auth_url if hooks.last_auth_url else None, "raw": err_text}
    except Exception as e:
        
        return {"authenticated": False, "auth_url": hooks.last_auth_url if hooks and getattr(hooks, "last_auth_url", None) else None, "raw": str(e)}


def _normalize_row_keys(row: Dict) -> Dict:
    """
    Normalize commonly-expected Google Sheet columns into snake_case keys:
    - Company -> company
    - HR Email or HR_Email or HR_Email -> hr_email
    - Job Role or Job_Role -> job_role
    Any other keys are preserved.
    """
    normalized = {}
    
    company = row.get("Company") or row.get("company") or row.get("COMPANY") or row.get("company_name") or ""
    hr_email = row.get("HR Email") or row.get("hr_email") or row.get("HR_Email") or row.get("Email") or ""
    job_role = row.get("Job Role") or row.get("job_role") or row.get("Role") or row.get("JobRole") or ""
    normalized["company"] = (company or "").strip()
    normalized["hr_email"] = (hr_email or "").strip()
    normalized["job_role"] = (job_role or "").strip()
    
    if "subject" in row:
        normalized["subject"] = row["subject"]
    if "body" in row:
        normalized["body"] = row["body"]
    return normalized

# --------- Generate drafts ----------
PROMPT_TEMPLATE = """You are an expert job application writer.
Write a concise ({word_limit} words max) professional email for:
Company: {company}
Role: {job_role}

Use relevant skills/projects from this resume to tailor the pitch:
{resume_text}

Rules:
- DO NOT include a subject line in the body.
- No meta text ("here's your email", etc.).
- Mention the company/role naturally.
- Close with a signature on separate lines (parsed from resume if possible):
  Full Name
  Email
  Phone
  LinkedIn (if present)
- End with: "I have attached my resume for your review: {resume_link}"

Output only the final email body in plain text.
"""

def generate_drafts(sheet_id: str, resume_id: str) -> Dict:
    """
    Retrieve rows via Portia (Google Sheets tool), parse resume if given,
    generate email bodies with Portia LLM and return a list of drafts (not sent).
    """
    portia, _hooks = init_portia_if_needed()

    # 1) get sheet rows
    try:
        sheet_result = portia.run(
            query=f"Retrieve all rows from the Google Sheet with ID {sheet_id}.",
            tools=["portia:google:sheets:get_spreadsheet"],
        )
        rows_raw = getattr(getattr(sheet_result.outputs, "final_output", None), "value", None) or {}
    except Exception as e:
        
        return {"drafts": [], "resume_link": "", "error": f"Failed to fetch Google Sheet rows: {str(e)}"}

    
    if isinstance(rows_raw, dict):
        
        if "Sheet1" in rows_raw:
            rows_list = rows_raw.get("Sheet1", [])
        elif "sheet1" in rows_raw:
            rows_list = rows_raw.get("sheet1", [])
        else:
            
            first_val = next(iter(rows_raw.values()), [])
            rows_list = first_val if isinstance(first_val, list) else []
    elif isinstance(rows_raw, list):
        rows_list = rows_raw
    else:
        rows_list = []

    resume_text, resume_link = "", ""
    if resume_id:
        try:
            resume_path = download_resume(resume_id)
            resume_text = parse_resume(resume_path)
            resume_link = f"https://drive.google.com/file/d/{resume_id}/view"
        except Exception:
            resume_text, resume_link = "", ""

    drafts = []
    for row_raw in rows_list:
        
        if isinstance(row_raw, dict):
            nr = _normalize_row_keys(row_raw)
        else:
            
            continue

        company = nr.get("company", "")
        hr_email = nr.get("hr_email", "")
        job_role = nr.get("job_role", "")

        prompt = PROMPT_TEMPLATE.format(
            company=company or "the company",
            job_role=job_role or "the role",
            resume_text=(resume_text or "")[:12000],
            resume_link=resume_link or "",
            word_limit=200,
        )

        
        try:
            email_resp = portia.run(query=prompt)
            
            raw_out = getattr(getattr(email_resp.outputs, "final_output", None), "value", None)
            if raw_out is None:
                body_text = ""
            else:
                body_text = str(raw_out).strip()
        except Exception as e:
            # If LLM failed, return a clear error body so frontend can show it
            body_text = f"[LLM generation failed: {str(e)}]"

        subject = f"Job Application - {job_role or 'the role'} at {company or 'Company'}"
        drafts.append({
            "company": company,
            "hr_email": hr_email,
            "job_role": job_role,
            "subject": subject,
            "body": body_text,
            "resume_link": resume_link,
        })

    return {"drafts": drafts, "resume_link": resume_link}

# --------- Send email ----------
def send_email(to_address: str, subject: str, body: str) -> Dict:
    """
    Use Portia Gmail tool to send a single email.
    Returns a dict with ok / error info.
    """
    portia, _hooks = init_portia_if_needed()
    # sanitize inputs
    to_address = str(to_address or "")
    subject = str(subject or "")
    body = str(body or "")

    try:
        result = portia.run(
            query=f"""
            Send an email using Gmail:
            To: {to_address}
            Subject: {subject}
            Body:
            {body}
            """,
            tools=["portia:google:gmail:send_email"],
        )
        
        out = getattr(getattr(result.outputs, "final_output", None), "value", None)
        return {"ok": True, "raw": str(out) if out is not None else ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}
