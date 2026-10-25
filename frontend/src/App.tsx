import { BrowserRouter as Router, Navigate, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Report from './pages/Report';
import Queue from './pages/Queue';
import Calibration from './pages/Calibration';
import SiteDetail from './pages/SiteDetail';
import Settings from './pages/Settings';
import Live from './pages/Live';
import Traces from './pages/Traces';
import TraceDetail from './pages/TraceDetail';
import Approvals from './pages/Approvals';
import Rivers from './pages/Rivers';
import Relief from './pages/Relief';
import Story from './pages/Story';
import './index.css'; // ensure tailwind is imported here or in main.tsx

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/live" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="report" element={<Report />} />
          <Route path="queue" element={<Queue />} />
          <Route path="sites/:id" element={<SiteDetail />} />
          <Route path="sites/:id/calibrate" element={<Calibration />} />
          <Route path="settings" element={<Settings />} />
          <Route path="live" element={<Live />} />
          <Route path="traces" element={<Traces />} />
          <Route path="traces/:traceId" element={<TraceDetail />} />
          <Route path="approvals" element={<Approvals />} />
          <Route path="rivers" element={<Rivers />} />
          <Route path="relief" element={<Relief />} />
          <Route path="story" element={<Story />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
