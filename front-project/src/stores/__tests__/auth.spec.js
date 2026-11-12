import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/config', () => ({
  apiClient: {
    post: vi.fn(),
    get: vi.fn(),
    defaults: { headers: { common: {} } },
  },
}))

import { apiClient } from '@/api/config'
import { useAuthStore } from '@/stores/auth'

describe('auth store endpoints', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('login posts to /auth/login (not the old /auth/auth/login)', async () => {
    apiClient.post.mockResolvedValue({ data: { access_token: 't', token_type: 'bearer' } })
    await useAuthStore().login('a@b.c', 'pw')
    expect(apiClient.post).toHaveBeenCalledWith('/auth/login', { email: 'a@b.c', password: 'pw' })
  })

  it('register posts to /auth/register (not the old /auth/auth/register)', async () => {
    apiClient.post.mockResolvedValue({ data: { access_token: 't', token_type: 'bearer' } })
    await useAuthStore().register({ email: 'a@b.c', name: 'n', password: 'pw' })
    expect(apiClient.post).toHaveBeenCalledWith('/auth/register', {
      email: 'a@b.c',
      name: 'n',
      password: 'pw',
    })
  })
})
