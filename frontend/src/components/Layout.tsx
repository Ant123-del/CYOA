import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { SleepControl } from './Sleep'

const links = [
  { to: '/today', label: 'Today', icon: '🧭' },
  { to: '/plan', label: 'Plan', icon: '🗺️' },
  { to: '/board', label: 'Board', icon: '📋' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

function NavLinks({ className }: { className: string }) {
  return (
    <nav className={className}>
      {links.map((l) => (
        <NavLink key={l.to} to={l.to} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          <span aria-hidden className="nav-icon">
            {l.icon}
          </span>
          <span>{l.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

export default function Layout() {
  const { user, settings, logOut } = useAuth()
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CYOA</span>
          <span className="brand-sub">Choose Your Own Adventure</span>
        </div>
        <NavLinks className="nav" />
        <div className="user">
          {settings && (!settings.googleConnected || settings.hasWritableCalendar === false) && (
            <NavLink to="/settings" className="pill warn link-cal">
              {settings.googleConnected ? 'Make a calendar editable' : 'Link calendar'}
            </NavLink>
          )}
          <SleepControl />
          {user?.photoURL ? (
            <img className="avatar" src={user.photoURL} alt="" referrerPolicy="no-referrer" />
          ) : (
            <div className="avatar fallback">{(user?.displayName ?? '?')[0]}</div>
          )}
          <button className="btn ghost small sign-out" onClick={logOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
      <NavLinks className="tabbar" />
    </div>
  )
}
