// SlidePresentation class from the slides skill (references/html-template.md)
class SlidePresentation {
    constructor(options = {}) {
        this.slides = Array.from(document.querySelectorAll('.slide'));
        this.current = 0;
        this.isAnimating = false;
        this.touchStartY = 0;
        this.touchStartX = 0;

        // Options
        this.dotColor    = options.dotColor    || 'var(--accent)';
        this.accentColor = options.accentColor || 'var(--accent)';

        this.init();
    }

    init() {
        if (!this.slides.length) return;
        this.buildNavDots();
        this.buildProgressBar();
        this.bindKeyboard();
        this.bindTouch();
        this.bindWheel();
        this.bindHash();
        this.observeSlides();
        this.goTo(this.getInitialSlide(), false);
    }

    // ── Navigation Dots ──────────────────────────────────────────────────────
    buildNavDots() {
        const nav = document.getElementById('navDots');
        if (!nav) return;
        this.slides.forEach((_, i) => {
            const btn = document.createElement('button');
            btn.className = 'nav-dot';
            btn.dataset.index = i;
            btn.setAttribute('aria-label', `Go to slide ${i + 1}`);
            btn.addEventListener('click', () => this.goTo(i));
            nav.appendChild(btn);
        });
        this.dots = Array.from(nav.querySelectorAll('.nav-dot'));
    }

    // ── Progress Bar ─────────────────────────────────────────────────────────
    buildProgressBar() {
        this.progressBar = document.getElementById('progressBar');
    }

    updateProgress() {
        if (!this.progressBar) return;
        const pct = this.slides.length > 1
            ? (this.current / (this.slides.length - 1)) * 100
            : 100;
        this.progressBar.style.width = `${pct}%`;
        this.progressBar.setAttribute('aria-valuenow', Math.round(pct));

        if (this.dots) {
            this.dots.forEach((d, i) => d.classList.toggle('active', i === this.current));
        }
    }

    // ── Navigation ───────────────────────────────────────────────────────────
    goTo(index, animate = true) {
        const target = Math.max(0, Math.min(index, this.slides.length - 1));
        if (target === this.current && animate) return;

        this.current = target;
        const slide = this.slides[target];
        slide.scrollIntoView({ behavior: animate ? 'smooth' : 'instant' });
        this.updateProgress();
        this.triggerEntranceAnimations(slide);

        // Update URL hash without triggering scroll
        history.replaceState(null, '', `#slide-${target + 1}`);

        // Announce to screen readers
        const region = slide.getAttribute('aria-label') || `Slide ${target + 1}`;
        this.announce(region);
    }

    next() { this.goTo(this.current + 1); }
    prev() { this.goTo(this.current - 1); }

    getInitialSlide() {
        const hash = window.location.hash;
        const match = hash.match(/#slide-(\d+)/);
        return match ? parseInt(match[1], 10) - 1 : 0;
    }

    // ── Keyboard ─────────────────────────────────────────────────────────────
    bindKeyboard() {
        document.addEventListener('keydown', (e) => {
            // Don't intercept if user is editing
            if (e.target.matches('[contenteditable]') || e.target.matches('input, textarea')) return;

            switch (e.key) {
                case 'ArrowDown': case 'ArrowRight': case ' ': case 'PageDown':
                    e.preventDefault(); this.next(); break;
                case 'ArrowUp': case 'ArrowLeft': case 'PageUp':
                    e.preventDefault(); this.prev(); break;
                case 'Home':
                    e.preventDefault(); this.goTo(0); break;
                case 'End':
                    e.preventDefault(); this.goTo(this.slides.length - 1); break;
                case 'Escape':
                    this.toggleOverview(); break;
                case 'f': case 'F':
                    if (!e.ctrlKey && !e.metaKey) this.toggleFullscreen(); break;
            }
        });
    }

    // ── Touch / Swipe ─────────────────────────────────────────────────────────
    bindTouch() {
        document.addEventListener('touchstart', (e) => {
            this.touchStartY = e.touches[0].clientY;
            this.touchStartX = e.touches[0].clientX;
        }, { passive: true });

        document.addEventListener('touchend', (e) => {
            const dy = this.touchStartY - e.changedTouches[0].clientY;
            const dx = this.touchStartX - e.changedTouches[0].clientX;

            // Only trigger on predominantly vertical swipe
            if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 40) {
                dy > 0 ? this.next() : this.prev();
            }
        }, { passive: true });
    }

    // ── Wheel ─────────────────────────────────────────────────────────────────
    bindWheel() {
        let wheelTimeout;
        document.addEventListener('wheel', (e) => {
            e.preventDefault();
            clearTimeout(wheelTimeout);
            wheelTimeout = setTimeout(() => {
                e.deltaY > 0 ? this.next() : this.prev();
            }, 50);
        }, { passive: false });
    }

    // ── Intersection Observer ──────────────────────────────────────────────────
    observeSlides() {
        const opts = { threshold: 0.6 };
        const obs = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const idx = this.slides.indexOf(entry.target);
                    if (idx !== -1 && idx !== this.current) {
                        this.current = idx;
                        this.updateProgress();
                        this.triggerEntranceAnimations(entry.target);
                    }
                }
            });
        }, opts);
        this.slides.forEach(s => obs.observe(s));
    }

    // ── Entrance Animations ───────────────────────────────────────────────────
    triggerEntranceAnimations(slide) {
        // Reset elements that should re-animate on revisit
        const animated = slide.querySelectorAll('[class*="enter-"]');
        animated.forEach(el => {
            el.style.animation = 'none';
            el.offsetHeight; // reflow
            el.style.animation = '';
        });
    }

    // ── Hash navigation ───────────────────────────────────────────────────────
    bindHash() {
        window.addEventListener('hashchange', () => {
            const idx = this.getInitialSlide();
            this.goTo(idx);
        });
    }

    // ── Overview mode (ESC) ──────────────────────────────────────────────────
    toggleOverview() {
        document.body.classList.toggle('overview-mode');
        if (document.body.classList.contains('overview-mode')) {
            document.querySelectorAll('.slide').forEach(s => {
                s.style.scrollSnapAlign = 'none';
                s.style.height = '20vh';
                s.style.cursor = 'pointer';
                s.onclick = () => {
                    const idx = parseInt(s.dataset.slideIndex || 0);
                    this.exitOverview();
                    setTimeout(() => this.goTo(idx), 50);
                };
            });
            document.documentElement.style.scrollSnapType = 'none';
        } else {
            this.exitOverview();
        }
    }

    exitOverview() {
        document.body.classList.remove('overview-mode');
        document.querySelectorAll('.slide').forEach(s => {
            s.style.scrollSnapAlign = '';
            s.style.height = '';
            s.style.cursor = '';
            s.onclick = null;
        });
        document.documentElement.style.scrollSnapType = '';
    }

    // ── Fullscreen ────────────────────────────────────────────────────────────
    toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen?.();
        } else {
            document.exitFullscreen?.();
        }
    }

    // ── Screen reader live region ─────────────────────────────────────────────
    announce(message) {
        let region = document.getElementById('sr-live');
        if (!region) {
            region = document.createElement('div');
            region.id = 'sr-live';
            region.setAttribute('aria-live', 'polite');
            region.setAttribute('aria-atomic', 'true');
            region.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden;';
            document.body.appendChild(region);
        }
        region.textContent = '';
        requestAnimationFrame(() => { region.textContent = message; });
    }
}

// Auto-init
document.addEventListener('DOMContentLoaded', () => {
    window.presentation = new SlidePresentation();
});
