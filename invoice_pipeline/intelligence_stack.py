"""Separate stack: leaves legacy deployments and bucket logical IDs untouched."""

from pathlib import Path
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnParameter,
    CfnOutput,
    aws_s3 as s3,
    aws_s3_notifications as notifications,
    aws_lambda as fn,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_secretsmanager as secrets,
)
from constructs import Construct


class IntelligenceStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        root = Path(__file__).resolve().parents[1]
        secret_arn = CfnParameter(self, "DatabaseSecretArn", type="String")
        model = CfnParameter(
            self,
            "BedrockModelId",
            type="String",
            description="Converse-compatible in-region model ID",
        )
        model_arn = CfnParameter(
            self,
            "BedrockModelArn",
            type="String",
            description="Exact foundation-model ARN corresponding to BedrockModelId",
        )
        bucket = s3.Bucket(
            self,
            "Documents",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        secret = secrets.Secret.from_secret_complete_arn(
            self, "DatabaseSecret", secret_arn.value_as_string
        )
        layer = fn.LayerVersion(
            self,
            "PostgresDriver",
            code=fn.Code.from_asset(str(root / "layers/psycopg2")),
            compatible_runtimes=[fn.Runtime.PYTHON_3_11],
        )

        def handler(name, method, database=False):
            return fn.Function(
                self,
                name,
                runtime=fn.Runtime.PYTHON_3_11,
                architecture=fn.Architecture.X86_64,
                code=fn.Code.from_asset(str(root / "src/lambda_functions")),
                handler="intelligence_handlers." + method,
                timeout=Duration.seconds(120),
                memory_size=512,
                layers=[layer] if database else [],
                environment={
                    "BEDROCK_MODEL_ID": model.value_as_string,
                    "DATABASE_SECRET_ARN": secret_arn.value_as_string,
                },
            )

        ocr = handler("Extract", "textract")
        enrich = handler("Fallback", "fallback")
        queue = handler("QueueReview", "queue_review")
        save = handler("Persist", "save", True)
        bucket.grant_read(ocr, "invoices/*")
        bucket.grant_write(ocr, "extractions/*")
        bucket.grant_read_write(enrich, "extractions/*")
        bucket.grant_read(queue, "extractions/*")
        bucket.grant_write(queue, "pending-review/*")
        bucket.grant_read(save, "extractions/*")
        ocr.add_to_role_policy(
            iam.PolicyStatement(actions=["textract:AnalyzeExpense"], resources=["*"])
        )
        enrich.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"], resources=[model_arn.value_as_string]
            )
        )
        secret.grant_read(save)

        def task(name, worker):
            return tasks.LambdaInvoke(
                self, name, lambda_function=worker, payload_response_only=True
            )

        review = task("HoldForHumanReview", queue)
        persist = task("SaveVerifiedInvoice", save)
        fallback = task("RecoverMissingFields", enrich)
        # A provider outage must retain the candidate for review instead of accepting it.
        fallback.add_catch(review, result_path="$.fallbackFailure")
        choice = (
            sfn.Choice(self, "VerifiedFieldsOnly")
            .when(sfn.Condition.boolean_equals("$.ready", True), persist)
            .otherwise(review)
        )
        workflow = sfn.StateMachine(
            self,
            "Workflow",
            definition_body=sfn.DefinitionBody.from_chainable(
                task("TextractExtraction", ocr).next(fallback).next(choice)
            ),
            timeout=Duration.minutes(10),
        )
        start = handler("Starter", "starter")
        start.add_environment("STATE_MACHINE_ARN", workflow.state_machine_arn)
        workflow.grant_start_execution(start)
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            notifications.LambdaDestination(start),
            s3.NotificationKeyFilter(prefix="invoices/"),
        )
        CfnOutput(self, "InvoiceBucket", value=bucket.bucket_name)
        CfnOutput(self, "StateMachineArn", value=workflow.state_machine_arn)
