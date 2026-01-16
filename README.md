# Automated Invoice Processing Pipeline

Transform manual invoice data entry into a serverless cloud platform. Clients upload PDFs via secure portal → System automatically extracts data → Stores in database → Generates analytics dashboards.

##  What This Does

1. **Client uploads** PDF/image invoices via secure web portal (Streamlit)
2. **System automatically extracts** invoice data (text, tables, amounts) using AWS Textract
3. **Data stored** in PostgreSQL database with vendor, invoice number, date, line items, totals
4. **Client views reports** in embedded analytics dashboard (invoices over time, top vendors, etc.)
5. **Zero AWS Console access** - Client never sees AWS infrastructure (invisible cloud)

##  Quick Start

### Prerequisites
- AWS Account (free tier eligible)
- Python 3.11+
- Node.js (for CDK)
- AWS CLI (configured with credentials)

### Get Running in 5 Minutes

```bash
# 1. Create project directory
mkdir invoice-pipeline
cd invoice-pipeline

# 2. Initialize CDK project
npm install -g aws-cdk              # Install CDK globally (once)
cdk init app --language python

# 3. Create virtual environment
python -m venv .venv
source .venv/bin/activate            # On Windows: .venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Deploy first S3 bucket
cdk deploy

# 6. Verify deployment
aws s3 ls | grep invoice
```

Done! Your first cloud resource is live.

##  Architecture

### High-Level Flow
```
Streamlit Portal (Client)
    ↓ (upload PDF with presigned URL)
S3 Bucket (invoice storage)
    ↓ (event trigger)
Lambda Function (brain)
    ↓ (async call)
AWS Textract (OCR extraction)
    ↓ (store extracted data)
PostgreSQL (persistent database)
    ↓ (read queries)
Streamlit Dashboard (analytics)
```

### Components
- **Frontend**: Streamlit web app (Python, no React)
- **Processing**: Lambda function + AWS Textract
- **Storage**: RDS PostgreSQL (t3.micro, free tier)
- **IaC**: AWS CDK (Python-based infrastructure as code)

**See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed system design.**



# How I divided the workflow
| Phase | Focus | Status |
|-------|-------|--------|
| **1** | Foundation & project structure |  complete |
| **2** | S3 ingestion + Lambda trigger |  Complete |
| **3** | Textract OCR integration | Complete |
| **4** | RDS PostgreSQL setup | Complete |
| **5** | Streamlit web portal | Complete |
| **6** | Analytics dashboards | Complete |
| **7** | Account migration strategy | Complete |
| **8** | Monitoring & observability | Complete |

**Full roadmap**: See [invoice_pipeline_roadmap.md](invoice_pipeline_roadmap.md)

## 🛠️ Common Commands

```bash
# View all commands
make help

# Development
cdk synth              # Generate CloudFormation template
cdk diff               # See what will deploy
cdk deploy             # Deploy to AWS
cdk destroy            # Clean up resources (saves money)

# Testing
python -m pytest tests/ -v

# Virtual environment
source .venv/bin/activate   # Activate (macOS/Linux)
.venv\Scripts\activate      # Activate (Windows)
```

##  Tech Stack

- **Language**: Python 3.11+
- **Cloud**: AWS (Lambda, S3, RDS, Textract, IAM)
- **Infrastructure as Code**: AWS CDK v2
- **Frontend**: Streamlit
- **Database**: PostgreSQL 15
- **Testing**: Pytest

##  Project Structure

```
invoice-pipeline/
├── CLAUDE.md                         # AI agent context
├── llms.txt                          # LLM navigation
├── README.md                         # This file
├── Makefile                          # Common commands
├── requirements.txt                  # Python dependencies
├── cdk.json                          # CDK config
│
├── infrastructure/
│   └── invoice_pipeline_stack.py     # CDK stack definition
│
├── src/
│   ├── lambda_functions/
│   │   └── invoice_processor.py      # Lambda handler
│   └── web_portal/
│       └── app.py                    # Streamlit app
│
├── docs/
│   ├── ARCHITECTURE.md               # System design
│   ├── SETUP.md                      # Dev setup guide
│   ├── DEPLOYMENT.md                 # CDK deployment
│   ├── AWS_FREE_TIER.md              # Constraints
│   └── TROUBLESHOOTING.md            # Common issues
│
└── tests/
    ├── unit/
    │   └── test_invoice_processor.py
    └── integration/
        └── test_s3_lambda.py
```

##  Key Features

 **Serverless** - No servers to manage or monitor  
 **Cost-Optimized** - Uses AWS free tier limits ($0-$5/month typical)  
 **Scalable** - Handles 1-1000 invoices per month with same code  
 **Portable** - CDK makes it easy to transfer to client AWS account  
 **Secure** - S3 encryption, RDS no public access, presigned URLs  
 **Automated** - No manual data entry or copy-paste required  

##  Important Constraints

**AWS Free Tier Limits**:
- Lambda: 1M requests/month, 400K GB-seconds
- S3: 5GB storage, 20K GetObject requests/month  
- RDS: 750 hours/month t3.micro, 20GB storage
- **Textract**: ~$1 per 100 pages (NOT free tier)

**Other Limits**:
- RDS auto-stops after 7 days inactivity (personal account only)
- Lambda timeout max 15 minutes (Textract polling needs <10min)
- Presigned URLs expire in 15 minutes (generate fresh for each session)



### Testing Locally
```bash
# Unit tests
python -m pytest tests/unit/ -v

# Integration tests (need AWS credentials)
python -m pytest tests/integration/ -v

# All tests
python -m pytest tests/ -v
```

### Code Standards
- Type hints on all functions
- Docstrings for Lambda handlers
- Error handling returns structured JSON
- All logs go to CloudWatch
- Never hardcode secrets (use environment variables)

##  Support & Troubleshooting

See **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** for:
- Common CDK errors & fixes
- Lambda timeout issues
- Database connection problems
- S3 presigned URL issues
- Textract job failures

##  License

Proprietary - Client project (2026)

---

**Questions?** Check [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) or review **[CLAUDE.md](CLAUDE.md)** for project constraints.
