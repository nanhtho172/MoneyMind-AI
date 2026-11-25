import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@fontsource-variable/inter/wght.css'
import './styles.css'
import { AuthProvider } from './features/auth/auth'
import { AppRoutes } from './app/routes'

createRoot(document.getElementById('root')!).render(<StrictMode><BrowserRouter><AuthProvider><AppRoutes/></AuthProvider></BrowserRouter></StrictMode>)
