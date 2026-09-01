#!/usr/bin/env bash
set -euo pipefail

REGION="ap-southeast-2"
ACCOUNT_ID="285629514238"
TABLE_NAME="tobyai-waitlist"
FUNCTION_NAME="tobyai-waitlist"
ROLE_NAME="tobyai-waitlist-lambda"
API_NAME="tobyai-waitlist"
EXPECTED_API_ID="pc24esfy6h"
TABLE_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
SES_IDENTITY_ARN="arn:aws:ses:${REGION}:${ACCOUNT_ID}:identity/tobyai.io"

: "${HASH_SALT:?Export HASH_SALT before running this script. The value is never stored in the repository.}"
SIGNUP_EMAIL_FROM="${SIGNUP_EMAIL_FROM:-}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

cat > "$BUILD_DIR/trust-policy.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

cat > "$BUILD_DIR/table-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem"],
      "Resource": "${TABLE_ARN}"
    }
  ]
}
JSON

cat > "$BUILD_DIR/ses-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY_ARN}"
    }
  ]
}
JSON

cat > "$BUILD_DIR/cors.json" <<'JSON'
{
  "AllowOrigins": ["https://www.tobyai.io", "https://tobyai.io"],
  "AllowHeaders": ["Content-Type"],
  "AllowMethods": ["POST", "OPTIONS"],
  "MaxAge": 3600
}
JSON

aws dynamodb describe-table \
  --region "$REGION" \
  --table-name "$TABLE_NAME" >/dev/null 2>&1 || {
  aws dynamodb create-table \
    --region "$REGION" \
    --table-name "$TABLE_NAME" \
    --attribute-definitions AttributeName=pk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --sse-specification Enabled=true,SSEType=KMS \
    --deletion-protection-enabled
  aws dynamodb wait table-exists --region "$REGION" --table-name "$TABLE_NAME"
}

aws dynamodb update-time-to-live \
  --region "$REGION" \
  --table-name "$TABLE_NAME" \
  --time-to-live-specification Enabled=true,AttributeName=expires_at
aws dynamodb update-continuous-backups \
  --region "$REGION" \
  --table-name "$TABLE_NAME" \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true
aws dynamodb update-table \
  --region "$REGION" \
  --table-name "$TABLE_NAME" \
  --deletion-protection-enabled

if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://${BUILD_DIR}/trust-policy.json"
fi
aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name waitlist-table-write \
  --policy-document "file://${BUILD_DIR}/table-policy.json"
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name waitlist-email-send \
  --policy-document "file://${BUILD_DIR}/ses-policy.json"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

SIGNUP_EMAIL_FROM="$SIGNUP_EMAIL_FROM" python3 - "$BUILD_DIR/environment.json" <<'PY'
import json
import os
import sys

with open(sys.argv[1], "w", encoding="utf-8") as output:
    json.dump(
        {
            "Variables": {
                "WAITLIST_TABLE": "tobyai-waitlist",
                "ALLOWED_ORIGINS": "https://www.tobyai.io,https://tobyai.io",
                "RATE_LIMIT_PER_HOUR": "5",
                "HASH_SALT": os.environ["HASH_SALT"],
                "SIGNUP_EMAIL_FROM": os.environ.get("SIGNUP_EMAIL_FROM", ""),
            }
        },
        output,
    )
PY

cp "$SCRIPT_DIR/handler.py" "$BUILD_DIR/handler.py"
(cd "$BUILD_DIR" && zip -q function.zip handler.py)

if aws lambda get-function \
  --region "$REGION" \
  --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://${BUILD_DIR}/function.zip" >/dev/null
  aws lambda update-function-configuration \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.13 \
    --handler handler.handler \
    --role "$ROLE_ARN" \
    --environment "file://${BUILD_DIR}/environment.json"
else
  aws lambda create-function \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.13 \
    --handler handler.handler \
    --role "$ROLE_ARN" \
    --zip-file "fileb://${BUILD_DIR}/function.zip" \
    --environment "file://${BUILD_DIR}/environment.json"
fi

aws logs create-log-group \
  --region "$REGION" \
  --log-group-name "/aws/lambda/${FUNCTION_NAME}" >/dev/null 2>&1 || true
aws logs put-retention-policy \
  --region "$REGION" \
  --log-group-name "/aws/lambda/${FUNCTION_NAME}" \
  --retention-in-days 90

FUNCTION_ARN="$(
  aws lambda get-function \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --query Configuration.FunctionArn \
    --output text
)"

API_ID="$(
  aws apigatewayv2 get-apis \
    --region "$REGION" \
    --query "Items[?Name=='${API_NAME}'].ApiId | [0]" \
    --output text
)"
if [[ "$API_ID" == "None" || -z "$API_ID" ]]; then
  API_ID="$(
    aws apigatewayv2 create-api \
      --region "$REGION" \
      --name "$API_NAME" \
      --protocol-type HTTP \
      --cors-configuration "file://${BUILD_DIR}/cors.json" \
      --query ApiId \
      --output text
  )"
else
  aws apigatewayv2 update-api \
    --region "$REGION" \
    --api-id "$API_ID" \
    --cors-configuration "file://${BUILD_DIR}/cors.json" >/dev/null
fi

INTEGRATION_URI="arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${FUNCTION_ARN}/invocations"
INTEGRATION_ID="$(
  aws apigatewayv2 get-integrations \
    --region "$REGION" \
    --api-id "$API_ID" \
    --query "Items[?IntegrationUri=='${INTEGRATION_URI}'].IntegrationId | [0]" \
    --output text
)"
if [[ "$INTEGRATION_ID" == "None" || -z "$INTEGRATION_ID" ]]; then
  INTEGRATION_ID="$(
    aws apigatewayv2 create-integration \
      --region "$REGION" \
      --api-id "$API_ID" \
      --integration-type AWS_PROXY \
      --integration-uri "$INTEGRATION_URI" \
      --payload-format-version 2.0 \
      --query IntegrationId \
      --output text
  )"
fi

ROUTE_ID="$(
  aws apigatewayv2 get-routes \
    --region "$REGION" \
    --api-id "$API_ID" \
    --query "Items[?RouteKey=='POST /waitlist'].RouteId | [0]" \
    --output text
)"
if [[ "$ROUTE_ID" == "None" || -z "$ROUTE_ID" ]]; then
  aws apigatewayv2 create-route \
    --region "$REGION" \
    --api-id "$API_ID" \
    --route-key "POST /waitlist" \
    --target "integrations/${INTEGRATION_ID}" >/dev/null
else
  aws apigatewayv2 update-route \
    --region "$REGION" \
    --api-id "$API_ID" \
    --route-id "$ROUTE_ID" \
    --target "integrations/${INTEGRATION_ID}" >/dev/null
fi

ACCESS_LOG_GROUP="/aws/apigateway/${API_NAME}"
aws logs create-log-group \
  --region "$REGION" \
  --log-group-name "$ACCESS_LOG_GROUP" >/dev/null 2>&1 || true
aws logs put-retention-policy \
  --region "$REGION" \
  --log-group-name "$ACCESS_LOG_GROUP" \
  --retention-in-days 90
ACCESS_LOG_ARN="arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${ACCESS_LOG_GROUP}"
ACCESS_LOG_FORMAT='$context.requestId $context.httpMethod $context.routeKey $context.status $context.integrationErrorMessage'

if ! aws apigatewayv2 get-stage \
  --region "$REGION" \
  --api-id "$API_ID" \
  --stage-name '$default' >/dev/null 2>&1; then
  aws apigatewayv2 create-stage \
    --region "$REGION" \
    --api-id "$API_ID" \
    --stage-name '$default' \
    --auto-deploy \
    --default-route-settings ThrottlingRateLimit=5,ThrottlingBurstLimit=10 \
    --access-log-settings "DestinationArn=${ACCESS_LOG_ARN},Format=${ACCESS_LOG_FORMAT}"
else
  aws apigatewayv2 update-stage \
    --region "$REGION" \
    --api-id "$API_ID" \
    --stage-name '$default' \
    --auto-deploy \
    --default-route-settings ThrottlingRateLimit=5,ThrottlingBurstLimit=10 \
    --access-log-settings "DestinationArn=${ACCESS_LOG_ARN},Format=${ACCESS_LOG_FORMAT}" >/dev/null
fi

STATEMENT_ID="apigateway-waitlist"
if ! aws lambda get-policy \
  --region "$REGION" \
  --function-name "$FUNCTION_NAME" \
  --query "Policy" \
  --output text 2>/dev/null | grep -q "$STATEMENT_ID"; then
  aws lambda add-permission \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --statement-id "$STATEMENT_ID" \
    --action lambda:InvokeFunction \
    --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*"
fi

echo "Deployed ${FUNCTION_NAME} and POST /waitlist on API ${API_ID} in ${REGION}."
echo "Expected existing API ID: ${EXPECTED_API_ID}."
