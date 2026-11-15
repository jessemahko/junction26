import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import SqlDrawer, { SqlProvider } from './views/SqlDrawer.jsx'
import './styles.css'
import './demo.css'


createRoot(document.getElementById('root')).render(
  <SqlProvider>
    <App />
    <SqlDrawer />
  </SqlProvider>,
)
