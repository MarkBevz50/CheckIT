import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleResponseError, isLoginRequest } from '@/api/config'

function error401(url) {
  return { response: { status: 401, data: { detail: 'x' } }, config: { url } }
}

describe('isLoginRequest', () => {
  it.each([
    '/auth/login',
    '/api/auth/login',
    'http://localhost/api/auth/login',
    '/api/auth/login?x=1',
    '/auth/login/',
  ])('matches %s', (url) => {
    expect(isLoginRequest(url)).toBe(true)
  })

  it.each(['/auth/register', '/auth/loginx', '/tenders/', '/api/tenders/auth/login-history', '', undefined])(
    'does not match %s',
    (url) => {
      expect(isLoginRequest(url)).toBe(false)
    },
  )
})

describe('handleResponseError', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'abc')
    vi.stubGlobal('location', { href: '/' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it.each(['/auth/login', '/api/auth/login'])(
    '401 from %s keeps the token, does not redirect and passes the error on',
    async (url) => {
      const error = error401(url)
      await expect(handleResponseError(error)).rejects.toBe(error)
      expect(localStorage.getItem('token')).toBe('abc')
      expect(window.location.href).toBe('/')
    },
  )

  it.each(['/tenders/', '/api/tenders/'])(
    '401 from %s clears the token and redirects to /signin',
    async (url) => {
      const error = error401(url)
      await expect(handleResponseError(error)).rejects.toBe(error)
      expect(localStorage.getItem('token')).toBeNull()
      expect(window.location.href).toBe('/signin')
    },
  )

  it('non-401 errors are passed on untouched', async () => {
    const error = { response: { status: 500 }, config: { url: '/auth/login' } }
    await expect(handleResponseError(error)).rejects.toBe(error)
    expect(localStorage.getItem('token')).toBe('abc')
    expect(window.location.href).toBe('/')
  })
})
