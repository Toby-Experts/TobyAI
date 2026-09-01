# Sydney waitlist endpoint

`handler.py` is the deployed Lambda handler for the TobyAI waitlist. The
endpoint accepts `POST /waitlist` at
`https://pc24esfy6h.execute-api.ap-southeast-2.amazonaws.com/waitlist`.

The stack is in `ap-southeast-2`:

- DynamoDB table `tobyai-waitlist`, with `pk` as its string partition key,
  on-demand billing, KMS encryption, TTL on `expires_at`, point-in-time
  recovery, and deletion protection.
- Lambda `tobyai-waitlist`, using Python 3.13 and `handler.handler`.
- IAM role `tobyai-waitlist-lambda`, limited to `PutItem` and `UpdateItem` on
  the table, `ses:SendEmail` on the `tobyai.io` SES identity, plus the basic
  Lambda execution policy.
- HTTP API route `POST /waitlist`, with CORS for `https://www.tobyai.io` and
  `https://tobyai.io`, stage throttling of 5 requests per second with a burst
  of 10, and 90-day access-log retention.

Run `deploy.sh` from this directory with `HASH_SALT` exported in the
environment. Set `SIGNUP_EMAIL_FROM` to the verified sender address when
email receipts should be enabled. It defaults to empty, which leaves email
disabled. The script never contains or prints the hash salt. It is not run by
tests or site deployment.

The sender identity must be verified in SES in `ap-southeast-2`. The account
remains in the SES sandbox until production access is approved, so only
verified recipient addresses receive mail. Only the first signup for an
address is sent a receipt. Repeated submissions retain the same response and
do not send another receipt.

Install the test dependencies with
`python -m pip install -r waitlist/requirements-dev.txt`, then run
`python -m pytest waitlist/`.
