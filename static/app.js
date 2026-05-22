/* ╔══════════════════════════════════════════════════════════╗
   ║  Memorex — Hermes Agent Memory Dashboard                ║
   ║  Application Logic (Vanilla JS, D3.js v7)              ║
   ╚══════════════════════════════════════════════════════════╝ */

(() => {
  'use strict';

  // ── Constants ──
  const TYPE_COLORS = {
    person:  '#f59e0b',
    project: '#3b82f6',
    tool:    '#10b981',
    concept: '#8b5cf6',
  };

  const EVENT_COLORS = {
    created:      'emerald',
    modified:     'blue',
    pruned:       'red',
    consolidated: 'amber',
    retained:     'emerald',
  };

  const DEBOUNCE_MS     = 300;
  const STATUS_INTERVAL = 30_000;

  // ── State ──
  let currentTab       = 'graph';
  let graphData        = null;
  let graphSimulation  = null;
  let graphZoom        = null;
  let graphSvgGroup    = null;
  let statusTimer      = null;

  // ── DOM Refs ──
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

  // ─────────────────────────────────────
  //  UTILITIES
  // ─────────────────────────────────────

  /** Safe fetch with error handling */
  async function apiFetch(url, retries = 2) {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
      } catch (err) {
        if (attempt === retries) {
          showToast(`Failed to load: ${url.split('?')[0]}`, 'error');
          throw err;
        }
        await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
      }
    }
  }

  /** Format seconds → human-readable uptime */
  function formatUptime(s) {
    if (s == null) return '—';
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m`;
    return `${Math.floor(s)}s`;
  }

  /** Format ISO date to readable string */
  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function formatDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  /** Format bytes */
  function formatBytes(bytes) {
    if (!bytes) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }

  /** Debounce */
  function debounce(fn, ms) {
    let id;
    return (...args) => {
      clearTimeout(id);
      id = setTimeout(() => fn(...args), ms);
    };
  }

  /** Escape HTML */
  function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /** Toast notification */
  function showToast(msg, type = 'info') {
    const container = $('#toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.animation = 'toastOut 0.3s var(--ease) forwards';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // ─────────────────────────────────────
  //  TAB NAVIGATION
  // ─────────────────────────────────────

  function initTabs() {
    const btns = $$('.tab-btn');
    const indicator = $('#tabIndicator');

    function activateTab(tabName) {
      currentTab = tabName;

      // Buttons
      btns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));

      // Panels
      $$('.tab-panel').forEach(p => {
        p.classList.toggle('active', p.id === `panel-${tabName}`);
      });

      // Indicator position
      const activeBtn = $(`.tab-btn[data-tab="${tabName}"]`);
      if (activeBtn && indicator) {
        indicator.style.left = activeBtn.offsetLeft + 'px';
        indicator.style.width = activeBtn.offsetWidth + 'px';
      }

      // Lazy-load content
      if (tabName === 'graph' && !graphData) loadGraph();
      if (tabName === 'skills') loadSkills();
    }

    btns.forEach(btn => {
      btn.addEventListener('click', () => activateTab(btn.dataset.tab));
    });

    // Initial position
    requestAnimationFrame(() => activateTab('graph'));

    // Reposition indicator on resize
    window.addEventListener('resize', debounce(() => {
      const activeBtn = $(`.tab-btn.active`);
      if (activeBtn && indicator) {
        indicator.style.left = activeBtn.offsetLeft + 'px';
        indicator.style.width = activeBtn.offsetWidth + 'px';
      }
    }, 150));
  }

  // ─────────────────────────────────────
  //  STATUS BAR
  // ─────────────────────────────────────

  async function refreshStatus() {
    try {
      const data = await apiFetch('/api/status');
      $('#statEntities').textContent = data.entity_count?.toLocaleString() ?? '—';
      $('#statSkills').textContent   = data.skill_count?.toLocaleString() ?? '—';
      $('#statEdges').textContent    = data.edge_count?.toLocaleString() ?? '—';
      $('#statUptime').textContent   = formatUptime(data.uptime_seconds);
    } catch {
      // Silently fail — status is non-critical
    }
  }

  function startStatusPolling() {
    refreshStatus();
    statusTimer = setInterval(refreshStatus, STATUS_INTERVAL);
  }

  // ─────────────────────────────────────
  //  KNOWLEDGE GRAPH (D3.js)
  // ─────────────────────────────────────

  async function loadGraph() {
    const filterType = $('#filterType').value;
    const maxNodes   = +$('#maxNodes').value;

    $('#graphLoading').classList.remove('hidden');

    try {
      graphData = await apiFetch(`/api/graph?filter_type=${filterType}&max_nodes=${maxNodes}`);
      renderGraph(graphData);
      renderGraphStats(graphData.stats);
    } catch {
      // Error already toasted
    } finally {
      $('#graphLoading').classList.add('hidden');
    }
  }

  function renderGraphStats(stats) {
    if (!stats) return;
    const container = $('#graphStats');
    const types = stats.entity_types || {};
    container.innerHTML = `
      <div class="stat-chip">
        <span class="stat-chip-value" style="color:var(--blue)">${stats.total_nodes ?? 0}</span>
        <span class="stat-chip-label">Nodes</span>
      </div>
      <div class="stat-chip">
        <span class="stat-chip-value" style="color:var(--violet)">${stats.total_edges ?? 0}</span>
        <span class="stat-chip-label">Edges</span>
      </div>
      ${Object.entries(types).map(([type, count]) => `
        <div class="stat-chip">
          <span class="stat-chip-value" style="color:${TYPE_COLORS[type] || '#fff'}">${count}</span>
          <span class="stat-chip-label">${esc(type)}</span>
        </div>
      `).join('')}
    `;
  }

  function renderGraph(data) {
    const svg = d3.select('#graphSvg');
    svg.selectAll('*').remove();

    const wrapper = document.getElementById('graphCanvasWrapper');
    const width   = wrapper.clientWidth;
    const height  = wrapper.clientHeight;

    svg.attr('viewBox', [0, 0, width, height]);

    // Container group for zoom/pan
    graphSvgGroup = svg.append('g');

    // Zoom behavior
    graphZoom = d3.zoom()
      .scaleExtent([0.2, 5])
      .on('zoom', (event) => {
        graphSvgGroup.attr('transform', event.transform);
      });

    svg.call(graphZoom);

    // Arrow marker for directed edges
    svg.append('defs').append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4')
      .attr('fill', 'rgba(255,255,255,0.15)');

    const nodes = data.nodes || [];
    const edges = data.edges || [];

    // Force simulation
    graphSimulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(100))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 8));

    // Links
    const link = graphSvgGroup.append('g')
      .selectAll('line')
      .data(edges)
      .join('line')
      .attr('class', 'graph-link')
      .attr('stroke-opacity', d => Math.min(0.6, 0.1 + (d.weight || 1) * 0.05))
      .attr('marker-end', 'url(#arrowhead)');

    // Link labels
    const linkLabel = graphSvgGroup.append('g')
      .selectAll('text')
      .data(edges)
      .join('text')
      .attr('class', 'graph-link-label')
      .text(d => d.label || '');

    // Node groups
    const nodeGroup = graphSvgGroup.append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('class', 'graph-node-group');

    // Node circles
    const circle = nodeGroup.append('circle')
      .attr('class', 'graph-node-circle')
      .attr('r', d => nodeRadius(d))
      .attr('fill', d => TYPE_COLORS[d.type] || '#666')
      .attr('stroke', d => {
        const c = TYPE_COLORS[d.type] || '#666';
        return d3.color(c).darker(0.5).toString();
      })
      .attr('opacity', 0.85);

    // Node labels
    const label = nodeGroup.append('text')
      .attr('class', 'graph-node-label')
      .attr('dy', d => nodeRadius(d) + 14)
      .text(d => d.label || d.id);

    // Drag
    const drag = d3.drag()
      .on('start', (event, d) => {
        if (!event.active) graphSimulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) graphSimulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeGroup.call(drag);

    // Hover tooltip
    const tooltip = document.getElementById('tooltip');

    nodeGroup
      .on('mouseenter', (event, d) => {
        const color = TYPE_COLORS[d.type] || '#888';
        tooltip.innerHTML = `
          <span class="tip-type" style="color:${color}">${esc(d.type || 'unknown')}</span>
          <span class="tip-name">${esc(d.label || d.id)}</span>
          <span class="tip-mentions">${d.mentions ?? 0} mentions</span>
        `;
        tooltip.classList.add('visible');

        // Highlight connected
        highlightNode(d, nodes, edges, circle, label, link);
      })
      .on('mousemove', (event) => {
        tooltip.style.left = (event.clientX + 14) + 'px';
        tooltip.style.top  = (event.clientY - 10) + 'px';
      })
      .on('mouseleave', () => {
        tooltip.classList.remove('visible');
        clearHighlights(circle, label, link);
      });

    // Click for detail
    nodeGroup.on('click', (event, d) => {
      event.stopPropagation();
      showNodeDetail(d, nodes, edges);
    });

    // Click background to deselect
    svg.on('click', () => {
      hideNodeDetail();
    });

    // Simulation tick
    graphSimulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);

      linkLabel
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2);

      nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`);
    });
  }

  function nodeRadius(d) {
    const mentions = d.mentions || 1;
    return Math.max(6, Math.min(24, 4 + Math.sqrt(mentions) * 2.5));
  }

  function highlightNode(d, nodes, edges, circleSel, labelSel, linkSel) {
    const connectedIds = new Set();
    connectedIds.add(d.id);

    edges.forEach(e => {
      const sid = typeof e.source === 'object' ? e.source.id : e.source;
      const tid = typeof e.target === 'object' ? e.target.id : e.target;
      if (sid === d.id) connectedIds.add(tid);
      if (tid === d.id) connectedIds.add(sid);
    });

    circleSel.classed('highlighted', n => n.id === d.id)
             .classed('dimmed', n => !connectedIds.has(n.id));

    labelSel.classed('highlighted', n => n.id === d.id)
            .classed('dimmed', n => !connectedIds.has(n.id));

    linkSel.classed('highlighted', e => {
      const sid = typeof e.source === 'object' ? e.source.id : e.source;
      const tid = typeof e.target === 'object' ? e.target.id : e.target;
      return sid === d.id || tid === d.id;
    }).classed('dimmed', e => {
      const sid = typeof e.source === 'object' ? e.source.id : e.source;
      const tid = typeof e.target === 'object' ? e.target.id : e.target;
      return sid !== d.id && tid !== d.id;
    });
  }

  function clearHighlights(circleSel, labelSel, linkSel) {
    circleSel.classed('highlighted', false).classed('dimmed', false);
    labelSel.classed('highlighted', false).classed('dimmed', false);
    linkSel.classed('highlighted', false).classed('dimmed', false);
  }

  function showNodeDetail(node, nodes, edges) {
    const panel = $('#nodeDetail');
    const body  = $('#nodeDetailBody');
    const dot   = $('#nodeDetailDot');
    const name  = $('#nodeDetailName');

    const color = TYPE_COLORS[node.type] || '#888';
    dot.style.background = color;
    name.textContent = node.label || node.id;

    // Connected nodes
    const connected = [];
    edges.forEach(e => {
      const sid = typeof e.source === 'object' ? e.source.id : e.source;
      const tid = typeof e.target === 'object' ? e.target.id : e.target;
      if (sid === node.id) {
        const target = nodes.find(n => n.id === tid);
        if (target) connected.push({ node: target, relation: e.label, direction: 'out' });
      }
      if (tid === node.id) {
        const source = nodes.find(n => n.id === sid);
        if (source) connected.push({ node: source, relation: e.label, direction: 'in' });
      }
    });

    body.innerHTML = `
      <div class="detail-row">
        <span class="detail-key">Type</span>
        <span class="detail-value" style="color:${color}">${esc(node.type || 'unknown')}</span>
      </div>
      <div class="detail-row">
        <span class="detail-key">Mentions</span>
        <span class="detail-value">${node.mentions ?? 0}</span>
      </div>
      <div class="detail-row">
        <span class="detail-key">First Seen</span>
        <span class="detail-value">${formatDate(node.first_seen)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-key">Last Seen</span>
        <span class="detail-value">${formatDate(node.last_seen)}</span>
      </div>
      ${node.metadata?.context ? `
        <div class="detail-row">
          <span class="detail-key">Context</span>
          <span class="detail-value">${esc(node.metadata.context)}</span>
        </div>
      ` : ''}
      ${connected.length > 0 ? `
        <div class="detail-section-title">Connected Nodes (${connected.length})</div>
        <div>
          ${connected.map(c => {
            const cColor = TYPE_COLORS[c.node.type] || '#666';
            const arrow = c.direction === 'out' ? '→' : '←';
            return `<span class="connected-node-chip" data-node-id="${esc(c.node.id)}">
              <span class="chip-dot" style="background:${cColor}"></span>
              ${arrow} ${esc(c.node.label || c.node.id)}
              <span style="color:var(--text-tertiary);font-style:italic;margin-left:2px">${esc(c.relation || '')}</span>
            </span>`;
          }).join('')}
        </div>
      ` : ''}
    `;

    panel.classList.remove('hidden');

    // Connected node chip clicks
    body.querySelectorAll('.connected-node-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const targetId = chip.dataset.nodeId;
        const targetNode = nodes.find(n => n.id === targetId);
        if (targetNode) showNodeDetail(targetNode, nodes, edges);
      });
    });
  }

  function hideNodeDetail() {
    $('#nodeDetail').classList.add('hidden');
  }

  function initGraphControls() {
    // Filter type
    $('#filterType').addEventListener('change', () => loadGraph());

    // Max nodes slider
    const slider = $('#maxNodes');
    const sliderVal = $('#maxNodesValue');
    slider.addEventListener('input', () => {
      sliderVal.textContent = slider.value;
    });
    slider.addEventListener('change', () => loadGraph());

    // Node search
    const nodeSearch = $('#nodeSearch');
    nodeSearch.addEventListener('input', debounce(() => {
      const query = nodeSearch.value.trim().toLowerCase();
      if (!graphData || !graphSvgGroup) return;

      const circles = graphSvgGroup.selectAll('.graph-node-circle');
      const labels  = graphSvgGroup.selectAll('.graph-node-label');

      if (!query) {
        circles.classed('highlighted', false).classed('dimmed', false);
        labels.classed('highlighted', false).classed('dimmed', false);
        return;
      }

      circles.classed('highlighted', d => (d.label || d.id).toLowerCase().includes(query))
             .classed('dimmed', d => !(d.label || d.id).toLowerCase().includes(query));
      labels.classed('highlighted', d => (d.label || d.id).toLowerCase().includes(query))
            .classed('dimmed', d => !(d.label || d.id).toLowerCase().includes(query));
    }, 200));

    // Close detail panel
    $('#closeNodeDetail').addEventListener('click', (e) => {
      e.stopPropagation();
      hideNodeDetail();
    });

    // Zoom controls
    $('#zoomIn').addEventListener('click', () => {
      d3.select('#graphSvg').transition().duration(300).call(graphZoom.scaleBy, 1.5);
    });
    $('#zoomOut').addEventListener('click', () => {
      d3.select('#graphSvg').transition().duration(300).call(graphZoom.scaleBy, 0.67);
    });
    $('#zoomReset').addEventListener('click', () => {
      d3.select('#graphSvg').transition().duration(500).call(graphZoom.transform, d3.zoomIdentity);
    });
  }

  // ─────────────────────────────────────
  //  SKILL EVOLUTION TIMELINE
  // ─────────────────────────────────────

  let skillsLoaded = false;

  async function loadSkills() {
    if (skillsLoaded) return;

    const loading = $('#skillsLoading');
    loading.classList.remove('hidden');

    try {
      const data = await apiFetch('/api/skills?include_diffs=true');
      renderCuratorSummary(data.curator_summary);
      renderTimeline(data);
      skillsLoaded = true;
    } catch {
      // Error already toasted
    } finally {
      loading.classList.add('hidden');
    }
  }

  function renderCuratorSummary(summary) {
    if (!summary) return;
    const container = $('#curatorStats');
    container.innerHTML = `
      <div class="curator-stat-card">
        <div class="curator-stat-value" style="color:var(--blue)">${summary.total_runs ?? 0}</div>
        <div class="curator-stat-label">Total Runs</div>
      </div>
      <div class="curator-stat-card">
        <div class="curator-stat-value" style="color:var(--emerald)">${summary.skills_retained ?? 0}</div>
        <div class="curator-stat-label">Retained</div>
      </div>
      <div class="curator-stat-card">
        <div class="curator-stat-value" style="color:var(--red)">${summary.skills_pruned ?? 0}</div>
        <div class="curator-stat-label">Pruned</div>
      </div>
      <div class="curator-stat-card">
        <div class="curator-stat-value" style="color:var(--amber)">${summary.skills_consolidated ?? 0}</div>
        <div class="curator-stat-label">Consolidated</div>
      </div>
    `;
  }

  function renderTimeline(data) {
    const container = $('#timeline');
    container.innerHTML = '';

    // Build a unified event list from skills
    const events = [];

    (data.skills || []).forEach(skill => {
      // Skill changes (created, modified, etc.)
      (skill.changes || []).forEach(change => {
        events.push({
          date: change.date,
          type: change.type,
          skill: skill.name,
          summary: change.summary,
          diff: change.diff,
          description: skill.description,
          size: skill.size_bytes,
          isAgentAuthored: skill.is_agent_authored,
        });
      });

      // Curator actions
      (skill.curator_actions || []).forEach(action => {
        events.push({
          date: action.date,
          type: action.action,
          skill: skill.name,
          summary: action.reason,
          curatorAction: true,
        });
      });
    });

    // Sort by date descending (newest first)
    events.sort((a, b) => new Date(b.date) - new Date(a.date));

    if (events.length === 0) {
      container.innerHTML = `
        <div class="no-results">
          <p>No skill evolution events found.</p>
        </div>
      `;
      return;
    }

    events.forEach((evt, i) => {
      const eventEl = document.createElement('div');
      eventEl.className = 'timeline-event';
      eventEl.style.animationDelay = `${i * 0.05}s`;

      const dotClass = evt.type || 'modified';
      const badgeClass = evt.type || 'modified';
      const diffId = `diff-${i}`;

      let diffHtml = '';
      if (evt.diff) {
        const parsedDiff = parseDiff(evt.diff);
        diffHtml = `
          <button class="timeline-diff-toggle" data-target="${diffId}">
            <svg viewBox="0 0 12 12" fill="none"><path d="M4 2l5 4-5 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            View changes
          </button>
          <div class="timeline-diff" id="${diffId}">${parsedDiff}</div>
        `;
      }

      let curatorHtml = '';
      if (evt.curatorAction) {
        curatorHtml = `
          <div class="timeline-curator-note">
            <strong>Curator:</strong> ${esc(evt.summary || '')}
          </div>
        `;
      }

      let metaHtml = '';
      if (evt.description && evt.type === 'created') {
        metaHtml = `<div class="timeline-summary" style="margin-top:4px;font-size:0.75rem;color:var(--text-tertiary)">${esc(evt.description)}</div>`;
      }
      if (evt.isAgentAuthored && evt.type === 'created') {
        metaHtml += `<div style="margin-top:6px"><span class="event-badge" style="background:var(--violet-dim);color:var(--violet)">🤖 Agent-Authored</span></div>`;
      }

      eventEl.innerHTML = `
        <div class="timeline-dot ${dotClass}"></div>
        <div class="timeline-card">
          <div class="timeline-card-header">
            <div>
              <span class="timeline-skill-name">${esc(evt.skill)}</span>
              <span class="event-badge ${badgeClass}">${esc(evt.type)}</span>
            </div>
            <span class="timeline-date">${formatDateTime(evt.date)}</span>
          </div>
          ${!evt.curatorAction ? `<div class="timeline-summary">${esc(evt.summary || '')}</div>` : ''}
          ${metaHtml}
          ${curatorHtml}
          ${diffHtml}
        </div>
      `;

      container.appendChild(eventEl);
    });

    // Wire diff toggles
    container.querySelectorAll('.timeline-diff-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = document.getElementById(btn.dataset.target);
        if (target) {
          const isOpen = target.classList.toggle('open');
          btn.classList.toggle('open', isOpen);
          btn.innerHTML = `
            <svg viewBox="0 0 12 12" fill="none"><path d="M4 2l5 4-5 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            ${isOpen ? 'Hide changes' : 'View changes'}
          `;
        }
      });
    });
  }

  function parseDiff(diff) {
    if (!diff) return '';
    return diff.split('\n').map(line => {
      if (line.startsWith('+')) return `<span class="diff-add">${esc(line)}</span>`;
      if (line.startsWith('-')) return `<span class="diff-remove">${esc(line)}</span>`;
      return esc(line);
    }).join('\n');
  }

  // ─────────────────────────────────────
  //  MEMORY SEARCH
  // ─────────────────────────────────────

  function initSearch() {
    const input      = $('#searchInput');
    const typeSelect = $('#searchType');
    const results    = $('#searchResults');
    const info       = $('#searchResultsInfo');
    const emptyState = $('#searchEmptyState');

    const doSearch = debounce(async () => {
      const q    = input.value.trim();
      const type = typeSelect.value;

      if (!q) {
        results.innerHTML = '';
        results.appendChild(emptyState);
        emptyState.style.display = '';
        info.innerHTML = '';
        return;
      }

      info.innerHTML = '<span style="color:var(--text-tertiary)">Searching…</span>';

      try {
        const data = await apiFetch(`/api/search?q=${encodeURIComponent(q)}&type=${type}&limit=20`);
        renderSearchResults(data, q);
      } catch {
        results.innerHTML = '<div class="no-results">Search failed. Please try again.</div>';
        info.innerHTML = '';
      }
    }, DEBOUNCE_MS);

    input.addEventListener('input', doSearch);
    typeSelect.addEventListener('change', doSearch);
  }

  function renderSearchResults(data, query) {
    const results    = $('#searchResults');
    const info       = $('#searchResultsInfo');
    const emptyState = $('#searchEmptyState');

    const items = data.results || [];
    const total = data.total || items.length;

    if (items.length === 0) {
      results.innerHTML = `<div class="no-results">No memories found matching "<strong>${esc(query)}</strong>"</div>`;
      info.innerHTML = '';
      return;
    }

    info.innerHTML = `Showing <span class="count">${items.length}</span> of <span class="count">${total}</span> results for "<strong>${esc(query)}</strong>"`;

    results.innerHTML = items.map((item, i) => {
      const highlighted = highlightContent(item.content || '', query, item.highlights);
      const relevancePct = Math.round((item.relevance || 0) * 100);
      const contextId = `ctx-${i}`;
      const hasContext = item.context_before || item.context_after;

      return `
        <div class="search-result-card" style="animation-delay:${i * 0.05}s">
          <div class="result-header">
            <div class="result-badges">
              <span class="source-badge">${esc(item.source || 'unknown')}</span>
              <span class="section-badge">${esc(item.section || '')}</span>
            </div>
            <span class="result-timestamp">${formatDateTime(item.timestamp)}</span>
          </div>

          <div class="result-content">${highlighted}</div>

          <div class="relevance-bar-wrapper">
            <span class="relevance-label">Relevance</span>
            <div class="relevance-bar">
              <div class="relevance-fill" style="width:${relevancePct}%"></div>
            </div>
            <span class="relevance-value">${relevancePct}%</span>
          </div>

          ${hasContext ? `
            <button class="context-toggle" data-target="${contextId}">
              <svg viewBox="0 0 12 12" fill="none"><path d="M4 2l5 4-5 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              Show context
            </button>
            <div class="context-content" id="${contextId}">
              ${item.context_before ? `
                <div class="context-label">Before</div>
                <div class="context-text">${esc(item.context_before)}</div>
              ` : ''}
              ${item.context_before && item.context_after ? '<div class="context-divider"></div>' : ''}
              ${item.context_after ? `
                <div class="context-label">After</div>
                <div class="context-text">${esc(item.context_after)}</div>
              ` : ''}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');

    // Wire context toggles
    results.querySelectorAll('.context-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = document.getElementById(btn.dataset.target);
        if (target) {
          const isOpen = target.classList.toggle('open');
          btn.classList.toggle('open', isOpen);
          btn.innerHTML = `
            <svg viewBox="0 0 12 12" fill="none"><path d="M4 2l5 4-5 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            ${isOpen ? 'Hide context' : 'Show context'}
          `;
        }
      });
    });
  }

  function highlightContent(content, query, highlights) {
    if (!content) return '';

    // Use provided highlight ranges if available
    if (highlights && highlights.length > 0) {
      let result = '';
      let lastIdx = 0;
      // Sort highlights by start position
      const sorted = [...highlights].sort((a, b) => a[0] - b[0]);
      sorted.forEach(([start, end]) => {
        result += esc(content.slice(lastIdx, start));
        result += `<mark>${esc(content.slice(start, end))}</mark>`;
        lastIdx = end;
      });
      result += esc(content.slice(lastIdx));
      return result;
    }

    // Fallback: simple case-insensitive highlight
    if (!query) return esc(content);
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return esc(content).replace(regex, '<mark>$1</mark>');
  }

  // ─────────────────────────────────────
  //  INITIALIZATION
  // ─────────────────────────────────────

  function init() {
    initTabs();
    initGraphControls();
    initSearch();
    startStatusPolling();

    // Handle window resize for graph
    window.addEventListener('resize', debounce(() => {
      if (currentTab === 'graph' && graphData) {
        renderGraph(graphData);
      }
    }, 300));
  }

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
