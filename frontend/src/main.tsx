import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './lib/auth.tsx'
import { firebaseConfigured } from './lib/firebase.ts'

function SetupNeeded() {
  return (
    <div className="login">
      <div className="login-card">
        <div className="compass">🧭</div>
        <h1>CYOA</h1>
        <p className="lede">
          Firebase isn't configured. Set the <code>VITE_FIREBASE_*</code> variables in <code>frontend/.env.local</code>{' '}
          (or in Vercel → Settings → Environment Variables) and restart / redeploy.
        </p>
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {firebaseConfigured ? (
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    ) : (
      <SetupNeeded />
    )}
  </StrictMode>,
)
