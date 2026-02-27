# Scraping API Handlers

This directory owns scraping-domain handler code imported by the shared dashboard backend.

Current module:

- `scraping_handlers.py`

Integration path:

- `dashboard/backend/services/scraping.py` imports handlers from this directory
- `dashboard/backend/routers/scraping.py` registers scraping routes

Purpose:

- keep scraping business logic close to scraper codebase
- allow dashboard backend to stay a thin routing/control-plane layer
