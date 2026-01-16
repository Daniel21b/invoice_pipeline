<div align="center">
  <img src="https://placehold.co/1200x350/232F3E/ffffff?text=Automated+Invoice+Processing+Pipeline" alt="Invoice Pipeline Banner" width="100%" />

  <h1>Automated Invoice Processing Pipeline</h1>

  <p>
    <strong>Transform manual data entry into an invisible, serverless cloud platform.</strong>
  </p>

  <p>
    <a href="https://www.python.org/">
      <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.11+">
    </a>
    <a href="https://aws.amazon.com/">
      <img src="https://img.shields.io/badge/AWS-Serverless-232F3E?style=flat&logo=amazon-aws&logoColor=white" alt="AWS">
    </a>
    <a href="https://streamlit.io/">
      <img src="https://img.shields.io/badge/Frontend-Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white" alt="Streamlit">
    </a>
    <a href="https://github.com/aws/aws-cdk">
      <img src="https://img.shields.io/badge/IaC-AWS%20CDK-8C4FFF?style=flat&logo=terraform&logoColor=white" alt="AWS CDK">
    </a>
    <img src="https://img.shields.io/badge/License-MIT-green?style=flat" alt="License">
  </p>

  <h4>
    <a href="#-demo">View Demo</a> •
    <a href="#-features">Features</a> •
    <a href="#-quick-start">Quick Start</a> •
    <a href="docs/ARCHITECTURE.md">Architecture</a>
  </h4>
</div>

<br />

## 🎥 Demo

<div align="center">
  <video src="https://github.com/user-attachments/assets/9b869613-a0ab-4605-9b82-60c0bbd7c887" controls="controls" muted="muted" style="max-width: 100%;">
  </video>
  <p><em>Watch the full Extract, Load, Analyze pipeline in action (0:45)</em></p>
</div>

---

## 🚀 What This Does

This project eliminates manual data entry by orchestrating a complete **Extract, Load, Analyze (ELA)** pipeline completely in the cloud.

| Step | Action | Tech Used |
| :--- | :--- | :--- |
| **1. Upload** | Client uploads PDF/Image via secure portal | **Streamlit** |
| **2. Extract** | System identifies text, tables, and amounts | **AWS Textract** |
| **3. Store** | Structured data is saved relationally | **PostgreSQL (RDS)** |
| **4. Visualize** | Client views costs, vendors, and timelines | **Dashboards** |
| **5. Invisible** | Zero console access required for the client | **Presigned URLs** |

---

## ✨ Key Features

<div align="center">

| ☁️ **Serverless** | 💰 **Cost-Optimized** | 🔒 **Secure** |
| :--- | :--- | :--- |
| No servers to manage. <br>Scales from 1 to 1k invoices. | Uses Free Tier limits. <br>Est. cost: $0-$5/month. | S3 Encryption, Private RDS, <br>Presigned URLs. |

</div>

<details>
<summary><strong>View Technical Constraints & Limits</strong></summary>

* **Lambda:** 1M requests/month (Free Tier)
* **S3:** 5GB Storage (Free Tier)
* **RDS:** t3.micro auto-stops after 7 days inactivity
* **Textract:** ~$1.50 per 1000 pages (Not Free Tier)
* **Timeouts:** Lambda max 15 mins (Textract polling)
</details>

---

## 🛠️ Tech Stack

* **Core:** ![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
* **Infrastructure:** ![AWS CDK](https://img.shields.io/badge/AWS_CDK-v2-orange)
* **Compute:** AWS Lambda, Step Functions
* **Storage:** S3 (Raw), RDS PostgreSQL 15 (Structured)
* **AI/OCR:** AWS Textract
* **Interface:** Streamlit (Python-only frontend)

---

## ⚡ Quick Start

### Prerequisites
* AWS Account (Free tier eligible)
* Python 3.11+ & Node.js (for CDK)
* AWS CLI configured

### Deploy in 5 Minutes

```bash
# 1. Clone & Init
git clone [https://github.com/yourusername/invoice-pipeline.git](https://github.com/yourusername/invoice-pipeline.git)
cd invoice-pipeline
npm install -g aws-cdk

# 2. Virtual Env Setup
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Deploy Stack
cdk bootstrap              # Prepare AWS environment (first time only)
cdk deploy                 # Push infrastructure to cloud
