/**
 * liquid-glass.js
 * ---------------
 * SVG Displacement Map generator for liquid glass refraction effect.
 * Based on the technique from https://kube.io/blog/liquid-glass-css-svg/
 *
 * Uses Snell's Law + squircle convex surface profile to compute a
 * per-pixel displacement map, then applies it via SVG <feDisplacementMap>.
 *
 * On WebKit (pywebview/macOS), falls back to backdrop-filter: blur().
 */

const LiquidGlass = (() => {
    const isWebKit = /AppleWebKit/.test(navigator.userAgent) && !/Chrome/.test(navigator.userAgent);

    // --- Surface functions ---

    function squircleHeight(t) {
        if (t <= 0) return 0;
        if (t >= 1) return 1;
        return 1 - Math.pow(1 - t, 2.5);
    }

    function derivative(fn, t) {
        const d = 0.001;
        return (fn(Math.min(1, t + d)) - fn(Math.max(0, t - d))) / (2 * d);
    }

    // --- Snell's Law displacement calculation ---

    function preCalculateDisplacements(bezelWidth, thickness, n2) {
        const samples = 128;
        const displacements = new Float64Array(samples);

        for (let i = 0; i < samples; i++) {
            const t = i / (samples - 1);
            const height = squircleHeight(t) * thickness * bezelWidth;
            const slope = derivative(squircleHeight, t) * thickness;
            const incidentAngle = Math.abs(Math.atan(slope));

            if (incidentAngle < 0.001) { displacements[i] = 0; continue; }

            const sinRefracted = Math.sin(incidentAngle) / n2;
            if (Math.abs(sinRefracted) >= 1) { displacements[i] = 0; continue; }

            const refractedAngle = Math.asin(sinRefracted);
            displacements[i] = Math.abs(height * Math.tan(refractedAngle - incidentAngle));
        }
        return displacements;
    }

    function normalize(arr) {
        const max = Math.max(...arr);
        if (max === 0) return { normalized: arr, max: 0 };
        return { normalized: arr.map(v => v / max), max };
    }

    // --- Map generation ---

    function generateCircleMap(radius, opts = {}) {
        const thickness = opts.thickness || 0.35;
        const n2 = opts.refractiveIndex || 1.5;
        const bezelRatio = opts.bezelRatio || 1.0;
        const size = radius * 2;
        const bezelWidth = radius * bezelRatio;

        const raw = preCalculateDisplacements(bezelWidth, thickness, n2);
        const { normalized, max } = normalize(raw);

        const canvas = document.createElement('canvas');
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext('2d');
        const img = ctx.createImageData(size, size);
        const d = img.data;
        const cx = radius, cy = radius;

        for (let y = 0; y < size; y++) {
            for (let x = 0; x < size; x++) {
                const dx = x - cx, dy = y - cy;
                const dist = Math.sqrt(dx * dx + dy * dy);
                const idx = (y * size + x) * 4;

                if (dist >= radius) {
                    d[idx] = 128; d[idx + 1] = 128; d[idx + 2] = 128; d[idx + 3] = 255;
                    continue;
                }

                const t = Math.min((radius - dist) / bezelWidth, 1);
                const si = t * (normalized.length - 1);
                const lo = Math.floor(si), hi = Math.min(lo + 1, normalized.length - 1);
                const mag = normalized[lo] * (1 - (si - lo)) + normalized[hi] * (si - lo);

                const angle = Math.atan2(dy, dx);
                const dispX = -Math.cos(angle) * mag;
                const dispY = -Math.sin(angle) * mag;

                d[idx] = Math.round(128 + dispX * 127);
                d[idx + 1] = Math.round(128 + dispY * 127);
                d[idx + 2] = 128;
                d[idx + 3] = 255;
            }
        }

        ctx.putImageData(img, 0, 0);
        return { dataUrl: canvas.toDataURL(), maxDisplacement: max, width: size, height: size };
    }

    function generatePillMap(width, height, borderRadius, opts = {}) {
        const thickness = opts.thickness || 0.35;
        const n2 = opts.refractiveIndex || 1.5;
        const bezelRatio = opts.bezelRatio || 1.0;
        const bezelWidth = borderRadius * bezelRatio;

        const raw = preCalculateDisplacements(bezelWidth, thickness, n2);
        const { normalized, max } = normalize(raw);

        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        const img = ctx.createImageData(width, height);
        const d = img.data;

        const r = borderRadius;
        const corners = [
            { cx: r, cy: r },
            { cx: width - r, cy: r },
            { cx: r, cy: height - r },
            { cx: width - r, cy: height - r }
        ];

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const idx = (y * width + x) * 4;
                let distFromEdge, angle;

                // Find distance from nearest edge (rounded rect SDF)
                const clampX = Math.max(r, Math.min(x, width - r));
                const clampY = Math.max(r, Math.min(y, height - r));
                const dx = x - clampX, dy = y - clampY;
                const cornerDist = Math.sqrt(dx * dx + dy * dy);

                const inCorner = (x < r || x >= width - r) && (y < r || y >= height - r);

                if (inCorner) {
                    distFromEdge = r - cornerDist;
                    angle = Math.atan2(dy, dx);
                } else {
                    // Straight edges
                    const dLeft = x, dRight = width - 1 - x;
                    const dTop = y, dBottom = height - 1 - y;
                    const minDist = Math.min(dLeft, dRight, dTop, dBottom);
                    distFromEdge = minDist;

                    if (minDist === dLeft) angle = Math.PI;
                    else if (minDist === dRight) angle = 0;
                    else if (minDist === dTop) angle = -Math.PI / 2;
                    else angle = Math.PI / 2;
                }

                if (distFromEdge <= 0 || (inCorner && cornerDist >= r)) {
                    d[idx] = 128; d[idx + 1] = 128; d[idx + 2] = 128; d[idx + 3] = 255;
                    continue;
                }

                const t = Math.min(distFromEdge / bezelWidth, 1);
                const si = t * (normalized.length - 1);
                const lo = Math.floor(si), hi = Math.min(lo + 1, normalized.length - 1);
                const mag = normalized[lo] * (1 - (si - lo)) + normalized[hi] * (si - lo);

                // Displacement points inward
                const dispX = -Math.cos(angle) * mag;
                const dispY = -Math.sin(angle) * mag;

                d[idx] = Math.round(128 + dispX * 127);
                d[idx + 1] = Math.round(128 + dispY * 127);
                d[idx + 2] = 128;
                d[idx + 3] = 255;
            }
        }

        ctx.putImageData(img, 0, 0);
        return { dataUrl: canvas.toDataURL(), maxDisplacement: max, width, height };
    }

    // --- SVG filter creation ---

    function ensureSvgContainer() {
        let el = document.getElementById('glass-svg-filters');
        if (!el) {
            const ns = 'http://www.w3.org/2000/svg';
            el = document.createElementNS(ns, 'svg');
            el.id = 'glass-svg-filters';
            el.setAttribute('style', 'position:absolute;width:0;height:0;pointer-events:none;');
            el.setAttribute('aria-hidden', 'true');
            document.body.appendChild(el);
        }
        return el;
    }

    function createFilter(id, mapInfo) {
        const ns = 'http://www.w3.org/2000/svg';
        const container = ensureSvgContainer();

        const old = document.getElementById(id);
        if (old) old.remove();

        const filter = document.createElementNS(ns, 'filter');
        filter.id = id;
        filter.setAttribute('x', '0'); filter.setAttribute('y', '0');
        filter.setAttribute('width', '100%'); filter.setAttribute('height', '100%');
        filter.setAttribute('color-interpolation-filters', 'sRGB');

        const feImage = document.createElementNS(ns, 'feImage');
        feImage.setAttribute('href', mapInfo.dataUrl);
        feImage.setAttribute('result', 'dispMap');
        feImage.setAttribute('x', '0'); feImage.setAttribute('y', '0');
        feImage.setAttribute('width', mapInfo.width);
        feImage.setAttribute('height', mapInfo.height);

        const feDisp = document.createElementNS(ns, 'feDisplacementMap');
        feDisp.setAttribute('in', 'SourceGraphic');
        feDisp.setAttribute('in2', 'dispMap');
        feDisp.setAttribute('scale', mapInfo.maxDisplacement);
        feDisp.setAttribute('xChannelSelector', 'R');
        feDisp.setAttribute('yChannelSelector', 'G');

        filter.appendChild(feImage);
        filter.appendChild(feDisp);
        container.appendChild(filter);
        return id;
    }

    // --- Public API ---

    function apply(element, opts = {}) {
        if (isWebKit) {
            // Fallback: enhanced blur glassmorphism
            element.style.backdropFilter = 'blur(5px) saturate(160%)';
            element.style.webkitBackdropFilter = 'blur(5px) saturate(160%)';
            return;
        }

        const rect = element.getBoundingClientRect();
        const w = Math.round(rect.width), h = Math.round(rect.height);
        const isCircle = opts.circle || Math.abs(w - h) < 2;
        const filterId = 'glass-' + (element.id || Date.now());

        let mapInfo;
        if (isCircle) {
            mapInfo = generateCircleMap(Math.round(w / 2), opts);
        } else {
            const br = opts.borderRadius || Math.round(h / 2);
            mapInfo = generatePillMap(w, h, br, opts);
        }

        createFilter(filterId, mapInfo);
        element.style.backdropFilter = 'url(#' + filterId + ')';
    }

    return { apply, generateCircleMap, generatePillMap, createFilter, isWebKit };
})();
