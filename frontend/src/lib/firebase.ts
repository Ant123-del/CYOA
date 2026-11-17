import { initializeApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, type Auth } from 'firebase/auth'

// Values come from frontend/.env.local locally, and from Vercel's Environment Variables in production.
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
}

export const firebaseConfigured = Boolean(firebaseConfig.apiKey && firebaseConfig.appId)

// getAuth() throws auth/invalid-api-key without a key, which would blank the whole page,
// so only initialize when configured (main.tsx shows a setup screen otherwise).
export const auth: Auth = firebaseConfigured ? getAuth(initializeApp(firebaseConfig)) : (null as unknown as Auth)
export const googleProvider = new GoogleAuthProvider()
googleProvider.setCustomParameters({ prompt: 'select_account' })
