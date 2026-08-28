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
  the table, plus the basic Lambda execution policy.
- HTTP API route `POST /waitlist`, with CORS for `https://www.tobyai.io` and
  `https://tobyai.io`, stage throttling of 5 requests per second with a burst
  of 10, and 90-day access-log retention.

Run `deploy.sh` from this directory with `HASH_SALT` exported in the
environment. The script never contains or prints that secret. It is not run
by tests or site deployment.

Install the test dependencies with
`python -m pip install -r waitlist/requirements-dev.txt`, then run
`python -m pytest waitlist/`.
