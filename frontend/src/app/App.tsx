import { Route, Routes } from 'react-router';

import { RequireAuth } from '@/features/authentication/RequireAuth';
import { SignInPage } from '@/features/authentication/SignInPage';
import { SignUpPage } from '@/features/authentication/SignUpPage';
import { HomePage } from '@/pages/HomePage';
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
            <HomePage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
