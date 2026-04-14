const listeners = new Map()
const sseClients = new Set()

export function onPipelineEvent(event, handler) {
  if (!listeners.has(event)) listeners.set(event, new Set())
  listeners.get(event).add(handler)
  return () => listeners.get(event)?.delete(handler)
}

export function emitPipelineEvent(event, data) {
  const eventPayload = { event, data, timestamp: Date.now() }

  const handlers = listeners.get(event)
  if (handlers) {
    for (const handler of handlers) {
      try {
        handler(data, event)
      } catch (e) {
        console.error(`[events] handler error for ${event}:`, e.message)
      }
    }
  }

  for (const client of sseClients) {
    try {
      client.write(`data: ${JSON.stringify(eventPayload)}\n\n`)
    } catch {
      sseClients.delete(client)
    }
  }
}

export function addSSEClient(res) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  })
  res.write(`data: ${JSON.stringify({ event: 'connected', timestamp: Date.now() })}\n\n`)
  sseClients.add(res)

  const heartbeat = setInterval(() => {
    try {
      res.write(': heartbeat\n\n')
    } catch {
      clearInterval(heartbeat)
      sseClients.delete(res)
    }
  }, 30_000)

  res.on('close', () => {
    clearInterval(heartbeat)
    sseClients.delete(res)
  })
}

export function getSSEClientCount() {
  return sseClients.size
}
