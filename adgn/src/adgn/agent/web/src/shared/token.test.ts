import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import {
  extractTokenFromURL,
  saveToken,
  getToken,
  clearToken,
  getOrExtractToken,
} from './token'

describe('token utilities', () => {
  const TOKEN_KEY = 'mcp_auth_token'
  const TEST_TOKEN = 'test-token-123'

  beforeEach(() => {
    localStorage.clear()
    // Reset URL to default
    delete (window as any).location
    ;(window as any).location = { search: '' }
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('extractTokenFromURL', () => {
    it('returns token when present in URL', () => {
      ;(window as any).location = { search: '?token=abc123' }
      expect(extractTokenFromURL()).toBe('abc123')
    })

    it('returns null when token parameter is missing', () => {
      ;(window as any).location = { search: '?other=value' }
      expect(extractTokenFromURL()).toBe(null)
    })

    it('returns null when URL has no search params', () => {
      ;(window as any).location = { search: '' }
      expect(extractTokenFromURL()).toBe(null)
    })

    it('handles URL with multiple parameters', () => {
      ;(window as any).location = { search: '?foo=bar&token=xyz789&baz=qux' }
      expect(extractTokenFromURL()).toBe('xyz789')
    })

    it('handles empty token value', () => {
      ;(window as any).location = { search: '?token=' }
      expect(extractTokenFromURL()).toBe('')
    })

    it('returns null on URLSearchParams error', () => {
      // Mock window.location.search to throw
      Object.defineProperty(window, 'location', {
        get() {
          throw new Error('Access denied')
        },
        configurable: true,
      })
      expect(extractTokenFromURL()).toBe(null)
    })

    it('handles URL-encoded token values', () => {
      ;(window as any).location = { search: '?token=abc%2Bdef%3D123' }
      expect(extractTokenFromURL()).toBe('abc+def=123')
    })
  })

  describe('saveToken', () => {
    it('saves token to localStorage', () => {
      saveToken(TEST_TOKEN)
      expect(localStorage.getItem(TOKEN_KEY)).toBe(TEST_TOKEN)
    })

    it('overwrites existing token', () => {
      localStorage.setItem(TOKEN_KEY, 'old-token')
      saveToken(TEST_TOKEN)
      expect(localStorage.getItem(TOKEN_KEY)).toBe(TEST_TOKEN)
    })

    it('handles localStorage errors silently', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('QuotaExceededError')
      })
      expect(() => saveToken(TEST_TOKEN)).not.toThrow()
    })

    it('saves empty string token', () => {
      saveToken('')
      expect(localStorage.getItem(TOKEN_KEY)).toBe('')
    })
  })

  describe('getToken', () => {
    it('retrieves token from localStorage', () => {
      localStorage.setItem(TOKEN_KEY, TEST_TOKEN)
      expect(getToken()).toBe(TEST_TOKEN)
    })

    it('returns null when token not found', () => {
      expect(getToken()).toBe(null)
    })

    it('returns null on localStorage error', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('Access denied')
      })
      expect(getToken()).toBe(null)
    })

    it('retrieves empty string token', () => {
      localStorage.setItem(TOKEN_KEY, '')
      expect(getToken()).toBe('')
    })
  })

  describe('clearToken', () => {
    it('removes token from localStorage', () => {
      localStorage.setItem(TOKEN_KEY, TEST_TOKEN)
      clearToken()
      expect(localStorage.getItem(TOKEN_KEY)).toBe(null)
    })

    it('handles clearing non-existent token', () => {
      expect(() => clearToken()).not.toThrow()
      expect(localStorage.getItem(TOKEN_KEY)).toBe(null)
    })

    it('handles localStorage errors silently', () => {
      vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
        throw new Error('Access denied')
      })
      expect(() => clearToken()).not.toThrow()
    })
  })

  describe('getOrExtractToken', () => {
    it('returns token from localStorage when present', () => {
      localStorage.setItem(TOKEN_KEY, TEST_TOKEN)
      ;(window as any).location = { search: '?token=url-token' }
      expect(getOrExtractToken()).toBe(TEST_TOKEN)
    })

    it('extracts and saves token from URL when not in localStorage', () => {
      ;(window as any).location = { search: '?token=url-token' }
      const result = getOrExtractToken()
      expect(result).toBe('url-token')
      expect(localStorage.getItem(TOKEN_KEY)).toBe('url-token')
    })

    it('returns null when token not in localStorage or URL', () => {
      ;(window as any).location = { search: '' }
      expect(getOrExtractToken()).toBe(null)
    })

    it('prioritizes localStorage over URL', () => {
      localStorage.setItem(TOKEN_KEY, 'stored-token')
      ;(window as any).location = { search: '?token=url-token' }
      expect(getOrExtractToken()).toBe('stored-token')
      // Should not overwrite with URL token
      expect(localStorage.getItem(TOKEN_KEY)).toBe('stored-token')
    })

    it('handles URL extraction failure gracefully', () => {
      Object.defineProperty(window, 'location', {
        get() {
          throw new Error('Access denied')
        },
        configurable: true,
      })
      expect(getOrExtractToken()).toBe(null)
    })

    it('saves URL token even if localStorage save fails', () => {
      ;(window as any).location = { search: '?token=url-token' }
      const setItemSpy = vi
        .spyOn(Storage.prototype, 'setItem')
        .mockImplementation(() => {
          throw new Error('QuotaExceededError')
        })

      // Should still return the token even though save failed
      expect(getOrExtractToken()).toBe('url-token')
      expect(setItemSpy).toHaveBeenCalledWith(TOKEN_KEY, 'url-token')
    })

    it('handles empty string from URL', () => {
      ;(window as any).location = { search: '?token=' }
      expect(getOrExtractToken()).toBe('')
      expect(localStorage.getItem(TOKEN_KEY)).toBe('')
    })
  })

  describe('integration scenarios', () => {
    it('typical flow: extract from URL, then retrieve from storage', () => {
      // First visit with token in URL
      ;(window as any).location = { search: '?token=session-123' }
      expect(getOrExtractToken()).toBe('session-123')

      // Subsequent visit without token in URL
      ;(window as any).location = { search: '' }
      expect(getToken()).toBe('session-123')
      expect(getOrExtractToken()).toBe('session-123')
    })

    it('logout flow: clear token', () => {
      saveToken(TEST_TOKEN)
      expect(getToken()).toBe(TEST_TOKEN)

      clearToken()
      expect(getToken()).toBe(null)
      expect(getOrExtractToken()).toBe(null)
    })

    it('token refresh flow: overwrite existing token', () => {
      saveToken('old-token')
      expect(getToken()).toBe('old-token')

      saveToken('new-token')
      expect(getToken()).toBe('new-token')
    })
  })
})
