"""Streamlit page styling — Quantum Technologies · Executive Intelligence design system.

Glassmorphism: rich gradient canvas (#0b1426), frosted glass cards (backdrop-filter blur),
bright gold (#f5c518) accent, maximum-contrast white text, electric blue depth gradients.
Cutting-edge executive AI platform aesthetic — Vercel meets Bloomberg Terminal.

Usage:
    from ui.styling import get_css
    st.markdown(get_css(), unsafe_allow_html=True)
"""

from __future__ import annotations

# --------------------------------------------------------------------- tokens
_TOKENS_CSS = """
:root {
    /* ── Executive — Quantum Technologies design system ── */

    /* Gold ramp (primary accent) — brighter for glass readability */
    --p-50:rgba(245,197,24,0.10); --p-100:rgba(245,197,24,0.18); --p-200:rgba(245,197,24,0.28); --p-300:#f9e080; --p-400:#f7d04e;
    --p-500:#f5c518; --p-600:#d4a800; --p-700:#a07c00; --p-800:#6b5200; --p-900:#3a2c0f;

    /* Secondary (steel blue) */
    --s-300:#7ba3d4; --s-500:#4a7fb5; --s-600:#3a6a9a;

    /* Tertiary (amber — medium severity only) */
    --t-300:#F4C357; --t-500:#E89B12;

    /* Neutral (navy-grey) */
    --n-50:#f0f4ff; --n-100:#d8e2f5; --n-200:#b0c0dc; --n-300:#7a90b0; --n-400:#4d6080;
    --n-500:#324060; --n-600:#243050; --n-700:#1a2236; --n-800:#111827; --n-900:#0a0f1e;

    /* ── Glassmorphism canvas ── */
    --bg:             #0b1426;
    --surface:        rgba(255,255,255,0.07);
    --surface-muted:  rgba(255,255,255,0.04);
    --divider:        rgba(255,255,255,0.12);
    --text-1:         #ffffff;
    --text-2:         #cbd5e1;
    --text-3:         #64748b;

    /* Brand — Bright Gold */
    --primary:        #f5c518;
    --primary-press:  #d4a800;
    --hero-fill:      linear-gradient(150deg, #f5c518 0%, #d4a800 50%, #a07c00 100%);
    --dark-fill:      #050810;
    --brand:          #f5c518;

    /* Semantic status */
    --success:        #22C55E;
    --success-soft:   rgba(34,197,94,0.12);
    --warning:        #F59E0B;
    --warning-soft:   rgba(245,158,11,0.12);
    --danger:         #F87171;
    --danger-soft:    rgba(248,113,113,0.12);
    --info:           #60A5FA;
    --info-soft:      rgba(96,165,250,0.12);

    /* AI — RESERVED teal */
    --ai:             #00C2A8;
    --ai-soft:        rgba(0,194,168,0.12);
    --ai-ink:         #A7F3D0;
    --gradient-ai:    linear-gradient(135deg,#5AE5D0 0%,#00C2A8 60%,#0A9D88 100%);
    --ai-glow:        0 0 0 1px rgba(0,194,168,.28), 0 8px 32px rgba(0,194,168,.2);

    /* Radius */
    --r-sm:  12px;
    --r-md:  20px;
    --r-lg:  28px;
    --r-xl:  32px;
    --r-full:9999px;

    /* Elevation */
    --elev-1: 0 1px 2px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.35);
    --elev-2: 0 8px 24px rgba(0,0,0,0.55);
    --elev-3: 0 20px 48px rgba(0,0,0,0.75);
    --purple-glow: 0 0 0 1px rgba(245,197,24,0.4), 0 12px 28px rgba(245,197,24,0.2);

    /* Legacy aliases */
    --accent:           #f5c518;
    --accent-strong:    #d4a800;
    --accent-dim:       #f7d04e;
    --accent-glow:      rgba(245,197,24,0.15);
    --accent-glow-strong: rgba(245,197,24,0.28);
    --text:             #ffffff;
    --text-muted:       #cbd5e1;
    --text-faint:       #64748b;
    --border:           rgba(255,255,255,0.12);
    --border-strong:    rgba(255,255,255,0.20);
    --border-accent:    rgba(245,197,24,0.45);
    --bg-elev-1:        rgba(255,255,255,0.09);
    --bg-elev-2:        rgba(255,255,255,0.12);
    --bg-card:          rgba(255,255,255,0.07);
    --bg-panel:         rgba(255,255,255,0.09);
    --violet:           #38bdf8;
    --violet-glow:      rgba(56,189,248,0.15);
    --green:            #22C55E;
    --green-glow:       rgba(34,197,94,0.15);
    --amber:            #F59E0B;
    --amber-glow:       rgba(245,158,11,0.15);
    --rose:             #F87171;
    --rose-glow:        rgba(248,113,113,0.15);
    --gold:             #f5c518;
    --gold-glow:        rgba(245,197,24,0.18);
    --silver:           #94a3b8;
    --silver-glow:      rgba(148,163,184,0.2);
    --chrome:           #94a3b8;
    --speed-line:       rgba(245,197,24,0.05);
}
"""

# ----------------------------------------------------------------- base shell
_SHELL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

.stApp {
    background: #0b1426;
    background-image:
        radial-gradient(ellipse 75% 60% at 12% -8%,  rgba(56,189,248,0.22) 0%, transparent 55%),
        radial-gradient(ellipse 55% 50% at 88% 8%,   rgba(245,197,24,0.18) 0%, transparent 50%),
        radial-gradient(ellipse 65% 55% at 50% 115%, rgba(14,165,233,0.15) 0%, transparent 55%),
        radial-gradient(ellipse 45% 40% at 8%  85%,  rgba(245,197,24,0.10) 0%, transparent 50%),
        radial-gradient(ellipse 40% 35% at 92% 88%,  rgba(0,194,168,0.08) 0%, transparent 50%);
    color: var(--text-1);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
}

/* Glass shimmer overlay */
.stApp::before {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    background: linear-gradient(
        135deg,
        rgba(255,255,255,0.015) 0%,
        transparent 40%,
        rgba(245,197,24,0.02) 70%,
        transparent 100%
    );
}

/* Hide ALL Streamlit chrome */
#MainMenu, footer,
[data-testid="stDeployButton"],
[data-testid="stToolbar"],
[data-testid="stToolbarActions"],
[data-testid="stStatusWidget"],
[data-testid="stAppDeployButton"],
button[title="View app in Streamlit Community Cloud"],
button[aria-label="Open app in Streamlit Community Cloud"],
.stDeployButton { display: none !important; visibility: hidden !important; height: 0 !important; }

/* ══════════════════════════════════════════════════════════════
   SIDEBAR
══════════════════════════════════════════════════════════════ */

[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"],
button[aria-label*="sidebar" i] { display: none !important; }

section[data-testid="stSidebar"],
section[data-testid="stSidebar"][aria-expanded="false"] {
    transform: none !important;
    visibility: visible !important;
    min-width: 360px !important;
    margin-left: 0 !important;
}

section[data-testid="stSidebar"] > div:first-child {
    min-width: 360px;
    width: 360px;
}

section[data-testid="stSidebar"] > div { visibility: visible !important; }

[data-testid="stAppViewContainer"] > .main,
[data-testid="stMain"] { padding-top: 0 !important; }

.block-container { padding-top: 1.5rem !important; }

section[data-testid="stSidebar"] {
    background: rgba(11,20,38,0.85);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border-right: 1px solid rgba(255,255,255,0.10);
    overflow-x: hidden !important;
}

/* Sidebar section headers */
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] .stMarkdown h3 {
    color: var(--primary);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-top: 1.4rem;
    margin-bottom: 0.4rem;
    padding: 0.35rem 0.6rem;
    border-left: 3px solid var(--primary);
    background: rgba(245,197,24,0.10);
    border-radius: 0 var(--r-sm) var(--r-sm) 0;
}

section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stMultiSelect label,
section[data-testid="stSidebar"] .stTextInput label,
section[data-testid="stSidebar"] .stToggle label,
section[data-testid="stSidebar"] .stCheckbox label,
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stCaption {
    white-space: normal !important;
    word-wrap: break-word !important;
    overflow-wrap: break-word !important;
}

section[data-testid="stSidebar"] [data-baseweb="select"] span,
section[data-testid="stSidebar"] [data-baseweb="select"] div {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
}

section[data-testid="stSidebar"] [data-testid="stRadio"] > div { gap: 0.3rem !important; }
section[data-testid="stSidebar"] [data-testid="stRadio"] label {
    font-size: 0.82rem !important;
    padding: 0.1rem 0 !important;
}

/* ══════════════════════════════════════════════════════════════
   APP HEADER
══════════════════════════════════════════════════════════════ */
_HEADER_CSS_PLACEHOLDER
"""

_HEADER_CSS = """
/* Signal bar at top of main content — gold */
.rev-bar {
    height: 2px;
    background: linear-gradient(90deg,
        transparent 0%,
        var(--p-300) 15%,
        var(--primary) 55%,
        var(--p-300) 80%,
        transparent 100%
    );
    margin-bottom: 1.2rem;
    border-radius: 2px;
    animation: signal-sweep 5s ease-in-out infinite;
    opacity: 0.6;
}

@keyframes signal-sweep {
    0%, 100% { opacity: 0.4; }
    50%       { opacity: 0.9; }
}

.app-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.75rem 1.2rem;
    background: var(--surface);
    border: 1px solid var(--divider);
    border-left: 4px solid var(--primary);
    border-radius: 0 var(--r-md) var(--r-md) 0;
    margin-bottom: 1.2rem;
    box-shadow: var(--elev-1);
}

.app-icon {
    font-size: 1.5rem;
    line-height: 1;
    width: 42px; height: 42px;
    border-radius: var(--r-sm);
    background: var(--hero-fill);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    box-shadow: var(--purple-glow);
}

.app-title-block { flex: 1; }

.app-title {
    font-size: 1.15rem;
    font-weight: 800;
    letter-spacing: -0.01em;
    color: var(--text-1);
    line-height: 1.1;
}

.app-tagline {
    font-size: 0.72rem;
    color: var(--text-2);
    letter-spacing: 0.02em;
    margin-top: 0.15rem;
}

.app-client-chip {
    display: inline-flex; align-items: center; gap: 0.4rem;
    padding: 0.3rem 0.85rem;
    background: var(--p-100);
    border: 1px solid var(--p-200);
    border-radius: var(--r-full);
    font-size: 0.68rem; font-weight: 700;
    letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--primary);
}

/* Brand wordmark in sidebar */
.acc-brand {
    display: flex; flex-direction: column; gap: 0.2rem;
    padding: 0.3rem 0 1rem 0;
}
.acc-wordmark {
    font-size: 1.6rem; font-weight: 600; letter-spacing: -0.02em;
    color: var(--text-1); line-height: 1.05;
}
.acc-wordmark .acc-mark {
    color: var(--primary); font-weight: 800; margin-left: 1px; font-size: 1.75rem;
}
.acc-eyebrow {
    font-size: 0.62rem; letter-spacing: 0.16em; text-transform: uppercase;
    color: var(--text-3);
}
.acc-footer {
    margin-top: 1.6rem; padding-top: 0.9rem; border-top: 1px solid var(--divider);
    font-size: 0.67rem; color: var(--text-3); letter-spacing: 0.03em; line-height: 1.5;
}
.acc-footer .acc-mark { color: var(--primary); font-weight: 800; }

/* Progress log */
.progress-log {
    display: flex; flex-direction: column; gap: 4px;
    max-height: 320px; overflow-y: auto;
    padding: 10px 14px; margin-top: 8px;
    background: var(--surface); border: 1px solid var(--divider);
    border-radius: var(--r-sm); font-size: 0.85rem;
    box-shadow: var(--elev-1);
}
.log-line { color: var(--text-2); line-height: 1.55; }
.log-line strong { color: var(--text-1); }
.log-icon { display: inline-block; width: 1.2em; color: var(--text-3); }
.log-evt { color: var(--text-3); text-transform: uppercase;
           font-size: 0.7rem; letter-spacing: 0.06em; }
.log-started .log-icon   { color: var(--primary); }
.log-completed .log-icon,
.log-done .log-icon      { color: var(--success); }
.log-failed .log-icon    { color: var(--danger); }
.log-failed strong       { color: var(--danger); }
.log-skipped .log-icon   { color: var(--warning); }
.log-failover            { color: var(--warning); }
.log-failover .log-icon  { color: var(--warning); }
.log-failover strong     { color: var(--warning); }
.log-failover .log-evt   { color: var(--warning); }

@media (max-width: 900px) { .pipeline { grid-template-columns: 1fr 1fr; } }

[data-testid="stMultiSelect"] [data-baseweb="tag"] {
    background-color: var(--surface-muted) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-sm) !important; color: var(--text-1) !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"] span { color: var(--text-1) !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"] svg {
    color: var(--text-3) !important; fill: var(--text-3) !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"]:hover { border-color: var(--primary) !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"]:hover svg {
    color: var(--primary) !important; fill: var(--primary) !important;
}
"""

# ------------------------------------------------------------- pipeline cards
_PIPELINE_CSS = """
/* ══ PIPELINE — horizontal stage track ══════════════════════ */
.pipeline {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 0;
    margin: 0 0 1.5rem 0;
    background: var(--surface);
    border: 1px solid var(--divider);
    border-radius: var(--r-md);
    overflow: hidden;
    position: relative;
    box-shadow: var(--elev-1);
}

.pipeline::before {
    content: '';
    position: absolute;
    top: 50%; left: 0; right: 0;
    height: 1px;
    background: var(--divider);
    transform: translateY(-50%);
    pointer-events: none;
}

.stage {
    padding: 0.9rem 0.75rem 0.75rem;
    background: var(--surface);
    border-right: 1px solid var(--divider);
    position: relative;
    transition: all 0.2s ease;
    text-align: center;
}
.stage:last-child { border-right: none; }

.stage.active {
    background: rgba(201,168,76,0.05);
    animation: stage-active-bg 1.8s ease-in-out infinite;
}
@keyframes stage-active-bg {
    0%, 100% { background: rgba(201,168,76,0.04); }
    50%       { background: rgba(201,168,76,0.09); }
}

.stage.done    { background: var(--success-soft); }
.stage.error   { background: var(--danger-soft); }
.stage.skipped { opacity: 0.45; }

.stage::before {
    content: '';
    display: block;
    width: 10px; height: 10px;
    border-radius: 50%;
    background: var(--n-300);
    border: 2px solid var(--surface);
    margin: 0 auto 0.6rem;
    position: relative;
    z-index: 1;
    box-shadow: 0 0 0 3px var(--surface);
    transition: all 0.2s ease;
}
.stage.active::before {
    background: var(--primary);
    box-shadow: 0 0 0 3px var(--surface), 0 0 12px rgba(201,168,76,0.4);
    animation: dot-pulse 1.4s ease-in-out infinite;
}
.stage.done::before  { background: var(--success); box-shadow: 0 0 0 3px var(--surface), 0 0 8px rgba(22,163,74,0.3); }
.stage.error::before { background: var(--danger);  box-shadow: 0 0 0 3px var(--surface); }

@keyframes dot-pulse {
    0%, 100% { box-shadow: 0 0 0 3px var(--surface), 0 0 10px rgba(201,168,76,0.3); }
    50%       { box-shadow: 0 0 0 3px var(--surface), 0 0 22px rgba(201,168,76,0.55); }
}

.stage-icon {
    font-size: 1.4rem; line-height: 1;
    margin-bottom: 0.3rem; display: block;
}

.stage-glyph {
    position: absolute; top: 0.4rem; right: 0.5rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.8rem; font-weight: 700; line-height: 1;
}
.stage.active .stage-glyph { color: var(--primary); animation: pulse 1.2s ease-in-out infinite; }
.stage.done   .stage-glyph { color: var(--success); }
.stage.error  .stage-glyph { color: var(--danger); }
.stage.skipped .stage-glyph { color: var(--text-3); }

@keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%       { opacity: 0.5; transform: scale(0.8); }
}

.stage.active::after {
    content: '';
    position: absolute;
    left: 0; right: 0; bottom: 0; height: 2px;
    background: linear-gradient(90deg, transparent 0%, var(--primary) 50%, transparent 100%);
    background-size: 200% 100%;
    animation: stage-sweep 1.4s linear infinite;
}
@keyframes stage-sweep {
    0%   { background-position: -100% 0; }
    100% { background-position: 100% 0; }
}

.stage.done .stage-glyph { animation: done-pop 0.4s cubic-bezier(0.34,1.56,0.64,1) 1; }
@keyframes done-pop {
    0%   { transform: scale(0.4); opacity: 0; }
    60%  { transform: scale(1.3); opacity: 1; }
    100% { transform: scale(1); opacity: 1; }
}

.stage-num {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem; font-weight: 700;
    color: var(--text-3); letter-spacing: 0.08em; margin-bottom: 0.2rem;
}

.stage-name {
    font-size: 0.82rem; font-weight: 700;
    color: var(--text-1); line-height: 1.2;
}

.stage.active .stage-name { color: var(--primary); }
.stage.done   .stage-name { color: var(--success); }

.stage-sub {
    font-size: 0.65rem; color: var(--text-2); margin-top: 0.2rem; line-height: 1.3;
}

.stage-model {
    display: inline-flex; align-items: center; gap: 0.3rem;
    margin-top: 0.4rem; padding: 0.18rem 0.45rem;
    background: var(--p-50);
    border: 1px solid var(--p-200);
    border-radius: var(--r-full);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6rem; color: var(--primary);
    letter-spacing: 0.02em; width: fit-content;
    font-weight: 600; margin-left: auto; margin-right: auto;
}
.stage-model-dot {
    width: 4px; height: 4px; border-radius: 50%;
    background: var(--primary); box-shadow: 0 0 5px rgba(201,168,76,0.4);
}
.stage-tokens {
    display: flex; gap: 0.4rem; margin-top: 0.3rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.58rem; color: var(--text-3);
    justify-content: center;
}
.stage-tokens-out { color: var(--success); }
.stage.done .stage-model { background: var(--success-soft); border-color: rgba(22,163,74,0.2); color: var(--success); }
.stage.done .stage-model-dot { background: var(--success); box-shadow: 0 0 5px rgba(22,163,74,0.3); }

.progress-status {
    margin: -0.5rem 0 1.2rem 0; padding: 0.55rem 0.9rem;
    background: var(--surface);
    border: 1px solid var(--divider);
    border-left: 3px solid var(--primary);
    border-radius: var(--r-sm);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem; color: var(--text-2);
    box-shadow: var(--elev-1);
}
.progress-status strong { color: var(--primary); margin-right: 0.5rem; font-weight: 700; letter-spacing: 0.04em; }

.pipeline-wrap {
    background: var(--surface); border: 1px solid var(--divider);
    border-radius: var(--r-md); padding: 1.2rem 1.4rem; margin-bottom: 1.5rem;
    transition: opacity 0.25s ease; box-shadow: var(--elev-1);
}
.pipeline-wrap.is-idle { opacity: 0.55; background: var(--surface-muted); }
.pl-stage { position: relative; z-index: 1; text-align: center; }
.pl-stage .pl-dot {
    width: 32px; height: 32px; border-radius: 50%;
    background: var(--surface-muted); border: 2px solid var(--divider);
    margin: 0 auto 0.6rem auto;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.72rem; font-weight: 700; color: var(--text-3);
}
.pl-stage.active .pl-dot {
    background: var(--primary); border-color: var(--primary); color: #0a0f1e;
    box-shadow: 0 0 0 4px rgba(201,168,76,0.15), 0 0 24px rgba(201,168,76,0.2);
    animation: pl-pulse 1.4s ease-in-out infinite;
}
.pl-stage.done .pl-dot { background: var(--surface-muted); border-color: var(--primary); color: var(--primary); }
@keyframes pl-pulse {
    0%, 100% { box-shadow: 0 0 0 4px rgba(201,168,76,0.12), 0 0 18px rgba(201,168,76,0.15); }
    50%       { box-shadow: 0 0 0 6px rgba(201,168,76,0.18), 0 0 30px rgba(201,168,76,0.25); }
}
.pl-label { font-size: 0.82rem; font-weight: 600; color: var(--text-1); margin-bottom: 0.2rem; }
.pl-sub   { font-size: 0.72rem; color: var(--text-3); }
"""

# --------------------------------------------------------------- KPI / cards
_KPI_CSS = """
/* ══ KPI CARDS ══════════════════════ */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 0.6rem;
    margin: 0 0 1.5rem 0;
}

.kpi {
    position: relative;
    padding: 1.2rem 1rem 0.9rem;
    background: var(--surface);
    border: 1px solid var(--divider);
    border-radius: var(--r-lg);
    overflow: hidden;
    box-shadow: var(--elev-1);
    transition: box-shadow 0.2s;
}

.kpi:hover { box-shadow: var(--elev-2); transform: translateY(-2px); transition: box-shadow 0.2s, transform 0.2s; }

/* Gauge bottom bar */
.kpi::after {
    content: '';
    position: absolute;
    left: 0; right: 0; bottom: 0; height: 3px;
    background: var(--divider);
    border-radius: 0 0 var(--r-lg) var(--r-lg);
}

.kpi.accent::after { background: linear-gradient(90deg, var(--primary), transparent); }
.kpi.violet::after { background: linear-gradient(90deg, var(--s-500), transparent); }
.kpi.amber::after  { background: linear-gradient(90deg, var(--warning), transparent); }
.kpi.rose::after   { background: linear-gradient(90deg, var(--danger), transparent); }
.kpi.green::after  { background: linear-gradient(90deg, var(--success), transparent); }

/* Hero KPI card — filled gold */
.kpi.hero {
    background: var(--hero-fill);
    border-color: transparent;
    box-shadow: var(--purple-glow);
    color: #0a0f1e;
}
.kpi.hero::after { background: rgba(255,255,255,0.2); }

.kpi-icon {
    font-size: 1.2rem; margin-bottom: 0.4rem; display: block; line-height: 1;
}

.kpi-label {
    font-size: 0.6rem; font-weight: 700;
    letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--text-3); margin-bottom: 0.4rem;
}
.kpi.hero .kpi-label { color: rgba(255,255,255,0.75); }

.kpi-value {
    font-size: clamp(1.8rem,2.5vw,2.4rem);
    font-weight: 800; letter-spacing: -0.03em;
    color: var(--text-1); line-height: 1;
}
.kpi.hero .kpi-value { color: #fff; }

.kpi.accent .kpi-value { color: var(--primary); }
.kpi.violet .kpi-value { color: var(--s-500); }
.kpi.amber  .kpi-value { color: var(--warning); }
.kpi.rose   .kpi-value { color: var(--danger); }
.kpi.green  .kpi-value { color: var(--success); }

.kpi-meta { font-size: 0.7rem; color: var(--text-3); margin-top: 0.3rem; }
.kpi.hero .kpi-meta { color: rgba(255,255,255,0.7); }
"""

# --------------------------------------------------------------- empty state
_EMPTY_CSS = """
.empty-state {
    padding: 2.5rem 2rem;
    background: var(--surface);
    border: 1px dashed var(--divider);
    border-radius: var(--r-lg);
    text-align: center;
    margin-top: 0.5rem; margin-bottom: 1.5rem;
    box-shadow: var(--elev-1);
}

.empty-eyebrow {
    font-size: 0.7rem; font-weight: 700;
    letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--primary); margin-bottom: 0.6rem;
}

.empty-title {
    font-size: 1.8rem; font-weight: 800; letter-spacing: -0.02em;
    color: var(--text-1); margin-bottom: 0.6rem;
}

.empty-sub {
    font-size: 0.9rem; color: var(--text-2);
    max-width: 640px; margin: 0 auto 1.5rem;
}

.empty-steps {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.85rem;
    max-width: 900px; margin: 0 auto;
    text-align: left;
}

.empty-step {
    padding: 0.95rem 1.05rem;
    background: var(--surface-muted);
    border: 1px solid var(--divider);
    border-radius: var(--r-md);
    transition: border-color 0.15s, box-shadow 0.15s;
}
.empty-step:hover { border-color: var(--p-300); box-shadow: var(--elev-1); }

.empty-step-num {
    font-size: 0.75rem; font-weight: 700; color: var(--primary);
    letter-spacing: 0.12em; margin-bottom: 0.3rem;
}

.empty-step-title { font-size: 0.9rem; font-weight: 600; color: var(--text-1); margin-bottom: 0.25rem; }
.empty-step-body  { font-size: 0.78rem; color: var(--text-2); line-height: 1.4; }

.empty-state-eyebrow {
    font-size: 0.7rem; font-weight: 700;
    letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--primary); margin-bottom: 0.6rem;
}

.empty-state-title {
    font-size: 1.5rem; font-weight: 800; letter-spacing: -0.01em;
    color: var(--text-1); line-height: 1.25; margin-bottom: 0.35rem;
}

.empty-state-subtitle {
    font-size: 0.88rem; color: var(--text-2); line-height: 1.5; margin-bottom: 1.3rem;
}
.empty-state-subtitle strong { color: var(--primary); }

.empty-step-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.85rem;
}

/* ── Main CTA button ─────────────────────────────────────────── */
.main-cta-wrap { margin: 1.4rem 0 0.6rem 0; }

.main-cta-wrap .stButton button {
    background: var(--primary) !important;
    color: #0a0f1e !important;
    border: none !important;
    font-weight: 700 !important;
    font-size: 1.1rem !important;
    letter-spacing: 0.04em !important;
    padding: 1.1rem 2rem !important;
    border-radius: var(--r-full) !important;
    box-shadow: var(--purple-glow) !important;
    transition: all 0.18s ease !important;
    min-height: 3.2rem !important;
}

.main-cta-wrap .stButton button:hover:not(:disabled) {
    background: var(--primary-press) !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 16px 40px rgba(201,168,76,0.35) !important;
}

.main-cta-wrap .stButton button:disabled {
    opacity: 0.35 !important; cursor: not-allowed !important;
}
"""

# ---------------------------------------------------- epic / story cards
_STORY_CSS = """
.epic-card {
    background: var(--surface);
    border: 1px solid var(--divider);
    border-left: 4px solid var(--primary);
    border-radius: var(--r-md);
    padding: 1rem 1.2rem;
    margin-bottom: 1.2rem;
    box-shadow: var(--elev-1);
}

.epic-head { display: flex; align-items: baseline; gap: 0.7rem; margin-bottom: 0.5rem; }

.epic-id {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem; font-weight: 700;
    color: var(--text-3); letter-spacing: 0.08em; text-transform: uppercase;
}

.epic-title { font-size: 1.1rem; font-weight: 800; color: var(--text-1); letter-spacing: -0.01em; }
.epic-desc  { font-size: 0.84rem; color: var(--text-2); line-height: 1.45; margin-bottom: 0.7rem; }

.story-card {
    background: var(--surface-muted);
    border: 1px solid var(--divider);
    border-radius: var(--r-sm);
    padding: 0.8rem 1rem;
    margin-bottom: 0.65rem;
    transition: border-color 0.15s, box-shadow 0.15s;
}
.story-card:hover { border-color: var(--p-300); box-shadow: var(--elev-2); transform: translateY(-1px); }
.epic-card  { animation: fadeUp 0.3s cubic-bezier(.2,0,.2,1) both; }
.story-card { transition: border-color 0.18s, box-shadow 0.18s, transform 0.18s; }

.story-head { display: flex; align-items: center; gap: 0.55rem; margin-bottom: 0.4rem; }

.story-id {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.63rem; font-weight: 700;
    color: var(--text-3); letter-spacing: 0.08em; text-transform: uppercase;
}

.story-title { font-size: 0.9rem; font-weight: 600; color: var(--text-1); }

.story-pri {
    font-size: 0.63rem; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase;
    padding: 0.12rem 0.5rem; border-radius: var(--r-full); margin-left: auto;
}

.pri-high {
    background: var(--danger-soft); color: var(--danger);
    border: 1px solid rgba(229,72,77,.35);
    position: relative;
}
.pri-high::before {
    content: "";
    display: inline-block; width: 5px; height: 5px; border-radius: 999px;
    background: var(--danger); margin-right: 0.3rem;
    vertical-align: middle; box-shadow: 0 0 5px rgba(229,72,77,0.4);
    animation: pri-pulse 2.2s ease-in-out infinite;
}
@keyframes pri-pulse { 0%, 100% { opacity: 0.85; } 50% { opacity: 0.3; } }
.pri-medium { background: var(--warning-soft); color: var(--warning); border: 1px solid rgba(245,158,11,.35); }
.pri-low    { background: var(--success-soft); color: var(--success); border: 1px solid rgba(22,163,74,.35); }

.story-user { font-size: 0.82rem; color: var(--text-1); font-style: italic; margin-bottom: 0.4rem; }
.story-ac   { margin: 0.4rem 0 0.4rem 1rem; padding: 0; font-size: 0.78rem; color: var(--text-2); line-height: 1.45; }
.story-ac li { margin-bottom: 0.15rem; }

.tags-row { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.4rem 0; }
.tag {
    font-size: 0.63rem; font-weight: 600;
    padding: 0.12rem 0.48rem;
    background: var(--p-50); color: var(--primary);
    border: 1px solid var(--p-200); border-radius: var(--r-full);
}

.task-list { margin: 0.35rem 0 0 1rem; padding: 0; font-size: 0.75rem; color: var(--text-2); line-height: 1.5; }

.summary-card {
    background: var(--surface);
    border: 1px solid var(--divider);
    border-left: 4px solid var(--primary);
    border-radius: var(--r-md);
    padding: 1.1rem 1.35rem;
    margin-bottom: 1.2rem;
    font-size: 0.92rem; line-height: 1.55; color: var(--text-1);
    box-shadow: var(--elev-1);
}

.summary-label {
    font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.12em; color: var(--primary); margin-bottom: 0.5rem;
}
"""

# ---------------------------------------------- findings
_FINDING_CSS = """
.finding-card {
    background: var(--surface);
    border: 1px solid var(--divider);
    border-radius: var(--r-md);
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.75rem;
    box-shadow: var(--elev-1);
    transition: box-shadow 0.18s, transform 0.18s;
}
.finding-card:hover { box-shadow: var(--elev-2); transform: translateY(-1px); }
.finding-gap      { border-left: 4px solid var(--warning); }
.finding-conflict { border-left: 4px solid var(--danger); }
.finding-dup      { border-left: 4px solid var(--s-500); }
.finding-head     { display: flex; align-items: baseline; gap: 0.55rem; margin-bottom: 0.3rem; }
.finding-kind {
    font-size: 0.63rem; font-weight: 700;
    letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-3);
}
.finding-title   { font-size: 0.94rem; font-weight: 600; color: var(--text-1); }
.finding-body    { font-size: 0.82rem; color: var(--text-2); line-height: 1.5; }
.finding-evidence {
    margin-top: 0.4rem; padding: 0.5rem 0.7rem;
    background: var(--surface-muted); border-left: 2px solid var(--divider);
    border-radius: var(--r-sm); font-size: 0.76rem; color: var(--text-2); font-style: italic;
}
"""

# --------------------------------------------------------------- run meta
_RUN_META_CSS = """
.run-meta {
    display: flex; flex-wrap: wrap; gap: 0.5rem 1.1rem; align-items: center;
    padding: 0.55rem 0.85rem;
    background: var(--surface);
    border: 1px solid var(--divider); border-radius: var(--r-md);
    font-size: 0.8rem; color: var(--text-1); margin-bottom: 1rem;
    box-shadow: var(--elev-1);
}
.run-meta-item  { display: inline-flex; align-items: center; gap: 0.4rem; }
.run-meta-icon  { font-size: 0.95rem; line-height: 1; color: var(--primary); }
.run-meta-label { font-size: 0.66rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); margin-right: 0.25rem; }
.run-meta-sep   { color: var(--text-3); opacity: 0.55; }
.run-meta strong { color: var(--text-1); margin-right: 0.35rem; font-weight: 600; }
"""

# ------------------------------------------------------------- what's-next
_NEXT_CSS = """
.next-strip {
    display: flex; flex-wrap: wrap; align-items: center; gap: 0.85rem;
    margin: 0.4rem 0 1.1rem 0; padding: 0.7rem 1rem;
    background: var(--surface); border: 1px solid var(--divider); border-radius: var(--r-md);
    box-shadow: var(--elev-1);
}
.next-strip-label {
    font-size: 0.64rem; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--text-3);
}
.next-strip-items { display: flex; flex-wrap: wrap; gap: 0.5rem; flex: 1; }
.next-chip {
    display: inline-flex; align-items: center; gap: 0.4rem;
    padding: 0.3rem 0.7rem; background: var(--surface-muted);
    border: 1px solid var(--divider); border-radius: var(--r-full);
    font-size: 0.75rem; color: var(--text-1);
}
.next-chip-violet { color: var(--s-500); border-color: rgba(123,102,230,0.4); background: rgba(123,102,230,0.06); font-weight: 600; }
.next-chip-amber  { color: var(--warning); border-color: rgba(245,158,11,0.4);  background: var(--warning-soft);  font-weight: 600; }
.next-chip-icon   { font-size: 0.85rem; line-height: 1; opacity: 0.85; }

section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button {
    white-space: nowrap !important; overflow: hidden !important;
    text-overflow: ellipsis !important; padding: 0.5rem 0.5rem !important;
    font-size: 0.82rem !important; min-width: 0 !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="secondary"] {
    background: var(--surface) !important;
    border: 1px solid var(--divider) !important;
    color: var(--text-1) !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="secondary"]:hover {
    background: var(--surface-muted) !important;
    border-color: var(--primary) !important;
    color: var(--primary) !important;
}

/* Guardrail PASS */
.guardrail-pass {
    margin: 0.5rem 0 1.2rem 0; padding: 1.1rem 1.3rem;
    background: var(--success-soft); border: 1px solid rgba(22,163,74,0.3);
    border-left: 4px solid var(--success); border-radius: var(--r-md); color: var(--text-1);
    box-shadow: var(--elev-1);
}
.guardrail-pass-tag    { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--success); margin-bottom: 0.55rem; }
.guardrail-pass-title  { font-size: 0.98rem; font-weight: 600; color: var(--text-1); margin-bottom: 0.55rem; }
.guardrail-pass-body   { font-size: 0.84rem; color: var(--text-2); line-height: 1.55; }

.next-strip-label-row {
    font-size: 0.64rem; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--text-3);
    margin: 0.6rem 0 0.45rem 0; padding: 0 0.1rem;
}
.next-action-row { display: none; }

/* Global button theming */
div[data-testid="stButton"] > button,
div[data-testid="stDownloadButton"] > button {
    background: var(--surface) !important;
    color: var(--text-1) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-full) !important; font-weight: 500 !important;
    transition: all 0.15s ease !important; box-shadow: var(--elev-1) !important;
}
div[data-testid="stButton"] > button:hover,
div[data-testid="stDownloadButton"] > button:hover {
    border-color: var(--primary) !important; color: var(--primary) !important;
    background: rgba(201,168,76,0.06) !important; transform: translateY(-1px);
    box-shadow: var(--elev-2) !important;
}
div[data-testid="stButton"] > button:focus,
div[data-testid="stDownloadButton"] > button:focus {
    box-shadow: 0 0 0 2px var(--p-300) !important; outline: none !important;
}
div[data-testid="stButton"] > button[kind="primary"] {
    background: var(--primary) !important;
    border: none !important;
    color: #0a0f1e !important; font-weight: 700 !important;
    box-shadow: var(--purple-glow) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: var(--primary-press) !important;
    box-shadow: 0 8px 28px rgba(201,168,76,0.4) !important;
    color: #0a0f1e !important;
    transform: translateY(-1px);
}
.next-strip-label-row + div[data-testid="stVerticalBlock"] div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button,
.next-strip-label-row ~ div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button {
    border-radius: var(--r-full) !important; padding: 0.5rem 1rem !important; font-size: 0.82rem !important;
}

/* Streamlit component overrides */
.stProgress > div > div > div { background: var(--primary) !important; }

[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--divider);
    border-radius: var(--r-lg);
    padding: 1rem 1.2rem;
    box-shadow: var(--elev-1);
}
[data-testid="stMetricValue"] {
    font-size: clamp(1.8rem,2.5vw,2.2rem) !important;
    font-weight: 800 !important;
    letter-spacing: -0.03em !important;
    color: var(--text-1) !important;
}
[data-testid="stMetricLabel"] { color: var(--text-3) !important; font-weight: 600 !important; }

.stTabs [data-baseweb="tab-list"] {
    background: var(--surface-muted);
    border-radius: var(--r-full);
    padding: 4px;
    gap: 2px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: var(--r-full) !important;
    color: var(--text-2) !important;
    font-weight: 500 !important;
}
.stTabs [aria-selected="true"] {
    background: var(--surface) !important;
    color: var(--primary) !important;
    font-weight: 700 !important;
    box-shadow: var(--elev-1) !important;
}

.stExpander {
    background: var(--surface) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-lg) !important;
    box-shadow: var(--elev-1) !important;
}

.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div,
.stTextInput input {
    background: var(--surface-muted) !important;
    border-color: var(--divider) !important;
    border-radius: var(--r-full) !important;
}
.stTextInput input:focus {
    border-color: var(--p-400) !important;
    box-shadow: 0 0 0 2px var(--p-200) !important;
}
"""

# -------------------------------------------------- duplicate diff modal
_DUP_DIFF_CSS = """
.dup-pair { display: grid; grid-template-columns: 1fr auto 1fr; gap: 1rem; align-items: stretch; margin: 0.8rem 0; }
.dup-side { background: var(--surface); border: 1px solid var(--divider); border-radius: var(--r-md); padding: 0.9rem 1rem; box-shadow: var(--elev-1); }
.dup-side.new      { border-left: 3px solid var(--primary); }
.dup-side.existing { border-left: 3px solid var(--s-500); }
.dup-side-label    { font-size: 0.63rem; text-transform: uppercase; letter-spacing: 0.14em; font-weight: 600; color: var(--text-3); margin-bottom: 0.4rem; }
.dup-side.new .dup-side-label      { color: var(--primary); }
.dup-side.existing .dup-side-label { color: var(--s-500); }
.dup-side-title { font-size: 0.95rem; font-weight: 600; line-height: 1.3; margin-bottom: 0.4rem; color: var(--text-1); }
.dup-side-desc  { font-size: 0.8rem; color: var(--text-2); line-height: 1.5; }
.dup-side-missing { font-size: 0.8rem; color: var(--text-3); font-style: italic; }
.dup-diff-add { background: var(--success-soft); color: var(--success); border-radius: 3px; padding: 0 2px; }
.dup-diff-del { background: var(--warning-soft); color: var(--warning); border-radius: 3px; padding: 0 2px; text-decoration: line-through; text-decoration-color: rgba(245,158,11,0.55); }
.dup-diff-legend { display: flex; flex-wrap: wrap; gap: 1rem; margin: 0 0 0.75rem 0; font-size: 0.73rem; color: var(--text-2); }
.dup-diff-legend-item { display: inline-flex; align-items: center; gap: 0.4rem; }
.dup-vs { align-self: center; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.14em; color: var(--text-3); }
.dup-reason { background: var(--surface-muted); border: 1px solid var(--divider); border-radius: var(--r-sm); padding: 0.65rem 0.9rem; font-size: 0.83rem; color: var(--text-1); margin-bottom: 1.4rem; line-height: 1.5; }
.dup-reason .conf-tag { display: inline-block; padding: 0.1rem 0.5rem; border-radius: var(--r-full); font-size: 0.63rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; background: rgba(123,102,230,0.08); color: var(--s-500); margin-right: 0.5rem; }
"""

# ---------------------------------------------------- run-history dialog
_HISTORY_CSS = """
.rh-card { background: var(--surface); border: 1px solid var(--divider); border-radius: var(--r-lg); padding: 0.85rem 1rem; margin-bottom: 0.55rem; box-shadow: var(--elev-1); }
.rh-card-top { display: flex; justify-content: space-between; align-items: center; gap: 0.85rem; }
.rh-card-date { font-family: 'IBM Plex Mono', monospace; font-size: 0.73rem; color: var(--text-3); letter-spacing: 0.06em; }
.rh-card-source { font-size: 0.92rem; font-weight: 600; color: var(--text-1); line-height: 1.3; margin-top: 0.15rem; }
.rh-card-meta { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.45rem; }
.rh-chip { display: inline-flex; align-items: center; font-family: 'IBM Plex Mono', monospace; font-size: 0.64rem; font-weight: 600; letter-spacing: 0.04em; color: var(--text-2); background: var(--surface-muted); border: 1px solid var(--divider); border-radius: var(--r-full); padding: 0.15rem 0.55rem; }
.rh-chip-accent  { color: var(--primary);  border-color: var(--p-200);  background: var(--p-50); }
.rh-chip-current { color: var(--s-500);    border-color: rgba(123,102,230,0.4); background: rgba(123,102,230,0.06); }
.rh-card-current { border-color: var(--p-300) !important; box-shadow: 0 0 0 1px var(--p-200); }
.rh-summary-chip { flex: 1; background: var(--surface); border: 1px solid var(--divider); border-radius: var(--r-md); padding: 0.55rem 0.75rem; font-size: 1rem; font-weight: 800; color: var(--text-1); text-align: center; box-shadow: var(--elev-1); }
.rh-summary-chip span { display: block; font-size: 0.6rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--text-3); margin-bottom: 0.15rem; }

/* AI surfaces — teal, reserved */
.ai-panel {
    background: var(--ai-soft);
    border: 1px solid var(--ai);
    border-radius: var(--r-lg);
    overflow: hidden;
    box-shadow: var(--ai-glow);
}
.ai-panel .strip {
    background: var(--gradient-ai);
    padding: 14px 20px;
    color: #fff;
    display: flex; align-items: center; gap: 10px;
    font-weight: 700;
}
.ai-panel .body { padding: 20px; color: var(--ai-ink); }
.ai-badge {
    display: inline-flex; align-items: center; gap: 5px;
    background: var(--gradient-ai); color: #fff;
    font-size: 11px; font-weight: 700; padding: 3px 9px;
    border-radius: var(--r-full);
}
.ai-chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: #fff; border: 1px solid var(--ai);
    color: var(--ai-ink); font-size: 13px; font-weight: 600;
    padding: 7px 13px; border-radius: var(--r-full);
}
"""


# ----------------------------------------------------------------- scrollbars
_SCROLLBAR_CSS = """
/* Thin branded scrollbars */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: var(--n-300);
    border-radius: var(--r-full);
}
::-webkit-scrollbar-thumb:hover { background: var(--primary); }
* { scrollbar-width: thin; scrollbar-color: var(--n-300) transparent; }
html { scroll-behavior: smooth; }
"""

# ----------------------------------------------------------------- animations
_ANIMATIONS_CSS = """
/* ── Entrance animations ─────────────────────────────────────── */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(14px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
}
@keyframes scaleIn {
    from { opacity: 0; transform: scale(0.96); }
    to   { opacity: 1; transform: scale(1); }
}

.animate-fadeup  { animation: fadeUp  0.35s cubic-bezier(.2,0,.2,1) both; }
.animate-fadein  { animation: fadeIn  0.25s ease both; }
.animate-scalein { animation: scaleIn 0.25s cubic-bezier(.2,0,.2,1) both; }

/* Staggered children */
.stagger > *:nth-child(1) { animation-delay:   0ms; }
.stagger > *:nth-child(2) { animation-delay:  60ms; }
.stagger > *:nth-child(3) { animation-delay: 120ms; }
.stagger > *:nth-child(4) { animation-delay: 180ms; }
.stagger > *:nth-child(5) { animation-delay: 240ms; }

/* ── Skeleton loader ──────────────────────────────────────────── */
@keyframes shimmer {
    0%   { background-position: -600px 0; }
    100% { background-position:  600px 0; }
}
.skeleton {
    background: linear-gradient(
        90deg,
        var(--surface-muted) 25%,
        var(--n-200) 50%,
        var(--surface-muted) 75%
    );
    background-size: 1200px 100%;
    animation: shimmer 1.6s ease-in-out infinite;
    border-radius: var(--r-sm);
}
.skeleton-text  { height: 14px; border-radius: var(--r-full); margin-bottom: 8px; }
.skeleton-title { height: 24px; width: 60%; border-radius: var(--r-full); margin-bottom: 12px; }
.skeleton-card  {
    height: 120px; border-radius: var(--r-lg);
    background: linear-gradient(
        90deg,
        var(--surface-muted) 25%,
        var(--n-200) 50%,
        var(--surface-muted) 75%
    );
    background-size: 1200px 100%;
    animation: shimmer 1.6s ease-in-out infinite;
    margin-bottom: 12px;
}
"""

# --------------------------------------------------------- deep Streamlit overrides
_STREAMLIT_DEEP_CSS = """
/* ── Global ─────────────────────────────────────────────────── */
.block-container {
    max-width: 1200px !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}

/* ── Typography ─────────────────────────────────────────────── */
h1, .stMarkdown h1 {
    font-size: clamp(1.6rem,2.5vw,2.2rem) !important;
    font-weight: 800 !important;
    letter-spacing: -0.02em !important;
    color: var(--text-1) !important;
    line-height: 1.1 !important;
    margin-bottom: 0.5rem !important;
}
h2, .stMarkdown h2 {
    font-size: 1.3rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.01em !important;
    color: var(--text-1) !important;
    border-bottom: 2px solid var(--divider) !important;
    padding-bottom: 0.4rem !important;
    margin-bottom: 1rem !important;
}
h3, .stMarkdown h3 {
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    color: var(--text-1) !important;
}
p, .stMarkdown p { color: var(--text-2); line-height: 1.65; }

/* ── Alerts ─────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: var(--r-md) !important;
    border-left-width: 4px !important;
    padding: 0.85rem 1.1rem !important;
    box-shadow: var(--elev-1) !important;
    font-size: 0.88rem !important;
    line-height: 1.55 !important;
}
div[data-testid="stAlert"][kind="info"]    { background: var(--info-soft)    !important; border-color: var(--info)    !important; color: #1e3a5f !important; }
div[data-testid="stAlert"][kind="success"] { background: var(--success-soft) !important; border-color: var(--success) !important; color: #14532d !important; }
div[data-testid="stAlert"][kind="warning"] { background: var(--warning-soft) !important; border-color: var(--warning) !important; color: #78350f !important; }
div[data-testid="stAlert"][kind="error"]   { background: var(--danger-soft)  !important; border-color: var(--danger)  !important; color: #7f1d1d !important; }

/* ── Checkbox ───────────────────────────────────────────────── */
[data-testid="stCheckbox"] label {
    font-size: 0.88rem !important; font-weight: 500 !important;
    color: var(--text-1) !important; cursor: pointer;
}
[data-baseweb="checkbox"] > div {
    border-radius: 6px !important;
    width: 18px !important; height: 18px !important;
    border: 2px solid var(--n-300) !important;
    transition: border-color 0.15s, background 0.15s !important;
}
[data-baseweb="checkbox"] > div:hover { border-color: var(--primary) !important; }
[data-baseweb="checkbox"] [data-checked="true"] > div {
    background-color: var(--primary) !important;
    border-color: var(--primary) !important;
}

/* ── Toggle ─────────────────────────────────────────────────── */
[data-testid="stToggle"] [role="switch"][aria-checked="true"] { background: var(--primary) !important; }
[data-testid="stToggle"] [role="switch"] { transition: background 0.2s ease !important; }

/* ── Radio ──────────────────────────────────────────────────── */
[data-baseweb="radio"] [data-checked="true"] div:first-child {
    border-color: var(--primary) !important;
    background: var(--primary) !important;
}
[data-baseweb="radio"] div:first-child { transition: border-color 0.15s !important; }

/* ── Selectbox / Multiselect ────────────────────────────────── */
[data-baseweb="select"] > div {
    background: var(--surface) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-full) !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
    box-shadow: var(--elev-1) !important;
}
[data-baseweb="select"] > div:hover { border-color: var(--p-400) !important; }
[data-baseweb="select"] > div:focus-within {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 3px rgba(201,168,76,0.18) !important;
}
[data-baseweb="popover"] [role="listbox"] {
    background: var(--surface) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-md) !important;
    box-shadow: var(--elev-3) !important;
    padding: 6px !important;
}
[data-baseweb="option"] {
    border-radius: var(--r-sm) !important;
    font-size: 0.88rem !important;
    color: var(--text-1) !important;
    transition: background 0.1s !important;
}
[data-baseweb="option"]:hover,
[data-baseweb="option"][aria-selected="true"] {
    background: rgba(201,168,76,0.08) !important;
    color: var(--primary) !important;
}

/* ── Text input / Textarea ───────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background: var(--surface) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-md) !important;
    color: var(--text-1) !important;
    font-size: 0.9rem !important;
    padding: 0.6rem 0.9rem !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
    box-shadow: var(--elev-1) !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 3px rgba(201,168,76,0.2) !important;
    outline: none !important;
}
[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label {
    font-size: 0.82rem !important; font-weight: 600 !important;
    color: var(--text-2) !important; margin-bottom: 4px !important;
}

/* ── File uploader ──────────────────────────────────────────── */
[data-testid="stFileUploader"] > div {
    background: var(--surface) !important;
    border: 2px dashed var(--divider) !important;
    border-radius: var(--r-lg) !important;
    transition: border-color 0.2s, background 0.2s !important;
    box-shadow: var(--elev-1) !important;
}
[data-testid="stFileUploader"] > div:hover {
    border-color: var(--primary) !important;
    background: rgba(201,168,76,0.05) !important;
}
[data-testid="stFileUploader"] small,
[data-testid="stFileUploader"] span { color: var(--text-3) !important; font-size: 0.82rem !important; }

/* ── Progress bar ───────────────────────────────────────────── */
.stProgress > div > div {
    background: var(--surface-muted) !important;
    border-radius: var(--r-full) !important;
    height: 6px !important;
    overflow: hidden !important;
}
.stProgress > div > div > div {
    background: var(--hero-fill) !important;
    border-radius: var(--r-full) !important;
    transition: width 0.4s cubic-bezier(.2,0,.2,1) !important;
}

/* ── Divider ────────────────────────────────────────────────── */
[data-testid="stDivider"] hr, hr {
    border: none !important;
    border-top: 1px solid var(--divider) !important;
    margin: 1.5rem 0 !important;
}

/* ── Spinner ────────────────────────────────────────────────── */
[data-testid="stSpinner"] { color: var(--primary) !important; }
[data-testid="stSpinner"] > div { border-top-color: var(--primary) !important; }

/* ── Status message boxes ───────────────────────────────────── */
.stSuccess { background: var(--success-soft) !important; border-radius: var(--r-md) !important; }
.stError   { background: var(--danger-soft)  !important; border-radius: var(--r-md) !important; }
.stWarning { background: var(--warning-soft) !important; border-radius: var(--r-md) !important; }
.stInfo    { background: var(--info-soft)    !important; border-radius: var(--r-md) !important; }

/* ── Expander ───────────────────────────────────────────────── */
.stExpander {
    background: var(--surface) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-lg) !important;
    box-shadow: var(--elev-1) !important;
    overflow: hidden !important;
    transition: box-shadow 0.2s !important;
    margin-bottom: 0.75rem !important;
}
.stExpander:hover { box-shadow: var(--elev-2) !important; }
.stExpander summary,
.stExpander [data-testid="stExpanderToggleIcon"] { color: var(--primary) !important; }
.stExpander > details > summary {
    padding: 0.85rem 1.1rem !important;
    font-weight: 600 !important; font-size: 0.94rem !important;
    border-radius: var(--r-lg) !important;
    transition: background 0.15s !important;
}
.stExpander > details > summary:hover { background: rgba(201,168,76,0.06) !important; }
.stExpander > details[open] > summary {
    border-bottom: 1px solid var(--divider) !important;
    border-radius: var(--r-lg) var(--r-lg) 0 0 !important;
}

/* ── Tabs ───────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: var(--surface-muted) !important;
    border-radius: var(--r-full) !important;
    padding: 4px !important; gap: 2px !important;
    border: 1px solid var(--divider) !important;
    box-shadow: inset 0 1px 3px rgba(23,21,31,0.05) !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: var(--r-full) !important;
    padding: 0.45rem 1.1rem !important;
    font-size: 0.84rem !important; font-weight: 500 !important;
    color: var(--text-2) !important;
    transition: all 0.18s ease !important; border: none !important;
}
.stTabs [data-baseweb="tab"]:hover:not([aria-selected="true"]) {
    background: rgba(201,168,76,0.05) !important;
    color: var(--primary) !important;
}
.stTabs [aria-selected="true"] {
    background: var(--surface) !important; color: var(--primary) !important;
    font-weight: 700 !important; box-shadow: var(--elev-1) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none !important; }

/* ── DataFrame ──────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-lg) !important;
    overflow: hidden !important;
    box-shadow: var(--elev-1) !important;
}
.stDataFrame thead th {
    background: var(--surface-muted) !important;
    font-size: 0.75rem !important; font-weight: 700 !important;
    text-transform: uppercase !important; letter-spacing: 0.06em !important;
    color: var(--text-3) !important; padding: 12px 14px !important;
    border-bottom: 1px solid var(--divider) !important;
}
.stDataFrame tbody td {
    font-size: 0.88rem !important; color: var(--text-2) !important;
    padding: 11px 14px !important; border-bottom: 1px solid var(--divider) !important;
    transition: background 0.1s !important;
}
.stDataFrame tbody tr:hover td { background: rgba(201,168,76,0.05) !important; }

/* ── Dialog / modal ─────────────────────────────────────────── */
[data-testid="stDialog"],
[role="dialog"] {
    border-radius: var(--r-xl) !important;
    box-shadow: var(--elev-3) !important;
    border: 1px solid var(--divider) !important;
    overflow: hidden !important;
}
[data-testid="stDialogScrollableContent"] { padding: 1.5rem !important; }

/* ── Slider ─────────────────────────────────────────────────── */
[data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"] {
    background: var(--primary) !important;
    border: 2px solid var(--primary) !important;
    box-shadow: 0 0 0 4px var(--p-200) !important;
}

/* ── Caption ────────────────────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--text-3) !important;
    font-size: 0.78rem !important; line-height: 1.45 !important;
}

/* ── Code blocks ────────────────────────────────────────────── */
code {
    background: var(--n-800) !important; color: var(--n-100) !important;
    border-radius: var(--r-sm) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.83rem !important; padding: 2px 5px !important;
}
pre {
    background: var(--n-800) !important; border-radius: var(--r-md) !important;
    padding: 1.1rem !important; border: 1px solid var(--n-700) !important;
    box-shadow: var(--elev-2) !important;
}

/* ── Number input ───────────────────────────────────────────── */
[data-testid="stNumberInput"] input {
    background: var(--surface) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-md) !important; color: var(--text-1) !important;
}
[data-testid="stNumberInput"] input:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 3px rgba(201,168,76,0.18) !important; outline: none !important;
}

/* ── Accessibility — focus ring ─────────────────────────────── */
*:focus-visible {
    outline: 2px solid var(--p-400) !important; outline-offset: 2px !important;
}
button:focus-visible, a:focus-visible {
    outline: 2px solid var(--p-400) !important;
    outline-offset: 3px !important; border-radius: var(--r-sm) !important;
}

/* ── Sidebar selects ────────────────────────────────────────── */
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: var(--surface) !important;
    border: 1px solid var(--divider) !important;
    border-radius: var(--r-md) !important;
    font-size: 0.88rem !important;
    box-shadow: var(--elev-1) !important;
    transition: border-color 0.15s !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] > div:hover {
    border-color: var(--primary) !important;
}
section[data-testid="stSidebar"] .stToggle [role="switch"][aria-checked="true"] {
    background: var(--primary) !important;
}

/* ── Images ─────────────────────────────────────────────────── */
[data-testid="stImage"] img {
    border-radius: var(--r-lg) !important;
    box-shadow: var(--elev-2) !important; max-width: 100% !important;
}

/* ── Global transition smoothing ────────────────────────────── */
button, a, input, select, textarea,
[data-testid="stButton"] > button,
[data-baseweb="select"] > div {
    transition-duration: 0.18s !important;
    transition-timing-function: cubic-bezier(0.2,0,0.2,1) !important;
}
"""

# ----------------------------------------------------------------- tooltips
_TOOLTIP_CSS = """
/* data-tooltip attribute tooltip */
[data-tooltip] { position: relative; cursor: help; }
[data-tooltip]::after {
    content: attr(data-tooltip);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%; transform: translateX(-50%);
    background: var(--n-800); color: #fff;
    font-size: 0.72rem; font-weight: 500;
    padding: 6px 10px; border-radius: var(--r-sm);
    white-space: nowrap; pointer-events: none;
    opacity: 0; transition: opacity 0.18s;
    z-index: 9999; box-shadow: var(--elev-2);
}
[data-tooltip]:hover::after { opacity: 1; }
"""


_GLASS_CSS = """
/* ══ GLASSMORPHISM — frosted glass applied to all card surfaces ══ */

/* Custom card classes */
.kpi, .epic-card, .story-card, .finding-card, .summary-card,
.pipeline, .pipeline-wrap, .stage, .progress-log,
.run-meta, .next-strip, .empty-state, .empty-step,
.rh-card, .dup-side, .dup-reason, .ai-panel {
    background: rgba(255,255,255,0.07) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border-color: rgba(255,255,255,0.13) !important;
}

.kpi.hero {
    background: rgba(245,197,24,0.18) !important;
    border-color: rgba(245,197,24,0.4) !important;
    box-shadow: 0 0 0 1px rgba(245,197,24,0.3), 0 12px 40px rgba(245,197,24,0.15) !important;
    color: #fff !important;
}
.kpi.hero .kpi-value { color: #f5c518 !important; }
.kpi.hero .kpi-label { color: rgba(255,255,255,0.8) !important; }

.stage {
    background: rgba(255,255,255,0.05) !important;
    border-color: rgba(255,255,255,0.10) !important;
}
.stage.active {
    background: rgba(245,197,24,0.10) !important;
    border-color: rgba(245,197,24,0.30) !important;
}
.stage.done {
    background: rgba(34,197,94,0.10) !important;
    border-color: rgba(34,197,94,0.25) !important;
}

/* Streamlit native components */
.stExpander {
    background: rgba(255,255,255,0.07) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(255,255,255,0.13) !important;
    border-radius: var(--r-lg) !important;
}

[data-testid="stMetric"] {
    background: rgba(255,255,255,0.07) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(255,255,255,0.13) !important;
}

[data-baseweb="select"] > div {
    background: rgba(255,255,255,0.08) !important;
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
}

[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    color: #ffffff !important;
}

[data-testid="stFileUploader"] > div {
    background: rgba(255,255,255,0.05) !important;
    border: 2px dashed rgba(255,255,255,0.18) !important;
}

section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.13) !important;
}

/* Model stage badge */
.stage-model {
    background: rgba(245,197,24,0.15) !important;
    border-color: rgba(245,197,24,0.4) !important;
    color: #f5c518 !important;
    font-weight: 700 !important;
}
.stage-model-dot { background: #f5c518 !important; }

/* Story/epic borders — keep colored left accent visible */
.epic-card  { border-left: 4px solid var(--primary) !important; }
.story-card:hover {
    background: rgba(255,255,255,0.11) !important;
    border-color: rgba(245,197,24,0.4) !important;
}

/* Progress log entries */
.log-started .log-icon   { color: #f5c518 !important; }
.log-completed .log-icon { color: #22C55E !important; }

/* Tags — glass pill */
.tag {
    background: rgba(245,197,24,0.12) !important;
    color: #f5c518 !important;
    border-color: rgba(245,197,24,0.35) !important;
}

/* Buttons — primary CTA gold with dark text */
div[data-testid="stButton"] > button[kind="primary"] {
    background: #f5c518 !important;
    color: #0b1426 !important;
    box-shadow: 0 0 0 1px rgba(245,197,24,0.5), 0 8px 32px rgba(245,197,24,0.25) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #d4a800 !important;
    box-shadow: 0 0 0 1px rgba(245,197,24,0.6), 0 12px 40px rgba(245,197,24,0.35) !important;
    color: #0b1426 !important;
}

/* Secondary buttons — glass */
div[data-testid="stButton"] > button:not([kind="primary"]),
div[data-testid="stDownloadButton"] > button {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.18) !important;
    color: #ffffff !important;
    backdrop-filter: blur(10px) !important;
}
div[data-testid="stButton"] > button:not([kind="primary"]):hover,
div[data-testid="stDownloadButton"] > button:hover {
    background: rgba(245,197,24,0.12) !important;
    border-color: rgba(245,197,24,0.45) !important;
    color: #f5c518 !important;
}

/* Priority badges — more visible on glass */
.pri-high   { background: rgba(248,113,113,0.18) !important; color: #fca5a5 !important; }
.pri-medium { background: rgba(245,158,11,0.18)  !important; color: #fcd34d !important; }
.pri-low    { background: rgba(34,197,94,0.18)   !important; color: #86efac !important; }

/* KPI value text — always gold accent */
.kpi.accent .kpi-value { color: #f5c518 !important; }

/* Popover / dropdown glass */
[data-baseweb="popover"] [role="listbox"] {
    background: rgba(15,25,50,0.92) !important;
    backdrop-filter: blur(24px) !important;
    -webkit-backdrop-filter: blur(24px) !important;
    border: 1px solid rgba(255,255,255,0.14) !important;
}
[data-baseweb="option"]:hover,
[data-baseweb="option"][aria-selected="true"] {
    background: rgba(245,197,24,0.12) !important;
    color: #f5c518 !important;
}

/* Tab bar — glass pill */
.stTabs [data-baseweb="tab-list"] {
    background: rgba(255,255,255,0.06) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
}
.stTabs [aria-selected="true"] {
    background: rgba(245,197,24,0.15) !important;
    color: #f5c518 !important;
}

/* ══ AGENT PIPELINE FLOW ══════════════════════════════════════════ */
.ap-hero {
    text-align: center;
    padding: 2.2rem 1.5rem 1.6rem;
}
.ap-eyebrow {
    font-size: 0.65rem; font-weight: 700; letter-spacing: 0.22em;
    text-transform: uppercase; color: #f5c518;
    margin-bottom: 0.7rem;
}
.ap-title {
    font-size: clamp(1.5rem, 2.8vw, 2.1rem);
    font-weight: 800; letter-spacing: -0.025em;
    color: #ffffff; line-height: 1.15; margin-bottom: 0.6rem;
}
.ap-sub {
    font-size: 0.92rem; color: #94a3b8; line-height: 1.6;
    max-width: 620px; margin: 0 auto 2.2rem;
}
.ap-sub strong { color: #f5c518; }
.ap-flow {
    display: flex; align-items: stretch; gap: 0;
    margin: 0 0 2rem 0; overflow-x: auto;
    padding-bottom: 4px;
}
.ap-card {
    flex: 1; min-width: 148px;
    background: rgba(255,255,255,0.06);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 20px;
    padding: 1.3rem 1rem 1.1rem;
    text-align: center;
    position: relative;
    transition: transform 0.22s ease, box-shadow 0.22s ease, background 0.22s ease, border-color 0.22s ease;
    cursor: default;
}
.ap-card:hover {
    transform: translateY(-6px);
    background: rgba(245,197,24,0.10);
    border-color: rgba(245,197,24,0.45);
    box-shadow: 0 0 0 1px rgba(245,197,24,0.3), 0 20px 48px rgba(245,197,24,0.15);
}
.ap-num {
    width: 28px; height: 28px; border-radius: 50%;
    background: rgba(245,197,24,0.15);
    border: 1px solid rgba(245,197,24,0.4);
    font-size: 0.65rem; font-weight: 800; color: #f5c518;
    letter-spacing: 0.04em; margin: 0 auto 0.75rem;
    display: flex; align-items: center; justify-content: center;
}
.ap-icon {
    font-size: 2rem; line-height: 1;
    margin-bottom: 0.6rem; display: block;
    filter: drop-shadow(0 0 8px rgba(245,197,24,0.3));
}
.ap-name {
    font-size: 0.82rem; font-weight: 700;
    color: #ffffff; line-height: 1.25;
    margin-bottom: 0.35rem;
}
.ap-tag {
    font-size: 0.68rem; color: #94a3b8;
    line-height: 1.45; margin-bottom: 0.75rem;
}
.ap-outputs { display: flex; flex-wrap: wrap; gap: 4px; justify-content: center; }
.ap-badge {
    font-size: 0.58rem; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase;
    padding: 2px 7px; border-radius: 999px;
    background: rgba(245,197,24,0.12);
    border: 1px solid rgba(245,197,24,0.3);
    color: #f5c518;
}
.ap-arrow {
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; width: 36px; position: relative;
}
.ap-arrow::before {
    content: '';
    position: absolute; top: 50%; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, rgba(245,197,24,0.3) 0%, rgba(245,197,24,0.8) 50%, rgba(245,197,24,0.3) 100%);
    transform: translateY(-50%);
    animation: ap-flow-pulse 2.4s ease-in-out infinite;
}
.ap-arrow::after {
    content: '▸'; font-size: 0.85rem; color: #f5c518;
    position: relative; z-index: 1;
    animation: ap-arrow-pulse 2.4s ease-in-out infinite;
}
@keyframes ap-flow-pulse {
    0%, 100% { opacity: 0.4; }
    50%       { opacity: 1.0; }
}
@keyframes ap-arrow-pulse {
    0%, 100% { opacity: 0.5; transform: translateX(0); }
    50%       { opacity: 1.0; transform: translateX(2px); }
}
.ap-io {
    display: flex; justify-content: center; gap: 2rem;
    font-size: 0.72rem; color: #64748b;
    margin-top: 0.5rem; padding-top: 1.2rem;
    border-top: 1px solid rgba(255,255,255,0.07);
}
.ap-io-item { display: flex; align-items: center; gap: 0.4rem; }
.ap-io-dot  { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
"""


def get_css() -> str:
    """Return the full CSS payload wrapped in a <style> tag."""
    parts = [
        _TOKENS_CSS,
        _SHELL_CSS.replace("_HEADER_CSS_PLACEHOLDER", ""),
        _HEADER_CSS,
        _PIPELINE_CSS,
        _KPI_CSS,
        _EMPTY_CSS,
        _STORY_CSS,
        _FINDING_CSS,
        _RUN_META_CSS,
        _NEXT_CSS,
        _DUP_DIFF_CSS,
        _HISTORY_CSS,
        _SCROLLBAR_CSS,
        _ANIMATIONS_CSS,
        _STREAMLIT_DEEP_CSS,
        _TOOLTIP_CSS,
        _GLASS_CSS,
    ]
    return "<style>\n" + "\n".join(parts) + "\n</style>"
