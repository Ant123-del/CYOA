import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../lib/auth'

const links = [
  { to: '/today', label: 'Today', icon: '🧭' },
  { to: '/plan', label: 'Plan', icon: '🗺️' },
  { to: '/board', label: 'Board', icon: '📋' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

export default function Layout() {
  const { user, settings, logOut } = useAuth()
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CYOA</span>
          <span className="brand-sub">Choose Your Own Adventure</span>
        </div>
        <nav className="nav">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              <span aria-hidden>{l.icon}</span>
              <span>{l.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="user">
          {settings && !settings.googleConnected && (
            <NavLink to="/settings" className="pill warn">
              Connect calendar
            </NavLink>
          )}
          {user?.photoURL ? (
            <img className="avatar" src={user.photoURL} alt="" referrerPolicy="no-referrer" />
          ) : (
            <div className="avatar fallback">{(user?.displayName ?? '?')[0]}</div>
          )}
          <button className="btn ghost small" onClick={logOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
