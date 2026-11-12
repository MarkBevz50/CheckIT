import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/api/config', () => ({
  apiClient: { post: vi.fn(), get: vi.fn(), defaults: { headers: { common: {} } } },
}))

import { apiClient } from '@/api/config'
import SignInView from '@/views/SignInView.vue'

const MESSAGE = 'Неправильний email або пароль'

describe('SignInView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('shows the server message in the form after a 401 and stays on the page', async () => {
    apiClient.post.mockRejectedValue({ response: { status: 401, data: { detail: MESSAGE } } })
    const wrapper = mount(SignInView, { global: { stubs: { 'router-link': true } } })

    await wrapper.find('#email').setValue('a@example.com')
    await wrapper.find('#password').setValue('wrong')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('.alert-error').text()).toBe(MESSAGE)
    expect(push).not.toHaveBeenCalled()
  })
})
