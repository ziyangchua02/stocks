// Vercel serves the dashboard; the data still lives on the machine at home.
//
// The browser keeps talking to /api on its own origin, exactly as it does behind
// the Vite dev proxy, and this function forwards the call over the tunnel. The
// backend token is attached here, on the server, so it never ships in the bundle.
const BACKEND = (process.env.BACKEND_URL || '').replace(/\/$/, '')
const TOKEN = process.env.BACKEND_API_TOKEN || ''

export default async function handler(request, response) {
  if (!BACKEND) {
    response.status(500).json({ detail: 'BACKEND_URL is not set on this deployment.' })
    return
  }

  const method = request.method || 'GET'
  const headers = { 'Content-Type': 'application/json' }
  if (TOKEN) headers['X-API-Token'] = TOKEN
  const sendsBody = method !== 'GET' && method !== 'HEAD' && request.body != null

  try {
    const upstream = await fetch(`${BACKEND}${request.url}`, {
      method,
      headers,
      body: sendsBody ? JSON.stringify(request.body) : undefined,
    })
    const text = await upstream.text()
    response.status(upstream.status)
    response.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/json')
    response.send(text)
  } catch (error) {
    // The workstation is asleep, the tunnel is down, or the backend is restarting.
    response.status(502).json({ detail: `Backend unreachable: ${error.message}` })
  }
}
