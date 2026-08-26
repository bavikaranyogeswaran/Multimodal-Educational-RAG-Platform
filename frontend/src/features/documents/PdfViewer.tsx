/**
 * PDF page renderer using PDF.js.
 *
 * This module is imported with React.lazy so it is split into its own chunk and
 * never included in the main bundle unless the viewer is actually opened.
 */

import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import * as pdfjsLib from 'pdfjs-dist';

import styles from '@/features/documents/documents.module.css';
import type { DocumentRegion } from '@/schemas/document';

// Worker path resolved at build time; Vite includes it in the output.
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).href;

const MIN_SCALE = 0.5;
const MAX_SCALE = 3.0;
const SCALE_STEP = 0.25;

interface BoundingBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

interface PdfViewerProps {
  /** Presigned URL from the backend — must be fetched before rendering. */
  url: string;
  /** When changed, jump to this 1-indexed page. The user can navigate freely afterwards. */
  targetPage?: number;
  /** Bounding box in PDF-point coordinates (origin at page bottom-left) to highlight. */
  overlay?: BoundingBox | null;
  /** Table and figure regions that render as invisible click targets on their page. */
  regions?: readonly DocumentRegion[];
  /** Called when the student clicks a table or figure region. */
  onRegionClick?: (region: DocumentRegion) => void;
}

export function PdfViewer({ url, targetPage, overlay, regions, onRegionClick }: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null);

  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [scale, setScale] = useState(1.0);
  const [isLoading, setIsLoading] = useState(true);
  // Height of the current page at scale=1 (PDF points), used to flip the y-axis for the overlay.
  const [basePageHeight, setBasePageHeight] = useState(0);

  // Load the PDF document whenever the URL changes.
  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    pdfjsLib
      .getDocument(url)
      .promise.then((doc) => {
        if (!cancelled) {
          setPdfDoc(doc);
          setTotalPages(doc.numPages);
          setCurrentPage(1);
          setIsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  // Jump to the externally requested page whenever it changes (e.g. citation chip click).
  // Also fires when totalPages becomes non-zero so a targetPage that arrived before the
  // document finished loading still takes effect.
  useEffect(() => {
    if (targetPage != null && totalPages > 0 && targetPage >= 1 && targetPage <= totalPages) {
      setCurrentPage(targetPage);
    }
  }, [targetPage, totalPages]);

  // Re-render the current page whenever pdfDoc, currentPage, or scale changes.
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current || isLoading) return;
    let cancelled = false;

    // Cancel any render still in progress from a previous update.
    renderTaskRef.current?.cancel();

    pdfDoc
      .getPage(currentPage)
      .then((page) => {
        if (cancelled || !canvasRef.current) return;

        const viewport = page.getViewport({ scale });
        // Store the unscaled height so the overlay can convert PDF y-coordinates to CSS pixels.
        const baseViewport = page.getViewport({ scale: 1.0 });
        const canvas = canvasRef.current;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        canvas.width = viewport.width;
        canvas.height = viewport.height;

        if (!cancelled) setBasePageHeight(baseViewport.height);

        const renderTask = page.render({ canvasContext: ctx, viewport });
        renderTaskRef.current = renderTask;

        renderTask.promise
          .then(() => {
            if (cancelled || !textLayerRef.current) return;
            const textDiv = textLayerRef.current;
            textDiv.style.width = `${viewport.width}px`;
            textDiv.style.height = `${viewport.height}px`;
            textDiv.innerHTML = '';

            page.getTextContent().then((textContent) => {
              if (cancelled || !textDiv) return;
              pdfjsLib.renderTextLayer({
                textContentSource: textContent,
                container: textDiv,
                viewport,
                textDivs: [],
              });
            });
          })
          // RenderingCancelledException is normal when a new render starts before
          // the previous one finishes; silence it here.
          .catch(() => {});
      });

    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [pdfDoc, currentPage, scale, isLoading]);

  function goToPrev() {
    setCurrentPage((p) => Math.max(1, p - 1));
  }

  function goToNext() {
    setCurrentPage((p) => Math.min(totalPages, p + 1));
  }

  function handlePageInput(e: ChangeEvent<HTMLInputElement>) {
    const n = parseInt(e.target.value, 10);
    if (!Number.isNaN(n) && n >= 1 && n <= totalPages) {
      setCurrentPage(n);
    }
  }

  function zoomIn() {
    setScale((s) => Math.min(MAX_SCALE, parseFloat((s + SCALE_STEP).toFixed(2))));
  }

  function zoomOut() {
    setScale((s) => Math.max(MIN_SCALE, parseFloat((s - SCALE_STEP).toFixed(2))));
  }

  if (isLoading) {
    return <div className={styles.pdfLoading}>Loading PDF…</div>;
  }

  return (
    <div className={styles.pdfViewer}>
      <div className={styles.pdfToolbar}>
        <button
          type="button"
          className={styles.pdfNavBtn}
          onClick={goToPrev}
          disabled={currentPage <= 1}
          aria-label="Previous page"
        >
          ‹
        </button>
        <input
          type="number"
          className={styles.pdfPageInput}
          value={currentPage}
          min={1}
          max={totalPages}
          aria-label="Current page"
          onChange={handlePageInput}
        />
        <span className={styles.pdfPageTotal}>/ {totalPages}</span>
        <button
          type="button"
          className={styles.pdfNavBtn}
          onClick={goToNext}
          disabled={currentPage >= totalPages}
          aria-label="Next page"
        >
          ›
        </button>
        <span className={styles.pdfDivider} />
        <button
          type="button"
          className={styles.pdfNavBtn}
          onClick={zoomOut}
          disabled={scale <= MIN_SCALE}
          aria-label="Zoom out"
        >
          −
        </button>
        <span className={styles.pdfZoom}>{Math.round(scale * 100)}%</span>
        <button
          type="button"
          className={styles.pdfNavBtn}
          onClick={zoomIn}
          disabled={scale >= MAX_SCALE}
          aria-label="Zoom in"
        >
          +
        </button>
      </div>

      <div className={styles.pdfCanvasArea}>
        <div className={styles.pdfCanvasWrapper}>
          <canvas ref={canvasRef} aria-label={`PDF page ${currentPage} of ${totalPages}`} />
          <div ref={textLayerRef} className={styles.textLayer} aria-hidden="true" />
          {overlay && basePageHeight > 0 ? (
            <div
              className={styles.citationOverlay}
              style={{
                // PDF x-axis matches canvas; y-axis is flipped (PDF origin at bottom-left).
                left: overlay.x0 * scale,
                top: (basePageHeight - overlay.y1) * scale,
                width: (overlay.x1 - overlay.x0) * scale,
                height: (overlay.y1 - overlay.y0) * scale,
              }}
            />
          ) : null}
          {basePageHeight > 0
            ? regions
                ?.filter((r) => r.page_number === currentPage)
                .map((r) => (
                  <div
                    key={r.id}
                    className={styles.regionTarget}
                    role="button"
                    tabIndex={0}
                    aria-label={`Select ${r.region_type}`}
                    style={{
                      left: r.bounding_box.x0 * scale,
                      top: (basePageHeight - r.bounding_box.y1) * scale,
                      width: (r.bounding_box.x1 - r.bounding_box.x0) * scale,
                      height: (r.bounding_box.y1 - r.bounding_box.y0) * scale,
                    }}
                    onClick={() => onRegionClick?.(r)}
                    onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onRegionClick?.(r);
                      }
                    }}
                  />
                ))
            : null}
        </div>
      </div>
    </div>
  );
}
