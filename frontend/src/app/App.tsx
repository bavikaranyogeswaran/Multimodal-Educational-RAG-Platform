import { Route, Routes } from 'react-router';

import { RequireAuth } from '@/features/authentication/RequireAuth';
import { SignInPage } from '@/features/authentication/SignInPage';
import { SignUpPage } from '@/features/authentication/SignUpPage';
import { ChatPage } from '@/features/conversations/ChatPage';
import { ConversationListPage } from '@/features/conversations/ConversationListPage';
import { DocumentListPage } from '@/features/documents/DocumentListPage';
import { GraphPage } from '@/features/graph/GraphPage';
import { KnowledgeBaseListPage } from '@/features/knowledge-bases/KnowledgeBaseListPage';
import { MemoryPage } from '@/features/memory/MemoryPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

/**
 * Every address this application answers.
 *
 * The guard wraps each protected element rather than sitting once around a layout route,
 * so a route added later is unprotected only if somebody writes it that way. A single
 * wrapper higher up reads as safer and is the opposite: everything nested under it is
 * protected by where it happens to sit in the file.
 */
export function App() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/sign-up" element={<SignUpPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <KnowledgeBaseListPage />
          </RequireAuth>
        }
      />
      <Route
        path="/knowledge-bases/:kbId"
        element={
          <RequireAuth>
            <DocumentListPage />
          </RequireAuth>
        }
      />
      <Route
        path="/knowledge-bases/:kbId/memory"
        element={
          <RequireAuth>
            <MemoryPage />
          </RequireAuth>
        }
      />
      <Route
        path="/knowledge-bases/:kbId/graph"
        element={
          <RequireAuth>
            <GraphPage />
          </RequireAuth>
        }
      />
      <Route
        path="/knowledge-bases/:kbId/conversations"
        element={
          <RequireAuth>
            <ConversationListPage />
          </RequireAuth>
        }
      />
      <Route
        path="/knowledge-bases/:kbId/conversations/:convId"
        element={
          <RequireAuth>
            <ChatPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
