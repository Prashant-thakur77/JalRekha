import { lazy, Suspense, type ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Live from './pages/Live';
import Traces from './pages/Traces';
import TraceDetail from './pages/TraceDetail';
import Approvals from './pages/Approvals';
import Rivers from './pages/Rivers';
import Relief from './pages/Relief';
import Story from './pages/Story';
import Credits from './pages/Credits';
import ScrollToTop from './components/ScrollToTop';

// Older tools load on demand so the main pages stay light.
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Report = lazy(() => import('./pages/Report'));
const Queue = lazy(() => import('./pages/Queue'));
const Calibration = lazy(() => import('./pages/Calibration'));
const SiteDetail = lazy(() => import('./pages/SiteDetail'));
const Settings = lazy(() => import('./pages/Settings'));
const Vision = lazy(() => import('./pages/Vision'));
const Cloud = lazy(() => import('./pages/Cloud'));

function Legacy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<p className="ns-muted">…</p>}>{children}</Suspense>;
}

function App() {
  return (
    <Router>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="dashboard" element={<Legacy><Dashboard /></Legacy>} />
          <Route path="report" element={<Legacy><Report /></Legacy>} />
          <Route path="queue" element={<Legacy><Queue /></Legacy>} />
          <Route path="sites/:id" element={<Legacy><SiteDetail /></Legacy>} />
          <Route path="sites/:id/calibrate" element={<Legacy><Calibration /></Legacy>} />
          <Route path="settings" element={<Legacy><Settings /></Legacy>} />
          <Route path="live" element={<Live />} />
          <Route path="traces" element={<Traces />} />
          <Route path="traces/:traceId" element={<TraceDetail />} />
          <Route path="vision" element={<Legacy><Vision /></Legacy>} />
          <Route path="cloud" element={<Legacy><Cloud /></Legacy>} />
          <Route path="approvals" element={<Approvals />} />
          <Route path="rivers" element={<Rivers />} />
          <Route path="relief" element={<Relief />} />
          <Route path="story" element={<Story />} />
          <Route path="credits" element={<Credits />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
