import { StrictMode } from 'react'
import React from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// v1.9.x (FE-9): mount @axe-core/react in dev only so the developer
// console surfaces accessibility violations during the local dev loop.
// Gated on import.meta.env.DEV so the production bundle is unchanged.
// Async-imported so the production bundle tree-shakes the dev-only
// package out when DEV is false.
if (import.meta.env.DEV) {
  void import('@axe-core/react').then(({ default: axe }) => {
    void import('react-dom').then(({ default: ReactDOM }) => {
      axe(React, ReactDOM, 1000)
    })
  })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)