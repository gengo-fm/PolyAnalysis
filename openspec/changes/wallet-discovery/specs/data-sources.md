# Specs: Data Sources Integration for Wallet Discovery

## 1. Polymarket Leaderboard Scraper

### Goal
Extract top N wallet addresses, names, profit, and volume from the official Polymarket leaderboard page.

### Input
- URL: `https://polymarket.com/leaderboard`
- Parameters:
    - `limit`: Number of top traders to extract (e.g., 20, 50, 100). Max 20 per page, requires pagination.
    - `timeframe`: "Today", "Weekly", "Monthly", "All" (defaults to "All" for comprehensive data).

### Output
A list of dictionaries, each containing:
- `address`: Wallet address (e.g., `0x...`)
- `name`: Trader name (if available)
- `profit`: Total profit (string, e.g., "+$4,016,108")
- `volume`: Total volume (string, e.g., "$12,394,130")
- `rank`: Rank on the leaderboard (integer)

### Implementation Details

#### Library: `OpenClaw browser tool`
- Use `browser.open()` to navigate to the URL.
- Use `browser.act()` with JavaScript `querySelector` and `querySelectorAll` to extract elements.
- Handle pagination by clicking the "next page" button or directly constructing page URLs (if applicable, though Polymarket uses buttons).

#### Extraction Logic

1.  **Initial Load**: Load `https://polymarket.com/leaderboard`.
2.  **Timeframe Selection**: If `timeframe` is not "All", click the corresponding button (e.g., `button "Monthly"`).
3.  **Data Extraction**:
    -   Identify the container for each leaderboard entry. (e.g., `generic[ref=e109]`, `generic[ref=e131]`, etc. from snapshot)
    -   For each entry:
        -   `rank`: `generic[ref=e111]` text content.
        -   `name`: `link[ref=e123]` text content (or `paragraph[ref=e124]`).
        -   `address`: Extracted from the `href` attribute of the profile `link[ref=e115]` (e.g., `/profile/0x02227b8f5a9636e895607edd3185ed6ee5598ff7`).
        -   `profit`: `paragraph[ref=e127]` text content.
        -   `volume`: `paragraph[ref=e129]` text content.
4.  **Pagination**:
    -   Check for a "next page" button (`img[ref=e514]`) or page number links.
    -   Click "next page" (`browser.act(kind='click', ref='e514', targetId=target_id)`) until `limit` is reached or no more pages.
    -   Collect data from each page.

#### Error Handling
- Handle page loading errors.
- Handle missing elements (e.g., if page structure changes).
- Implement retries with exponential backoff for network issues.

---

## 2. TradeFox Smart Money Scraper

### Goal
Extract wallet addresses from the TradeFox "Smart Money" page.

### Input
- URL: `https://thetradefox.com/follow-traders/smart-money`
- (No explicit parameters, TradeFox provides its own curated list)

### Output
A list of wallet addresses (e.g., `0x...`).

### Implementation Details

#### Library: `OpenClaw browser tool`
- Use `browser.open()` to navigate to the URL.
- Use `browser.act()` with JavaScript `querySelector` and `querySelectorAll` to extract elements.

#### Extraction Logic
1.  **Load Page**: Load `https://thetradefox.com/follow-traders/smart-money`.
2.  **Data Extraction**:
    -   Identify sections containing trader profiles.
    -   For each trader, extract the wallet address. This might require inspecting the page structure to find data attributes or specific text patterns. (Assume the wallet address is clearly visible or embedded in a link/data attribute).

#### Error Handling
- Handle page loading errors.
- Handle missing elements.
- Implement retries.

---

## 3. HashDive / Polymarket Analytics Scrapers (Initial Exploration)

### Goal
Explore and, if feasible, extract "Smart Money" or Top Trader lists from HashDive and Polymarket Analytics.

### Input
- HashDive URL: `https://www.hashdive.com/`
- Polymarket Analytics URL: `https://polymarketanalytics.com/`

### Output
A list of wallet addresses, potentially with associated metrics.

### Implementation Details

#### Library: `OpenClaw browser tool`
- Will require manual inspection of each site's structure to determine extractable data and methods.
- Likely to involve similar `browser.act()` usage as Polymarket leaderboard.

#### Challenges
- These sites might require login or have more complex anti-scraping mechanisms.
- Data presentation might vary significantly, requiring tailored scraping logic for each.
- Initial approach will be to check if lists are publicly accessible without authentication.

---

## 4. GitHub `Awesome-Prediction-Market-Tools` Parsing

### Goal
Parse the GitHub `README.md` to identify additional analytics platforms, aggregators, or tools that might contain smart money lists.

### Input
- GitHub URL: `https://github.com/aarora4/Awesome-Prediction-Market-Tools`

### Output
A list of URLs or platform names to be further investigated for wallet discovery.

### Implementation Details

#### Library: `web_fetch`
- Use `web_fetch` to get the raw `README.md` content.
- Parse the Markdown content to identify tool names and their associated URLs (e.g., under "Analytics Tools", "Aggregator" sections).
- Filter for tools explicitly mentioning "smart money", "whale tracking", or "top traders".

#### Challenges
- `web_fetch` might be blocked by GitHub (though less likely for public READMEs).
- Parsing Markdown accurately to extract structured data can be tricky.

---
