import './index.css'
import { HashRouter, Route, Routes } from 'react-router-dom'
import AuthPage from './pages/AuthPage'
import StartPage from './pages/StartPage'
import MenuPage from './pages/MenuPage'
import HistoryPage from './pages/HistoryPage'
import { useReminders } from './hooks/useReminders'

export default function App() {
  useReminders()

  return (
    <HashRouter>
      <Routes>
        {/* Авторизация теперь на главном экране */}
        <Route path="/" element={<AuthPage />} />
        <Route path="/start" element={<StartPage />} />
        <Route path="/menu" element={<MenuPage />} />
        <Route path="/history" element={<HistoryPage />} />
      </Routes>
    </HashRouter>
  )
}