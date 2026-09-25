import { Navigate, Route, Routes } from 'react-router'
import App from '../App'
import { AuthGate } from '../auth/AuthGate'
import { LoginPage } from '../auth/LoginPage'
import { HomePage } from '../home/HomePage'

export function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route
        path="/login"
        element={(
          <AuthGate access="guest">
            <LoginPage />
          </AuthGate>
        )}
      />
      <Route
        path="/chat"
        element={(
          <AuthGate access="protected">
            <App />
          </AuthGate>
        )}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
