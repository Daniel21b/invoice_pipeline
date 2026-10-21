#!/usr/bin/env python3
import aws_cdk as cdk
from invoice_pipeline.intelligence_stack import IntelligenceStack

app = cdk.App()
IntelligenceStack(app, "InvoiceIntelligenceStack")
app.synth()
