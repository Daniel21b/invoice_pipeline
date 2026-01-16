# Invoice Pipeline Makefile
# Common commands for development and deployment

.PHONY: help install synth diff deploy destroy test clean

# Default target
help:
	@echo "Invoice Pipeline - Available Commands"
	@echo "======================================"
	@echo ""
	@echo "Setup:"
	@echo "  make install    - Install Python dependencies"
	@echo "  make bootstrap  - Bootstrap CDK (first time only)"
	@echo ""
	@echo "Development:"
	@echo "  make synth      - Synthesize CloudFormation template"
	@echo "  make diff       - Show changes to be deployed"
	@echo "  make deploy     - Deploy stack to AWS"
	@echo "  make destroy    - Destroy stack (cleanup)"
	@echo ""
	@echo "Testing:"
	@echo "  make test       - Run all tests"
	@echo "  make test-unit  - Run unit tests only"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean      - Remove build artifacts"
	@echo "  make verify     - Verify S3 bucket exists"

# Setup
install:
	pip install -r requirements.txt

bootstrap:
	cdk bootstrap

# Development
synth:
	cdk synth

diff:
	cdk diff

deploy:
	cdk deploy --require-approval never

destroy:
	cdk destroy --force

# Testing
test:
	python -m pytest tests/ -v

test-unit:
	python -m pytest tests/unit/ -v

# Utilities
clean:
	rm -rf cdk.out
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

verify:
	@echo "Checking for invoice bucket..."
	aws s3 ls | grep -i invoice || echo "No invoice bucket found"
