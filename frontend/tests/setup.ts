import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Vitest does not unmount between tests automatically when globals are enabled.
afterEach(() => {
  cleanup();
});
