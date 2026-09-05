import cytoscape, { type Core, type ElementDefinition } from 'cytoscape';
import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router';

import { useApi } from '@/api/apiContext';
import { useDocuments } from '@/features/documents/hooks';
import { ApiGraphGateway } from '@/features/graph/apiGateway';
import { useGraph, useGraphEntity } from '@/features/graph/hooks';
import styles from '@/features/graph/graph.module.css';
import type { GraphEntity, GraphRelationship, RelationshipType } from '@/schemas/graph';

// ── Colour palette keyed by entity type ─────────────────────────────────────

const NODE_COLORS: Record<string, string> = {
  KnowledgeBase: '#7c3aed',
  Document: '#0369a1',
  Chapter: '#0891b2',
  Section: '#059669',
  Concept: '#d97706',
  Figure: '#db2777',
  Table: '#dc2626',
};

const EDGE_LABELS: Record<RelationshipType, string> = {
  CONTAINS: 'contains',
  PART_OF: 'part of',
  DEFINED_IN: 'defined in',
  RELATED_TO: 'related',
  PREREQUISITE_OF: 'prerequisite',
  COMPARES_WITH: 'compares',
  EXPLAINED_BY: 'explained by',
  SHOWN_IN: 'shown in',
  REFERENCES: 'references',
};

// ── Cytoscape helpers ────────────────────────────────────────────────────────

function toElements(
  entities: readonly GraphEntity[],
  relationships: readonly GraphRelationship[],
): ElementDefinition[] {
  const nodes: ElementDefinition[] = entities.map((e) => ({
    data: {
      id: e.id,
      label: e.name,
      type: e.entity_type,
      color: NODE_COLORS[e.entity_type] ?? '#6b7280',
    },
  }));
  const edges: ElementDefinition[] = relationships.map((r) => ({
    data: {
      id: r.id,
      source: r.source_entity_id,
      target: r.target_entity_id,
      label: EDGE_LABELS[r.relationship_type] ?? r.relationship_type,
    },
  }));
  return [...nodes, ...edges];
}

// ── Component ────────────────────────────────────────────────────────────────

export function GraphPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const loc = useLocation();
  const navigate = useNavigate();
  const kbName = (loc.state as { kbName?: string } | null)?.kbName ?? 'Knowledge Base';

  const apiClient = useApi();
  const gatewayRef = useRef(new ApiGraphGateway(apiClient));
  useEffect(() => {
    gatewayRef.current = new ApiGraphGateway(apiClient);
  }, [apiClient]);

  const { data: docs } = useDocuments(kbId!);
  const completedDocs = docs?.filter((d) => d.status === 'COMPLETED') ?? [];

  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [expanding, setExpanding] = useState(false);

  const effectiveDocId = selectedDocId ?? completedDocs[0]?.id ?? null;

  const { data: graph, isLoading: graphLoading } = useGraph(kbId!, effectiveDocId);
  const { data: entityDetail } = useGraphEntity(kbId!, selectedEntityId);

  // ── Cytoscape instance ───────────────────────────────────────────────────
  const canvasRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!canvasRef.current) return;

    const cy = cytoscape({
      container: canvasRef.current,
      elements: [],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)',
            label: 'data(label)',
            color: '#ffffff',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': '10px',
            'text-wrap': 'wrap',
            'text-max-width': '80px',
            width: '60px',
            height: '60px',
          },
        },
        {
          selector: 'node:selected',
          style: { 'border-width': 3, 'border-color': '#f59e0b' },
        },
        {
          selector: 'edge',
          style: {
            width: '1.5px',
            'line-color': '#9ca3af',
            'target-arrow-color': '#9ca3af',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': '8px',
            color: '#6b7280',
            'text-rotation': 'autorotate',
          },
        },
      ],
      layout: { name: 'cose', animate: false } as cytoscape.LayoutOptions,
      userZoomingEnabled: true,
      userPanningEnabled: true,
    });

    cy.on('tap', 'node', (evt) => {
      setSelectedEntityId(evt.target.id() as string);
    });
    cy.on('tap', (evt) => {
      if (evt.target === cy) setSelectedEntityId(null);
    });

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // Load graph data whenever it arrives or document changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !graph) return;
    setSelectedEntityId(null);
    cy.elements().remove();
    cy.add(toElements(graph.entities, graph.relationships));
    (cy.layout({ name: 'cose', animate: false } as cytoscape.LayoutOptions)).run();
    cy.fit(undefined, 30);
  }, [graph]);

  // Highlight selected node
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().unselect();
    if (selectedEntityId) cy.getElementById(selectedEntityId).select();
  }, [selectedEntityId]);

  // ── One-hop expansion ────────────────────────────────────────────────────
  async function expandNode(entityId: string) {
    const cy = cyRef.current;
    if (!cy || !kbId) return;
    setExpanding(true);
    try {
      const detail = await gatewayRef.current.getEntity(kbId, entityId);
      const knownIds = new Set(cy.nodes().map((n) => n.id()));
      const newElements: ElementDefinition[] = [];

      for (const r of detail.relationships) {
        const otherId =
          r.source_entity_id === entityId ? r.target_entity_id : r.source_entity_id;
        if (!knownIds.has(otherId)) {
          newElements.push({
            data: {
              id: otherId,
              label: '…',
              type: 'Concept',
              color: '#9ca3af',
            },
          });
          knownIds.add(otherId);
        }
        if (!cy.getElementById(r.id).length) {
          newElements.push({
            data: {
              id: r.id,
              source: r.source_entity_id,
              target: r.target_entity_id,
              label: EDGE_LABELS[r.relationship_type] ?? r.relationship_type,
            },
          });
        }
      }

      if (newElements.length) {
        cy.add(newElements);
        (cy.layout({ name: 'cose', animate: true } as cytoscape.LayoutOptions)).run();
      }
    } finally {
      setExpanding(false);
    }
  }

  // ── Detail panel data ────────────────────────────────────────────────────
  const selectedEntity = entityDetail?.entity ?? null;
  const entityRels = entityDetail?.relationships ?? [];
  const entityById = new Map((graph?.entities ?? []).map((e) => [e.id, e]));

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link
          to={`/knowledge-bases/${kbId}`}
          state={{ kbName }}
          className={styles.backLink}
        >
          ← {kbName}
        </Link>
        <h1 className={styles.title}>Concept graph</h1>
        {completedDocs.length > 0 && (
          <select
            className={styles.docSelect}
            aria-label="Select document"
            value={effectiveDocId ?? ''}
            onChange={(e) => {
              setSelectedDocId(e.target.value || null);
              setSelectedEntityId(null);
            }}
          >
            {completedDocs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </select>
        )}
      </header>

      <div className={styles.body}>
        {/* ── Canvas ──────────────────────────────────────────────────── */}
        <div className={styles.canvasWrap}>
          <div ref={canvasRef} className={styles.canvas} />
          {!effectiveDocId && !graphLoading && (
            <div className={styles.emptyState}>
              <p>No completed documents yet.</p>
              <p>Upload and process a document to explore its concept graph.</p>
            </div>
          )}
          {effectiveDocId && !graphLoading && graph?.entities.length === 0 && (
            <div className={styles.emptyState}>
              <p>No graph entities found for this document.</p>
              <p>Graph extraction runs after ingestion completes.</p>
            </div>
          )}
        </div>

        {/* ── Detail panel ────────────────────────────────────────────── */}
        <aside className={styles.panel}>
          {!selectedEntity ? (
            <p className={styles.panelPlaceholder}>Click a node to see details.</p>
          ) : (
            <>
              <p className={styles.entityName}>{selectedEntity.name}</p>
              <span className={styles.entityType}>{selectedEntity.entity_type}</span>

              {selectedEntity.description && (
                <p className={styles.entityDesc}>{selectedEntity.description}</p>
              )}

              {entityRels.length > 0 && (
                <>
                  <p className={styles.sectionLabel}>Relationships</p>
                  <ul className={styles.relList}>
                    {entityRels.slice(0, 8).map((r) => {
                      const otherId =
                        r.source_entity_id === selectedEntityId
                          ? r.target_entity_id
                          : r.source_entity_id;
                      const other = entityById.get(otherId);
                      return (
                        <li key={r.id} className={styles.relItem}>
                          <span className={styles.relType}>
                            {EDGE_LABELS[r.relationship_type]}
                          </span>
                          <span className={styles.relTarget} title={other?.name ?? otherId}>
                            {other?.name ?? '(unknown)'}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}

              {entityRels[0]?.evidence && (
                <>
                  <p className={styles.sectionLabel}>Evidence</p>
                  <div className={styles.evidenceBox}>{entityRels[0].evidence}</div>
                </>
              )}

              <div className={styles.panelActions}>
                <button
                  className={styles.btnPrimary}
                  onClick={() =>
                    void navigate(`/knowledge-bases/${kbId}/conversations`, {
                      state: {
                        kbName,
                        initialQuery: `Tell me about "${selectedEntity.name}"`,
                      },
                    })
                  }
                >
                  Ask about this concept
                </button>

                <button
                  className={styles.btnSecondary}
                  disabled={expanding}
                  onClick={() => void expandNode(selectedEntityId!)}
                >
                  {expanding ? 'Expanding…' : 'Expand one hop'}
                </button>

                {selectedEntity.source_document_id &&
                  selectedEntity.page_number != null && (
                    <Link
                      className={styles.btnSecondary}
                      to={`/knowledge-bases/${kbId}/documents/${selectedEntity.source_document_id}`}
                      state={{ page: selectedEntity.page_number }}
                      style={{ textAlign: 'center', display: 'block' }}
                    >
                      Open source — page {selectedEntity.page_number}
                    </Link>
                  )}
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
