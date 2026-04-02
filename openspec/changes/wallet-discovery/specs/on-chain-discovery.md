# Specs: On-Chain Data Analysis for Wallet Discovery

## 1. Goal
Identify potential "smart money" wallet addresses on the Polygon PoS blockchain by analyzing interactions with core Polymarket contracts.

## 2. Approach
Monitor Polymarket's primary contracts for events indicative of significant or early trading activity, and extract the associated wallet addresses.

## 3. Core Polymarket Contract Identification

### Method
- **Web Search**: Use `browser` or `multi-search-engine` to find official Polymarket documentation or reliable sources listing their main contract addresses on Polygon PoS.
- **Block Explorer**: Browse PolygonScan (e.g., `polygonscan.com`) to identify contracts with high transaction volumes that interact with Polymarket's front-end or known market addresses.

### Expected Contracts (Examples)
- `ConditionFactory` (to create new markets)
- `ConditionalTokens` (ERC-1155 token for outcomes)
- `FixedProductMarketMaker` (main trading contract)
- `ProxyFactory` (if markets are deployed via proxy)

### Output
A list of verified Polymarket core contract addresses on Polygon PoS.

## 4. On-Chain Data Extraction

### Library: `web3.py`

#### Setup
1.  **Install `web3.py`**:
    ```bash
    cd /Users/tkzz/.openclaw/workspace/agents/polymarket-bot/PolyAnalysis && source .venv/bin/activate && pip install web3
    ```
2.  **RPC Endpoint**: Configure connection to a Polygon PoS RPC endpoint (e.g., `https://polygon-rpc.com` or a private Alchemy/Infura endpoint).

#### Data Points to Extract
-   **Contract Events**: Listen for or query historical events from the identified Polymarket contracts.
    -   `MarketCreated`: Identify new markets being created, extract `creator` address.
    -   `PositionBought`, `PositionSold`: Extract `buyer`/`seller` addresses, `volume`, `price`.
    -   `CollateralDeposit`, `CollateralWithdrawal`: Identify addresses moving funds in/out of Polymarket.
-   **Transaction Data**: Analyze transactions interacting with Polymarket contracts.
    -   `from` address: The sender of the transaction.
    -   `value`: Amount of MATIC/USDC (collateral) involved.

### Filter Criteria for "Smart Money" Identification
-   **High Volume Traders**: Addresses involved in transactions exceeding a certain threshold (e.g., total volume > $10,000 in a market).
-   **Early Entrants**: Addresses that participate in new markets very shortly after `MarketCreated` events.
-   **Frequent Traders**: Addresses with a high number of interactions with Polymarket contracts over time.
-   **Profitable Patterns (Advanced)**: This would require more sophisticated on-chain analysis to track actual PnL on-chain, which is highly complex and likely beyond the scope of initial discovery. Focus on activity metrics first.

### Output
A list of wallet addresses that meet the specified on-chain criteria, along with basic metrics (e.g., total volume with Polymarket contracts, number of transactions).

## 5. Challenges and Considerations

-   **API Key for RPC**: High-volume queries to public RPCs might be rate-limited. Private RPC endpoints (Alchemy, Infura) require API keys. This should be made optional or gracefully handled.
-   **Data Storage**: Storing raw event data can be large. Prioritize extracting only necessary fields.
-   **Performance**: Querying large historical event ranges can be slow. Implement pagination, time range filtering, and asynchronous processing.
-   **Polymarket Contract ABI**: To decode contract events and function calls, we need the ABI (Application Binary Interface) for each Polymarket contract. These can usually be found on PolygonScan.

---
