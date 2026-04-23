/**
 * ui.js
 * -----
 * Handles all interactive UI: mermaid init, pin toggle, search bar,
 * keyboard shortcuts, and liquid glass application.
 *
 * Expects LiquidGlass to be loaded before this script.
 * Communicates with Python via window.pywebview.api.
 */

(function () {
    'use strict';

    // ----------------------------------------------------------------
    // Mermaid initialization
    // ----------------------------------------------------------------

    function initMermaid() {
        if (typeof mermaid === 'undefined') return;

        const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        mermaid.initialize({
            startOnLoad: false,
            theme: isDark ? 'dark' : 'default',
            securityLevel: 'loose'
        });

        const diagrams = document.querySelectorAll('div.mermaid');
        console.log('[md-prev] Bloques mermaid en DOM:', diagrams.length);
        if (diagrams.length > 0) {
            mermaid.run({ nodes: diagrams })
                .then(() => console.log('[md-prev] Mermaid renderizado OK'))
                .catch(err => console.error('[md-prev] Error en Mermaid:', err));
        }
    }

    // ----------------------------------------------------------------
    // Pin button
    // ----------------------------------------------------------------

    function initPinButton() {
        const btn = document.getElementById('pin-btn');
        if (!btn) return;

        btn.addEventListener('click', function () {
            if (!window.pywebview || !window.pywebview.api) return;
            window.pywebview.api.toggle_on_top().then(function (newState) {
                if (newState) {
                    btn.classList.remove('unpinned');
                    btn.setAttribute('aria-pressed', 'true');
                } else {
                    btn.classList.add('unpinned');
                    btn.setAttribute('aria-pressed', 'false');
                }
            });
        });
    }

    // ----------------------------------------------------------------
    // Search
    // ----------------------------------------------------------------

    let searchExpanded = false;
    let highlights = [];
    let currentHighlightIdx = -1;

    function escapeRegex(str) {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    function clearHighlights() {
        highlights.forEach(mark => {
            const parent = mark.parentNode;
            if (!parent) return;
            parent.replaceChild(document.createTextNode(mark.textContent), mark);
            parent.normalize();
        });
        highlights = [];
        currentHighlightIdx = -1;
        updateCounter();
    }

    function findAndHighlight(query) {
        clearHighlights();
        if (!query || !query.trim()) return;

        const container = document.querySelector('.container');
        if (!container) return;

        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);

        const regex = new RegExp(escapeRegex(query), 'gi');

        textNodes.forEach(node => {
            const text = node.textContent;
            regex.lastIndex = 0;
            if (!regex.test(text)) return;
            regex.lastIndex = 0;

            const fragment = document.createDocumentFragment();
            let lastIdx = 0, match;

            while ((match = regex.exec(text)) !== null) {
                if (match.index > lastIdx) {
                    fragment.appendChild(document.createTextNode(text.slice(lastIdx, match.index)));
                }
                const mark = document.createElement('mark');
                mark.className = 'search-highlight';
                mark.textContent = match[0];
                highlights.push(mark);
                fragment.appendChild(mark);
                lastIdx = regex.lastIndex;
            }

            if (lastIdx < text.length) {
                fragment.appendChild(document.createTextNode(text.slice(lastIdx)));
            }

            node.parentNode.replaceChild(fragment, node);
        });

        if (highlights.length > 0) {
            currentHighlightIdx = 0;
            highlights[0].classList.add('current');
            highlights[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        updateCounter();
    }

    function navigateHighlight(direction) {
        if (highlights.length === 0) return;
        highlights[currentHighlightIdx]?.classList.remove('current');

        currentHighlightIdx += direction;
        if (currentHighlightIdx >= highlights.length) currentHighlightIdx = 0;
        if (currentHighlightIdx < 0) currentHighlightIdx = highlights.length - 1;

        highlights[currentHighlightIdx].classList.add('current');
        highlights[currentHighlightIdx].scrollIntoView({ behavior: 'smooth', block: 'center' });
        updateCounter();
    }

    function updateCounter() {
        const counter = document.getElementById('search-counter');
        if (!counter) return;
        if (highlights.length === 0) {
            counter.textContent = '';
        } else {
            counter.textContent = (currentHighlightIdx + 1) + '/' + highlights.length;
        }
    }

    function toggleSearch(forceState) {
        const bar = document.getElementById('search-bar');
        const input = document.getElementById('search-input');
        if (!bar || !input) return;

        const shouldExpand = forceState !== undefined ? forceState : !searchExpanded;

        if (shouldExpand) {
            bar.classList.add('expanded');
            searchExpanded = true;
            setTimeout(() => input.focus(), 300);
            // Apply glass effect to expanded bar
            if (typeof LiquidGlass !== 'undefined') {
                setTimeout(() => LiquidGlass.apply(bar, { borderRadius: 20 }), 450);
            }
        } else {
            bar.classList.remove('expanded');
            searchExpanded = false;
            input.value = '';
            clearHighlights();
            // Re-apply glass for circle shape
            if (typeof LiquidGlass !== 'undefined') {
                setTimeout(() => LiquidGlass.apply(bar, { circle: true }), 450);
            }
        }
    }

    function initSearch() {
        const bar = document.getElementById('search-bar');
        const input = document.getElementById('search-input');
        if (!bar || !input) return;

        // Click on collapsed bar → expand
        bar.addEventListener('click', function (e) {
            if (!searchExpanded) {
                e.stopPropagation();
                toggleSearch(true);
            }
        });

        // Typing → search
        let debounceTimer;
        input.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => findAndHighlight(input.value), 150);
        });

        // Navigation buttons
        document.getElementById('search-prev')?.addEventListener('click', function (e) {
            e.stopPropagation();
            navigateHighlight(-1);
        });
        document.getElementById('search-next')?.addEventListener('click', function (e) {
            e.stopPropagation();
            navigateHighlight(1);
        });
        document.getElementById('search-close')?.addEventListener('click', function (e) {
            e.stopPropagation();
            toggleSearch(false);
        });

        // Input keyboard shortcuts
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                navigateHighlight(e.shiftKey ? -1 : 1);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                toggleSearch(false);
            }
        });

        // Prevent space/esc from closing window when input is focused
        input.addEventListener('keydown', function (e) {
            e.stopPropagation();
        });
    }

    // ----------------------------------------------------------------
    // Keyboard shortcuts
    // ----------------------------------------------------------------

    function initKeyboard() {
        document.addEventListener('keydown', function (e) {
            // Cmd+F or Ctrl+F → toggle search
            if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
                e.preventDefault();
                toggleSearch();
                return;
            }

            // If search is open, don't process further
            if (searchExpanded) return;

            // Esc or Space → close window
            if (e.key === 'Escape' || e.key === ' ') {
                e.preventDefault();
                if (window.pywebview && window.pywebview.api) {
                    window.pywebview.api.close_window();
                }
            }
        });
    }

    // ----------------------------------------------------------------
    // Liquid Glass application
    // ----------------------------------------------------------------

    function initGlass() {
        if (typeof LiquidGlass === 'undefined') return;

        const pinBtn = document.getElementById('pin-btn');
        const searchBar = document.getElementById('search-bar');

        if (pinBtn) LiquidGlass.apply(pinBtn, { circle: true });
        if (searchBar) LiquidGlass.apply(searchBar, { circle: true });
    }

    // ----------------------------------------------------------------
    // Bootstrap
    // ----------------------------------------------------------------

    function onReady(fn) {
        if (document.readyState !== 'loading') fn();
        else document.addEventListener('DOMContentLoaded', fn);
    }

    onReady(function () {
        initMermaid();
        initPinButton();
        initSearch();
        initKeyboard();
        initGlass();
    });

})();
