const TOKEN_KEY = 'mcp_auth_token'

/**
 * Extract token from URL search parameters
 * @returns Token value or null if not found
 */
export function extractTokenFromURL(): string | null {
  try {
    const params = new URLSearchParams(window.location.search)
    return params.get('token')
  } catch {
    return null
  }
}

/**
 * Store token in localStorage
 * @param token Token value to save
 */
export function saveToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // Silent failure if localStorage is unavailable
  }
}

/**
 * Retrieve token from localStorage
 * @returns Token value or null if not found
 */
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

/**
 * Remove token from localStorage
 */
export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Silent failure if localStorage is unavailable
  }
}

/**
 * Get token from localStorage or extract from URL
 * If token is found in URL, it will be saved to localStorage
 * @returns Token value or null if not found in either location
 */
export function getOrExtractToken(): string | null {
  // Try localStorage first
  const stored = getToken()
  if (stored !== null) {
    return stored
  }

  // Try URL
  const urlToken = extractTokenFromURL()
  if (urlToken !== null) {
    saveToken(urlToken)
    return urlToken
  }

  return null
}
