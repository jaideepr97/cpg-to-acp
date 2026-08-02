import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router';
import { LaunchPage } from './LaunchPage';
import { IPSViewerPage } from './IPSViewerPage';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/launch" element={<LaunchPage />} />
        <Route path="/app" element={<IPSViewerPage />} />
        <Route path="*" element={<p>IPS Viewer — waiting for SMART launch from EHR</p>} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
