const TARGET_REPO = 'Toby-Experts/tobyai-app';
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  let payload;
  try {
    payload = JSON.parse(event.body || '{}');
  } catch (err) {
    return { statusCode: 400, body: JSON.stringify({ error: 'Invalid JSON' }) };
  }

  const email = typeof payload.email === 'string' ? payload.email.trim() : '';
  if (!EMAIL_RE.test(email)) {
    return { statusCode: 400, body: JSON.stringify({ error: 'Invalid email address' }) };
  }

  const token = process.env.GITHUB_ISSUES_TOKEN;
  if (!token) {
    console.error('GITHUB_ISSUES_TOKEN is not set');
    return { statusCode: 500, body: JSON.stringify({ error: 'Server misconfigured' }) };
  }

  const submittedAt = new Date().toISOString();

  const response = await fetch(`https://api.github.com/repos/${TARGET_REPO}/issues`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'tobyai-waitlist-function',
    },
    body: JSON.stringify({
      title: `Waitlist signup: ${email}`,
      body: `**Email:** ${email}\n**Submitted:** ${submittedAt}`,
      labels: ['waitlist'],
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    console.error('GitHub issue creation failed', response.status, detail);
    return { statusCode: 502, body: JSON.stringify({ error: 'Failed to record signup' }) };
  }

  return { statusCode: 200, body: JSON.stringify({ success: true }) };
};
