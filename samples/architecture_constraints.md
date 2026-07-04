# Quantum Technologies Manufacturing Platform — Engineering Architecture Constraints

**Owner:** Architecture Review Board
**Last reviewed:** March 2026
**Audience:** All platform engineering and digital operations teams. This page captures the constraints any new initiative must respect or formally exception out of.

---

## 1. Performance budgets

- **PartnerPortal order-status API p95** must complete end-to-end under **2 seconds on a standard enterprise connection**. We measure with synthetic transactions hourly. Regressions block release.
- **MES shop-floor UI response time** for an operator-initiated action (work-order start, component scan) must stay under **300ms p95** at the terminal. If the network link is degraded, see Section 4.
- **Production order search p95** in the PartnerPortal must stay under **600ms**. The search service is rate-limited at the edge to protect this budget.

## 2. Required integrations

- All client and supplier identity must flow through **IdentityVault (IV)**. New auth flows MUST NOT introduce a separate credential store. Account-ID-bound identity federation with IV is the only supported pattern.
- All invoice and payment processing MUST go through the **InvoiceGateway**. Direct writes to ERP financial tables are forbidden — this is a PCI scope and audit trail requirement.
- All quality records (NCRs, CAPAs, inspection results) MUST go through the **QualityHub** service. QualityHub is the system of record for all non-conformance and corrective action data; writes to other stores cause AS9100 audit failures.

## 3. Security and compliance

- **IEC 62443 / NIST 800-82 (OT cybersecurity).** All firmware packages for embedded control modules must be cryptographically signed by the Quantum Technologies Code Signing Authority (QT-CSA). Unsigned or self-signed packages must be rejected at the device. No exceptions.
- **ITAR / EAR export controls.** Technical data for ITAR-controlled articles (EAR99 exclusion list in the product catalogue) must reside in US-jurisdiction servers. Cross-region replication of controlled technical data to EU/APAC regions without a current export licence on file is forbidden.
- **AS9100 / ISO 9001 quality management.** NCR and CAPA records require 10-year retention. Automatic closure of an NCR without a verified corrective action record in QualityHub is FORBIDDEN — this violates the AS9100 audit trail requirement.
- **REACH / RoHS compliance.** Every shipment Certificate of Conformance (COA) must reference a current REACH/RoHS compliance declaration for all components in the assembly. Missing or expired compliance declarations block shipment release in ComponentID.
- **GDPR / CCPA.** Any notification referencing a specific NCR number, controlled article ID, or client shipment detail linked to an ITAR-controlled order requires:
  - Explicit client consent stored on the account record
  - Delivery only to the client's *verified* technical contact, never the shared enterprise account default
  - Audit log of every notification sent, retained 10 years

## 4. Offline tolerance (shop floor and connectivity loss)

- **Core MES functions** (work-order display, scan-and-confirm, component routing) MUST continue to operate when the network link is lost. No core shop-floor feature may be cloud-dependent for normal operation.
- **Remote diagnostic commands** that arrive while a module is offline MUST be queued and executed within 60 seconds of connectivity restoration, provided they are still within their validity window.
- **Security-critical firmware operations** (cryptographic attestation, secure boot, certificate provisioning) MUST NEVER depend on network connectivity in a way that bypasses protection.
- **Gen1 embedded controllers** (2019–2021 vintage) cannot receive:
  - Differential (delta) firmware packages — full firmware images only, max 512 MB per update
  - TLS 1.3 connections — TLS 1.2 is the floor for Gen1
  - Background firmware downloads that run more than 60 minutes without operator acknowledgement

Stories that depend on capabilities unavailable on Gen1 controllers must explicitly declare the hardware floor and either gate by ControllerGeneration or target Gen2 only.

## 5. Data residency

- ITAR-controlled technical data must reside in our US-East and US-West regions. Cross-region replication to EU/APAC is forbidden without a current export licence on file.
- EU client PII (contact records, billing addresses) must remain in our EU-West and EU-Central regions. Cross-region replication to US/APAC is forbidden under the current GDPR program.
- Production telemetry aggregates (no PII, anonymised) may flow to our central data warehouse in US-East.

## 6. Forbidden patterns

- **Direct database writes** to QualityHub NCR/CAPA tables from non-QualityHub services. Use the QualityHub API.
- **Unsigned firmware packages** submitted to FirmwareVault or deployed to any device.
- **Automatic NCR closure** without a verified corrective action record in QualityHub.
- **Polling production telemetry** from the cloud at intervals shorter than 60 seconds. Use the production event stream instead.
- **Direct ERP financial table writes** from application-layer services. Route through InvoiceGateway.
- **Custom encryption.** Use the platform KMS and our standard TLS/DTLS libraries. Rolling your own crypto is forbidden.
- **Direct device actuation writes** from any application-layer service. All remote diagnostic commands must go through the diagnostic control plane with validated message authentication codes (MACs).

## 7. Recommended defaults (should, not must)

- Feature flagging via LaunchDarkly for any change that touches a client-facing surface
- Server-driven UI for any flow that changes more than monthly
- gRPC for service-to-service; REST only for external/partner APIs
- All new services emit OpenTelemetry traces by default

## 8. Hardware capabilities reference

| Hardware | Platform | Notes |
|---|---|---|
| Gen1 embedded controller (2019–2021) | ARM Cortex-M4, 256 MB flash | TLS 1.2 only; full firmware images only; max 512 MB. Refresh Q2 FY26. |
| Gen2 embedded controller (2022+) | ARM Cortex-M7, 1 GB flash | TLS 1.3; differential firmware; background download |
| MES shop-floor terminal | Industrial Android 10, ruggedised | Work-order display, scan-confirm; must work on plant Wi-Fi with no cellular |
| PartnerPortal client app | Web (modern browsers), mobile responsive | Order placement, status, COA download |
| Supplier tablet (SupplySync) | Android 12, ruggedised | Delivery confirmation, material receipt; plant Wi-Fi |

---

This page is updated quarterly. If your team needs an exception, file an ADR (Architecture Decision Record) tagged `exception:` and route it to the Architecture Review Board.