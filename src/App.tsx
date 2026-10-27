import './index.css'
import { HashRouter, Route, Routes } from 'react-router-dom'
import StartPage from './pages/StartPage'
import MenuPage from './pages/MenuPage'
import HistoryPage from './pages/HistoryPage'

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<StartPage />} />
        <Route path="/menu" element={<MenuPage />} />
        <Route path="/history" element={<HistoryPage />} />
      </Routes>
    </HashRouter>
  )
}