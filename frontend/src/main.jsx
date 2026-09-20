import React from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import Alerts from './pages/Alerts.jsx'
import AppShell from './components/AppShell.jsx'
import DailyBrief from './pages/DailyBrief.jsx'
import NewsFeed from './pages/NewsFeed.jsx'
import Overview from './pages/Overview.jsx'
import SignalLog from './pages/SignalLog.jsx'
import TickerDetail from './pages/TickerDetail.jsx'
import './index.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <HashRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/ticker/:ticker" element={<TickerDetail />} />
          <Route path="/news" element={<NewsFeed />} />
          <Route path="/signals" element={<SignalLog />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/brief" element={<DailyBrief />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </HashRouter>
  </React.StrictMode>,
)
