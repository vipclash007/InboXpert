
import streamlit as st 
import requests

# ---------------- CONFIG ----------------
MISTRAL_API_KEY = st.secrets.get("MISTRAL_API_KEY", "")
BACKEND = st.secrets.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Job Application Agent", layout="wide")
st.title("⚡ Job Application Agent (Portia + Mistral)")


with st.sidebar:
    st.markdown("### Step 1: Gmail Authentication")
    if st.button("🔐 Start / Check Gmail Auth"):
        try:
            resp = requests.post(f"{BACKEND}/start-auth")
            if resp.ok:
                data = resp.json()
                if data.get("authenticated"):
                    st.success("Gmail already authenticated ✅")
                elif data.get("auth_url"):
                    st.warning("Authentication required:")
                    st.markdown(
                        f"[👉 Click here to authenticate Gmail]({data['auth_url']})",
                        unsafe_allow_html=True,
                    )
                else:
                    st.error("Unexpected response from backend.")
            else:
                st.error(f"Backend error: {resp.text}")
        except Exception as e:
            st.error(f"Error contacting backend: {e}")

# ---------------- Draft Emails ----------------
st.markdown("### Step 2: Generate Draft Emails")

col1, col2 = st.columns(2)
with col1:
    sheet_id = st.text_input("Google Sheet ID (columns: Company, HR Email, Job Role)")
with col2:
    resume_id = st.text_input("Google Drive Resume File ID (optional)")

if "drafts" not in st.session_state:
    st.session_state["drafts"] = []
if "resume_link" not in st.session_state:
    st.session_state["resume_link"] = ""

if st.button("📝 Generate Draft Emails"):
    if not sheet_id:
        st.warning("Please enter the Google Sheet ID.")
    else:
        with st.spinner("Generating drafts using AI..."):
            try:
                r = requests.post(
                    f"{BACKEND}/generate-drafts",
                    json={"sheet_id": sheet_id, "resume_id": resume_id},
                )
            except Exception as e:
                st.error(f"Backend request failed: {e}")
                r = None

        if not r or not r.ok:
            st.error(r.text if r else "Unknown error.")
        else:
            data = r.json()

            # FIX: surface backend error message if present
            if data.get("error"):
                st.error(data["error"])

            drafts = data.get("drafts", [])
            resume_link = data.get("resume_link", "")
            st.session_state["drafts"] = drafts
            st.session_state["resume_link"] = resume_link

            if drafts:
                st.success("✅ Drafts generated. Review below before sending.")
            else:
                st.info("No rows found in the sheet.")

# ---------------- Review + Send ----------------
drafts = st.session_state.get("drafts", [])
resume_link = st.session_state.get("resume_link", "")

if drafts:
    st.markdown("### Step 3: Review & Send Emails")

    updated_drafts = []
    for i, d in enumerate(drafts):
        st.divider()
        # FIX: Changed 'Job Role' to 'job_role'
        st.subheader(f"{i+1}. {d.get('company','')} — {d.get('job_role','')}") 
        # FIX: Changed 'HR Email' to 'hr_email'
        st.write(f"**To:** {d.get('hr_email','')}")

        subject = st.text_input(
            f"Subject {i+1}", value=d.get("subject",""), key=f"sub_{i}"
        )
        body = st.text_area(
            f"Email Body {i+1}", value=d.get("body",""), height=220, key=f"body_{i}"
        )

        updated_drafts.append({
            "to": d.get("hr_email"), # FIX: Changed 'HR Email' to 'hr_email'
            "subject": subject,
            "body": body
        })

    if st.button("📤 Send All Emails"):
        for draft in updated_drafts:
            to, subject, body = draft["to"], draft["subject"], draft["body"]
            with st.spinner(f"Sending email to {to}..."):
                s = requests.post(
                    f"{BACKEND}/send-email",
                    json={"to": to, "subject": subject, "body": body},
                )
            if s.ok:
                st.success(f"Email sent to {to} ✅")
            else:
                st.error(s.text)

        if resume_link:
            st.caption(f"📎 Resume attached: {resume_link}")
