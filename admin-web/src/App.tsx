import { Navigate, Route, Routes } from 'react-router-dom'
import { AdminLayout } from './layouts/AdminLayout'
import { AuthLayout } from './layouts/AuthLayout'
import { LoginPage } from './pages/Login'
import { DashboardPage } from './pages/Dashboard'
import { KBsPage } from './pages/KBs'
import { AuditPage } from './pages/Audit'
import { SettingsPage } from './pages/Settings'
import { useAuth } from './context/AuthContext'

function RequireAdmin({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user) return <Navigate to="/admin/login" replace />
  if (user.role !== 'admin') return <Navigate to="/admin/login" replace />
  return children
}

export function App() {
  return (
    <Routes>
      <Route element={<AuthLayout />}>
        <Route path="/admin/login" element={<LoginPage />} />
      </Route>
      <Route element={<AdminLayout />}>
        <Route
          index
          path="/admin"
          element={
            <RequireAdmin>
              <DashboardPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/admin/kbs"
          element={
            <RequireAdmin>
              <KBsPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/admin/audit"
          element={
            <RequireAdmin>
              <AuditPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/admin/settings"
          element={
            <RequireAdmin>
              <SettingsPage />
            </RequireAdmin>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  )
}
