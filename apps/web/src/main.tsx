import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Toasts } from './components/Toasts';
import './index.css';
import { WorkspaceListPage } from './pages/WorkspaceList';
import { WorkspacePage } from './pages/Workspace';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 5_000, retry: 1 } },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<WorkspaceListPage />} />
          <Route path="/w/:slug" element={<WorkspacePage />} />
        </Routes>
      </BrowserRouter>
      <Toasts />
    </QueryClientProvider>
  </StrictMode>,
);
