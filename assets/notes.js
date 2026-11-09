/**
 * notes.js
 * --------
 * Handles the notes/annotation feature:
 *   - W3C TextQuoteSelector-based text anchoring
 *   - FAB (floating action button) on text selection
 *   - Note creation / editing / deletion dialogs
 *   - Highlight rendering and rehidration after DOM reload
 *
 * Communicates with Python via window.pywebview.api.
 * Loaded after ui.js in the template.
 */

(function () {
    'use strict';

    // ----------------------------------------------------------------
    // State
    // ----------------------------------------------------------------

    let viewToken = null;          // Opaque token from Python identifying current render
    let currentNotes = [];         // Notes loaded for this file
    let pendingSelector = null;    // Selector captured when FAB was clicked
    let editingNoteId = null;      // ID of note being edited (null = new)
    let fabVisible = false;

    const CONTEXT_LEN = 32;        // Characters of prefix/suffix context

    // ----------------------------------------------------------------
    // DOM references (cached on init)
    // ----------------------------------------------------------------

    let fab, dialog, inspector;
    let dialogQuote, dialogInput, dialogTitle, dialogSaveBtn;
    let inspectorQuote, inspectorBody, inspectorMeta;

    function cacheDom() {
        fab = document.getElementById('note-fab');
        dialog = document.getElementById('note-dialog');
        inspector = document.getElementById('note-inspector');

        if (dialog) {
            dialogQuote = dialog.querySelector('.note-dialog-quote');
            dialogInput = dialog.querySelector('.note-dialog-input');
            dialogTitle = dialog.querySelector('.note-dialog-title');
            dialogSaveBtn = dialog.querySelector('.note-dialog-save');
        }
        if (inspector) {
            inspectorQuote = inspector.querySelector('.note-inspector-quote');
            inspectorBody = inspector.querySelector('.note-inspector-body');
            inspectorMeta = inspector.querySelector('.note-inspector-meta');
        }
    }

    // ----------------------------------------------------------------
    // Text index utilities (W3C TextQuoteSelector)
    // ----------------------------------------------------------------

    function getAnnotatableContainer() {
        return document.querySelector('.container');
    }

    /**
     * Returns true if the node is inside a region that should be excluded
     * from annotation (Mermaid diagrams, MathJax output, toolbar, etc).
     */
    function isExcludedNode(node) {
        let el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
        while (el) {
            if (el.classList) {
                if (el.classList.contains('mermaid') ||
                    el.classList.contains('MathJax') ||
                    el.classList.contains('MathJax_Display') ||
                    el.id === 'toolbar' ||
                    el.id === 'note-fab' ||
                    el.id === 'note-dialog' ||
                    el.id === 'note-inspector') {
                    return true;
                }
                // MathJax v3 uses mjx- prefix
                if (el.tagName && el.tagName.toLowerCase().startsWith('mjx-')) {
                    return true;
                }
            }
            el = el.parentElement;
        }
        return false;
    }

    /**
     * Build a flat text index from the annotatable container.
     * Returns { text: string, nodes: [{node, start, end}] }
     * where start/end are character offsets into `text`.
     */
    function buildTextIndex(container) {
        if (!container) return { text: '', nodes: [] };

        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                if (isExcludedNode(node)) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        });

        let text = '';
        const nodes = [];
        while (walker.nextNode()) {
            const node = walker.currentNode;
            const start = text.length;
            text += node.textContent;
            nodes.push({ node: node, start: start, end: text.length });
        }
        return { text: text, nodes: nodes };
    }

    /**
     * Extract a TextQuoteSelector from a DOM Range within the container.
     */
    function rangeToSelector(container, range) {
        const index = buildTextIndex(container);
        if (!index.text) return null;

        // Find start offset in text index
        let startOffset = -1, endOffset = -1;

        for (const entry of index.nodes) {
            if (entry.node === range.startContainer) {
                startOffset = entry.start + range.startOffset;
            }
            if (entry.node === range.endContainer) {
                endOffset = entry.start + range.endOffset;
            }
        }

        if (startOffset < 0 || endOffset < 0 || startOffset >= endOffset) return null;

        const exact = index.text.slice(startOffset, endOffset);
        const prefix = index.text.slice(Math.max(0, startOffset - CONTEXT_LEN), startOffset);
        const suffix = index.text.slice(endOffset, Math.min(index.text.length, endOffset + CONTEXT_LEN));

        return {
            exact: exact,
            prefix: prefix,
            suffix: suffix,
            start: startOffset,
            end: endOffset
        };
    }

    /**
     * Resolve a TextQuoteSelector back to a DOM Range.
     * Uses fast-path (offset check) then context-search fallback.
     */
    function selectorToRange(container, selector) {
        const index = buildTextIndex(container);
        if (!index.text || !selector || !selector.exact) return null;

        const exact = selector.exact;

        // Fast path: check stored offsets
        if (typeof selector.start === 'number' && typeof selector.end === 'number') {
            const candidate = index.text.slice(selector.start, selector.end);
            if (candidate === exact) {
                // Verify context too
                const pMatch = !selector.prefix || index.text.slice(
                    Math.max(0, selector.start - selector.prefix.length), selector.start
                ).endsWith(selector.prefix);
                const sMatch = !selector.suffix || index.text.slice(
                    selector.end, selector.end + (selector.suffix || '').length
                ).startsWith(selector.suffix);
                if (pMatch && sMatch) {
                    return offsetsToRange(index, selector.start, selector.end);
                }
            }
        }

        // Context search: find all occurrences of exact
        const candidates = [];
        let searchStart = 0;
        while (true) {
            const idx = index.text.indexOf(exact, searchStart);
            if (idx === -1) break;
            candidates.push(idx);
            searchStart = idx + 1;
        }

        if (candidates.length === 0) return null;
        if (candidates.length === 1) {
            // Single match — verify at least some context
            return offsetsToRange(index, candidates[0], candidates[0] + exact.length);
        }

        // Multiple matches — disambiguate using prefix/suffix context
        let bestIdx = -1;
        let bestScore = -1;

        for (const cStart of candidates) {
            const cEnd = cStart + exact.length;
            let score = 0;

            if (selector.prefix) {
                const actual = index.text.slice(
                    Math.max(0, cStart - selector.prefix.length), cStart
                );
                score += matchScore(selector.prefix, actual);
            }
            if (selector.suffix) {
                const actual = index.text.slice(
                    cEnd, cEnd + selector.suffix.length
                );
                score += matchScore(selector.suffix, actual);
            }

            if (score > bestScore) {
                bestScore = score;
                bestIdx = cStart;
            }
        }

        if (bestIdx >= 0) {
            return offsetsToRange(index, bestIdx, bestIdx + exact.length);
        }

        return null;
    }

    /**
     * Compute a similarity score between two strings (character-level match).
     */
    function matchScore(expected, actual) {
        if (!expected || !actual) return 0;
        const len = Math.min(expected.length, actual.length);
        let score = 0;
        for (let i = 0; i < len; i++) {
            if (expected[i] === actual[i]) score++;
        }
        return score;
    }

    /**
     * Convert text-index offsets to a DOM Range.
     */
    function offsetsToRange(index, start, end) {
        let startNode = null, startOff = 0;
        let endNode = null, endOff = 0;

        for (const entry of index.nodes) {
            if (startNode === null && start >= entry.start && start <= entry.end) {
                startNode = entry.node;
                startOff = start - entry.start;
            }
            if (end >= entry.start && end <= entry.end) {
                endNode = entry.node;
                endOff = end - entry.start;
            }
        }

        if (!startNode || !endNode) return null;

        try {
            const range = document.createRange();
            range.setStart(startNode, startOff);
            range.setEnd(endNode, endOff);
            return range;
        } catch (e) {
            console.error('[notes] Failed to create range:', e);
            return null;
        }
    }

    // ----------------------------------------------------------------
    // Highlight application (DOM <mark> wrapping)
    // ----------------------------------------------------------------

    /**
     * Wrap a DOM Range with <mark class="md-note-highlight" data-note-id="...">
     * Handles ranges that span multiple text nodes.
     */
    function applyHighlight(range, noteId) {
        if (!range) return;

        try {
            // Use document fragment approach to handle cross-node ranges
            const rects = range.getClientRects();
            if (!rects || rects.length === 0) return;

            // For ranges within a single text node
            if (range.startContainer === range.endContainer &&
                range.startContainer.nodeType === Node.TEXT_NODE) {
                const mark = document.createElement('mark');
                mark.className = 'md-note-highlight';
                mark.dataset.noteId = noteId;
                range.surroundContents(mark);
                return;
            }

            // For cross-node ranges, we need to wrap each text node segment
            const nodes = getTextNodesInRange(range);
            for (const { node, startOff, endOff } of nodes) {
                const subRange = document.createRange();
                subRange.setStart(node, startOff);
                subRange.setEnd(node, endOff);

                const mark = document.createElement('mark');
                mark.className = 'md-note-highlight';
                mark.dataset.noteId = noteId;
                subRange.surroundContents(mark);
            }
        } catch (e) {
            console.error('[notes] Failed to apply highlight for', noteId, ':', e);
        }
    }

    /**
     * Get all text nodes (and their relevant offsets) within a Range.
     */
    function getTextNodesInRange(range) {
        const results = [];
        const container = range.commonAncestorContainer;
        const root = container.nodeType === Node.TEXT_NODE ? container.parentNode : container;

        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
        let inRange = false;

        while (walker.nextNode()) {
            const node = walker.currentNode;

            if (node === range.startContainer) {
                inRange = true;
                const startOff = range.startOffset;
                const endOff = (node === range.endContainer) ? range.endOffset : node.textContent.length;
                if (endOff > startOff) {
                    results.push({ node, startOff, endOff });
                }
                if (node === range.endContainer) break;
                continue;
            }

            if (node === range.endContainer) {
                if (range.endOffset > 0) {
                    results.push({ node, startOff: 0, endOff: range.endOffset });
                }
                break;
            }

            if (inRange && node.textContent.length > 0) {
                results.push({ node, startOff: 0, endOff: node.textContent.length });
            }
        }

        return results;
    }

    /**
     * Remove all highlight marks for a given note ID.
     */
    function removeHighlight(noteId) {
        const marks = document.querySelectorAll(`mark.md-note-highlight[data-note-id="${noteId}"]`);
        marks.forEach(mark => {
            const parent = mark.parentNode;
            while (mark.firstChild) {
                parent.insertBefore(mark.firstChild, mark);
            }
            parent.removeChild(mark);
            parent.normalize();
        });
    }

    // ----------------------------------------------------------------
    // FAB controller
    // ----------------------------------------------------------------

    function showFab(x, y) {
        if (!fab) return;
        // Clamp position within viewport
        const size = 32;
        const margin = 8;
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        let left = Math.min(Math.max(x, margin), vw - size - margin);
        let top = Math.min(Math.max(y, margin), vh - size - margin);

        fab.style.left = left + 'px';
        fab.style.top = top + 'px';
        fab.style.display = 'flex';

        // Trigger reflow then animate
        requestAnimationFrame(() => {
            fab.classList.add('visible');
        });
        fabVisible = true;
    }

    function hideFab() {
        if (!fab) return;
        fab.classList.remove('visible');
        // After transition, hide completely
        setTimeout(() => {
            if (!fabVisible) {
                fab.style.display = 'none';
            }
        }, 200);
        fabVisible = false;
    }

    function handleSelectionChange() {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.toString().trim()) {
            hideFab();
            return;
        }

        // Check that the selection is within the container
        const container = getAnnotatableContainer();
        if (!container) { hideFab(); return; }

        const range = sel.getRangeAt(0);
        if (!container.contains(range.commonAncestorContainer)) {
            hideFab();
            return;
        }

        // Check for excluded regions
        if (isExcludedNode(range.startContainer) || isExcludedNode(range.endContainer)) {
            hideFab();
            return;
        }

        // Position FAB at top-right of selection
        const rects = range.getClientRects();
        if (!rects || rects.length === 0) { hideFab(); return; }

        const firstRect = rects[0];
        const lastRect = rects[rects.length - 1];

        // Position: top-right of first line of selection
        const fabX = Math.min(firstRect.right + 6, window.innerWidth - 40);
        const fabY = firstRect.top - 36;

        // If FAB would be above viewport, put it below selection
        if (fabY < 8) {
            showFab(fabX, lastRect.bottom + 6);
        } else {
            showFab(fabX, fabY);
        }
    }

    function initFab() {
        if (!fab) return;

        // Capture selector BEFORE the click removes the selection
        fab.addEventListener('mousedown', function (e) {
            e.preventDefault(); // Prevent selection from being cleared
            e.stopPropagation();

            const sel = window.getSelection();
            if (!sel || sel.isCollapsed) return;

            const container = getAnnotatableContainer();
            if (!container) return;

            const range = sel.getRangeAt(0);
            pendingSelector = rangeToSelector(container, range);
        });

        fab.addEventListener('click', function (e) {
            e.stopPropagation();
            if (pendingSelector) {
                openDialog(pendingSelector, null);
                hideFab();
            }
        });

        // Listen for selection changes
        document.addEventListener('mouseup', function () {
            // Small delay to let the selection settle
            setTimeout(handleSelectionChange, 50);
        });

        // Hide FAB when clicking elsewhere (but not on the FAB itself)
        document.addEventListener('mousedown', function (e) {
            if (fabVisible && e.target !== fab && !fab.contains(e.target)) {
                // Don't hide if clicking on a note highlight
                if (e.target.classList && e.target.classList.contains('md-note-highlight')) return;
                hideFab();
            }
        });
    }

    // ----------------------------------------------------------------
    // Note Dialog controller
    // ----------------------------------------------------------------

    function openDialog(selector, noteIdToEdit) {
        if (!dialog || !dialogInput) return;

        editingNoteId = noteIdToEdit || null;
        pendingSelector = selector;

        // Set title
        if (dialogTitle) {
            dialogTitle.textContent = editingNoteId ? 'Editar Nota' : 'Nueva Nota';
        }

        // Set quote preview
        if (dialogQuote) {
            const quoteText = selector.exact || '';
            dialogQuote.textContent = quoteText.length > 80
                ? quoteText.slice(0, 77) + '...'
                : quoteText;
        }

        // Pre-fill body if editing
        if (editingNoteId) {
            const note = currentNotes.find(n => n.id === editingNoteId);
            dialogInput.value = note ? note.body : '';
        } else {
            dialogInput.value = '';
        }

        // Signal Python that edit is starting
        if (viewToken && window.pywebview && window.pywebview.api) {
            window.pywebview.api.notes_begin_edit(viewToken);
        }

        dialog.style.display = 'block';

        // Focus textarea after animation
        setTimeout(() => {
            dialogInput.focus();
        }, 100);

        updateSaveButtonState();
    }

    function closeDialog() {
        if (!dialog) return;
        dialog.style.display = 'none';
        editingNoteId = null;
        pendingSelector = null;

        // Signal Python that edit finished
        if (viewToken && window.pywebview && window.pywebview.api) {
            window.pywebview.api.notes_end_edit(viewToken);
        }
    }

    function updateSaveButtonState() {
        if (dialogSaveBtn && dialogInput) {
            dialogSaveBtn.disabled = !dialogInput.value.trim();
        }
    }

    async function saveNote() {
        if (!dialogInput || !pendingSelector || !viewToken) return;

        const body = dialogInput.value.trim();
        if (!body) return;

        const api = window.pywebview && window.pywebview.api;
        if (!api) return;

        dialogSaveBtn.disabled = true;

        try {
            let result;
            if (editingNoteId) {
                result = await api.notes_update(viewToken, editingNoteId, body, null);
            } else {
                const noteId = 'note_' + crypto.randomUUID().replace(/-/g, '').slice(0, 12);
                const selectorJson = JSON.stringify(pendingSelector);
                result = await api.notes_create(viewToken, noteId, body, selectorJson);
            }

            if (result && result.ok) {
                closeDialog();
                // Reload and re-apply all notes
                await loadAndApplyNotes();
            } else {
                console.error('[notes] Save failed:', result);
                dialogSaveBtn.disabled = false;
            }
        } catch (e) {
            console.error('[notes] Save error:', e);
            dialogSaveBtn.disabled = false;
        }
    }

    function initDialog() {
        if (!dialog) return;

        // Backdrop click closes
        const backdrop = dialog.querySelector('.note-dialog-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', closeDialog);
        }

        // Close button
        const closeBtn = dialog.querySelector('.note-dialog-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', closeDialog);
        }

        // Cancel button
        const cancelBtn = dialog.querySelector('.note-dialog-cancel');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', closeDialog);
        }

        // Save button
        if (dialogSaveBtn) {
            dialogSaveBtn.addEventListener('click', saveNote);
        }

        // Input events
        if (dialogInput) {
            dialogInput.addEventListener('input', updateSaveButtonState);

            dialogInput.addEventListener('keydown', function (e) {
                e.stopPropagation(); // Prevent space/esc from closing window

                // ⌘ + Enter = save
                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                    e.preventDefault();
                    saveNote();
                    return;
                }

                // Escape = close
                if (e.key === 'Escape') {
                    e.preventDefault();
                    closeDialog();
                    return;
                }
            });
        }
    }

    // ----------------------------------------------------------------
    // Note Inspector (view/edit/delete popover)
    // ----------------------------------------------------------------

    function showInspector(noteId, anchorEl) {
        if (!inspector || !inspectorBody || !inspectorQuote) return;

        const note = currentNotes.find(n => n.id === noteId);
        if (!note) return;

        // Populate
        inspectorQuote.textContent = note.selector.exact || '';
        inspectorBody.textContent = note.body;
        if (inspectorMeta) {
            inspectorMeta.textContent = formatRelativeTime(note.updated_at || note.created_at);
        }

        // Position near the anchor element
        const rect = anchorEl.getBoundingClientRect();
        const inspW = 300;
        const margin = 12;

        let left = rect.left;
        let top = rect.bottom + 6;

        // Clamp horizontally
        if (left + inspW > window.innerWidth - margin) {
            left = window.innerWidth - inspW - margin;
        }
        left = Math.max(margin, left);

        // If it would overflow below, show above
        if (top + 200 > window.innerHeight) {
            top = rect.top - 200 - 6;
            top = Math.max(margin, top);
        }

        inspector.style.left = left + 'px';
        inspector.style.top = top + 'px';
        inspector.style.display = 'block';

        // Store current note id for actions
        inspector.dataset.noteId = noteId;
    }

    function hideInspector() {
        if (!inspector) return;
        inspector.style.display = 'none';
        inspector.dataset.noteId = '';
    }

    function initInspector() {
        if (!inspector) return;

        // Edit button
        const editBtn = inspector.querySelector('.note-inspector-edit');
        if (editBtn) {
            editBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                const noteId = inspector.dataset.noteId;
                const note = currentNotes.find(n => n.id === noteId);
                if (note) {
                    hideInspector();
                    openDialog(note.selector, noteId);
                }
            });
        }

        // Delete button
        const deleteBtn = inspector.querySelector('.note-inspector-delete');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', async function (e) {
                e.stopPropagation();
                const noteId = inspector.dataset.noteId;
                if (!noteId || !viewToken) return;

                const api = window.pywebview && window.pywebview.api;
                if (!api) return;

                try {
                    const result = await api.notes_delete(viewToken, noteId);
                    if (result && result.ok) {
                        hideInspector();
                        removeHighlight(noteId);
                        currentNotes = currentNotes.filter(n => n.id !== noteId);
                    }
                } catch (err) {
                    console.error('[notes] Delete error:', err);
                }
            });
        }

        // Click on highlights → show inspector
        document.addEventListener('click', function (e) {
            const mark = e.target.closest('mark.md-note-highlight');
            if (mark) {
                e.preventDefault();
                e.stopPropagation();
                const noteId = mark.dataset.noteId;
                if (noteId) {
                    showInspector(noteId, mark);
                }
                return;
            }

            // Click outside inspector → hide
            if (inspector.style.display !== 'none' &&
                !inspector.contains(e.target)) {
                hideInspector();
            }
        });
    }

    // ----------------------------------------------------------------
    // Notes loading and rehidration
    // ----------------------------------------------------------------

    async function loadAndApplyNotes() {
        if (!viewToken) return;

        const api = window.pywebview && window.pywebview.api;
        if (!api) {
            console.log('[notes] pywebview API not ready, retrying in 200ms...');
            setTimeout(loadAndApplyNotes, 200);
            return;
        }

        try {
            const result = await api.notes_list(viewToken);
            if (!result || result.error) {
                console.warn('[notes] Failed to load notes:', result);
                return;
            }

            currentNotes = result.notes || [];
            console.log('[notes] Loaded', currentNotes.length, 'note(s)');

            // Apply highlights
            const container = getAnnotatableContainer();
            if (!container) return;

            for (const note of currentNotes) {
                const range = selectorToRange(container, note.selector);
                if (range) {
                    applyHighlight(range, note.id);
                } else {
                    console.warn('[notes] Could not anchor note', note.id,
                        '(exact:', note.selector.exact, ')');
                }
            }
        } catch (e) {
            console.error('[notes] Error loading notes:', e);
        }
    }

    // ----------------------------------------------------------------
    // Utility
    // ----------------------------------------------------------------

    function formatRelativeTime(isoStr) {
        if (!isoStr) return '';
        try {
            const date = new Date(isoStr);
            const now = new Date();
            const diffMs = now - date;
            const diffMin = Math.floor(diffMs / 60000);
            const diffHr = Math.floor(diffMs / 3600000);
            const diffDay = Math.floor(diffMs / 86400000);

            if (diffMin < 1) return 'ahora';
            if (diffMin < 60) return `hace ${diffMin} min`;
            if (diffHr < 24) return `hace ${diffHr}h`;
            if (diffDay < 30) return `hace ${diffDay}d`;
            return date.toLocaleDateString();
        } catch (e) {
            return isoStr;
        }
    }

    // ----------------------------------------------------------------
    // Entry point: called by Python after load_html
    // ----------------------------------------------------------------

    window.notesOnFileLoaded = function (token) {
        console.log('[notes] File loaded, token:', token);
        viewToken = token;
        currentNotes = [];
        hideInspector();
        hideFab();
        loadAndApplyNotes();
    };

    // ----------------------------------------------------------------
    // Bootstrap
    // ----------------------------------------------------------------

    function initNotes() {
        cacheDom();
        initFab();
        initDialog();
        initInspector();
        if (typeof LiquidGlass !== 'undefined' && fab) {
            try { LiquidGlass.apply(fab, { circle: true }); } catch (_) {}
        }
        console.log('[notes] Module initialized');
        if (window._pendingNotesToken) {
            window.notesOnFileLoaded(window._pendingNotesToken);
            window._pendingNotesToken = null;
        }
    }

    window.addEventListener('pywebviewready', function () {
        if (viewToken && currentNotes.length === 0) {
            loadAndApplyNotes();
        }
    });

    function onReady(fn) {
        if (document.readyState !== 'loading') fn();
        else document.addEventListener('DOMContentLoaded', fn);
    }

    onReady(initNotes);

})();

