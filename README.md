# Vatscore-radar
VatScore Web is a Streamlit-based global radar dashboard that fetches live flight and air traffic control (ATC) data from the VATSIM network to provide detailed airspace analytics.

## VatScore Strategic Development Roadmap

Our mission is to engineer the ultimate, high-fidelity data hub for the VATSIM network, focusing on premium telemetry and optimized interface layouts. Below is our active development queue.

### Phase 1: Telemetry and UI Expansion
- [x] Flight Detail Insight System: Implement interactive row-click actions on data tables to expand and view the full flight plan string (ROUTE), pilot real name, and voice VHF frequency metadata natively without leaving the view.

### Phase 2: Pro-Tier Filtering & Advanced Telemetry
- [ ] Airline Call-Sign Isolation: Expand standard FIR filters to support global ICAO airline codes, allowing users to explicitly isolate specific fleets (e.g., THY, PGT, BAW).
- [ ] Automated Telemetry Tagging: Integrate automated IFR and VFR flight rule telemetry tags based on live flight plan data.
- [x] Real-Time Haversine Distance Engine: Replace estimated progress tracking with a precise coordinate calculation framework based on the Haversine Formula, cross-referencing live positions against global airport databases.
- [ ] VIP Watchlist System: Allow seamless, persistent tracking of specific airframes and pilot CIDs across active radar sessions.
- [ ] High-Availability Server Migration: Upgrade core network infrastructure to high-availability servers to support premium custom branding and stable user connections.

### Phase 3: Hyper-Personalization
- [ ] Localized Favorites Ecosystem: Enable virtual airline pilots and heavy-user enthusiasts to bookmark specific callsigns using session states and local storage architecture to pin favorite airframes cleanly at the top of the radar hierarchy.
- [ ] White Mode for User Interface.

### Phase 4: Admin Infrastructure and Branding
- [ ] Hourly Analytics Profiles: Upgrade the encrypted VatScore HQ control room with analytical chart integration to model peak server connection hours graph-by-graph.
- [ ] Custom Domain Integration: Purchase a dedicated aviation-centric domain name and configure DNS routing (CNAME records) to transition the platform from a generic deployment to a fully branded premium web infrastructure.
