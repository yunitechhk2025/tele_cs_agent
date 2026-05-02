import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/AppLayout';
import Login from './pages/Login';
import Conversations from './pages/Conversations';
import KnowledgeBase from './pages/KnowledgeBase';
import Contracts from './pages/Contracts';
import Settings from './pages/Settings';
import Products from './pages/Products';
import SceneLibrary from './pages/SceneLibrary';
import TelegramSimulator from './pages/TelegramSimulator';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <AppLayout>
              <Routes>
                <Route path="/" element={<Conversations />} />
                <Route path="/conversations" element={<Navigate to="/" replace />} />
                <Route path="/conversations/:id" element={<Conversations />} />
                <Route path="/knowledge" element={<KnowledgeBase />} />
                <Route path="/contracts" element={<Contracts />} />
                <Route path="/bots" element={<Navigate to="/settings?tab=bots" replace />} />
                <Route path="/products" element={<Products />} />
                <Route path="/scenes" element={<SceneLibrary />} />
                <Route path="/simulator" element={<TelegramSimulator />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </AppLayout>
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
