import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiClient } from '@/api/config'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || null)
  const user = ref(null)

  const isAuthenticated = computed(() => !!token.value)

  function setToken(newToken) {
    token.value = newToken
    if (newToken) {
      localStorage.setItem('token', newToken)
      apiClient.defaults.headers.common['Authorization'] = `Bearer ${newToken}`
    } else {
      localStorage.removeItem('token')
      delete apiClient.defaults.headers.common['Authorization']
    }
  }

  async function login(email, password) {
    const response = await apiClient.post('/auth/login', { email, password })
    if (response.data.access_token) {
      setToken(response.data.access_token)
    } else {
      throw new Error('No access token in response')
    }
    return response.data
  }

  async function register(userData) {
    const response = await apiClient.post('/auth/register', {
      email: userData.email,
      name: userData.name,
      password: userData.password,
    })
    if (response.data.access_token) {
      setToken(response.data.access_token)
    }
    return response.data
  }

  function logout() {
    setToken(null)
    user.value = null
  }

  // Initialize token header on store creation
  if (token.value) {
    apiClient.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
  }

  return {
    token,
    user,
    isAuthenticated,
    login,
    register,
    logout,
    setToken,
  }
})
