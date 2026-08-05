# Vatscore-radar
VatScore Web is a Streamlit-based global radar dashboard that fetches live flight and air traffic control (ATC) data from the VATSIM network to provide detailed airspace analytics.

## VatScore Strategic Development Roadmap

Our mission is to engineer the ultimate, high-fidelity data hub for the VATSIM network, focusing on premium telemetry and optimized interface layouts. Below is our active development queue.

### Phase 1: Telemetry and UI Expansion
- [x] Flight Detail Insight System: Implement interactive row-click actions on data tables to expand and view the full flight plan string (ROUTE), pilot real name, and voice VHF frequency metadata natively without leaving the view.

### Phase 2: Pro-Tier Filtering & Advanced Telemetry
- [x] Airline Call-Sign Isolation: Expand standard FIR filters to support global ICAO airline codes, allowing users to explicitly isolate specific fleets (e.g., THY, PGT, BAW).
- [x] Automated Telemetry Tagging "Flight Rules Box": Integrate automated IFR and VFR flight rule telemetry tags based on live flight plan data.
- [x] Real-Time Haversine Distance Engine: Replace estimated progress tracking with a precise coordinate calculation framework based on the Haversine Formula, cross-referencing live positions against global airport databases.
- [x] VIP Watchlist System: Allow seamless, persistent tracking of specific airframes and pilot CIDs across active radar sessions.
- [x] FIR Boundary Engine Overhaul: Replaced legacy prefix-only sector matching with a dual-mode Shapely geometry system. Aircraft are now validated against official VATSIM GeoJSON boundaries, with a dedicated physical airspace toggle for strict coordinate-based filtering.
- [x] Precision FIR Selectbox: Consolidated 200+ raw sector entries into a clean, country-level hub selector. All sub-sectors are merged under a single unified prefix, eliminating list clutter entirely.
- [x] JS Render Pipeline Fix: Resolved a critical data bypass where the JS engine was independently fetching unfiltered VATSIM data on every 30-second sync cycle, overriding all Python-side FIR and isolation filters.
- [x] Airframe Info Expansion: Telemetry Dossier upgraded with Registration and SELCAL fields parsed directly from pilot remarks, displayed in unified Type | Reg | SELCAL format. Online time reformatted to Min | Hour Min split for precise session tracking.
- [x] Airlines DB Client-Side Migration: Moved airline identity resolution from server-side Python fetch to browser-side async fetch, eliminating 403 access failures on restricted hosting environments.
- [ ] High-Availability Server Migration: Upgrade core network infrastructure to high-availability servers to support premium custom branding and stable user connections. ** IT HAS BEEN POSTPONED TO FUTURE PHASES! **

### Phase 3: The Ultimate Score, Analytics & Hyper-Personalization — Completed
Phase 3 delivers on the core promise of turning VatScore from a simple radar into a full performance analytics and scoring hub, anchored by a dedicated CID Intelligence page.
- [x] Dedicated CID Intelligence Hub: Replaced the old flat "CID Stats" tab with a fully independent statistics page, reachable via a seamless single-click native tab (no intermediate confirmation screen) and fully separate from the live radar's rendering pipeline.
- [x] Full-History statsim.net Integration: Engineered a chunked, parallelized fetch pipeline that works around statsim.net's 31-day query ceiling, pulling a pilot's entire flight and ATC history back to registration in seconds via concurrent windowed requests.
- [x] Time-Series Flight Statistics: Delivered dynamic monthly/yearly activity charts, ICAO airframe and manufacturer distribution breakdowns (Airbus, Boeing, etc.) with live filtering, and a longest-to-shortest flight ranking engine driven by independent hour and nautical-mile threshold sliders.
- [x] Route & Airline Intelligence: Added most-flown route detection, most-flown aircraft/airline identification cross-referenced against the VATSIM Radar airline registry, and a "most interesting route" algorithm that surfaces rare, long-haul flights instead of just the busiest ones.
- [x] ATC Sector Mastery Module: Introduced per-position ATC session analytics (All Time / This Year / This Month) with time-on-position ranking for any CID carrying a controlling history.
- [x] High-Level Profile Badges: Pilot, ATC, and military rating badges now decode VATSIM's real bitmask/tier tables directly, alongside registration date, division, and live-online status.
- [x] Real VHF Frequency Telemetry: Replaced the placeholder Voice/Text indicator with live COM frequency data sourced directly from VATSIM's official transceivers feed — the same approach used by VATSIM Radar.
- [x] Network-Wide Auto-Refresh Engine: Replaced a silently non-functional JS sync bridge with a proper scoped-fragment architecture — Leaderboard, Global Stats, Anomaly Radar, and the network counters now refresh live in the background every 20 seconds without disturbing in-progress input anywhere else on the page.
- [x] Rating Accuracy Overhaul: Corrected the ATC and pilot rating decoders to match VATSIM's official rating tables exactly, eliminating a long-standing off-by-one misclassification (e.g., a real S1 controller no longer reads as S2).
- [x] Security & Stability Hardening: Closed a stored-XSS vector in pilot-supplied name fields, fixed an app-wide crash on missing secrets configuration, and removed several dead/never-functional code paths inherited from earlier phases.
- [ ] Localized Favorites Ecosystem and the network-wide Leaderboard Ranking Badge (#xxxxx) are carried over to Phase 4 below — no reliable public data source exists yet for a true cross-network ranking, and favorites/local-storage pinning is being redesigned alongside the upcoming White Mode UI! **POSTPONED TO PHASE 4!**

### Phase 4: Admin Infrastructure and Branding
- [ ] Hourly Analytics Profiles: Upgrade the encrypted VatScore HQ control room with analytical chart integration to model peak server connection hours graph-by-graph.
- [ ] Custom Domain Integration: Purchase a dedicated aviation-centric domain name and configure DNS routing (CNAME records) to transition the platform from a generic deployment to a fully branded premium web infrastructure.
- [ ] Localized Favorites Ecosystem: Enable virtual airline pilots and heavy-user enthusiasts to bookmark specific callsigns using session states and local storage architecture to pin favorite airframes cleanly at the top of the radar hierarchy.
- [ ] Global Leaderboard Ranking Badge (#xxxxx): Requires either a statsim.net endpoint exposing total hours across all users, or an in-house CID database accumulated over time, to compute a real network-wide standing.
- [ ] White Mode for User Interface.
