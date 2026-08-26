import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// ── Mock pdfjs-dist before importing the component ──────────────────────────

const mockRenderTask = { promise: Promise.resolve(), cancel: vi.fn() };

const mockPage = {
  getViewport: vi.fn(() => ({ width: 600, height: 800 })),
  render: vi.fn(() => mockRenderTask),
  getTextContent: vi.fn(() => Promise.resolve({ items: [] })),
};

const mockPdfDoc = {
  numPages: 3,
  getPage: vi.fn(() => Promise.resolve(mockPage)),
};

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: vi.fn(() => ({ promise: Promise.resolve(mockPdfDoc) })),
  renderTextLayer: vi.fn(),
}));

// ── Mock canvas context so jsdom doesn't throw ───────────────────────────────

beforeEach(() => {
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({}) as unknown as CanvasRenderingContext2D);
});

// ── Import component after mocks are in place ─────────────────────────────────

import { PdfViewer } from '@/features/documents/PdfViewer';

const TEST_URL = 'https://example.com/doc.pdf?sig=test';

describe('PdfViewer', () => {
  it('shows a loading state initially then renders page controls', async () => {
    render(<PdfViewer url={TEST_URL} />);

    // Initially the "Loading PDF…" text is visible.
    expect(screen.getByText(/loading pdf/i)).toBeInTheDocument();

    // After the async document load resolves, toolbar controls appear.
    await waitFor(() => {
      expect(screen.getByLabelText('Current page')).toBeInTheDocument();
    });
    expect(screen.getByText('/ 3')).toBeInTheDocument();
  });

  it('starts on page 1 with prev disabled and next enabled', async () => {
    render(<PdfViewer url={TEST_URL} />);
    await waitFor(() => screen.getByLabelText('Current page'));

    expect(screen.getByLabelText('Previous page')).toBeDisabled();
    expect(screen.getByLabelText('Next page')).not.toBeDisabled();
    expect((screen.getByLabelText('Current page') as HTMLInputElement).value).toBe('1');
  });

  it('advances to the next page when Next is clicked', async () => {
    render(<PdfViewer url={TEST_URL} />);
    await waitFor(() => screen.getByLabelText('Current page'));

    await userEvent.click(screen.getByLabelText('Next page'));

    await waitFor(() => {
      expect((screen.getByLabelText('Current page') as HTMLInputElement).value).toBe('2');
    });
  });

  it('goes back to the previous page when Prev is clicked', async () => {
    render(<PdfViewer url={TEST_URL} />);
    await waitFor(() => screen.getByLabelText('Current page'));

    await userEvent.click(screen.getByLabelText('Next page'));
    await waitFor(() =>
      expect((screen.getByLabelText('Current page') as HTMLInputElement).value).toBe('2'),
    );

    await userEvent.click(screen.getByLabelText('Previous page'));
    await waitFor(() =>
      expect((screen.getByLabelText('Current page') as HTMLInputElement).value).toBe('1'),
    );
  });

  it('disables Next on the last page', async () => {
    render(<PdfViewer url={TEST_URL} />);
    await waitFor(() => screen.getByLabelText('Current page'));

    // Advance to page 3 (the last page for the mocked 3-page doc).
    await userEvent.click(screen.getByLabelText('Next page'));
    await userEvent.click(screen.getByLabelText('Next page'));

    await waitFor(() =>
      expect((screen.getByLabelText('Current page') as HTMLInputElement).value).toBe('3'),
    );
    expect(screen.getByLabelText('Next page')).toBeDisabled();
  });

  it('shows the zoom percentage and zoom buttons', async () => {
    render(<PdfViewer url={TEST_URL} />);
    await waitFor(() => screen.getByLabelText('Current page'));

    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByLabelText('Zoom in')).toBeInTheDocument();
    expect(screen.getByLabelText('Zoom out')).toBeInTheDocument();
  });

  it('increases zoom when Zoom In is clicked', async () => {
    render(<PdfViewer url={TEST_URL} />);
    await waitFor(() => screen.getByLabelText('Current page'));

    await userEvent.click(screen.getByLabelText('Zoom in'));

    await waitFor(() => {
      expect(screen.getByText('125%')).toBeInTheDocument();
    });
  });

  it('decreases zoom when Zoom Out is clicked', async () => {
    render(<PdfViewer url={TEST_URL} />);
    await waitFor(() => screen.getByLabelText('Current page'));

    await userEvent.click(screen.getByLabelText('Zoom out'));

    await waitFor(() => {
      expect(screen.getByText('75%')).toBeInTheDocument();
    });
  });
});
