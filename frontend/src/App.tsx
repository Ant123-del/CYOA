import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth'
import Layout from './components/Layout'
import { SleepProvider } from './lib/sleep'
import { PatienceProvider } from './lib/patience'
import Login from './pages/Login'
import Board from './pages/Board'
import Plan from './pages/Plan'
import Today from './pages/Today'
import Settings from './pages/Settings'
import Hope from './pages/Hope'

export default function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="splash">
        <div className="compass spin">🧭</div>
      </div>
    )
  }
  if (!user) return <Login />

  return (
    <PatienceProvider>
      <SleepProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/today" replace />} />
            <Route path="/today" element={<Today />} />
            <Route path="/plan" element={<Plan />} />
            <Route path="/board" element={<Board />} />
            <Route path="/hope" element={<Hope />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/today" replace />} />
          </Route>
        </Routes>
      </SleepProvider>
    </PatienceProvider>
  )
}
