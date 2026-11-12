import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const apiClient = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json'
    },
    withCredentials: true
})

// Add request interceptor
apiClient.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('token')
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`
        }
        return config
    },
    (error) => {
        return Promise.reject(error)
    }
)

// True for the login request itself, with or without the /api prefix (nginx) or a host,
// and ignoring a query string: '/auth/login', '/api/auth/login', 'https://x/api/auth/login?a=1'
export function isLoginRequest(url) {
    if (!url) return false
    const path = String(url).split(/[?#]/)[0]
    return /(^|\/)auth\/login\/?$/.test(path)
}

// A 401 from /auth/login means wrong email or password: leave the page alone and let the
// form show the message. A 401 from any other request means the session is gone.
export async function handleResponseError(error) {
    if (error.response?.status === 401 && !isLoginRequest(error.config?.url)) {
        localStorage.removeItem('token')
        window.location.href = '/signin'
    }
    return Promise.reject(error)
}

// Add response interceptor
apiClient.interceptors.response.use((response) => response, handleResponseError)