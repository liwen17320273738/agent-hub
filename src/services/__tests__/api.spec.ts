/**
 * Unit tests for the unified API client.
 *
 * Covers: token management, auth headers, error handling, 401 auto-logout.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
  }
})()
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

// Mock fetch
const mockFetch = vi.fn()
Object.defineProperty(globalThis, 'fetch', { value: mockFetch, writable: true })

// Import after mocks are set up
import { setAuthToken, getAuthToken, getAuthTokenOrPipelineKey, ApiError, apiFetch } from '../api'

describe('api.ts — token management', () => {
  beforeEach(() => {
    localStorageMock.clear()
    setAuthToken(null)
  })

  it('setAuthToken stores token and getAuthToken retrieves it', () => {
    setAuthToken('test-jwt-token')
    expect(getAuthToken()).toBe('test-jwt-token')
    expect(localStorageMock.getItem('agent-hub-token')).toBe('test-jwt-token')
  })

  it('setAuthToken(null) clears token from memory and localStorage', () => {
    setAuthToken('some-token')
    setAuthToken(null)
    expect(getAuthToken()).toBeNull()
    expect(localStorageMock.getItem('agent-hub-token')).toBeNull()
  })

  it('getAuthToken reads from localStorage on initial load', () => {
    // Simulate page reload: localStorage has a token from prior session
    localStorageMock.setItem('agent-hub-token', 'persisted-token')
    // getAuthToken first checks _token (null after module load), then localStorage
    // Since _token starts null and we haven't called setAuthToken, it reads localStorage
    const token = getAuthToken()
    expect(token).toBe('persisted-token')
  })

  it('getAuthTokenOrPipelineKey returns JWT if available', () => {
    setAuthToken('my-jwt')
    expect(getAuthTokenOrPipelineKey()).toBe('my-jwt')
  })

  it('getAuthTokenOrPipelineKey falls back to pipeline key from localStorage', () => {
    setAuthToken(null) // No JWT
    localStorageMock.setItem('agent-hub-pipeline-key', 'ahrelay_test123')
    expect(getAuthTokenOrPipelineKey()).toBe('ahrelay_test123')
  })
})

describe('api.ts — apiFetch', () => {
  beforeEach(() => {
    localStorageMock.clear()
    setAuthToken(null)
    mockFetch.mockReset()
  })

  it('makes GET request with correct headers', async () => {
    setAuthToken('bearer-token')
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ data: 'test' }),
    })

    const result = await apiFetch('/test')
    expect(result).toEqual({ data: 'test' })

    const [url, options] = mockFetch.mock.calls[0]
    expect(url).toContain('/api/test')
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer bearer-token',
      'Content-Type': 'application/json',
    })
  })

  it('throws ApiError on non-2xx response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ detail: 'Not found' }),
    })

    try {
      await apiFetch('/missing')
      expect.unreachable('Should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect((err as ApiError).status).toBe(404)
      expect((err as ApiError).message).toContain('Not found')
    }
  })

  it('clears auth token on 401 response', async () => {
    setAuthToken('expired-token')
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: 'Token expired' }),
    })

    try {
      await apiFetch('/protected')
    } catch {
      // Expected
    }

    expect(getAuthToken()).toBeNull()
    expect(localStorageMock.getItem('agent-hub-token')).toBeNull()
  })

  it('returns undefined for 204 No Content', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
    })

    const result = await apiFetch('/delete-something')
    expect(result).toBeUndefined()
  })

  it('handles FormData without Content-Type header', async () => {
    setAuthToken('form-token')
    const formData = new FormData()
    formData.append('file', new Blob(['test']), 'test.txt')

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: '1' }),
    })

    await apiFetch('/upload', { method: 'POST', body: formData })
    const options = mockFetch.mock.calls[0][1]
    // Should NOT have Content-Type when sending FormData
    expect(options.headers['Content-Type']).toBeUndefined()
    expect(options.headers.Authorization).toBe('Bearer form-token')
  })
})
