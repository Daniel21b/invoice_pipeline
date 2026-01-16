"""
Invoice Pipeline CDK Stack - Phase 3

Creates the AWS resources for the invoice processing pipeline.
Phase 1: S3 bucket for invoice storage with proper security settings.
Phase 2: Lambda function triggered by S3 events with CloudWatch logging.
Phase 3: Textract OCR integration for PDF processing.
"""

import os
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    CfnOutput,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_s3_notifications as s3n,
    aws_iam as iam,
)
from constructs import Construct
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class InvoicePipelineStack(Stack):
    """
    Main CDK stack for the Invoice Processing Pipeline.

    Phase 1 Resources:
    - S3 bucket for invoice PDF storage with encryption and lifecycle rules

    Phase 2 Resources:
    - Lambda function triggered by S3 events
    - IAM role with S3 read and CloudWatch permissions
    - S3 EventNotification to Lambda

    Phase 3 Resources:
    - Textract IAM permissions for OCR processing
    - Extended Lambda timeout for Textract calls
    - Environment variables for RDS connection

    Future Phases:
    - RDS PostgreSQL (Phase 4)
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # S3 Bucket configuration
        # Use existing bucket from environment variable, or create new one
        existing_bucket_name = os.getenv("S3_BUCKET")

        if existing_bucket_name:
            # Use existing bucket (user already created it)
            self.invoice_bucket = s3.Bucket.from_bucket_name(
                self,
                "InvoiceBucket",
                bucket_name=existing_bucket_name,
            )
        else:
            # Create new bucket with proper security settings
            self.invoice_bucket = s3.Bucket(
                self,
                "InvoiceBucket",
                bucket_name=None,  # Auto-generate unique name
                encryption=s3.BucketEncryption.S3_MANAGED,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                versioned=False,  # Free tier optimization
                removal_policy=RemovalPolicy.DESTROY,  # Dev only - change for prod
                auto_delete_objects=True,  # Dev only - removes objects on stack destroy
                cors=[
                    s3.CorsRule(
                        allowed_methods=[
                            s3.HttpMethods.GET,
                            s3.HttpMethods.PUT,
                            s3.HttpMethods.POST,
                        ],
                        allowed_origins=["*"],  # Tighten in production
                        allowed_headers=["*"],
                        max_age=3000,
                    )
                ],
                lifecycle_rules=[
                    s3.LifecycleRule(
                        id="ArchiveOldInvoices",
                        enabled=True,
                        transitions=[
                            s3.Transition(
                                storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                                transition_after=Duration.days(90),
                            )
                        ],
                    )
                ],
            )

        # Output the bucket name for reference
        CfnOutput(
            self,
            "InvoiceBucketName",
            value=self.invoice_bucket.bucket_name,
            description="S3 bucket for invoice uploads",
            export_name="InvoiceBucketName",
        )

        CfnOutput(
            self,
            "InvoiceBucketArn",
            value=self.invoice_bucket.bucket_arn,
            description="ARN of the invoice S3 bucket",
            export_name="InvoiceBucketArn",
        )

        # ============ PHASE 2: LAMBDA FUNCTION ============

        # Lambda execution role with CloudWatch logging permissions
        lambda_role = iam.Role(
            self,
            "InvoiceProcessorRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            description="Execution role for InvoiceProcessor Lambda",
        )

        # Grant Lambda read access to S3 bucket
        self.invoice_bucket.grant_read(lambda_role)

        # ============ PHASE 3: TEXTRACT PERMISSIONS ============

        # Add Textract permissions to Lambda role
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "textract:DetectDocumentText",
                    "textract:AnalyzeDocument",
                ],
                resources=["*"],
                effect=iam.Effect.ALLOW,
            )
        )

        # Add S3 GetObject permission for Textract to read from bucket
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{self.invoice_bucket.bucket_arn}/*"],
                effect=iam.Effect.ALLOW,
            )
        )

        # Lambda layer for psycopg2 (PostgreSQL driver)
        # Built from local directory with Linux-compatible psycopg2-binary
        psycopg2_layer = lambda_.LayerVersion(
            self,
            "Psycopg2Layer",
            code=lambda_.Code.from_asset("layers/psycopg2"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_11],
            description="psycopg2-binary for PostgreSQL connectivity",
        )

        # Lambda function for processing invoice uploads
        # Phase 3: Extended timeout for Textract processing
        self.invoice_processor = lambda_.Function(
            self,
            "InvoiceProcessor",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="invoice_processor.lambda_handler",
            code=lambda_.Code.from_asset("src/lambda_functions"),
            role=lambda_role,
            timeout=Duration.seconds(120),  # Extended for Textract processing
            memory_size=512,
            layers=[psycopg2_layer],
            environment={
                "INVOICE_BUCKET": self.invoice_bucket.bucket_name,
                "LOG_LEVEL": "INFO",
                "ALLOWED_FORMATS": "pdf,jpg,jpeg,png",
                # Phase 3: Textract configuration
                "TEXTRACT_ENABLED": "true",
                "TEXTRACT_CONFIDENCE_THRESHOLD": "70",
                # Phase 4: Database configuration
                "RDS_HOST": os.getenv("RDS_HOST", ""),
                "RDS_PORT": os.getenv("RDS_PORT", "5432"),
                "RDS_USER": os.getenv("RDS_USER", ""),
                "RDS_PASSWORD": os.getenv("RDS_PASSWORD", ""),
                "RDS_DB": os.getenv("RDS_DB", "invoices"),
            },
            description="Process S3 invoice uploads with Textract OCR",
        )

        # S3 → Lambda trigger: invoke Lambda on new PDF uploads
        self.invoice_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.invoice_processor),
            s3.NotificationKeyFilter(prefix="invoices/", suffix=".pdf"),
        )

        # Also trigger on JPG uploads
        self.invoice_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.invoice_processor),
            s3.NotificationKeyFilter(prefix="invoices/", suffix=".jpg"),
        )

        # Phase 3: Also trigger on JPEG and PNG uploads
        self.invoice_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.invoice_processor),
            s3.NotificationKeyFilter(prefix="invoices/", suffix=".jpeg"),
        )

        self.invoice_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.invoice_processor),
            s3.NotificationKeyFilter(prefix="invoices/", suffix=".png"),
        )

        # Output the Lambda function ARN
        CfnOutput(
            self,
            "InvoiceProcessorArn",
            value=self.invoice_processor.function_arn,
            description="ARN of the InvoiceProcessor Lambda function",
            export_name="InvoiceProcessorArn",
        )

        CfnOutput(
            self,
            "InvoiceProcessorName",
            value=self.invoice_processor.function_name,
            description="Name of the InvoiceProcessor Lambda function",
            export_name="InvoiceProcessorName",
        )
