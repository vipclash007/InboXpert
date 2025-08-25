# InboXpert  
An AI agent that helps automate your job applications by managing emails, extracting information, and streamlining job workflows.  

---

## 🚀 Features
- Automates job application tasks via email.
- Integrates with Google APIs (Gmail, Sheets).
- Runs with FastAPI backend + AI agent runner.
- Easily extensible for other automation workflows.

---

## 🛠️ Setup Instructions

### 1. Clone the Repository
git clone https://github.com/vipclash007/inboXpert.git
cd inboXpert

### 2. Create Virtual Environment
python -m venv .venv

Activate it:  
Windows (PowerShell) - venv\Scripts\activate
Linux/Mac - source .venv/bin/activate

### 3. Install Dependencies:
pip install -r requirements.txt

### 4. Setup Environment Variables
Create a .env file in the project root and add the required keys:

MISTRAL_API_KEY=your_mistral_api_key
PORTIA_API_KEY=your_portia_api_key

## Running Locally
1. Start the FastAPI Backend
- uvicorn main:app --reload

2. Access the API
Open in your browser:
👉 http://127.0.0.1:8000/
