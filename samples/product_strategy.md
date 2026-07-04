# Quantum Technologies Manufacturing Platform — Q3 Product Strategy (Client Operations Track)

**Author:** Priya Chen, VP Digital Operations
**Status:** Draft for executive review
**Target:** Q3 FY26 (July – September)
**Audience:** Engineering, product, and operations leadership

---

## Background

In Q2 we improved remote diagnostic command success rates by 12% through connectivity resilience improvements and reduced PartnerPortal crash rates by half. Client satisfaction scores held flat. The next inflection point will come from solving the experience problems that surface *during the production and quality journey* and *across service channels* — places where our two largest client segments (high-volume OEM accounts, compliance-active quality teams) feel friction on every interaction.

Voice-of-client data from the last 90 days converges on five themes. Three of them are P0 for Q3. Two are P1 candidates depending on capacity.

---

## P0 — Must ship by end of Q3

### 1. Firmware deployment resilience under CDN saturation

**The problem.** When a deployment wave exceeds FirmwareVault CDN throughput limits, modules in the batch stall in "Update Pending" with the embedded controller unresponsive. Three regional clusters experienced a 45-minute outage window last month affecting roughly 6,000 modules. Direct client NPS impact: -18 for affected modules in the 48 hours following a failed deployment night. Indirect: clients who associate Quantum Technologies with unexpected field downtime.

**The goal.** Firmware deployments adopt staged rollout rings with per-ring throttle controls. Modules that stall must resume normal controller operation within 60 seconds. Downloads checkpoint on the module so a resumed session continues from byte offset rather than restarting the full firmware package.

**Constraints.** IEC 62443 and our firmware signing policy prohibit automatic rollback for security-critical firmware updates without a validated rollback image. Rollback path must be pre-qualified for each target firmware build before deployment authorisation.

**Success metric.** Zero "embedded controller unresponsive due to firmware stall" incidents during the next major deployment wave, measured via telemetry. Synthetic test: saturate the CDN throttle artificially, confirm 100% of modules return to normal operation within 60 seconds.

### 2. NCR / CAPA case unification

**The problem.** Clients can submit an NCR via the PartnerPortal OR contact their account manager and have the quality engineer enter it directly into QualityHub. These two intake channels write to different systems with no real-time reconciliation. Clients regularly follow up expecting their case is in review when it isn't, or vice versa. The quality support line spends an estimated 20% of its call volume simply disambiguating NCR status.

**The goal.** Both channels become writes to **QualityHub**, the system of record. The client sees a single case status (submitted / in review / resolved) regardless of intake channel. Status changes trigger a push notification to the verified technical contact.

**Constraints.** GDPR and ITAR: consent-based notifications only for any message referencing a specific NCR number or controlled article ID — stored on the account record, sent to the client's verified technical contact (not the shared enterprise account default), audit log retained 10 years.

### 3. Production order status — live accuracy

**The problem.** The PartnerPortal does not incorporate real-time production status from the MES. Clients search for their orders, see "On Track" results, click through, and find the order is actually behind in production. NPS for clients who hit this is -28; for clients who don't it's +18.

**The goal.** Order status results are re-ranked by verified live production data from the MES event stream. When the top result shows high latency risk, surface alternative delivery windows inline — not after the client has already escalated to their account manager.

**Constraints.** ITAR access control gating: differential order status for ITAR-controlled article orders must be gated by verified clearance level. Maintain the 600ms p95 production order search latency budget.

**Success metric.** 30-day rolling NPS for PartnerPortal order-status sessions that end with an acknowledged delivery commitment improves to +10 minimum from the current -4 platform-wide average.

---

## P1 — Stretch goals for Q3

### 4. Supplier delivery confirmation transparency

A modest UX addition. Production planners and clients don't understand when a "Materials Confirmed" alert represents a firm delivery date versus a provisional confirmation. We add a "material status" card in the PartnerPortal showing: confirmed delivery date, outstanding PO status, and production schedule impact. Client feedback from the last account survey suggests this lands well even as a small change.

**Success metric.** Client support contact rate for "why was my production date moved" drops 50% within 90 days of launch.

### 5. Gen1 controller hardware capability gating

Our 2019–2021 embedded controllers run Gen1 hardware which limits what we can deploy to those modules. A hardware device-refresh campaign is approved for FY26 but full coverage won't be reached until Q2 FY26. In Q3 we should ensure any *new* firmware-dependent feature is explicitly tagged with its hardware floor — Gen2 only, or Gen1-compatible with fallbacks — so we don't silently break older modules in the field.

This is more a discipline than a feature: every new firmware-dependent story must declare its controller generation floor.

---

## Out of scope for Q3 (explicitly)

- **Remote firmware scripting by clients.** Hardware/platform project owned by the device HW team, not platform engineering.
- **SupplySync portal redesign.** Slated for FY27 H1.
- **B2B enterprise account analytics dashboard.** Still in research; no decision before Q4.
- **Multi-language PartnerPortal.** In flight (QT-096) but not a Q3 commitment.

---

## Cross-cutting expectations

- Every Q3 story must trace to a client-facing outcome or a compliance forcing function. Pure tech-debt items continue to be funded out of the engineering capacity reserve, not the OKR-attributed capacity.
- Compliance review (Legal + InfoSec) is mandatory for: NCR notifications (GDPR/ITAR), order status access control (ITAR), and any new payment flow (PCI).
- Architecture Review Board (ARB) sign-off required for any deviation from the constraints in the engineering architecture wiki.

---

## What I'm asking engineering to do next

1. Synthesize this strategy into a structured Q3 backlog: epics → stories → tasks.
2. Cross-check against the existing JIRA/GitHub items so we don't redo work that's already planned.
3. Surface any **gaps** — capabilities I implied here that neither this strategy nor the existing backlog covers.
4. Surface any **conflicts** with the architecture constraints early.

I want this back by the next steering meeting in two weeks so we can sequence the Q3 calendar.